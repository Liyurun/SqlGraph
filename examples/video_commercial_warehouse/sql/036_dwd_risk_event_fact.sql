-- DWD / risk: 内容、广告与无效流量统一风险事实
CREATE OR REPLACE TABLE dwd_risk_event_fact AS
SELECT audit_id AS risk_event_id, 'video' AS entity_type, video_id AS entity_id,
                 audit_status AS risk_type, risk_score, event_date
          FROM stg_content_audit
          UNION ALL
          SELECT audit_id, 'ad_creative', ad_creative_id, audit_status, risk_score, event_date
          FROM stg_ad_audit
          UNION ALL
          SELECT signal_id, 'request', request_id, signal_type, risk_score, event_date
          FROM stg_invalid_traffic_signal;
