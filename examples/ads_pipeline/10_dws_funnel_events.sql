-- 统一事件流：UNION ALL 把曝光/点击/转化拉成同一张漏斗事件表
INSERT OVERWRITE TABLE dws_funnel_events
SELECT
    req_id,
    creative_id,
    user_id,
    'impression' AS event_type,
    imp_time AS event_time,
    1 AS event_weight,
    dt
FROM stg_impressions

UNION ALL

SELECT
    req_id,
    creative_id,
    user_id,
    'click' AS event_type,
    click_time AS event_time,
    3 AS event_weight,
    dt
FROM dwd_ad_event
WHERE is_click = 1

UNION ALL

SELECT
    req_id,
    creative_id,
    user_id,
    conv_type AS event_type,
    conv_time AS event_time,
    10 AS event_weight,
    dt
FROM stg_conversions;
