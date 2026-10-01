-- Node (FC) scorecard: defect rate, cross-node z-score, status, rank.
-- Tables: fulfillment. Mirrors modules/anomaly_detector.by_node (reconciled in tests).
WITH node AS (
    SELECT node,
           SUM(total_shipments)  AS total_shipments,
           SUM(total_defects)    AS total_defects,
           SUM(late_delivery)    AS late_delivery,
           SUM(missing_package)  AS missing_package,
           SUM(damaged_goods)    AS damaged_goods,
           SUM(wrong_item)       AS wrong_item,
           SUM(inventory_discrepancy) AS inventory_discrepancy,
           SUM(failed_pickup)    AS failed_pickup,
           AVG(avg_delivery_hrs) AS avg_delivery_hrs
    FROM fulfillment
    GROUP BY node
),
rated AS (
    SELECT *, total_defects * 1.0 / total_shipments AS defect_rate FROM node
),
stats AS (
    SELECT AVG(defect_rate) AS mu, STDDEV_SAMP(defect_rate) AS sigma FROM rated
)
SELECT r.node,
       r.total_shipments, r.total_defects,
       r.late_delivery, r.missing_package, r.damaged_goods,
       r.wrong_item, r.inventory_discrepancy, r.failed_pickup,
       r.avg_delivery_hrs,
       r.defect_rate,
       CASE WHEN s.sigma = 0 THEN 0 ELSE (r.defect_rate - s.mu) / s.sigma END AS z_score,
       CASE WHEN r.defect_rate >= $esc  THEN 'ESCALATE'
            WHEN r.defect_rate >= $warn THEN 'WATCH'
            ELSE 'OK' END AS status,
       RANK() OVER (ORDER BY r.defect_rate DESC) AS rank
FROM rated r CROSS JOIN stats s
ORDER BY r.defect_rate DESC;
