-- DWS / content: 内容分类流量日报
CREATE OR REPLACE TABLE dws_category_traffic_daily AS
SELECT e.category_id, e.category_name, e.event_date,
                 COUNT(DISTINCT e.exposure_id) AS exposure_count,
                 COUNT(DISTINCT p.play_id) AS play_count,
                 AVG(p.completion_rate) AS avg_completion_rate
          FROM dwd_video_exposure_fact e
          LEFT JOIN dwd_video_play_fact p ON e.exposure_id = p.exposure_id
          GROUP BY e.category_id, e.category_name, e.event_date;
