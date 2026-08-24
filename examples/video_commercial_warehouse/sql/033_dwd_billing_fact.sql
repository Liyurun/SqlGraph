-- DWD / billing: 广告扣费事实
CREATE OR REPLACE TABLE dwd_billing_fact AS
SELECT c.*, a.industry, p.objective
          FROM stg_ad_charge c
          LEFT JOIN dim_advertiser a ON c.advertiser_id = a.advertiser_id
          LEFT JOIN dim_campaign p ON c.campaign_id = p.campaign_id;
