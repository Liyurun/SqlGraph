-- DWS / experiment: 受众效果日报
CREATE OR REPLACE TABLE dws_audience_performance_daily AS
SELECT u.audience_id, w.event_date, COUNT(*) AS impression_count,
                 SUM(w.is_clicked) AS click_count, SUM(w.is_converted) AS conversion_count,
                 SUM(w.cost) AS spend
          FROM dwd_ad_attribution_wide w
          LEFT JOIN dim_user u ON w.user_id = u.user_id
          GROUP BY u.audience_id, w.event_date;
