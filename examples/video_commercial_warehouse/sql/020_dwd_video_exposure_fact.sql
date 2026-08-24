-- DWD / traffic: 视频曝光明细宽表
CREATE OR REPLACE TABLE dwd_video_exposure_fact AS
SELECT x.*, v.creator_id, v.category_id, v.duration_sec,
                 cr.creator_tier, cc.category_name
          FROM stg_video_exposure x
          LEFT JOIN dim_video v ON x.video_id = v.video_id
          LEFT JOIN dim_creator cr ON v.creator_id = cr.creator_id
          LEFT JOIN dim_content_category cc ON v.category_id = cc.category_id;
