-- DWS / ad_delivery: 素材效果日报（故意保留百分数 CTR 作为治理场景）
CREATE OR REPLACE TABLE dws_creative_performance_daily AS
SELECT w.ad_creative_id, c.ad_group_id, w.campaign_id, w.advertiser_id,
                 w.event_date, COUNT(*) AS impression_count,
                 SUM(w.is_clicked) AS click_count, SUM(w.is_converted) AS conversion_count,
                 SUM(w.cost) AS spend, SUM(w.conversion_value) AS conversion_value,
                 ROUND(SUM(w.is_clicked) / NULLIF(COUNT(*),0), 6) AS ctr,
                 SUM(w.is_converted)::DOUBLE / NULLIF(SUM(w.is_clicked),0) AS cvr
          FROM dwd_ad_attribution_wide w
          LEFT JOIN dim_ad_creative c ON w.ad_creative_id = c.ad_creative_id
          GROUP BY w.ad_creative_id, c.ad_group_id, w.campaign_id, w.advertiser_id, w.event_date;
