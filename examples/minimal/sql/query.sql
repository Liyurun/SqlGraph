INSERT INTO dst_metric
SELECT clicks * 100.0 / impressions AS ctr
FROM src_events;
