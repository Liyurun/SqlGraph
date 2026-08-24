-- DWD / billing: 预算与消耗节奏事实
CREATE OR REPLACE TABLE dwd_budget_fact AS
SELECT b.*, c.advertiser_id, c.objective, c.status,
                 b.spent / NULLIF(b.budget, 0) AS pacing_ratio
          FROM stg_budget_snapshot b
          LEFT JOIN dim_campaign c ON b.campaign_id = c.campaign_id;
