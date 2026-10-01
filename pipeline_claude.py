"""
AB Fulfillment & Supply Defect Intelligence - Pipeline 2: Claude-Augmented
Runs Pipeline 1 first, then sends the pre-computed metrics to Claude to write
a stakeholder escalation memo.

Claude receives only pre-computed JSON. It never calculates a metric.
Every number Claude writes is checked by modules/hallucination_guard.py.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
from modules.excel_reporter import build_workbook
from modules.hallucination_guard import check as _guard
from pipeline_direct import run as run_direct


SYSTEM_PROMPT = """You are an Amazon Business Supply Chain Analyst writing a
weekly escalation memo to fulfillment center partners and operations leadership.

You will receive a JSON health report with pre-computed metrics.
A deterministic Python pipeline computed every number.
You did NOT compute any of them.

Your memo must:
1. State the overall defect rate and week-over-week trend
2. Name specific FCs that require escalation or watch and their defect rates
3. Identify the top 2 root causes by weighted impact score and the recommended action
4. Summarise supply risk: network OTIF, network fill rate, and the worst supplier
5. List the top escalation queue items (id, priority, entity, owner, due date)
6. Give 3 specific action items for the operations team

Rules:
- Use ONLY numbers from the JSON. Never estimate or invent.
- Write dollar amounts in full digits (for example $1,265,326), never as $1.2M.
- Write rates as percentages exactly as given (3.31%), do not re-round.
- Say once that the data is simulated if "simulated" is true.
- Address the memo to: FC Operations Partners and AB Supply Chain Leadership
- Subject line first, then body
- Tone: direct, data-driven, professional
- Numbered action items, no bullet-point soup.
- End with your name: Sejal Khade, Supply Chain Analyst, AB Operations"""


def _build_payload(direct_result: dict) -> dict:
    """Minimal structured payload sent to Claude. Nothing extra."""
    a = direct_result["anomalies"]
    r = direct_result["root_cause"]
    supply = direct_result.get("supply")
    payload = {
        "simulated":           bool(direct_result.get("simulated", True)),
        "week_range":          a["wow"].get("week_range"),
        "overall_defect_rate": a["overall"]["overall_defect_rate"],
        "total_shipments":     a["overall"]["total_shipments"],
        "total_defects":       a["overall"]["total_defects"],
        "wow_delta":           a["wow"]["delta"],
        "wow_direction":       a["wow"]["direction"],
        "escalate_nodes":      a["escalation"]["escalate_nodes"],
        "watch_nodes":         a["escalation"]["watch_nodes"],
        "nodes": [
            {"node": n["node"], "defect_rate": n["defect_rate"], "status": n["status"]}
            for n in a["nodes"][:6]
        ],
        "top_carriers_above_threshold": [
            {"carrier": c["carrier"], "defect_rate": c["defect_rate"]}
            for c in a["carriers"] if c["status"] != "OK"
        ],
        "top_3_root_causes": r["top_3"],
        "top_escalations": [
            {"id": q["id"], "priority": q["priority"], "entity": q["entity"],
             "owner": q["owner"], "due_date": q["due_date"],
             "severity_score": q["severity_score"], "est_cost_usd": int(round(q["est_cost_usd"]))}
            for q in direct_result.get("queue", [])[:5]
        ],
    }
    if supply:
        payload["supply"] = {
            "network_otif": round(supply["suppliers"]["network_otif"], 4),
            "worst_supplier": supply["suppliers"]["worst_supplier"],
            "worst_supplier_otif": round(supply["suppliers"]["worst_otif"], 4),
            "network_fill_rate": round(supply["inventory"]["network_fill_rate"], 4),
            "fcs_stocked_out_series": supply["inventory"]["stocked_out"],
        }
    return payload


def run(api_key: str, seed: int = 42, n_days: int = 90,
        output_path: str | None = None, data: dict | None = None) -> dict:

    print("Pipeline 2: Claude-Augmented")
    print("=" * 60)

    print("Step 1/5  Running direct pipeline...")
    tmp = str(Path(tempfile.gettempdir()) / "ab_direct_temp.xlsx")
    direct = run_direct(seed=seed, n_days=n_days, output_path=tmp, data=data, verbose=False)

    print("Step 2/5  Building Claude payload...")
    payload = _build_payload(direct)

    print(f"Step 3/5  Calling Claude ({config.CLAUDE_MODEL})...")
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    try:
        msg = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    "Write the weekly escalation memo based on this report.\n\n"
                    f"METRICS JSON:\n{json.dumps(payload, indent=2, default=str)}\n\n"
                    "Use only the numbers above."
                )
            }]
        )
        memo_text = msg.content[0].text
        claude_ok, claude_err = True, None
    except Exception as e:
        memo_text = f"Claude call failed: {e}"
        claude_ok, claude_err = False, str(e)

    print("Step 4/5  Running hallucination guard...")
    guard = _guard(memo_text, payload) if claude_ok else None
    if guard:
        print(f"          Reliability: {guard['reliability_score']}% "
              f"({guard['verified']} verified, {guard['approx']} approx, {guard['unverified']} unverified)")

    print("Step 5/5  Rebuilding Excel with memo (reusing computed frames)...")
    f = direct["_frames"]
    supply = f["supply"]
    path = build_workbook(
        df=f["df"], anomalies=f["anomalies"], root=f["root"], memo_text=memo_text,
        output_path=output_path, queue=f["queue"], supply=supply, simulated=direct["simulated"])
    print(f"          Saved: {path}")

    return {
        "status":   "ok" if claude_ok else "claude_failed",
        "pipeline": "claude",
        "direct":   direct,
        "claude": {
            "success":      claude_ok,
            "error":        claude_err,
            "memo_text":    memo_text,
            "payload_sent": payload,
        },
        "hallucination_guard": guard,
        "output_path": str(path),
    }


if __name__ == "__main__":
    import os
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("Set ANTHROPIC_API_KEY to run the Claude-augmented pipeline.")
    run(key)
