"""
DuckDB warehouse. Loads the fulfillment, inventory, purchase-order and
supplier tables and runs the named SQL files in sql/.

All heavy aggregation is done in SQL (CTEs, window functions, UNPIVOT,
conditional aggregation). Python only orchestrates and post-processes.

Named queries take bound parameters ($name) for values and {name} templating
for integer window sizes (SQL cannot bind a frame bound). Parameters default
to config.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd

import config

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

DEFAULT_PARAMS = {
    "esc": config.DEFECT_THRESHOLD,
    "warn": config.WARNING_THRESHOLD,
    "z": config.ROLLING_Z_FLAG,
    "min_excess": config.ROLLING_MIN_EXCESS,
    "weeks": config.ROLLING_BASELINE_WEEKS,
    "tol": config.IN_FULL_TOLERANCE,
    "otif_target": config.OTIF_TARGET,
    "otif_watch": config.OTIF_WATCH,
}

_READONLY = re.compile(r"^\s*(with|select|describe|show|summarize|from)\b", re.I)
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|copy|export|import|"
    r"install|load|pragma|call|set)\b", re.I)

DATE_COLS = {
    "fulfillment": ["date"],
    "inventory": ["date"],
    "purchase_orders": ["order_date", "promised_date", "received_date"],
}


class Warehouse:
    def __init__(self) -> None:
        self.con = duckdb.connect(":memory:")

    # ── loading ────────────────────────────────────────────────────────────
    def load(self, fulfillment: pd.DataFrame,
             inventory: pd.DataFrame | None = None,
             purchase_orders: pd.DataFrame | None = None,
             suppliers: pd.DataFrame | None = None) -> "Warehouse":
        frames = {"fulfillment": fulfillment, "inventory": inventory,
                  "purchase_orders": purchase_orders, "suppliers": suppliers}
        for name, df in frames.items():
            if df is None:
                continue
            self.con.register(f"_stg_{name}", df)
            casts = ", ".join(f"CAST({c} AS DATE) AS {c}" for c in DATE_COLS.get(name, [])
                              if c in df.columns)
            replace = f" REPLACE ({casts})" if casts else ""
            self.con.execute(
                f"CREATE OR REPLACE TABLE {name} AS SELECT *{replace} FROM _stg_{name}")
            self.con.unregister(f"_stg_{name}")
        return self

    def tables(self) -> list[str]:
        return [r[0] for r in self.con.execute("SHOW TABLES").fetchall()]

    # ── named queries ──────────────────────────────────────────────────────
    @staticmethod
    def list_queries() -> list[str]:
        return sorted(p.stem for p in SQL_DIR.glob("*.sql"))

    @staticmethod
    def query_text(name: str) -> str:
        return (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")

    def run(self, name: str, **overrides) -> pd.DataFrame:
        """Run sql/<name>.sql. Unused parameters are ignored."""
        text = self.query_text(name)
        params = {**DEFAULT_PARAMS, **overrides}
        for key in re.findall(r"\{(\w+)\}", text):
            text = text.replace("{" + key + "}", str(int(params[key])))
        used = {k: v for k, v in params.items() if re.search(rf"\${k}\b", text)}
        return self.con.execute(text, used).df()

    # ── ad-hoc, read-only (dashboard SQL explorer) ─────────────────────────
    def sql(self, text: str, limit: int = 1000) -> pd.DataFrame:
        stmt = text.strip().rstrip(";")
        if ";" in stmt or not _READONLY.match(stmt) or _FORBIDDEN.search(stmt):
            raise ValueError("Only a single read-only SELECT / WITH query is allowed.")
        return self.con.execute(f"SELECT * FROM ({stmt}) LIMIT {int(limit)}").df()

    def close(self) -> None:
        self.con.close()
