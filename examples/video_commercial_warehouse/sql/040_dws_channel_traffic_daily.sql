-- DWS / traffic: 渠道流量日报
CREATE OR REPLACE TABLE dws_channel_traffic_daily AS
SELECT r.channel_id, r.channel_name, r.event_date,
                 COUNT(DISTINCT r.request_id) AS request_count,
                 COUNT(e.exposure_id) AS exposure_count
          FROM dwd_recommend_request_fact r
          LEFT JOIN dwd_video_exposure_fact e ON r.request_id = e.request_id
          GROUP BY r.channel_id, r.channel_name, r.event_date;
