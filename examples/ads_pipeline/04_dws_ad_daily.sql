INSERT OVERWRITE TABLE dws_ad_daily
SELECT
    ad_id,
    dt,
    COUNT(*) AS imp_count,
    SUM(is_click) AS click_count,
    MAX(click_price) AS max_click_price,
    ROUND(SUM(is_click) * 100.0 / COUNT(*), 4) AS ctr,
    ROUND(SUM(COALESCE(click_price, 0)) / NULLIF(COUNT(*), 0), 4) AS avg_cpc,
    SUM(COALESCE(click_price, 0)) AS total_spend
FROM dwd_ad_event
GROUP BY ad_id, dt;
