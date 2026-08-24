-- ADS / content: 内容分类效率报告
CREATE OR REPLACE TABLE ads_content_efficiency_report AS
SELECT *, play_count::DOUBLE / NULLIF(exposure_count,0) AS play_rate
          FROM dws_category_traffic_daily;
