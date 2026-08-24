-- DWS / user: 用户参与度日报
CREATE OR REPLACE TABLE dws_user_engagement_daily AS
WITH p AS (
            SELECT user_id, event_date, COUNT(*) AS play_count,
                   SUM(play_duration_sec) AS play_duration_sec
            FROM dwd_video_play_fact GROUP BY user_id, event_date
          ), i AS (
            SELECT user_id, event_date, COUNT(*) AS interaction_count
            FROM dwd_user_interaction_fact GROUP BY user_id, event_date
          )
          SELECT p.user_id, p.event_date, p.play_count, p.play_duration_sec,
                 COALESCE(i.interaction_count, 0) AS interaction_count
          FROM p LEFT JOIN i USING(user_id, event_date);
