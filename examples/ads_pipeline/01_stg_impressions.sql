INSERT OVERWRITE TABLE stg_impressions
SELECT
    log_id,
    req_id,
    CAST(ad_id AS BIGINT) AS ad_id,
    CAST(creative_id AS BIGINT) AS creative_id,
    CAST(user_id AS BIGINT) AS user_id,
    CAST(imp_time AS TIMESTAMP) AS imp_time,
    COALESCE(device_type, 'unknown') AS device_type,
    CASE
        WHEN lower(os) LIKE '%android%' THEN 'android'
        WHEN lower(os) LIKE '%ios%' THEN 'ios'
        WHEN lower(os) LIKE '%windows%' THEN 'windows'
        WHEN lower(os) LIKE '%mac%' THEN 'mac'
        ELSE 'other'
    END AS os_family,
    1 AS imp_flag,
    to_date(imp_time) AS dt
FROM ods_impression_log
WHERE imp_time IS NOT NULL
  AND ad_id IS NOT NULL;
