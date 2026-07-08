-- 归因宽表：多 CTE + 多表 JOIN，把曝光点击事件、转化、用户画像、维度表打宽
WITH conv_agg AS (
    SELECT
        req_id,
        creative_id,
        user_id,
        SUM(conv_flag) AS conv_count,
        SUM(CASE WHEN conv_type = 'purchase' THEN conv_value ELSE 0 END) AS purchase_value,
        MAX(conv_time) AS last_conv_time
    FROM stg_conversions
    GROUP BY req_id, creative_id, user_id
),
event_enriched AS (
    SELECT
        e.imp_log_id,
        e.req_id,
        e.ad_id,
        e.creative_id,
        e.user_id,
        e.is_click,
        e.click_price,
        e.device_type,
        e.os_family,
        e.dt,
        cr.advertiser_id,
        cr.campaign_id,
        cr.material_type
    FROM dwd_ad_event e
    LEFT JOIN dim_creative cr
        ON e.creative_id = cr.creative_id
)
INSERT OVERWRITE TABLE dwd_attribution_wide
SELECT
    ev.imp_log_id,
    ev.req_id,
    ev.ad_id,
    ev.creative_id,
    ev.user_id,
    ev.advertiser_id,
    ev.campaign_id,
    ev.material_type,
    ev.device_type,
    ev.os_family,
    up.age_group,
    up.gender,
    up.city_level,
    ev.is_click,
    COALESCE(ca.conv_count, 0) AS conv_count,
    COALESCE(ca.purchase_value, 0.0) AS purchase_value,
    COALESCE(ev.click_price, 0.0) AS click_price,
    CASE WHEN COALESCE(ca.conv_count, 0) > 0 THEN 1 ELSE 0 END AS is_converted,
    ev.dt
FROM event_enriched ev
LEFT JOIN conv_agg ca
    ON ev.req_id = ca.req_id
    AND ev.creative_id = ca.creative_id
    AND ev.user_id = ca.user_id
LEFT JOIN stg_user_profile up
    ON ev.user_id = up.user_id;
