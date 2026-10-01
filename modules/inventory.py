"""
Inventory analytics: demand forecast + safety stock / reorder point.

Forecast (per node x category series, 3 candidate methods, chosen by backtest):
  ma7     flat forecast = mean of the last 7 days
  ses     simple exponential smoothing, alpha picked by one-step in-sample SSE
  dow     level (mean of last 28 days) x weekday index (captures the weekly cycle)
Backtest: hold out the last FORECAST_HOLDOUT_DAYS days, train on the rest,
score with WAPE = sum|actual - forecast| / sum(actual). Best method per series
is refit on all data and projected FORECAST_HORIZON_DAYS ahead.

Safety stock (standard formula, demand AND lead-time variability):
  SS  = z * sqrt( LT * sd_d^2 + d^2 * sd_LT^2 )
  ROP = d * LT + SS
where d, sd_d are trailing-14-day daily demand mean / std, and LT, sd_LT come
from the supplier's observed lead times on received POs (SQL: 07_supplier_scorecard).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config
from modules.supply_generator import POLICY_COVER_FACTOR

METHODS = ("ma7", "ses", "dow")
ALPHAS = (0.1, 0.2, 0.3, 0.5, 0.7)


# ── forecasting ────────────────────────────────────────────────────────────
def _ses_level(y: np.ndarray, alpha: float) -> tuple[float, float]:
    level, sse = y[0], 0.0
    for v in y[1:]:
        sse += (v - level) ** 2
        level = alpha * v + (1 - alpha) * level
    return level, sse


def _forecast(method: str, y: np.ndarray, dows: np.ndarray, future_dows: np.ndarray) -> np.ndarray:
    n = len(future_dows)
    if method == "ma7":
        return np.full(n, y[-7:].mean())
    if method == "ses":
        best = min((_ses_level(y, a) + (a,) for a in ALPHAS), key=lambda t: t[1])
        return np.full(n, best[0])
    if method == "dow":
        overall = y.mean()
        idx = {d: (y[dows == d].mean() / overall if overall else 1.0) for d in range(7)}
        level = y[-28:].mean()
        return np.array([level * idx.get(d, 1.0) for d in future_dows])
    raise ValueError(method)


def _wape(actual: np.ndarray, fc: np.ndarray) -> float:
    denom = actual.sum()
    return float(np.abs(actual - fc).sum() / denom) if denom else float("nan")


def forecast_demand(daily: pd.DataFrame,
                    horizon: int = config.FORECAST_HORIZON_DAYS,
                    holdout: int = config.FORECAST_HOLDOUT_DAYS
                    ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    daily: columns date, node, category, demand_units (one row per day per series).
    Returns (forecast_long, accuracy).
    """
    daily = daily.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    fc_rows, acc_rows = [], []

    for (node, category), g in daily.groupby(["node", "category"]):
        g = g.sort_values("date")
        y = g["demand_units"].to_numpy(dtype=float)
        dows = g["date"].dt.dayofweek.to_numpy()
        if len(y) < holdout + 28:
            continue
        train_y, train_d = y[:-holdout], dows[:-holdout]
        test_y, test_d = y[-holdout:], dows[-holdout:]

        scores = {m: _wape(test_y, _forecast(m, train_y, train_d, test_d)) for m in METHODS}
        best = min(scores, key=lambda m: (np.inf if np.isnan(scores[m]) else scores[m]))
        naive = _wape(test_y, np.full(holdout, train_y[-7:].mean()))

        last = g["date"].max()
        fdates = pd.date_range(last + pd.Timedelta(days=1), periods=horizon)
        fvals = _forecast(best, y, dows, fdates.dayofweek.to_numpy())
        for d, v in zip(fdates, fvals):
            fc_rows.append({"node": node, "category": category,
                            "date": d.strftime("%Y-%m-%d"),
                            "forecast_units": round(float(v), 1), "method": best})
        acc_rows.append({
            "node": node, "category": category,
            "wape_ma7": scores["ma7"], "wape_ses": scores["ses"], "wape_dow": scores["dow"],
            "best_method": best, "best_wape": scores[best],
            "improvement_vs_naive": (naive - scores[best]) / naive if naive else float("nan"),
            "forecast_total": float(fvals.sum()),
        })
    return pd.DataFrame(fc_rows), pd.DataFrame(acc_rows)


