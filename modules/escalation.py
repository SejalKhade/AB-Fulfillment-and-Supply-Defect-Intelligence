"""
Escalation queue: turns every analysis into one prioritised, owned, dated
action list. This is the part an SC Analyst's manager actually reads.

Severity score (0-100), identical formula for every source so items compare:

    score = 100 * ( 0.5 * impact + 0.5 * deviation )

    impact    = min(1, est_cost_usd / COST_CAP_USD[domain])   money at stake vs domain materiality
    deviation = how far the metric is from its benchmark, scaled 0..1 per source:
        segment   min(1, (rate_ratio - 1) / 0.75)        2x worse than network = ~1.0
        event     min(1, excess_rate / 0.06)             +6pp over own baseline = 1.0
        supplier  min(1, (OTIF target - OTIF) / target)
        inventory min(1, (1 - fill_rate) / 0.15)         85% fill rate = 1.0

    P1 >= P1_SCORE, P2 >= P2_SCORE, else P3.  SLA and owner come from config.

Sources: node x carrier / node x category contribution (SQL 05), recent
rolling-baseline anomaly events (SQL 02), supplier scorecard (SQL 07),
inventory policy (SQL 08 + modules/inventory).
"""

from __future__ import annotations

import pandas as pd

import config

DEFECT_COLS = list(config.DEFECT_WEIGHTS)


def _priority(score: float) -> str:
    return "P1" if score >= config.P1_SCORE else "P2" if score >= config.P2_SCORE else "P3"


def _score(domain: str, impact_usd: float, deviation: float) -> int:
    impact = min(1.0, max(0.0, impact_usd / config.COST_CAP_USD[domain]))
    dev = min(1.0, max(0.0, deviation))
    return int(round(100 * (0.5 * impact + 0.5 * dev)))


def _avg_cost(row: pd.Series) -> float:
    n = sum(row[c] for c in DEFECT_COLS)
    if not n:
        return 0.0
    return sum(row[c] * config.COST_PER_DEFECT[c] for c in DEFECT_COLS) / n


def _segment_items(contribution: pd.DataFrame) -> list[dict]:
    items = []
    for dim in ("carrier", "category"):
        sub = contribution[(contribution["dimension"] == dim)
                           & (contribution["rate_ratio"] >= 1.10)
                           & (contribution["excess_defects"] > 0)]
        for _, r in sub.head(config.MAX_ITEMS_PER_SOURCE).iterrows():
            cost = r["excess_defects"] * _avg_cost(r)
            label = r["top_defect"].replace("_", " ")
            items.append({
                "domain": "Fulfillment",
                "entity": f"{r['node']} / {r['segment']}",
                "issue": (f"{r['node']} x {r['segment']} defect rate {r['defect_rate']:.2%} is "
                          f"{r['rate_ratio']:.2f}x the network rate; main driver: {label}"),
                "metric": "defect_rate", "value": float(r["defect_rate"]),
                "benchmark": float(r["net_rate"]),
                "est_cost_usd": float(cost),
                "deviation": (r["rate_ratio"] - 1) / 0.75,
                "owner": config.OWNERS["carrier" if dim == "carrier" else "node"],
                "action": (f"Joint review with {'carrier' if dim == 'carrier' else 'FC'} owner: "
                           f"{r['excess_defects']:,.0f} excess defects over 90 days; "
                           f"root-cause {label} and agree a recovery plan with a weekly checkpoint."),
            })
    return items


def _event_items(anoms: pd.DataFrame, report_date: pd.Timestamp, avg_defect_cost: float) -> list[dict]:
    a = anoms[anoms["is_anomaly"]].sort_values(["node", "date"]).copy()
    if a.empty:
        return []
    a["date"] = pd.to_datetime(a["date"])
    a["grp"] = (a.groupby("node")["date"].diff().dt.days.fillna(99) > 1).cumsum()
    items = []
    for _, g in a.groupby("grp"):
        end = g["date"].max()
        if (report_date - end).days > config.EVENT_LOOKBACK_DAYS:
            continue
        node = g["node"].iloc[0]
        excess = float(g["excess_defects"].sum())
        peak = float(g["defect_rate"].max())
        items.append({
            "domain": "Fulfillment",
            "entity": f"{node} ({g['date'].min():%b %d}-{end:%b %d})",
            "issue": (f"{node} ran {len(g)} consecutive days far above its same-weekday baseline "
                      f"(peak {peak:.2%}, {excess:,.0f} excess defects)"),
            "metric": "peak_defect_rate", "value": peak,
            "benchmark": float(g["base_mean"].mean()),
            "est_cost_usd": excess * avg_defect_cost,
            "deviation": float(g["excess_rate"].max()) / 0.06,
            "owner": config.OWNERS["node"],
            "action": ("Post-event review: confirm cause (weather / carrier / FC), check backlog "
                       "cleared, and document the contingency plan for next occurrence."),
        })
    return items


