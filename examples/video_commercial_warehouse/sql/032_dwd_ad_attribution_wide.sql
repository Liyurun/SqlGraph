-- DWD / attribution: 曝光点击转化归因宽表
CREATE OR REPLACE TABLE dwd_ad_attribution_wide AS
SELECT i.ad_impression_id, i.ad_request_id, i.user_id, i.ad_creative_id,
                 i.ad_group_id, i.campaign_id, i.advertiser_id, i.ad_slot_id,
                 i.cost, i.event_date,
                 CASE WHEN c.ad_click_id IS NULL THEN 0 ELSE 1 END AS is_clicked,
                 CASE WHEN v.conversion_id IS NULL THEN 0 ELSE 1 END AS is_converted,
                 COALESCE(v.conversion_value, 0) AS conversion_value
          FROM dwd_ad_delivery_fact i
          LEFT JOIN dwd_ad_click_fact c ON i.ad_impression_id = c.ad_impression_id
          LEFT JOIN dwd_ad_conversion_fact v ON c.ad_click_id = v.ad_click_id;
