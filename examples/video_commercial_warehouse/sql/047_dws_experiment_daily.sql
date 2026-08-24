-- DWS / experiment: 实验流量与广告机会日报
CREATE OR REPLACE TABLE dws_experiment_daily AS
SELECT r.experiment_id, r.experiment_variant, r.event_date,
                 COUNT(DISTINCT r.request_id) AS request_count,
                 COUNT(DISTINCT e.exposure_id) AS video_exposure_count,
                 COUNT(DISTINCT a.ad_request_id) AS ad_request_count
          FROM dwd_recommend_request_fact r
          LEFT JOIN dwd_video_exposure_fact e ON r.request_id = e.request_id
          LEFT JOIN dwd_ad_opportunity_fact a ON r.request_id = a.request_id
          GROUP BY r.experiment_id, r.experiment_variant, r.event_date;
