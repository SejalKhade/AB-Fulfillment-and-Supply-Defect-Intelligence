-- Weekly defect-rate trend per node with week-over-week delta.
-- Technique: date_trunc + LAG() window. Only complete 7-day weeks are kept.
WITH wk AS (
    SELECT date_trunc('week', date)::DATE AS week_start, node,
           SUM(total_shipments) AS shipments,
           SUM(total_defects)   AS defects
    FROM fulfillment
    GROUP BY 1, 2
    HAVING COUNT(DISTINCT date) = 7
)
SELECT week_start, node, shipments, defects,
       defects * 1.0 / shipments AS defect_rate,
       LAG(defects * 1.0 / shipments) OVER (PARTITION BY node ORDER BY week_start) AS prev_rate,
       defects * 1.0 / shipments
         - LAG(defects * 1.0 / shipments) OVER (PARTITION BY node ORDER BY week_start) AS wow_delta
FROM wk
ORDER BY week_start, node;
