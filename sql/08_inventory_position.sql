-- Current inventory position per node x category.
-- Trailing 14-day demand mean/sd, latest on-hand, days of supply, whole-period fill rate.
WITH mx AS (SELECT MAX(date) AS max_d FROM inventory),
trail AS (
    SELECT i.node, i.category,
           AVG(i.demand_units)                      AS avg_daily_demand,
           COALESCE(STDDEV_SAMP(i.demand_units), 0) AS sd_daily_demand
    FROM inventory i CROSS JOIN mx
    WHERE i.date > mx.max_d - 14
    GROUP BY i.node, i.category
),
latest AS (
    SELECT i.node, i.category, i.supplier_id, i.on_hand_end, i.on_order_end, i.unit_cost
    FROM inventory i CROSS JOIN mx WHERE i.date = mx.max_d
),
hist AS (
    SELECT node, category,
           SUM(demand_units)    AS demand_units,
           SUM(fulfilled_units) AS fulfilled_units,
           SUM(stockout_units)  AS stockout_units,
           COUNT(*) FILTER (WHERE stockout_units > 0) AS stockout_days,
           SUM(shrink_units)    AS shrink_units
    FROM inventory GROUP BY node, category
)
SELECT l.node, l.category, l.supplier_id, l.unit_cost,
       l.on_hand_end AS on_hand, l.on_order_end AS on_order,
       t.avg_daily_demand, t.sd_daily_demand,
       l.on_hand_end / NULLIF(t.avg_daily_demand, 0) AS days_of_supply,
       h.fulfilled_units * 1.0 / h.demand_units       AS fill_rate,
       h.demand_units, h.fulfilled_units,
       h.stockout_units, h.stockout_days, h.shrink_units
FROM latest l
JOIN trail t USING (node, category)
JOIN hist  h USING (node, category)
ORDER BY l.node, l.category;
