-- DWD / ad_inventory: 广告机会明细
CREATE OR REPLACE TABLE dwd_ad_opportunity_fact AS
SELECT r.*, s.slot_name, s.scene, s.floor_price, a.audience_name
          FROM stg_ad_request r
          LEFT JOIN dim_ad_slot s ON r.ad_slot_id = s.ad_slot_id
          LEFT JOIN dim_audience a ON r.audience_id = a.audience_id;
