"""
Supplier performance. The scorecard itself is SQL (sql/07_supplier_scorecard.sql);
this module adds the target gap and a one-line summary for reports.

OTIF = On Time AND In Full, per PO (the standard supply-chain definition).
"""

from __future__ import annotations

import pandas as pd

import config


def run_all(scorecard: pd.DataFrame) -> dict:
    sc = scorecard.copy()
    sc["otif_gap_pts"] = (config.OTIF_TARGET - sc["otif"]).clip(lower=0) * 100
    n_bad = int((sc["status"] == "ESCALATE").sum())
    n_watch = int((sc["status"] == "WATCH").sum())
    worst = sc.iloc[0] if len(sc) else None
    return {
        "scorecard": sc,
        "summary": {
            "suppliers": int(len(sc)),
            "escalate": n_bad,
            "watch": n_watch,
            "network_otif": float((sc["otif"] * sc["pos_received"]).sum() / sc["pos_received"].sum()),
            "shortfall_value_usd": float(sc["shortfall_value"].sum()),
            "worst_supplier": None if worst is None else worst["supplier_id"],
            "worst_otif": None if worst is None else float(worst["otif"]),
        },
    }
