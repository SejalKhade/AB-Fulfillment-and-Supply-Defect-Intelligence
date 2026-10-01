"""
Reconciliation controls. The same metrics are computed twice by independent
code paths (pandas modules vs SQL). If they disagree, something is wrong with
the data load or the logic, and the pipeline should say so before anyone acts
on the numbers. This is the data-quality check an analyst would put in front
of a report.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _close(a, b, tol=1e-9) -> bool:
    return bool(np.allclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float), rtol=tol, atol=tol))


def run_checks(df: pd.DataFrame, py_nodes: pd.DataFrame, sql_nodes: pd.DataFrame,
               py_pareto: pd.DataFrame, sql_pareto: pd.DataFrame) -> list[dict]:
    checks = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    n_py = py_nodes.sort_values("node").reset_index(drop=True)
    n_sql = sql_nodes.sort_values("node").reset_index(drop=True)
    add("Node set identical (pandas vs SQL)", list(n_py["node"]) == list(n_sql["node"]))
    add("Node defect rates match (pandas vs SQL)", _close(n_py["defect_rate"], n_sql["defect_rate"]))
    add("Node z-scores match (pandas vs SQL)", _close(n_py["z_score"], n_sql["z_score"], 1e-3))
    add("Node status labels match", list(n_py["status"]) == list(n_sql["status"]))
    add("Pareto counts match (pandas vs SQL)",
        _close(py_pareto.sort_values("defect_type")["count"],
               sql_pareto.sort_values("defect_type")["count"]))
    add("Sum of node defects equals row-level total",
        int(n_sql["total_defects"].sum()) == int(df["total_defects"].sum()),
        f"{int(n_sql['total_defects'].sum()):,} vs {int(df['total_defects'].sum()):,}")
    breakdown = int(df[["late_delivery", "missing_package", "damaged_goods", "wrong_item",
                        "inventory_discrepancy", "failed_pickup"]].sum().sum())
    add("Defect-type breakdown sums to total defects", breakdown == int(df["total_defects"].sum()),
        f"{breakdown:,} vs {int(df['total_defects'].sum()):,}")
    add("No defects exceed shipments", bool((df["total_defects"] <= df["total_shipments"]).all()))
    add("No duplicate (date, node, carrier, category) rows",
        not df.duplicated(["date", "node", "carrier", "category"]).any())
    return checks