# ── safety stock / reorder point ───────────────────────────────────────────
def inventory_policy(position: pd.DataFrame, supplier_sc: pd.DataFrame,
                     suppliers: pd.DataFrame, accuracy: pd.DataFrame,
                     z: float = config.SERVICE_LEVEL_Z) -> pd.DataFrame:
    """Join position (SQL 08) with supplier lead-time stats and compute policy + status."""
    lt = supplier_sc[["supplier_id", "lead_time_mean", "lead_time_sd"]]
    prom = suppliers[["supplier_id", "promised_lead_days"]]
    df = (position.merge(lt, on="supplier_id", how="left")
                  .merge(prom, on="supplier_id", how="left")
                  .merge(accuracy[["node", "category", "best_method", "best_wape", "forecast_total"]],
                         on=["node", "category"], how="left"))

    d, sd_d = df["avg_daily_demand"], df["sd_daily_demand"]
    LT, sd_lt = df["lead_time_mean"], df["lead_time_sd"]
    df["safety_stock"] = z * np.sqrt(LT * sd_d ** 2 + d ** 2 * sd_lt ** 2)
    df["reorder_point"] = d * LT + df["safety_stock"]
    df["current_policy_rop"] = d * df["promised_lead_days"] * POLICY_COVER_FACTOR
    df["rop_gap_units"] = df["reorder_point"] - df["current_policy_rop"]
    df["inventory_position"] = df["on_hand"] + df["on_order"]
    df["order_up_to"] = df["reorder_point"] + d * 7
    df["recommended_order_qty"] = (df["order_up_to"] - df["inventory_position"]).clip(lower=0)
    df["forecast_daily"] = df["forecast_total"] / config.FORECAST_HORIZON_DAYS
    df["forecast_days_of_supply"] = df["on_hand"] / df["forecast_daily"].replace(0, np.nan)
    df["lost_margin_usd"] = df["stockout_units"] * df["unit_cost"] * config.STOCKOUT_MARGIN

    def status(r) -> str:
        if r["on_hand"] <= 0:
            return "STOCKED OUT"
        if r["inventory_position"] < r["reorder_point"]:
            return "REORDER"
        if r["days_of_supply"] > config.EXCESS_DAYS_OF_SUPPLY:
            return "EXCESS"
        return "OK"

    df["status"] = df.apply(status, axis=1)
    for c in ("safety_stock", "reorder_point", "current_policy_rop", "rop_gap_units",
              "order_up_to", "recommended_order_qty"):
        df[c] = df[c].round(0)
    order = {"STOCKED OUT": 0, "REORDER": 1, "EXCESS": 2, "OK": 3}
    df["_o"] = df["status"].map(order)
    return (df.sort_values(["_o", "lost_margin_usd"], ascending=[True, False])
              .drop(columns="_o").reset_index(drop=True))


def run_all(daily: pd.DataFrame, position: pd.DataFrame,
            supplier_sc: pd.DataFrame, suppliers: pd.DataFrame) -> dict:
    fc, acc = forecast_demand(daily)
    pol = inventory_policy(position, supplier_sc, suppliers, acc)
    return {
        "forecast": fc,
        "accuracy": acc,
        "policy": pol,
        "summary": {
            "series": int(len(pol)),
            "stocked_out": int((pol["status"] == "STOCKED OUT").sum()),
            "reorder": int((pol["status"] == "REORDER").sum()),
            "excess": int((pol["status"] == "EXCESS").sum()),
            "network_fill_rate": float(position["fulfilled_units"].sum()
                                       / position["demand_units"].sum()),
            "lost_margin_usd": float(pol["lost_margin_usd"].sum()),
            "median_wape": float(acc["best_wape"].median()) if len(acc) else None,
        },
    }
