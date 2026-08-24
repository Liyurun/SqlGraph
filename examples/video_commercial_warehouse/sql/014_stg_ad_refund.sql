-- STG / billing: 标准化 ods_ad_refund 并去除完全重复记录
CREATE OR REPLACE TABLE stg_ad_refund AS
SELECT DISTINCT * FROM ods_ad_refund;
