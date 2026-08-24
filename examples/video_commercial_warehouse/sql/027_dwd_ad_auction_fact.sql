-- DWD / ad_delivery: 竞价与胜出事实
CREATE OR REPLACE TABLE dwd_ad_auction_fact AS
SELECT b.*, c.ad_request_id, c.ad_creative_id, c.ad_group_id,
                 c.campaign_id, c.advertiser_id, c.predicted_ctr,
                 b.bid_price * c.predicted_ctr AS rank_score
          FROM stg_ad_bid b
          JOIN dwd_ad_candidate_fact c ON b.candidate_id = c.candidate_id;
