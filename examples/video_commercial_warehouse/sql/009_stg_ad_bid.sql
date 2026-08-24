-- STG / ad_delivery: 标准化 ods_ad_bid 并去除完全重复记录
CREATE OR REPLACE TABLE stg_ad_bid AS
SELECT DISTINCT * FROM ods_ad_bid;
