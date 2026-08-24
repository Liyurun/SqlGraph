-- DWD / traffic: 视频播放及有效播放事实
CREATE OR REPLACE TABLE dwd_video_play_fact AS
SELECT p.*, v.creator_id, v.category_id, v.duration_sec,
                 CASE WHEN p.completion_rate >= 0.9 THEN 1 ELSE 0 END AS is_complete_play,
                 CASE WHEN p.play_duration_sec >= 5 THEN 1 ELSE 0 END AS is_valid_play
          FROM stg_video_play p
          LEFT JOIN dim_video v ON p.video_id = v.video_id;
