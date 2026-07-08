-- 广告主日报：多窗口函数 + 维度 JOIN + 复合指标
WITH daily_metrics AS (
    SELECT
        w.advertiser_id,
        w.campaign_id,
        w.dt,
        COUNT(*) AS imp_count,
        SUM(w.is_click) AS click_count,
        SUM(w.is_converted) AS conv_count,
        SUM(w.click_price) AS total_spend,
        SUM(w.purchase_value) AS total_gmv
    FROM dwd_attribution_wide w
    GROUP BY w.advertiser_id, w.campaign_id, w.dt
)
INSERT OVERWRITE TABLE ads_advertiser_daily
SELECT
    dm.advertiser_id,
    adv.advertiser_name,
    adv.industry,
    dm.campaign_id,
    cmp.campaign_name,
    cmp.budget,
    dm.dt,
    dm.imp_count,
    dm.click_count,
    dm.conv_count,
    dm.total_spend,
    dm.total_gmv,
    ROUND(dm.click_count * 100.0 / NULLIF(dm.imp_count, 0), 4) AS ctr,
    ROUND(dm.conv_count * 100.0 / NULLIF(dm.click_count, 0), 4) AS cvr,
    ROUND(dm.total_gmv / NULLIF(dm.total_spend, 0), 4) AS roi,
    ROUND(dm.total_spend / NULLIF(dm.total_spend, 0), 4) AS budget_pacing,
    RANK() OVER (PARTITION BY dm.dt ORDER BY dm.total_spend DESC) AS spend_rank,
    SUM(dm.total_spend) OVER (PARTITION BY dm.advertiser_id ORDER BY dm.dt ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS spend_7d,
    AVG(dm.total_gmv) OVER (PARTITION BY dm.campaign_id ORDER BY dm.dt ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS gmv_7d_avg
FROM daily_metrics dm
LEFT JOIN dim_advertiser adv
    ON dm.advertiser_id = adv.advertiser_id
LEFT JOIN dim_campaign cmp
    ON dm.campaign_id = cmp.campaign_id;
