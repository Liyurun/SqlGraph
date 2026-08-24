-- DS-04 CTE 与子查询：CTE 作为 table 节点、子查询字段血缘。
INSERT INTO dws_ad_daily_di
WITH click_agg AS (
    SELECT ad_id, dt, COUNT(*) AS click_cnt
    FROM dwd_click_di
    GROUP BY ad_id, dt
),
imp_agg AS (
    SELECT ad_id, dt, COUNT(*) AS imp_cnt
    FROM dwd_impression_di
    GROUP BY ad_id, dt
)
SELECT
    c.ad_id,
    c.dt,
    c.click_cnt,
    i.imp_cnt,
    c.click_cnt / i.imp_cnt AS ctr
FROM click_agg c
JOIN imp_agg i ON c.ad_id = i.ad_id AND c.dt = i.dt
