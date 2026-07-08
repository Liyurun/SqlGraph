INSERT OVERWRITE TABLE stg_clicks
SELECT
    log_id,
    req_id,
    CAST(ad_id AS BIGINT) AS ad_id,
    CAST(creative_id AS BIGINT) AS creative_id,
    CAST(user_id AS BIGINT) AS user_id,
    CAST(click_time AS TIMESTAMP) AS click_time,
    CAST(click_price AS DOUBLE) AS click_price,
    1 AS click_flag,
    to_date(click_time) AS dt
FROM ods_click_log
WHERE click_time IS NOT NULL
  AND ad_id IS NOT NULL;
