-- ADS / ad_delivery: 素材效果与 CTR 分级报告
CREATE OR REPLACE TABLE ads_creative_report AS
SELECT p.*, c.creative_format,
                 CASE
                   WHEN p.ctr >= 0.05 THEN 'A_excellent'
                   WHEN p.ctr >= 0.03 THEN 'B_good'
                   WHEN p.ctr >= 0.01 THEN 'C_normal'
                   ELSE 'D_poor'
                 END AS ctr_level,
                 RANK() OVER (
                   PARTITION BY p.advertiser_id, p.event_date ORDER BY p.ctr DESC
                 ) AS ctr_rank
          FROM dws_creative_performance_daily p
          LEFT JOIN dim_ad_creative c USING(ad_creative_id,ad_group_id);
