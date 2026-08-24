-- DWD / attribution: 点击到转化的归因触点
CREATE OR REPLACE TABLE dwd_attribution_touch_fact AS
SELECT c.ad_click_id AS touch_id, c.ad_impression_id, c.user_id,
                 c.ad_creative_id, c.campaign_id, c.advertiser_id,
                 v.conversion_id, COALESCE(v.conversion_value, 0) AS conversion_value,
                 CASE WHEN v.conversion_id IS NULL THEN 0 ELSE 1 END AS is_converted,
                 c.event_date
          FROM dwd_ad_click_fact c
          LEFT JOIN dwd_ad_conversion_fact v ON c.ad_click_id = v.ad_click_id;