def _supplier_items(sc: pd.DataFrame) -> list[dict]:
    items = []
    for _, r in sc[sc["status"] != "OK"].head(config.MAX_ITEMS_PER_SOURCE).iterrows():
        items.append({
            "domain": "Supplier",
            "entity": f"{r['supplier_id']} ({r['category']})",
            "issue": (f"OTIF {r['otif']:.1%} vs {config.OTIF_TARGET:.0%} target "
                      f"(on-time {r['on_time_rate']:.1%}, in-full {r['in_full_rate']:.1%}, "
                      f"avg {r['avg_days_late']:.1f} days late)"),
            "metric": "otif", "value": float(r["otif"]), "benchmark": config.OTIF_TARGET,
            "est_cost_usd": float(r["shortfall_value"]),
            "deviation": (config.OTIF_TARGET - r["otif"]) / config.OTIF_TARGET,
            "owner": config.OWNERS["supplier"],
            "action": (f"Supplier performance review: ${r['shortfall_value']:,.0f} of short-shipped "
                       f"value; agree corrective plan, lead-time commitment, and interim safety stock."),
        })
    return items


def _inventory_items(policy: pd.DataFrame) -> list[dict]:
    """Roll node x category series up to one item per category (one supplier, one root cause)."""
    cand = policy[(policy["fill_rate"] < 0.97) | (policy["status"] == "STOCKED OUT")]
    items = []
    for category, g in cand.groupby("category"):
        allcat = policy[policy["category"] == category]
        cat_fill = allcat["fulfilled_units"].sum() / allcat["demand_units"].sum()
        worst = g.sort_values("lost_margin_usd", ascending=False).iloc[0]
        shrunk = g[g["shrink_units"] > 0]
        shrink = (f"; {shrunk['node'].iloc[0]} also lost {int(shrunk['shrink_units'].iloc[0]):,} units "
                  f"to shrink - schedule a cycle count" if len(shrunk) else "")
        n_out = int((g["status"] == "STOCKED OUT").sum())
        items.append({
            "domain": "Inventory",
            "entity": f"{category} ({len(g)} of {len(allcat)} FCs)",
            "issue": (f"{category} fill rate {cat_fill:.1%}; {len(g)} FCs below 97% "
                      f"({n_out} stocked out now); worst {worst['node']} at {worst['fill_rate']:.1%} "
                      f"with {int(worst['stockout_days'])} stockout days; supplier {worst['supplier_id']}{shrink}"),
            "metric": "fill_rate", "value": float(cat_fill), "benchmark": 0.97,
            "est_cost_usd": float(g["lost_margin_usd"].sum()),
            "deviation": (1 - cat_fill) / 0.15,
            "owner": config.OWNERS["inventory"],
            "action": (f"Raise reorder points at {len(g)} FCs by {g['rop_gap_units'].sum():,.0f} units total "
                       f"(safety stock at z={config.SERVICE_LEVEL_Z}); place "
                       f"{g['recommended_order_qty'].sum():,.0f} units of open replenishment now; "
                       f"align with {worst['supplier_id']} escalation."),
        })
    items.sort(key=lambda i: -i["est_cost_usd"])
    return items[:config.MAX_ITEMS_PER_SOURCE]


def build_queue(report_date, contribution: pd.DataFrame, anomalies_daily: pd.DataFrame,
                avg_defect_cost: float, supplier_sc: pd.DataFrame | None = None,
                inventory_policy: pd.DataFrame | None = None) -> pd.DataFrame:
    report_date = pd.Timestamp(report_date)
    items = _segment_items(contribution) + _event_items(anomalies_daily, report_date, avg_defect_cost)
    if supplier_sc is not None:
        items += _supplier_items(supplier_sc)
    if inventory_policy is not None:
        items += _inventory_items(inventory_policy)

    for it in items:
        it["severity_score"] = _score(it["domain"], it["est_cost_usd"], it.pop("deviation"))
        it["priority"] = _priority(it["severity_score"])
        it["due_date"] = (report_date + pd.Timedelta(days=config.SLA_DAYS[it["priority"]])).strftime("%Y-%m-%d")
        it["status"] = "OPEN"

    q = pd.DataFrame(items)
    if q.empty:
        return q
    q = q.sort_values(["severity_score", "est_cost_usd"], ascending=False).reset_index(drop=True)
    q.insert(0, "id", [f"ESC-{i:03d}" for i in range(1, len(q) + 1)])
    return q[["id", "priority", "severity_score", "domain", "entity", "issue", "metric", "value",
              "benchmark", "est_cost_usd", "owner", "due_date", "action", "status"]]
