-- DWD / attribution: 广告转化事实
CREATE OR REPLACE TABLE dwd_ad_conversion_fact AS
SELECT c.*, k.ad_impression_id, k.advertiser_id, k.ad_slot_id,
                 DATE_DIFF('second', k.click_time, c.conversion_time) AS conversion_delay_sec
          FROM stg_ad_conversion c
          JOIN dwd_ad_click_fact k ON c.ad_click_id = k.ad_click_id;
