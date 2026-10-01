-- Node-day anomalies against a SAME-WEEKDAY rolling baseline.
-- Why same weekday: Mondays are structurally worse; comparing a Monday to the
-- previous 4 Mondays avoids flagging the weekly pattern as an anomaly.
-- Technique: window function with PARTITION BY node, weekday.
WITH daily AS (
    SELECT date, node, dayofweek(date) AS dow,
           SUM(total_shipments) AS shipments,
           SUM(total_defects)   AS defects,
           SUM(total_defects) * 1.0 / SUM(total_shipments) AS defect_rate
    FROM fulfillment
    GROUP BY date, node
),
base AS (
    SELECT *,
           AVG(defect_rate)         OVER w AS base_mean,
           STDDEV_SAMP(defect_rate) OVER w AS base_sd,
           COUNT(defect_rate)       OVER w AS base_n
    FROM daily
    WINDOW w AS (PARTITION BY node, dow ORDER BY date
                 ROWS BETWEEN {weeks} PRECEDING AND 1 PRECEDING)
),
scored AS (
    SELECT *,
           (defect_rate - base_mean) / NULLIF(base_sd, 0) AS rolling_z,
           defect_rate - base_mean                        AS excess_rate,
           (defect_rate - base_mean) * shipments          AS excess_defects
    FROM base
)
SELECT date, node, shipments, defects, defect_rate,
       base_mean, base_sd, rolling_z, excess_rate, excess_defects,
       COALESCE(base_n >= 3 AND rolling_z >= $z AND excess_rate >= $min_excess, FALSE) AS is_anomaly
FROM scored
ORDER BY date, node;
