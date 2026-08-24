-- DWS / billing: 预算节奏日报
CREATE OR REPLACE TABLE dws_budget_pacing_daily AS
SELECT b.campaign_id, b.advertiser_id, b.snapshot_date AS event_date,
                 b.budget, b.spent AS snapshot_spent,
                 COALESCE(d.spend,0) AS actual_spend,
                 COALESCE(d.spend,0) / NULLIF(b.budget,0) AS pacing_ratio
          FROM dwd_budget_fact b
          LEFT JOIN dws_campaign_delivery_daily d
            ON b.campaign_id = d.campaign_id AND b.snapshot_date = d.event_date;
