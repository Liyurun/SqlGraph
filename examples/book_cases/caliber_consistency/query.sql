INSERT INTO ads_creative_report
SELECT clicks * 100.0 / impressions AS ctr
FROM dwd_ad_events;
