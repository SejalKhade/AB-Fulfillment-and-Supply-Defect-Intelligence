"""
AB Supply Data Generator  (SIMULATED DATA — not real Amazon data)

Generates the inventory and supplier side of the network so the analytics
can cover more than outbound defects:

  inventory   daily on-hand / demand / stockout per node x category
  purchase_orders  one row per replenishment PO (promised vs actual dates)
  suppliers   supplier master (one supplier per category)

Demand is NOT invented separately: it is the shipment volume already in the
fulfillment table (1 unit per shipment — documented assumption), so inventory
and fulfillment tell one coherent story.

Seeded patterns the analytics should find:
  * Electronics supplier is late on most POs and short-ships often
  * Furniture supplier has high lead-time variability (needs bigger safety stock)
  * IT Hardware supplier is moderately unreliable
  * SEA-2 Electronics has shrink (inventory accuracy problem, matches the
    fulfillment generator's seeded SEA-2 defect pattern)
The replenishment policy used in the simulation deliberately carries NO safety
stock, so the safety-stock analysis has something real to recommend.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# supplier_id: (category, promised_lead_days, late_prob, late_days_mean, late_days_sd,
#               short_prob, short_fill_low, short_fill_high, unit_cost)
# A PO is late with probability late_prob (then by ~late_days_mean days) and short-shipped
# with probability short_prob (then fills between short_fill_low and short_fill_high).
SUPPLIER_SPEC = {
    "SUP-ELEC-01": ("Electronics",     7, 0.85, 4.0, 2.0, 0.80, 0.70, 0.95,  42.0),
    "SUP-OFFC-02": ("Office Supplies", 5, 0.02, 1.5, 0.5, 0.02, 0.90, 0.97,   6.5),
    "SUP-JANI-03": ("Janitorial",      6, 0.05, 1.5, 0.8, 0.03, 0.88, 0.97,   9.0),
    "SUP-FOOD-04": ("Food & Beverage", 3, 0.07, 1.2, 0.5, 0.03, 0.90, 0.97,   4.0),
    "SUP-MEDI-05": ("Medical",         8, 0.03, 1.5, 0.7, 0.01, 0.92, 0.97,  21.0),
    "SUP-SAFE-06": ("Safety",          6, 0.03, 1.5, 0.7, 0.02, 0.90, 0.97,  15.0),
    "SUP-FURN-07": ("Furniture",      14, 0.35, 6.0, 4.0, 0.10, 0.75, 0.95,  88.0),
    "SUP-ITHW-08": ("IT Hardware",    10, 0.45, 3.0, 1.5, 0.25, 0.80, 0.96, 120.0),
}

SHRINK_NODE, SHRINK_CATEGORY, SHRINK_RATE = "SEA-2", "Electronics", 0.015
POLICY_COVER_FACTOR = 1.15   # ROP = trailing demand * promised LT * 1.15, no safety stock
ORDER_UP_TO_DAYS = 10        # order up to ROP + 10 days of demand


def suppliers_table() -> pd.DataFrame:
    rows = [
        {"supplier_id": sid, "category": v[0], "promised_lead_days": v[1],
         "unit_cost": v[8]}
        for sid, v in SUPPLIER_SPEC.items()
    ]
    return pd.DataFrame(rows)


def generate_supply(fulfillment: pd.DataFrame, seed: int = 42
                    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (inventory, purchase_orders, suppliers)."""
    rng = np.random.default_rng(seed + 1000)
    cat_to_sup = {v[0]: sid for sid, v in SUPPLIER_SPEC.items()}

    demand = (fulfillment.groupby(["date", "node", "category"])["total_shipments"]
              .sum().rename("demand").reset_index())
    dates = sorted(demand["date"].unique())

    inv_rows, po_rows = [], []
    po_seq = 0

    for (node, category), grp in demand.groupby(["node", "category"]):
        sid = cat_to_sup[category]
        _, lt, late_p, late_mu, late_sd, short_p, short_lo, short_hi, cost = SUPPLIER_SPEC[sid]
        series = grp.set_index("date")["demand"].reindex(dates).fillna(0).astype(int)

        on_hand = int(round(series.iloc[:14].mean() * 14))
        pipeline: list[tuple[int, int, int]] = []   # (arrival_index, qty_received, qty_ordered)
        open_po_qty = 0
        history: list[int] = []

        for t, date in enumerate(dates):
            d = int(series.iloc[t])
            landing = [(r, o) for (a, r, o) in pipeline if a == t]
            arrived = sum(r for r, _ in landing)
            open_po_qty -= sum(o for _, o in landing)
            pipeline = [x for x in pipeline if x[0] != t]
            on_hand += arrived

            shrink = 0
            if node == SHRINK_NODE and category == SHRINK_CATEGORY:
                shrink = int(round(on_hand * SHRINK_RATE))
                on_hand -= shrink

            fulfilled = min(on_hand, d)
            stockout = d - fulfilled
            on_hand -= fulfilled
            history.append(d)

            trailing = float(np.mean(history[-14:]))
            rop = trailing * lt * POLICY_COVER_FACTOR
            position = on_hand + open_po_qty
            if position <= rop:
                qty = int(round(rop + trailing * ORDER_UP_TO_DAYS - position))
                delay = (max(1, int(round(rng.normal(late_mu, late_sd))))
                         if rng.random() < late_p else 0)
                actual_lt = lt + delay
                fill = float(rng.uniform(short_lo, short_hi)) if rng.random() < short_p else 1.0
                recv_qty = int(round(qty * fill))
                arrival = t + actual_lt
                po_seq += 1
                order_date = pd.Timestamp(date)
                received = arrival < len(dates)
                po_rows.append({
                    "po_id": f"PO{po_seq:06d}",
                    "supplier_id": sid,
                    "node": node,
                    "category": category,
                    "order_date": order_date.strftime("%Y-%m-%d"),
                    "promised_date": (order_date + pd.Timedelta(days=lt)).strftime("%Y-%m-%d"),
                    "received_date": ((order_date + pd.Timedelta(days=actual_lt)).strftime("%Y-%m-%d")
                                      if received else None),
                    "qty_ordered": qty,
                    "qty_received": recv_qty if received else None,
                    "unit_cost": cost,
                })
                open_po_qty += qty
                if received:
                    pipeline.append((arrival, recv_qty, qty))

            inv_rows.append({
                "date": date, "node": node, "category": category,
                "supplier_id": sid, "demand_units": d,
                "receipts_units": arrived, "fulfilled_units": fulfilled,
                "stockout_units": stockout, "shrink_units": shrink,
                "on_hand_end": on_hand, "on_order_end": max(open_po_qty, 0),
                "unit_cost": cost,
            })

    inventory = pd.DataFrame(inv_rows).sort_values(["date", "node", "category"]).reset_index(drop=True)
    pos = pd.DataFrame(po_rows)
    return inventory, pos, suppliers_table()


if __name__ == "__main__":
    from modules.data_generator import generate
    f = generate(n_days=90)
    inv, pos, sup = generate_supply(f)
    print(f"inventory rows: {len(inv):,} | POs: {len(pos):,}")
    print(f"fill rate: {inv.fulfilled_units.sum() / inv.demand_units.sum():.2%}")
