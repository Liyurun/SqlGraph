-- DS-01 基础血缘：单语句 SELECT/INSERT/JOIN。
-- 覆盖 reads_from / writes_to / has_column / table_lineage 四类基础关系。
INSERT INTO dws_order_enriched_di
SELECT
    o.order_id,
    o.user_id,
    u.user_name,
    o.amount
FROM dwd_order_di o
JOIN dim_user u ON o.user_id = u.user_id
