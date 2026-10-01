"""
Bring-your-own-data loaders. Lets the pipeline run on a real extract
(e.g. a public logistics dataset reshaped to this schema, or a company export)
instead of the simulator.

Fulfillment CSV - required columns (names can be remapped with column_map):
    date, node, carrier, category, total_shipments, total_defects
Optional (default 0 if missing; root-cause analysis needs them to be meaningful):
    late_delivery, missing_package, damaged_goods, wrong_item,
    inventory_discrepancy, failed_pickup, avg_delivery_hrs, weather_event

Inventory CSV:  date, node, category, supplier_id, demand_units, fulfilled_units,
                stockout_units, on_hand_end, on_order_end, unit_cost
                (optional: receipts_units, shrink_units)
PO CSV:         po_id, supplier_id, order_date, promised_date, received_date,
                qty_ordered, qty_received, unit_cost  (optional: node, category)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import config

REQUIRED = ["date", "node", "carrier", "category", "total_shipments", "total_defects"]
DEFECT_COLS = list(config.DEFECT_WEIGHTS)
INV_REQUIRED = ["date", "node", "category", "supplier_id", "demand_units", "fulfilled_units",
                "stockout_units", "on_hand_end", "on_order_end", "unit_cost"]
PO_REQUIRED = ["po_id", "supplier_id", "order_date", "promised_date", "received_date",
               "qty_ordered", "qty_received", "unit_cost"]


class DataError(ValueError):
    pass


def _check(df: pd.DataFrame, required: list[str], what: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataError(f"{what}: missing required columns {missing}")


def load_fulfillment_csv(path: str | Path, column_map: dict | None = None) -> pd.DataFrame:
    df = pd.read_csv(path)
    if column_map:
        df = df.rename(columns=column_map)
    _check(df, REQUIRED, "fulfillment CSV")
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    for c in DEFECT_COLS:
        if c not in df.columns:
            df[c] = 0
    if "avg_delivery_hrs" not in df.columns:
        df["avg_delivery_hrs"] = np.nan
    if "weather_event" not in df.columns:
        df["weather_event"] = None
    if (df["total_defects"] > df["total_shipments"]).any():
        raise DataError("fulfillment CSV: total_defects exceeds total_shipments on some rows")
    if (df[["total_shipments", "total_defects"]] < 0).any().any():
        raise DataError("fulfillment CSV: negative counts found")
    dt = pd.to_datetime(df["date"])
    df["weekday"] = dt.dt.day_name()
    df["day_num"] = (dt - dt.min()).dt.days + 1
    df["defect_rate"] = df["total_defects"] / df["total_shipments"].replace(0, np.nan)
    df["on_time_rate"] = 1 - df["defect_rate"]
    return df


def load_inventory_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    _check(df, INV_REQUIRED, "inventory CSV")
    for c in ("receipts_units", "shrink_units"):
        if c not in df.columns:
            df[c] = 0
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df


def load_po_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    _check(df, PO_REQUIRED, "PO CSV")
    for c in ("node", "category"):
        if c not in df.columns:
            df[c] = None
    return df


def suppliers_from_pos(pos: pd.DataFrame, inventory: pd.DataFrame | None = None) -> pd.DataFrame:
    """Derive the supplier master from POs when the user has no separate file."""
    g = pos.groupby("supplier_id").agg(unit_cost=("unit_cost", "mean")).reset_index()
    lt = (pd.to_datetime(pos["promised_date"]) - pd.to_datetime(pos["order_date"])).dt.days
    g["promised_lead_days"] = lt.groupby(pos["supplier_id"]).median().reindex(g["supplier_id"]).values
    if inventory is not None:
        cat = inventory.groupby("supplier_id")["category"].agg(lambda s: s.mode().iat[0])
        g["category"] = g["supplier_id"].map(cat)
    else:
        g["category"] = "Unknown"
    return g[["supplier_id", "category", "promised_lead_days", "unit_cost"]]
