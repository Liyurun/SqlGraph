-- DWS / ad_inventory: 商业化全漏斗日报
CREATE OR REPLACE TABLE dws_monetization_funnel_daily AS
SELECT o.event_date, COUNT(DISTINCT o.ad_request_id) AS request_count,
                 COUNT(DISTINCT c.candidate_id) AS candidate_count,
                 COUNT(DISTINCT CASE WHEN a.is_winner THEN a.bid_id END) AS win_count,
                 COUNT(DISTINCT i.ad_impression_id) AS impression_count,
                 COUNT(DISTINCT k.ad_click_id) AS click_count,
                 COUNT(DISTINCT v.conversion_id) AS conversion_count
          FROM dwd_ad_opportunity_fact o
          LEFT JOIN dwd_ad_candidate_fact c ON o.ad_request_id = c.ad_request_id
          LEFT JOIN dwd_ad_auction_fact a ON c.candidate_id = a.candidate_id
          LEFT JOIN dwd_ad_delivery_fact i ON o.ad_request_id = i.ad_request_id
          LEFT JOIN dwd_ad_click_fact k ON i.ad_impression_id = k.ad_impression_id
          LEFT JOIN dwd_ad_conversion_fact v ON k.ad_click_id = v.ad_click_id
          GROUP BY o.event_date;
