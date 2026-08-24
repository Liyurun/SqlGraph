-- ADS / billing: 广告主经营报告
CREATE OR REPLACE TABLE ads_advertiser_report AS
SELECT p.*, a.advertiser_name, a.industry, r.net_revenue,
                 p.conversion_value / NULLIF(p.spend,0) AS roi
          FROM dws_advertiser_performance_daily p
          LEFT JOIN dws_revenue_daily r USING(advertiser_id,event_date)
          LEFT JOIN dim_advertiser a USING(advertiser_id);
