-- DWS / billing: 平台广告收入日报
CREATE OR REPLACE TABLE dws_revenue_daily AS
WITH c AS (
            SELECT advertiser_id, event_date, SUM(amount) AS gross_revenue
            FROM dwd_billing_fact GROUP BY advertiser_id, event_date
          ), r AS (
            SELECT advertiser_id, event_date, SUM(amount) AS refund_amount
            FROM dwd_refund_fact GROUP BY advertiser_id, event_date
          )
          SELECT c.advertiser_id, c.event_date, c.gross_revenue,
                 COALESCE(r.refund_amount,0) AS refund_amount,
                 c.gross_revenue - COALESCE(r.refund_amount,0) AS net_revenue
          FROM c LEFT JOIN r USING(advertiser_id,event_date);
