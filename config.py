"""
Central configuration. Every threshold, weight and cost assumption lives here
so it can be defended, challenged and changed in one place.

IMPORTANT: all values marked ASSUMPTION are illustrative placeholders for the
simulated dataset. In a real deployment the business owner sets them
(weights from customer-contact / refund data, costs from finance).
"""

from __future__ import annotations

# ── Detection thresholds ───────────────────────────────────────────────────
DEFECT_THRESHOLD = 0.05      # >= 5%  -> ESCALATE
WARNING_THRESHOLD = 0.035    # >= 3.5% -> WATCH (calibrated to the ~3.3% simulated network baseline)
ZSCORE_FLAG = 2.0            # cross-node z-score flag
ROLLING_Z_FLAG = 3.0         # node-day vs same-weekday baseline
ROLLING_MIN_EXCESS = 0.01    # and at least +1.0pp above its own baseline
ROLLING_BASELINE_WEEKS = 4   # same-weekday observations in the baseline

# ── Customer-impact weights per defect type (ASSUMPTION) ───────────────────
DEFECT_WEIGHTS = {
    "failed_pickup":         0.35,   # never reaches customer
    "late_delivery":         0.25,   # SLA breach
    "missing_package":       0.20,   # refund / reship
    "damaged_goods":         0.12,   # return + replacement
    "wrong_item":            0.05,   # exchange only
    "inventory_discrepancy": 0.03,   # internal only
}

# ── Cost per defect in USD (ASSUMPTION) ────────────────────────────────────
COST_PER_DEFECT = {
    "failed_pickup":         14.0,
    "late_delivery":          6.5,
    "missing_package":       38.0,
    "damaged_goods":         27.0,
    "wrong_item":            12.0,
    "inventory_discrepancy":  4.0,
}

# ── Inventory policy ───────────────────────────────────────────────────────
SERVICE_LEVEL_Z = 1.645      # 95% cycle service level
EXCESS_DAYS_OF_SUPPLY = 45   # above this = excess stock
FORECAST_HORIZON_DAYS = 14
FORECAST_HOLDOUT_DAYS = 14
STOCKOUT_MARGIN = 0.22       # margin lost per stocked-out unit cost (ASSUMPTION)

# ── Supplier targets ───────────────────────────────────────────────────────
OTIF_TARGET = 0.95
OTIF_WATCH = 0.90
IN_FULL_TOLERANCE = 0.98     # received >= 98% of ordered counts as in-full

# ── Escalation workflow ────────────────────────────────────────────────────
SLA_DAYS = {"P1": 1, "P2": 3, "P3": 7}
P1_SCORE = 70
P2_SCORE = 40
# Materiality cap per domain: the dollar value at which the impact component saturates.
# Domains have different cost scales (a $25k carrier issue and a $1M supplier shortfall are
# equally material), so each domain gets its own cap. ASSUMPTION - set with finance.
COST_CAP_USD = {"Fulfillment": 30_000, "Supplier": 1_000_000, "Inventory": 400_000}
EVENT_LOOKBACK_DAYS = 30     # rolling-anomaly events newer than this get a post-event review item
MAX_ITEMS_PER_SOURCE = 5

OWNERS = {
    "carrier":   "Carrier Operations Manager",
    "node":      "FC Operations Manager",
    "inventory": "Inventory Control Lead",
    "supplier":  "Vendor Management Lead",
}

# ── Claude ─────────────────────────────────────────────────────────────────
import os  # noqa: E402

CLAUDE_MODEL = os.environ.get("AB_CLAUDE_MODEL", "claude-sonnet-5-5")
