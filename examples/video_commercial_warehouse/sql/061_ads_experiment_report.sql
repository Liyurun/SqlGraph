-- ADS / experiment: 实验流量与商业化效果报告
CREATE OR REPLACE TABLE ads_experiment_report AS
SELECT *, ad_request_count::DOUBLE / NULLIF(request_count,0) AS ad_request_rate,
                 video_exposure_count::DOUBLE / NULLIF(request_count,0) AS exposure_per_request
          FROM dws_experiment_daily;
