-- STG / recommendation: 标准化 ods_recommend_request 并去除完全重复记录
CREATE OR REPLACE TABLE stg_recommend_request AS
SELECT DISTINCT * FROM ods_recommend_request;
