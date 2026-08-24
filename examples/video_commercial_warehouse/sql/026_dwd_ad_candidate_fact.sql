-- DWD / ad_inventory: 广告候选召回明细
CREATE OR REPLACE TABLE dwd_ad_candidate_fact AS
SELECT c.*, cr.video_id, cr.creative_format, g.bid_type, g.bid_value
          FROM stg_ad_candidate c
          LEFT JOIN dim_ad_creative cr ON c.ad_creative_id = cr.ad_creative_id
          LEFT JOIN dim_ad_group g ON c.ad_group_id = g.ad_group_id;
