-- DWS / ad_inventory: 广告位请求到转化漏斗
CREATE OR REPLACE TABLE dws_ad_slot_funnel_daily AS
WITH o AS (
            SELECT ad_slot_id, event_date, COUNT(*) AS request_count
            FROM dwd_ad_opportunity_fact GROUP BY ad_slot_id, event_date
          ), i AS (
            SELECT ad_slot_id, event_date, COUNT(*) AS impression_count
            FROM dwd_ad_delivery_fact GROUP BY ad_slot_id, event_date
          ), c AS (
            SELECT ad_slot_id, event_date, COUNT(*) AS click_count
            FROM dwd_ad_click_fact GROUP BY ad_slot_id, event_date
          ), v AS (
            SELECT ad_slot_id, event_date, COUNT(*) AS conversion_count
            FROM dwd_ad_conversion_fact GROUP BY ad_slot_id, event_date
          )
          SELECT o.ad_slot_id, o.event_date, o.request_count,
                 COALESCE(i.impression_count,0) AS impression_count,
                 COALESCE(c.click_count,0) AS click_count,
                 COALESCE(v.conversion_count,0) AS conversion_count,
                 COALESCE(i.impression_count,0)::DOUBLE / NULLIF(o.request_count,0) AS fill_rate
          FROM o LEFT JOIN i USING(ad_slot_id,event_date)
          LEFT JOIN c USING(ad_slot_id,event_date)
          LEFT JOIN v USING(ad_slot_id,event_date);
