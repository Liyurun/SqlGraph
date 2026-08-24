-- STG / ad_inventory: 标准化 ods_ad_candidate 并去除完全重复记录
CREATE OR REPLACE TABLE stg_ad_candidate AS
SELECT DISTINCT * FROM ods_ad_candidate;
