-- DWS / billing: 广告主效果日报
CREATE OR REPLACE TABLE dws_advertiser_performance_daily AS
SELECT advertiser_id, event_date, SUM(impression_count) AS impression_count,
                 SUM(click_count) AS click_count, SUM(conversion_count) AS conversion_count,
                 SUM(spend) AS spend, SUM(conversion_value) AS conversion_value
          FROM dws_campaign_delivery_daily GROUP BY advertiser_id, event_date;
