-- DWD / billing: 广告退款事实
CREATE OR REPLACE TABLE dwd_refund_fact AS
SELECT r.*, b.campaign_id, b.event_date AS charge_date
          FROM stg_ad_refund r
          LEFT JOIN dwd_billing_fact b ON r.charge_id = b.charge_id;
