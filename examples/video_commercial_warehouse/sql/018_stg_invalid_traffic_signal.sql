-- STG / risk: 标准化 ods_invalid_traffic_signal 并去除完全重复记录
CREATE OR REPLACE TABLE stg_invalid_traffic_signal AS
SELECT DISTINCT * FROM ods_invalid_traffic_signal;
