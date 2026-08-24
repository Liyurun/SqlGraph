-- ADS / content: 作者流量与互动看板
CREATE OR REPLACE TABLE ads_creator_dashboard AS
SELECT d.*, c.creator_tier,
                 d.interaction_count::DOUBLE / NULLIF(d.play_count,0) AS interaction_rate
          FROM dws_creator_traffic_daily d
          LEFT JOIN dim_creator c ON d.creator_id = c.creator_id;
