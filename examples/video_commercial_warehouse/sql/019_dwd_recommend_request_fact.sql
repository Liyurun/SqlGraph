-- DWD / recommendation: 推荐请求明细宽表
CREATE OR REPLACE TABLE dwd_recommend_request_fact AS
SELECT r.*, u.age_bucket, d.device_type, d.os, g.country_code, g.region,
                 c.channel_name, e.variant AS experiment_variant
          FROM stg_recommend_request r
          LEFT JOIN dim_user u ON r.user_id = u.user_id
          LEFT JOIN dim_device d ON r.device_id = d.device_id
          LEFT JOIN dim_geo g ON r.geo_id = g.geo_id
          LEFT JOIN dim_channel c ON r.channel_id = c.channel_id
          LEFT JOIN dim_experiment e ON r.experiment_id = e.experiment_id;
