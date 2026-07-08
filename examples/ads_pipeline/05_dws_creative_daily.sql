WITH creative_imp AS (
    SELECT creative_id, dt, COUNT(*) AS imp_count
    FROM dwd_ad_event
    GROUP BY creative_id, dt
),
creative_clk AS (
    SELECT creative_id, dt, SUM(is_click) AS click_count, SUM(COALESCE(click_price,0)) AS total_spend
    FROM dwd_ad_event
    GROUP BY creative_id, dt
),
creative_base AS (
    SELECT creative_id, creative_name, advertiser_id, campaign_id, material_type FROM dim_creative
)
INSERT OVERWRITE TABLE dws_creative_daily
SELECT
    ci.creative_id,
    cb.creative_name,
    cb.advertiser_id,
    cb.campaign_id,
    cb.material_type,
    ci.dt,
    ci.imp_count,
    COALESCE(cc.click_count, 0) AS click_count,
    ROUND(COALESCE(cc.click_count,0) * 100.0 / NULLIF(ci.imp_count, 0), 4) AS ctr,
    COALESCE(cc.total_spend, 0) AS total_spend
FROM creative_imp ci
LEFT JOIN creative_clk cc ON ci.creative_id = cc.creative_id AND ci.dt = cc.dt
LEFT JOIN creative_base cb ON ci.creative_id = cb.creative_id

UNION ALL

SELECT
    CAST(0 AS BIGINT) AS creative_id,
    'UNKNOWN' AS creative_name,
    CAST(0 AS BIGINT) AS advertiser_id,
    CAST(0 AS BIGINT) AS campaign_id,
    'unknown' AS material_type,
    dt,
    COUNT(*) AS imp_count,
    CAST(0 AS BIGINT) AS click_count,
    CAST(0.0 AS DOUBLE) AS ctr,
    CAST(0.0 AS DOUBLE) AS total_spend
FROM dwd_ad_event
WHERE creative_id IS NULL
GROUP BY dt;
