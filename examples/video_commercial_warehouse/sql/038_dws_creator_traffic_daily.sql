-- DWS / content: 作者流量日报
CREATE OR REPLACE TABLE dws_creator_traffic_daily AS
SELECT v.creator_id, d.event_date, SUM(d.exposure_count) AS exposure_count,
                 SUM(d.play_count) AS play_count, SUM(d.interaction_count) AS interaction_count,
                 AVG(d.avg_completion_rate) AS avg_completion_rate
          FROM dws_video_traffic_daily d
          JOIN dim_video v ON d.video_id = v.video_id
          GROUP BY v.creator_id, d.event_date;
