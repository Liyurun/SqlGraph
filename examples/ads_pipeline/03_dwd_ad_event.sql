WITH imp_uniq AS (
    SELECT
        log_id,
        req_id,
        ad_id,
        creative_id,
        user_id,
        imp_time,
        device_type,
        os_family,
        dt,
        ROW_NUMBER() OVER (PARTITION BY req_id, creative_id ORDER BY imp_time ASC) AS rn
    FROM stg_impressions
)
INSERT OVERWRITE TABLE dwd_ad_event
SELECT
    i.log_id AS imp_log_id,
    c.log_id AS click_log_id,
    i.req_id,
    i.ad_id,
    i.creative_id,
    i.user_id,
    i.imp_time,
    c.click_time,
    c.click_price,
    i.device_type,
    i.os_family,
    i.dt,
    CASE WHEN c.log_id IS NOT NULL THEN 1 ELSE 0 END AS is_click
FROM imp_uniq i
LEFT JOIN stg_clicks c
    ON i.req_id = c.req_id
    AND i.creative_id = c.creative_id
    AND i.user_id = c.user_id
    AND c.click_time >= i.imp_time
    AND c.click_time <= i.imp_time + INTERVAL 1 HOUR
WHERE i.rn = 1;
