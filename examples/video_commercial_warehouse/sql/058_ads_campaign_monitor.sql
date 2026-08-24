-- ADS / ad_delivery: 计划投放与预算监控
CREATE OR REPLACE TABLE ads_campaign_monitor AS
SELECT d.*, c.objective, c.status, b.budget, b.pacing_ratio,
                 d.click_count::DOUBLE / NULLIF(d.impression_count,0) AS ctr,
                 d.conversion_count::DOUBLE / NULLIF(d.click_count,0) AS cvr
          FROM dws_campaign_delivery_daily d
          LEFT JOIN dws_budget_pacing_daily b USING(campaign_id,advertiser_id,event_date)
          LEFT JOIN dim_campaign c USING(campaign_id,advertiser_id);
