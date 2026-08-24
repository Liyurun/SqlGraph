-- DWD / ad_delivery: 广告点击事实
CREATE OR REPLACE TABLE dwd_ad_click_fact AS
SELECT c.*, i.ad_request_id, i.advertiser_id, i.ad_slot_id,
                 i.cost, i.impression_time,
                 DATE_DIFF('second', i.impression_time, c.click_time) AS click_delay_sec
          FROM stg_ad_click c
          JOIN dwd_ad_delivery_fact i ON c.ad_impression_id = i.ad_impression_id;
