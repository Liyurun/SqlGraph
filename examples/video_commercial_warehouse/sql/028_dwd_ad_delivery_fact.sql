-- DWD / ad_delivery: 广告曝光投放事实
CREATE OR REPLACE TABLE dwd_ad_delivery_fact AS
SELECT i.*, c.objective, cr.ad_group_id, cr.video_id, cr.creative_format,
                 s.scene, s.floor_price
          FROM stg_ad_impression i
          LEFT JOIN dim_campaign c ON i.campaign_id = c.campaign_id
          LEFT JOIN dim_ad_creative cr ON i.ad_creative_id = cr.ad_creative_id
          LEFT JOIN dim_ad_slot s ON i.ad_slot_id = s.ad_slot_id;
