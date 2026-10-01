-- Supplier OTIF scorecard from purchase orders.
--   on_time = received_date <= promised_date
--   in_full = qty_received >= tolerance * qty_ordered
--   OTIF    = on_time AND in_full   (the standard supply-chain definition)
-- Open POs (not yet received) are excluded from the rates and counted separately.
WITH recv AS (
    SELECT po.*,
           DATEDIFF('day', order_date, received_date)    AS lead_days,
           DATEDIFF('day', promised_date, received_date) AS days_late,
           received_date <= promised_date                AS on_time,
           qty_received >= $tol * qty_ordered            AS in_full
    FROM purchase_orders po
    WHERE received_date IS NOT NULL
),
open_pos AS (
    SELECT supplier_id, COUNT(*) AS open_pos
    FROM purchase_orders WHERE received_date IS NULL GROUP BY supplier_id
)
SELECT s.supplier_id, s.category,
       COUNT(*)                                       AS pos_received,
       AVG(CAST(r.on_time AS INT))                    AS on_time_rate,
       AVG(CAST(r.in_full AS INT))                    AS in_full_rate,
       AVG(CAST((r.on_time AND r.in_full) AS INT))    AS otif,
       AVG(r.lead_days)                               AS lead_time_mean,
       COALESCE(STDDEV_SAMP(r.lead_days), 0)          AS lead_time_sd,
       AVG(r.days_late)                               AS avg_days_late,
       SUM(r.qty_received) * 1.0 / SUM(r.qty_ordered) AS fill_rate,
       SUM(r.qty_received * r.unit_cost)              AS spend,
       SUM((r.qty_ordered - r.qty_received) * r.unit_cost) AS shortfall_value,
       COALESCE(o.open_pos, 0)                        AS open_pos,
       CASE WHEN AVG(CAST((r.on_time AND r.in_full) AS INT)) >= $otif_target THEN 'OK'
            WHEN AVG(CAST((r.on_time AND r.in_full) AS INT)) >= $otif_watch  THEN 'WATCH'
            ELSE 'ESCALATE' END                       AS status
FROM suppliers s
JOIN recv r ON r.supplier_id = s.supplier_id
LEFT JOIN open_pos o ON o.supplier_id = s.supplier_id
GROUP BY s.supplier_id, s.category, o.open_pos
ORDER BY otif ASC;
