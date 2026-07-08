-- 转化事件清洗：类型规范化 + 去重
INSERT OVERWRITE TABLE stg_conversions
SELECT
    log_id,
    req_id,
    CAST(ad_id AS BIGINT) AS ad_id,
    CAST(creative_id AS BIGINT) AS creative_id,
    CAST(user_id AS BIGINT) AS user_id,
    CAST(conv_time AS TIMESTAMP) AS conv_time,
    CASE
        WHEN lower(conv_type) IN ('purchase', 'order', 'pay') THEN 'purchase'
        WHEN lower(conv_type) IN ('register', 'signup') THEN 'register'
        WHEN lower(conv_type) IN ('form', 'lead') THEN 'lead'
        ELSE 'other'
    END AS conv_type,
    COALESCE(conv_value, 0.0) AS conv_value,
    1 AS conv_flag,
    to_date(conv_time) AS dt
FROM ods_conversion_log
WHERE conv_time IS NOT NULL
  AND user_id IS NOT NULL;
