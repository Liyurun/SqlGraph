-- STG / risk: 标准化 ods_content_audit 并去除完全重复记录
CREATE OR REPLACE TABLE stg_content_audit AS
SELECT DISTINCT * FROM ods_content_audit;
