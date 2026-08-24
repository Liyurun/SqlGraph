INSERT INTO critical_orders_archive
SELECT order_id, amount
FROM critical_orders;
