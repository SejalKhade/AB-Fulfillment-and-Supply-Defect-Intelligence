-- Contribution analysis: which node x carrier / node x category segments create
-- the most EXCESS defects versus the network-wide rate?
--   excess_defects = actual_defects - shipments * network_rate
-- Ranking by excess (not by raw rate) stops small segments with noisy rates
-- from outranking big segments that really hurt the network.
WITH net AS (
    SELECT SUM(total_defects) * 1.0 / SUM(total_shipments) AS net_rate FROM fulfillment
),
seg AS (
    SELECT node, 'carrier' AS dimension, carrier AS segment,
           SUM(total_shipments) AS shipments, SUM(total_defects) AS defects,
           SUM(late_delivery) AS late_delivery, SUM(missing_package) AS missing_package,
           SUM(damaged_goods) AS damaged_goods, SUM(wrong_item) AS wrong_item,
           SUM(inventory_discrepancy) AS inventory_discrepancy, SUM(failed_pickup) AS failed_pickup
    FROM fulfillment GROUP BY node, carrier
    UNION ALL
    SELECT node, 'category', category,
           SUM(total_shipments), SUM(total_defects),
           SUM(late_delivery), SUM(missing_package), SUM(damaged_goods),
           SUM(wrong_item), SUM(inventory_discrepancy), SUM(failed_pickup)
    FROM fulfillment GROUP BY node, category
),
scored AS (
    SELECT seg.*, net.net_rate,
           defects * 1.0 / shipments AS defect_rate,
           defects - shipments * net.net_rate AS excess_defects,
           (defects * 1.0 / shipments) / net.net_rate AS rate_ratio,
           CASE GREATEST(late_delivery, missing_package, damaged_goods,
                         wrong_item, inventory_discrepancy, failed_pickup)
                WHEN failed_pickup   THEN 'failed_pickup'
                WHEN late_delivery   THEN 'late_delivery'
                WHEN missing_package THEN 'missing_package'
                WHEN damaged_goods   THEN 'damaged_goods'
                WHEN wrong_item      THEN 'wrong_item'
                ELSE 'inventory_discrepancy' END AS top_defect
    FROM seg CROSS JOIN net
)
SELECT *, RANK() OVER (PARTITION BY dimension ORDER BY excess_defects DESC) AS rank_in_dimension
FROM scored
ORDER BY dimension, excess_defects DESC;
