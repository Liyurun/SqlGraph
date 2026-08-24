-- STG / attribution: 标准化 ods_ad_conversion 并去除完全重复记录
CREATE OR REPLACE TABLE stg_ad_conversion AS
SELECT DISTINCT * FROM ods_ad_conversion;
