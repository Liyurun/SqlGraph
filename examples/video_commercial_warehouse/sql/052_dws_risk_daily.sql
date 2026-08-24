-- DWS / risk: 内容、广告与流量风险日报
CREATE OR REPLACE TABLE dws_risk_daily AS
SELECT entity_type, event_date, COUNT(*) AS signal_count,
                 SUM(CASE WHEN risk_score >= 0.8 THEN 1 ELSE 0 END) AS high_risk_count,
                 AVG(risk_score) AS avg_risk_score
          FROM dwd_risk_event_fact GROUP BY entity_type, event_date;
