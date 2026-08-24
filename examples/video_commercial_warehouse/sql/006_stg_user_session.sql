-- STG / user: 标准化 ods_user_session 并去除完全重复记录
CREATE OR REPLACE TABLE stg_user_session AS
SELECT DISTINCT * FROM ods_user_session;
