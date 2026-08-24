-- DWS / attribution: 计划 ROI 日报
CREATE OR REPLACE TABLE dws_roi_daily AS
SELECT campaign_id, advertiser_id, event_date, spend, conversion_value,
                 conversion_value / NULLIF(spend,0) AS roi
          FROM dws_campaign_delivery_daily;
