-- ADS / billing: 商业收入与 ROI 驾驶舱
CREATE OR REPLACE TABLE ads_revenue_dashboard AS
SELECT r.event_date, SUM(r.gross_revenue) AS gross_revenue,
                 SUM(r.refund_amount) AS refund_amount, SUM(r.net_revenue) AS net_revenue,
                 AVG(i.roi) AS avg_roi
          FROM dws_revenue_daily r
          LEFT JOIN dws_roi_daily i ON r.event_date = i.event_date
          GROUP BY r.event_date;
