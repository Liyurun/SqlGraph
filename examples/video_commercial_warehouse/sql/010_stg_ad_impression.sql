-- STG / ad_delivery: 标准化 ods_ad_impression 并去除完全重复记录
CREATE OR REPLACE TABLE stg_ad_impression AS
SELECT DISTINCT * FROM ods_ad_impression;
