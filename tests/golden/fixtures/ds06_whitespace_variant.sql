-- DS-06 确定性样本：与 ds01 语义相同，仅空白 / 大小写不同。
-- 用于验证身份稳定（REQ-ID-01）：关键节点 ID 应与规范写法一致。
insert   into   dws_order_enriched_di
SELECT o.order_id,   o.user_id, u.user_name,o.amount
FROM   dwd_order_di   o
JOIN dim_user u   ON o.user_id=u.user_id
