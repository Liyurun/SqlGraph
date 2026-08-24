-- DWD / content: 用户互动明细
CREATE OR REPLACE TABLE dwd_user_interaction_fact AS
SELECT i.*, v.creator_id, v.category_id,
                 CASE WHEN i.interaction_type = 'like' THEN 1 ELSE 0 END AS is_like,
                 CASE WHEN i.interaction_type = 'comment' THEN 1 ELSE 0 END AS is_comment,
                 CASE WHEN i.interaction_type = 'share' THEN 1 ELSE 0 END AS is_share
          FROM stg_user_interaction i
          LEFT JOIN dim_video v ON i.video_id = v.video_id;
