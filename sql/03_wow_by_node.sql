-- Last 7 days vs prior 7 days per node (relative to the latest date in the data).
-- Technique: tag rows with a window label, then conditional aggregation (CASE inside SUM).
WITH mx AS (SELECT MAX(date) AS max_d FROM fulfillment),
tagged AS (
    SELECT f.node, f.total_shipments, f.total_defects,
           CASE WHEN f.date > mx.max_d - 7  THEN 'current'
                WHEN f.date > mx.max_d - 14 THEN 'prior' END AS wk
    FROM fulfillment f CROSS JOIN mx
),
agg AS (
    SELECT node,
           SUM(CASE WHEN wk = 'current' THEN total_defects   END) AS cur_defects,
           SUM(CASE WHEN wk = 'current' THEN total_shipments END) AS cur_ship,
           SUM(CASE WHEN wk = 'prior'   THEN total_defects   END) AS pri_defects,
           SUM(CASE WHEN wk = 'prior'   THEN total_shipments END) AS pri_ship
    FROM tagged
    WHERE wk IS NOT NULL
    GROUP BY node
)
SELECT node,
       cur_defects * 1.0 / cur_ship AS current_rate,
       pri_defects * 1.0 / pri_ship AS prior_rate,
       cur_defects * 1.0 / cur_ship - pri_defects * 1.0 / pri_ship AS delta
FROM agg
ORDER BY delta DESC;
