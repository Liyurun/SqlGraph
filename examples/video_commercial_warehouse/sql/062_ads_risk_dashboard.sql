-- ADS / risk: 商业化质量与风险驾驶舱
CREATE OR REPLACE TABLE ads_risk_dashboard AS
SELECT *, high_risk_count::DOUBLE / NULLIF(signal_count,0) AS high_risk_rate,
                 CASE WHEN avg_risk_score >= 0.8 THEN 'critical'
                      WHEN avg_risk_score >= 0.5 THEN 'warning'
                      ELSE 'normal' END AS risk_level
          FROM dws_risk_daily;
