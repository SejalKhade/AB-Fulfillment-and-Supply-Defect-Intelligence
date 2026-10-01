-- Pareto (80/20) of defect types. Technique: UNPIVOT + cumulative window SUM.
WITH long AS (
    SELECT defect_type, SUM(cnt) AS cnt
    FROM (UNPIVOT (SELECT late_delivery, missing_package, damaged_goods,
                          wrong_item, inventory_discrepancy, failed_pickup
                   FROM fulfillment)
          ON late_delivery, missing_package, damaged_goods,
             wrong_item, inventory_discrepancy, failed_pickup
          INTO NAME defect_type VALUE cnt)
    GROUP BY defect_type
)
SELECT defect_type, cnt AS count,
       cnt * 1.0 / SUM(cnt) OVER () AS pct_of_total,
       SUM(cnt) OVER (ORDER BY cnt DESC, defect_type
                      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) * 1.0
         / SUM(cnt) OVER () AS cumulative_pct
FROM long
ORDER BY cnt DESC, defect_type;
