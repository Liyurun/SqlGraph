-- STG / risk: 标准化 ods_ad_audit 并去除完全重复记录
CREATE OR REPLACE TABLE stg_ad_audit AS
SELECT DISTINCT * FROM ods_ad_audit;
