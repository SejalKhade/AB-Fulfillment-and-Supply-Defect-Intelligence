"""
AB Fulfillment & Supply Defect Intelligence - Pipeline 1: Direct
Fully deterministic. No API calls. Same input = same output.

Steps:
  1. Load data (simulator, or your own CSVs)
  2. Load into the DuckDB warehouse; reconcile SQL vs pandas
  3. Anomaly detection (cross-node z-score + same-weekday rolling baseline)
  4. Root cause: Pareto + weighted impact + contribution analysis
  5. Supply: supplier OTIF, demand forecast, safety stock / reorder points
  6. Escalation queue (scored, owned, dated)
  7. Excel workbook
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
from modules import escalation, inventory, supplier
from modules.anomaly_detector import run_all as detect
from modules.data_generator import generate
from modules.excel_reporter import build_workbook
from modules.reconcile import run_checks
from modules.root_cause import run_all as root_cause
from modules.supply_generator import generate_supply
from modules.warehouse import Warehouse


def _log(verbose: bool, msg: str) -> None:
    if verbose:
        print(msg)


def avg_defect_cost(df) -> float:
    tot = df[list(config.DEFECT_WEIGHTS)].sum()
    n = tot.sum()
    return float(sum(tot[k] * config.COST_PER_DEFECT[k] for k in tot.index) / n) if n else 0.0


def run(seed: int = 42, n_days: int = 90, output_path: str | None = None,
        data: dict | None = None, verbose: bool = True) -> dict:
    """
    data: optional {"fulfillment": df, "inventory": df|None, "purchase_orders": df|None,
                    "suppliers": df|None}. If omitted, simulated data is generated.
    """
    _log(verbose, "Pipeline 1: Direct (no LLM)")
    _log(verbose, "=" * 60)

    simulated = data is None
    _log(verbose, "Step 1/7  Loading data..." + ("  [SIMULATED]" if simulated else "  [user-supplied]"))
    if simulated:
        df = generate(n_days=n_days, seed=seed)
        inv, pos, sup = generate_supply(df, seed=seed)
    else:
        df, inv = data["fulfillment"], data.get("inventory")
        pos, sup = data.get("purchase_orders"), data.get("suppliers")
    has_supply = inv is not None and pos is not None and sup is not None
    _log(verbose, f"          {len(df):,} fulfillment rows | {df['total_shipments'].sum():,} shipments "
                  f"| {df['total_defects'].sum():,} defects"
                  + (f" | {len(inv):,} inventory rows | {len(pos):,} POs" if has_supply else ""))

    _log(verbose, "Step 2/7  Loading DuckDB warehouse and reconciling SQL vs pandas...")
    wh = Warehouse().load(df, inv, pos, sup)
    anomalies = detect(df)
    root = root_cause(df)
    sql_nodes = wh.run("01_node_scorecard")
    sql_pareto = wh.run("06_pareto")
    checks = run_checks(df, anomalies["nodes"], sql_nodes, root["pareto"], sql_pareto)
    failed = [c for c in checks if not c["passed"]]
    _log(verbose, f"          {len(checks) - len(failed)}/{len(checks)} reconciliation checks passed")
    for c in failed:
        _log(verbose, f"          FAILED: {c['check']} {c['detail']}")

    _log(verbose, "Step 3/7  Anomaly detection...")
    rolling = wh.run("02_rolling_anomalies")
    events = rolling[rolling["is_anomaly"]]
    esc = anomalies["escalation_summary"]
    _log(verbose, f"          Overall defect rate {anomalies['overall']['overall_defect_rate']:.2%} | "
                  f"escalate {esc['n_escalate']} / watch {esc['n_watch']} nodes | "
                  f"{len(events)} anomalous node-days vs same-weekday baseline")

    _log(verbose, "Step 4/7  Root cause (Pareto, weighted impact, contribution)...")
    contribution = wh.run("05_contribution")
    wow_nodes = wh.run("03_wow_by_node")
    top = root["top_3_priorities"]
    _log(verbose, f"          Top driver by impact: {top[0]['label']} (score {top[0]['impact_score']:.4f})")

    supply = None
    sc = pol = None
    if has_supply:
        _log(verbose, "Step 5/7  Supply: supplier OTIF, forecast, safety stock...")
        sc = supplier.run_all(wh.run("07_supplier_scorecard"))
        inv_res = inventory.run_all(wh.run("09_daily_demand"), wh.run("08_inventory_position"),
                                    sc["scorecard"], sup)
        pol = inv_res["policy"]
        supply = {
            "policy": pol, "accuracy": inv_res["accuracy"], "forecast": inv_res["forecast"],
            "daily_demand": wh.run("09_daily_demand"), "supplier_scorecard": sc["scorecard"],
            "inventory_summary": inv_res["summary"], "supplier_summary": sc["summary"],
        }
        _log(verbose, f"          Network OTIF {sc['summary']['network_otif']:.1%} | fill rate "
                      f"{inv_res['summary']['network_fill_rate']:.1%} | forecast WAPE "
                      f"{inv_res['summary']['median_wape']:.1%} (median)")
    else:
        _log(verbose, "Step 5/7  Supply: skipped (no inventory / PO data supplied)")

    _log(verbose, "Step 6/7  Building escalation queue...")
    queue = escalation.build_queue(
        df["date"].max(), contribution, rolling, avg_defect_cost(df),
        sc["scorecard"] if sc else None, pol)
    counts = queue["priority"].value_counts().to_dict() if len(queue) else {}
    _log(verbose, f"          {len(queue)} items: P1={counts.get('P1', 0)} P2={counts.get('P2', 0)} P3={counts.get('P3', 0)}")

    _log(verbose, "Step 7/7  Building Excel workbook...")
    path = build_workbook(df=df, anomalies=anomalies, root=root, memo_text="",
                          output_path=output_path, queue=queue, supply=supply, simulated=simulated)
    _log(verbose, f"          Saved: {path}")

    if verbose:
        print()
        print("TOP ESCALATIONS")
        print("-" * 60)
        for _, q in queue.head(5).iterrows():
            print(f"  {q['id']} {q['priority']} score {q['severity_score']:>3}  {q['entity']}")
            print(f"      {q['issue'][:100]}")
            print(f"      Owner: {q['owner']}  Due: {q['due_date']}  Est. ${q['est_cost_usd']:,.0f}")
        print()
        print(f"Week-over-week trend: {anomalies['wow']['direction']} ({anomalies['wow']['delta']:+.2%})")

    result = {
        "status": "ok",
        "pipeline": "direct",
        "simulated": simulated,
        "records": len(df),
        "reconciliation": checks,
        "anomalies": {
            "overall": anomalies["overall"],
            "escalation": esc,
            "wow": anomalies["wow"],
            "nodes": anomalies["nodes"].to_dict("records"),
            "carriers": anomalies["carriers"].to_dict("records"),
            "rolling_events": int(len(events)),
            "wow_by_node": wow_nodes.to_dict("records"),
        },
        "root_cause": {
            "top_3": root["top_3_priorities"],
            "pareto": root["pareto"].to_dict("records"),
            "weighted": root["weighted_impact"].to_dict("records"),
            "contribution_top": contribution[contribution["rank_in_dimension"] <= 3].to_dict("records"),
        },
        "supply": None if supply is None else {
            "inventory": supply["inventory_summary"],
            "suppliers": supply["supplier_summary"],
        },
        "queue": queue.to_dict("records"),
        "output_path": str(path),
        # kept for callers that want the frames (dashboard, tests)
        "_frames": {"df": df, "anomalies": anomalies, "root": root, "queue": queue,
                    "supply": supply, "warehouse": wh, "rolling": rolling,
                    "contribution": contribution},
    }
    return result


def _cli() -> None:
    ap = argparse.ArgumentParser(description="AB Defect Intelligence - direct pipeline")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=None, help="output .xlsx path")
    ap.add_argument("--csv", help="fulfillment CSV (see modules/data_loader.py for schema)")
    ap.add_argument("--inventory-csv")
    ap.add_argument("--po-csv")
    args = ap.parse_args()

    data = None
    if args.csv:
        from modules import data_loader as dl
        fulfil = dl.load_fulfillment_csv(args.csv)
        inv = dl.load_inventory_csv(args.inventory_csv) if args.inventory_csv else None
        pos = dl.load_po_csv(args.po_csv) if args.po_csv else None
        sup = dl.suppliers_from_pos(pos, inv) if pos is not None else None
        data = {"fulfillment": fulfil, "inventory": inv, "purchase_orders": pos, "suppliers": sup}
    run(seed=args.seed, n_days=args.days, output_path=args.out, data=data)


if __name__ == "__main__":
    _cli()
