"""
AB Fulfillment Defect Intelligence — Root Cause Analyzer
Performs Pareto analysis (80/20) on defect types to identify
which root causes are driving the most volume.

Weights each defect type by customer impact (config.DEFECT_WEIGHTS — an
ASSUMPTION on simulated data; in production derive from contact/refund data),
and prices each defect (config.COST_PER_DEFECT) to give a USD impact estimate.

Mirrors what an Amazon SC Analyst actually does in a root cause deep-dive.
"""

from __future__ import annotations
import pandas as pd
import numpy as np


from config import DEFECT_WEIGHTS, COST_PER_DEFECT  # noqa: E402

DEFECT_LABELS = {
    "failed_pickup":           "Failed Pickup",
    "late_delivery":           "Late Delivery",
    "missing_package":         "Missing Package",
    "damaged_goods":           "Damaged Goods",
    "wrong_item":              "Wrong Item",
    "inventory_discrepancy":   "Inventory Discrepancy",
}

ESCALATION_ACTIONS = {
    "failed_pickup":         "Escalate to carrier ops — failed pickups require same-day resolution to prevent SLA breach",
    "late_delivery":         "Review carrier routing with FC partners — check if issue is node-level or carrier-wide",
    "missing_package":       "Trigger inventory audit at flagged FC — missing packages require same-day trace",
    "damaged_goods":         "Inspect packaging standards at FC — coordinate with operations manager",
    "wrong_item":            "Review pick/pack accuracy at FC — may indicate staffing or training issue",
    "inventory_discrepancy": "Schedule cycle count at flagged FC — inventory discrepancies compound over time",
}


def pareto_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pareto (80/20) breakdown of defect types by raw volume.
    Shows which defect types account for 80% of total defects.
    """
    totals = {col: df[col].sum() for col in DEFECT_WEIGHTS}
    total_all = sum(totals.values())

    rows = []
    for col, count in sorted(totals.items(), key=lambda x: -x[1]):
        pct = count / total_all if total_all else 0
        rows.append({
            "defect_type":   col,
            "label":         DEFECT_LABELS[col],
            "count":         int(count),
            "pct_of_total":  round(pct, 4),
            "weight":        DEFECT_WEIGHTS[col],
            "action":        ESCALATION_ACTIONS[col],
        })

    result = pd.DataFrame(rows)
    result["cumulative_pct"] = result["pct_of_total"].cumsum().round(4)
    result["in_pareto_80"]   = result["cumulative_pct"] <= 0.80
    return result


def weighted_impact(df: pd.DataFrame) -> pd.DataFrame:
    """
    Score each defect type by weighted impact (volume x customer impact weight).
    This is the prioritization signal for what to fix first.
    """
    total_shipments = df["total_shipments"].sum()
    rows = []
    for col, weight in DEFECT_WEIGHTS.items():
        count = int(df[col].sum())
        raw_rate      = count / total_shipments if total_shipments else 0
        impact_score  = raw_rate * weight * 100  # scaled to 0-100
        rows.append({
            "defect_type":    col,
            "label":          DEFECT_LABELS[col],
            "count":          count,
            "raw_rate":       round(raw_rate, 4),
            "weight":         weight,
            "impact_score":   round(impact_score, 4),
            "formula":        f"({count}/{int(total_shipments)}) x {weight} x 100 = {impact_score:.4f}",
            "est_cost_usd":   round(count * COST_PER_DEFECT[col], 2),
            "action":         ESCALATION_ACTIONS[col],
        })
    result = pd.DataFrame(rows).sort_values("impact_score", ascending=False)
    result["rank"] = range(1, len(result) + 1)
    return result.reset_index(drop=True)


def node_defect_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """Which defect type is driving each node's problem."""
    rows = []
    for node, grp in df.groupby("node"):
        total = grp["total_shipments"].sum()
        defect_rates = {col: grp[col].sum() / total for col in DEFECT_WEIGHTS}
        top_defect   = max(defect_rates, key=defect_rates.get)
        rows.append({
            "node":           node,
            "overall_rate":   round(grp["total_defects"].sum() / total, 4),
            "top_defect":     DEFECT_LABELS[top_defect],
            "top_defect_rate": round(defect_rates[top_defect], 4),
            "action":         ESCALATION_ACTIONS[top_defect],
        })
    return pd.DataFrame(rows).sort_values("overall_rate", ascending=False).reset_index(drop=True)


def run_all(df: pd.DataFrame) -> dict:
    """Full root cause analysis."""
    pareto   = pareto_analysis(df)
    weighted = weighted_impact(df)
    by_node  = node_defect_breakdown(df)

    top3 = weighted.head(3)[["label", "impact_score", "action"]].to_dict("records")

    return {
        "pareto":            pareto,
        "weighted_impact":   weighted,
        "node_breakdown":    by_node,
        "top_3_priorities":  top3,
        "methodology": (
            "Pareto analysis identifies defect types causing 80% of volume. "
            "Weighted impact scores each type by (rate x customer impact weight) "
            "to prioritize interventions by business consequence, not just count."
        ),
    }
