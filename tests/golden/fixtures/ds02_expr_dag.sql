-- DS-02 表达式 DAG：嵌套算术 / CASE / 函数。
-- 覆盖 contains / compute_dependency / produces / expr_operand 四类计算关系。
INSERT INTO dws_user_value_di
SELECT
    user_id,
    (base_score + bonus_score) * weight AS total_score,
    CASE WHEN active_days >= 7 THEN 'active' ELSE 'inactive' END AS status,
    COALESCE(pay_amount, 0) + COALESCE(refund_amount, 0) AS net_amount
FROM dwd_user_metric_di
