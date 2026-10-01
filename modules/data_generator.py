"""
AB Fulfillment Data Generator  (SIMULATED DATA — not real Amazon data)
Generates 90 days of realistic Amazon Business fulfillment network data
across 12 fulfillment nodes, 6 carriers, and 8 product categories.

Intentionally seeds defect patterns that mirror real AB SC problems:
- Node PHX-7 has a chronic late pickup defect (carrier AMZL)
- Node DAL-3 has a weather-related spike in week 8
- Node SEA-2 has an inventory accuracy problem (product category: Electronics)
- Multiple nodes show day-of-week patterns (Monday spikes)
"""

import random
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

NODES = [
    "PHX-7", "PHX-12", "DAL-3", "DAL-9", "SEA-2",
    "CHI-4", "ATL-6", "NYC-1", "LAX-5", "MIA-8",
    "DEN-2", "HOU-11"
]

CARRIERS = ["AMZL", "UPS", "FedEx", "USPS", "OnTrac", "LaserShip"]

CATEGORIES = [
    "Electronics", "Office Supplies", "Janitorial",
    "Food & Beverage", "Medical", "Safety", "Furniture", "IT Hardware"
]

DEFECT_TYPES = [
    "Late Delivery", "Missing Package", "Damaged Goods",
    "Wrong Item", "Inventory Discrepancy", "Failed Pickup"
]

BASE_DATE = datetime(2026, 7, 1)

# Shipment-volume seasonality by weekday (Mon=0). Gives the demand forecast
# a real weekly pattern to learn.
WEEKDAY_VOLUME = {0: 1.10, 1: 1.05, 2: 1.00, 3: 1.00, 4: 1.05, 5: 0.85, 6: 0.80}

WEATHER_EVENTS = {
    55: ("DAL-3", "Severe Storm", 2.8),   # Day 55 — Dallas storm
    71: ("SEA-2", "Heavy Snow", 1.9),      # Day 71 — Seattle snow
    82: ("CHI-4", "Blizzard", 3.2),        # Day 82 — Chicago blizzard
}


def seed_defect_rate(node, carrier, category, day, base_rate=0.035):
    """
    Generate realistic defect rate with seeded patterns.
    These patterns are what the anomaly detector should catch.
    """
    rate = base_rate

    # PHX-7 + AMZL = chronic failed pickup problem (+40% baseline)
    if node == "PHX-7" and carrier == "AMZL":
        rate *= 1.40

    # SEA-2 + Electronics = inventory accuracy problem (+60%)
    if node == "SEA-2" and category == "Electronics":
        rate *= 1.60

    # Monday spike across all nodes (+25%)
    if (BASE_DATE + timedelta(days=day - 1)).weekday() == 0:
        rate *= 1.25

    # Weather events
    for event_day, (event_node, _, multiplier) in WEATHER_EVENTS.items():
        if node == event_node and abs(day - event_day) <= 2:
            rate *= multiplier

    # Random noise
    rate *= np.random.uniform(0.75, 1.25)
    return min(rate, 0.35)  # cap at 35%


def generate(n_days: int = 90, seed: int = 42) -> pd.DataFrame:
    """Generate full fulfillment dataset."""
    np.random.seed(seed)
    random.seed(seed)

    records = []
    base_date = BASE_DATE

    for day in range(1, n_days + 1):
        date = base_date + timedelta(days=day - 1)
        for node in NODES:
            for carrier in CARRIERS:
                for category in CATEGORIES:
                    lam = (180 if carrier == "AMZL" else 95) * WEEKDAY_VOLUME[date.weekday()]
                    n_shipments = int(np.random.poisson(lam=lam))
                    if n_shipments == 0:
                        continue

                    defect_rate = seed_defect_rate(node, carrier, category, day)
                    n_defects = int(n_shipments * defect_rate)

                    # Defect breakdown
                    if n_defects > 0:
                        weights = [0.35, 0.15, 0.12, 0.10, 0.18, 0.10]
                        defect_breakdown = np.random.multinomial(n_defects, weights)
                    else:
                        defect_breakdown = [0] * 6

                    avg_delivery_hrs = np.random.normal(
                        loc=28 if defect_rate < 0.05 else 42,
                        scale=4
                    )

                    records.append({
                        "date":                date.strftime("%Y-%m-%d"),
                        "day_num":             day,
                        "weekday":             date.strftime("%A"),
                        "node":                node,
                        "carrier":             carrier,
                        "category":            category,
                        "total_shipments":     n_shipments,
                        "total_defects":       n_defects,
                        "defect_rate":         round(defect_rate, 5),
                        "late_delivery":       defect_breakdown[0],
                        "missing_package":     defect_breakdown[1],
                        "damaged_goods":       defect_breakdown[2],
                        "wrong_item":          defect_breakdown[3],
                        "inventory_discrepancy": defect_breakdown[4],
                        "failed_pickup":       defect_breakdown[5],
                        "avg_delivery_hrs":    round(avg_delivery_hrs, 1),
                        "weather_event":       next(
                            (evt[1] for d, (n, evt, _) in WEATHER_EVENTS.items()
                             if node == n and abs(day - d) <= 2),
                            None
                        ),
                    })

    df = pd.DataFrame(records)
    df["on_time_rate"] = 1 - df["defect_rate"]
    return df


if __name__ == "__main__":
    df = generate()
    print(f"Generated {len(df):,} records")
    print(f"Nodes: {df['node'].nunique()} | Carriers: {df['carrier'].nunique()}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print("\nTop 5 node+carrier defect rates:")
    print(
        df.groupby(["node", "carrier"])["defect_rate"]
        .mean()
        .sort_values(ascending=False)
        .head(5)
        .round(4)
    )
