"""
Hallucination guard: every number Claude writes in the memo must trace back to
a number in the payload that the deterministic pipeline computed.

Matching is rounding-aware, not a loose percentage tolerance:
  VERIFIED    claimed == source rounded to the same number of decimals
              (also tries source*100 for rates written as percentages)
  APPROX      within 2% relative of a source value
  UNVERIFIED  no source number within 2%

Ignored (not claims): dates, list numbering ("1." at line start), and the
whole numbers 0-3 which appear in prose ("top 3", "2 root causes").
"""

from __future__ import annotations

import re

_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_LIST_NO = re.compile(r"(?m)^\s*\d+[.)]\s")
_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*\.?\d*")


def _flatten(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _flatten(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _flatten(v, f"{path}[{i}]")
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float)):
        yield float(obj), path


def extract_claims(text: str) -> list[tuple[float, int]]:
    """Return [(value, decimals)] for every numeric claim in the text."""
    text = _DATE.sub(" ", text)
    text = _LIST_NO.sub(" ", text)
    claims = []
    for tok in _NUM.findall(text):
        clean = tok.replace(",", "").rstrip(".")
        if not clean or clean == "-":
            continue
        try:
            val = float(clean)
        except ValueError:
            continue
        if abs(val) <= 3 and "." not in clean:
            continue
        decimals = len(clean.split(".")[1]) if "." in clean else 0
        claims.append((val, decimals))
    return claims


def check(claude_text: str, payload: dict) -> dict:
    source = [(v, p) for v, p in _flatten(payload) if v != 0]
    results, verified, approx, unverified = [], 0, 0, 0

    for claimed, dec in extract_claims(claude_text):
        status, where = "UNVERIFIED", None
        for sv, path in source:
            if any(round(c, dec) == round(claimed, dec) for c in (sv, sv * 100)):
                status, where = "VERIFIED", path
                break
        if status != "VERIFIED":
            for sv, path in source:
                if any(abs(claimed - c) / abs(c) <= 0.02 for c in (sv, sv * 100)):
                    status, where = "APPROX", path
                    break
        results.append({"claimed": claimed, "status": status, "source": where})
        if status == "VERIFIED":
            verified += 1
        elif status == "APPROX":
            approx += 1
        else:
            unverified += 1

    total = len(results)
    reliability = round((verified + approx * 0.5) / total * 100, 1) if total else 100.0
    return {
        "total_claims": total, "verified": verified, "approx": approx,
        "unverified": unverified, "reliability_score": reliability,
        "overall_status": "RELIABLE" if reliability >= 80 else "REVIEW REQUIRED",
        "details": results,
    }
