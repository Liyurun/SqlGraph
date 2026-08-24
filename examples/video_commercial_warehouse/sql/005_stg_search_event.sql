-- STG / traffic: 标准化 ods_search_event 并去除完全重复记录
CREATE OR REPLACE TABLE stg_search_event AS
SELECT DISTINCT * FROM ods_search_event;
