-- DWS / traffic: 视频流量效率日报
CREATE OR REPLACE TABLE dws_video_traffic_daily AS
WITH e AS (
            SELECT video_id, event_date, COUNT(*) AS exposure_count
            FROM dwd_video_exposure_fact GROUP BY video_id, event_date
          ), p AS (
            SELECT video_id, event_date, COUNT(*) AS play_count,
                   SUM(is_valid_play) AS valid_play_count,
                   AVG(completion_rate) AS avg_completion_rate
            FROM dwd_video_play_fact GROUP BY video_id, event_date
          ), i AS (
            SELECT video_id, event_date, COUNT(*) AS interaction_count
            FROM dwd_user_interaction_fact GROUP BY video_id, event_date
          )
          SELECT e.video_id, e.event_date, e.exposure_count,
                 COALESCE(p.play_count, 0) AS play_count,
                 COALESCE(p.valid_play_count, 0) AS valid_play_count,
                 COALESCE(p.avg_completion_rate, 0) AS avg_completion_rate,
                 COALESCE(i.interaction_count, 0) AS interaction_count
          FROM e LEFT JOIN p USING(video_id, event_date)
          LEFT JOIN i USING(video_id, event_date);
