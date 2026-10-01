"""
AB Fulfillment Defect Intelligence — Anomaly Detector
Flags statistical anomalies in defect rates across nodes, carriers, categories.

Uses z-score (>2 standard deviations = anomaly) AND threshold breach (>5%).
Both signals are shown transparently in the output — no black boxes.

This mirrors what Amazon SC Analysts actually do: identify which FC,
carrier, or category is above threshold and needs escalation.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from datetime import timedelta


from config import DEFECT_THRESHOLD, WARNING_THRESHOLD, ZSCORE_FLAG  # noqa: E402


def _zscore(series: pd.Series) -> pd.Series:
    mu, sigma = series.mean(), series.std()
    if sigma == 0:
        return pd.Series(0.0, index=series.index)
    return (series - mu) / sigma


def by_node(df: pd.DataFrame) -> pd.DataFrame:
    """Defect rate and anomaly flag per fulfillment center."""
    g = df.groupby("node").agg(
        total_shipments=("total_shipments", "sum"),
        total_defects=("total_defects", "sum"),
        late_delivery=("late_delivery", "sum"),
        missing_package=("missing_package", "sum"),
        damaged_goods=("damaged_goods", "sum"),
        wrong_item=("wrong_item", "sum"),
        inventory_discrepancy=("inventory_discrepancy", "sum"),
        failed_pickup=("failed_pickup", "sum"),
        avg_delivery_hrs=("avg_delivery_hrs", "mean"),
    ).reset_index()
    g["defect_rate"] = g["total_defects"] / g["total_shipments"]
    g["z_score"]     = _zscore(g["defect_rate"]).round(4)
    g["status"]      = g["defect_rate"].apply(
        lambda r: "ESCALATE" if r >= DEFECT_THRESHOLD else
                  "WATCH"    if r >= WARNING_THRESHOLD else "OK"
    )
    g["anomaly"]     = (g["z_score"].abs() >= ZSCORE_FLAG)
    return g.sort_values("defect_rate", ascending=False).reset_index(drop=True)


def by_carrier(df: pd.DataFrame) -> pd.DataFrame:
    """Defect rate and anomaly flag per carrier."""
    g = df.groupby("carrier").agg(
        total_shipments=("total_shipments", "sum"),
        total_defects=("total_defects", "sum"),
        late_delivery=("late_delivery", "sum"),
        failed_pickup=("failed_pickup", "sum"),
        avg_delivery_hrs=("avg_delivery_hrs", "mean"),
    ).reset_index()
    g["defect_rate"] = g["total_defects"] / g["total_shipments"]
    g["z_score"]     = _zscore(g["defect_rate"]).round(4)
    g["status"]      = g["defect_rate"].apply(
        lambda r: "ESCALATE" if r >= DEFECT_THRESHOLD else
                  "WATCH"    if r >= WARNING_THRESHOLD else "OK"
    )
    return g.sort_values("defect_rate", ascending=False).reset_index(drop=True)


def by_category(df: pd.DataFrame) -> pd.DataFrame:
    """Defect rate per product category."""
    g = df.groupby("category").agg(
        total_shipments=("total_shipments", "sum"),
        total_defects=("total_defects", "sum"),
    ).reset_index()
    g["defect_rate"] = g["total_defects"] / g["total_shipments"]
    g["z_score"]     = _zscore(g["defect_rate"]).round(4)
    g["status"]      = g["defect_rate"].apply(
        lambda r: "ESCALATE" if r >= DEFECT_THRESHOLD else
                  "WATCH"    if r >= WARNING_THRESHOLD else "OK"
    )
    return g.sort_values("defect_rate", ascending=False).reset_index(drop=True)


def by_weekday(df: pd.DataFrame) -> pd.DataFrame:
    """Defect rate by day of week — shows Monday spike pattern."""
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]
    g = df.groupby("weekday").agg(
        total_shipments=("total_shipments", "sum"),
        total_defects=("total_defects", "sum"),
    ).reset_index()
    g["defect_rate"] = g["total_defects"] / g["total_shipments"]
    g["weekday"]     = pd.Categorical(g["weekday"], categories=order, ordered=True)
    return g.sort_values("weekday").reset_index(drop=True)


def week_over_week(df: pd.DataFrame) -> dict:
    """
    Compare last full week vs the week before.
    Returns overall defect rate change and direction.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    latest_date = df["date"].max()
    week1_end   = latest_date
    week1_start = latest_date - timedelta(days=6)
    week2_end   = week1_start - timedelta(days=1)
    week2_start = week2_end - timedelta(days=6)

    w1 = df[(df["date"] >= week1_start) & (df["date"] <= week1_end)]
    w2 = df[(df["date"] >= week2_start) & (df["date"] <= week2_end)]

    r1 = w1["total_defects"].sum() / w1["total_shipments"].sum() if len(w1) else 0
    r2 = w2["total_defects"].sum() / w2["total_shipments"].sum() if len(w2) else 0
    delta = r1 - r2

    return {
        "current_week_defect_rate":  round(r1, 4),
        "previous_week_defect_rate": round(r2, 4),
        "delta":                     round(delta, 4),
        "direction":                 "UP" if delta > 0.001 else "DOWN" if delta < -0.001 else "STABLE",
        "current_week_shipments":    int(w1["total_shipments"].sum()),
        "current_week_defects":      int(w1["total_defects"].sum()),
        "week_range": f"{week1_start.date()} to {week1_end.date()}",
    }


def run_all(df: pd.DataFrame) -> dict:
    """Run all anomaly checks and return structured results."""
    nodes    = by_node(df)
    carriers = by_carrier(df)
    cats     = by_category(df)
    days     = by_weekday(df)
    wow      = week_over_week(df)

    total_shipments = int(df["total_shipments"].sum())
    total_defects   = int(df["total_defects"].sum())
    overall_rate    = round(total_defects / total_shipments, 4)

    escalate_nodes = nodes[nodes["status"] == "ESCALATE"]["node"].tolist()
    watch_nodes    = nodes[nodes["status"] == "WATCH"]["node"].tolist()
    anomaly_nodes  = nodes[nodes["anomaly"]]["node"].tolist()

    return {
        "overall": {
            "total_shipments":    total_shipments,
            "total_defects":      total_defects,
            "overall_defect_rate": overall_rate,
            "escalate_threshold": DEFECT_THRESHOLD,
            "warning_threshold":  WARNING_THRESHOLD,
            "formula":            f"defect_rate = total_defects / total_shipments = {total_defects}/{total_shipments} = {overall_rate:.4f}",
        },
        "nodes":    nodes,
        "carriers": carriers,
        "categories": cats,
        "weekday":  days,
        "wow":      wow,
        "escalation_summary": {
            "escalate_nodes": escalate_nodes,
            "watch_nodes":    watch_nodes,
            "anomaly_nodes":  anomaly_nodes,
            "n_escalate":     len(escalate_nodes),
            "n_watch":        len(watch_nodes),
        },
    }
