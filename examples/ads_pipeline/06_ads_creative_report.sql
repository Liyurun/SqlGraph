WITH daily AS (
    SELECT
        creative_id,
        creative_name,
        advertiser_id,
        campaign_id,
        material_type,
        dt,
        imp_count,
        click_count,
        ctr,
        total_spend,
        CASE
            WHEN ctr >= 0.05 THEN 'A_excellent'
            WHEN ctr >= 0.03 THEN 'B_good'
            WHEN ctr >= 0.01 THEN 'C_normal'
            ELSE 'D_poor'
        END AS ctr_level
    FROM dws_creative_daily
)
INSERT OVERWRITE TABLE ads_creative_report
SELECT
    creative_id,
    creative_name,
    advertiser_id,
    campaign_id,
    material_type,
    dt,
    imp_count,
    click_count,
    ctr,
    total_spend,
    ctr_level,
    RANK() OVER (PARTITION BY advertiser_id, dt ORDER BY ctr DESC) AS ctr_rank_in_advertiser,
    RANK() OVER (PARTITION BY campaign_id, dt ORDER BY total_spend DESC) AS spend_rank_in_campaign,
    SUM(imp_count) OVER (PARTITION BY creative_id ORDER BY dt ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS imp_count_7d,
    SUM(click_count) OVER (PARTITION BY creative_id ORDER BY dt ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS click_count_7d
FROM daily;
