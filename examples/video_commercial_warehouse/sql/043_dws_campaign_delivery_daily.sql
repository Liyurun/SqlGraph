-- DWS / ad_delivery: 计划投放效果日报
CREATE OR REPLACE TABLE dws_campaign_delivery_daily AS
SELECT campaign_id, advertiser_id, event_date,
                 COUNT(*) AS impression_count, SUM(is_clicked) AS click_count,
                 SUM(is_converted) AS conversion_count, SUM(cost) AS spend,
                 SUM(conversion_value) AS conversion_value
          FROM dwd_ad_attribution_wide
          GROUP BY campaign_id, advertiser_id, event_date;
