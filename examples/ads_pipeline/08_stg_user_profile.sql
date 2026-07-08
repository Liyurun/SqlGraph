-- 用户画像清洗：分桶与派生标签
INSERT OVERWRITE TABLE stg_user_profile
SELECT
    CAST(user_id AS BIGINT) AS user_id,
    age,
    CASE
        WHEN age < 18 THEN 'teen'
        WHEN age BETWEEN 18 AND 24 THEN '18-24'
        WHEN age BETWEEN 25 AND 34 THEN '25-34'
        WHEN age BETWEEN 35 AND 44 THEN '35-44'
        WHEN age >= 45 THEN '45+'
        ELSE 'unknown'
    END AS age_group,
    COALESCE(gender, 'U') AS gender,
    city,
    COALESCE(city_level, 'unknown') AS city_level,
    interest_tags
FROM ods_user_profile
WHERE user_id IS NOT NULL;
