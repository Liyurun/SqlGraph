-- DWD / user: 用户会话事实
CREATE OR REPLACE TABLE dwd_session_fact AS
SELECT s.*, d.device_type, d.os, c.channel_name,
                 DATE_DIFF('second', s.start_time, s.end_time) AS session_duration_sec
          FROM stg_user_session s
          LEFT JOIN dim_device d ON s.device_id = d.device_id
          LEFT JOIN dim_channel c ON s.channel_id = c.channel_id;
