-- Daily demand per node x category (input to the forecasting module).
SELECT date, node, category, SUM(demand_units) AS demand_units
FROM inventory
GROUP BY date, node, category
ORDER BY node, category, date;
