-- ADS / ad_inventory: 广告运营总览
CREATE OR REPLACE TABLE ads_ad_operation_dashboard AS
WITH revenue AS (
            SELECT event_date, SUM(net_revenue) AS net_revenue
            FROM dws_revenue_daily GROUP BY event_date
          )
          SELECT f.*, COALESCE(r.net_revenue,0) AS net_revenue,
                 f.impression_count::DOUBLE / NULLIF(f.request_count,0) AS fill_rate,
                 COALESCE(r.net_revenue,0) * 1000.0 / NULLIF(f.impression_count,0) AS ecpm
          FROM dws_monetization_funnel_daily f
          LEFT JOIN revenue r ON f.event_date = r.event_date;
