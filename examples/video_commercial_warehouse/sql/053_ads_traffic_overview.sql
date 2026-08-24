-- ADS / traffic: 平台流量总览
CREATE OR REPLACE TABLE ads_traffic_overview AS
SELECT c.event_date, SUM(c.request_count) AS request_count,
                 SUM(c.exposure_count) AS exposure_count,
                 SUM(v.play_count) AS play_count,
                 SUM(v.valid_play_count) AS valid_play_count
          FROM dws_channel_traffic_daily c
          LEFT JOIN dws_video_traffic_daily v ON c.event_date = v.event_date
          GROUP BY c.event_date;
