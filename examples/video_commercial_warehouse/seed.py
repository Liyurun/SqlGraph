"""DuckDB 确定性基础数据生成器。

所有大表都通过 DuckDB `range()` 和模运算集合生成，不依赖随机数，也不在 Python
中逐行插入。相同 profile 的表行数和内容可复算。
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb


@dataclass(frozen=True)
class SeedProfile:
    name: str
    days: int
    users: int
    creators: int
    videos: int
    advertisers: int
    campaigns: int
    ad_groups: int
    ad_creatives: int
    recommend_requests: int


PROFILES = {
    "smoke": SeedProfile("smoke", 3, 200, 30, 100, 8, 20, 40, 80, 5_000),
    "demo": SeedProfile("demo", 30, 5_000, 300, 2_000, 50, 200, 500, 1_000, 200_000),
}


def _run(con: duckdb.DuckDBPyConnection, sql: str) -> None:
    con.execute(sql)


def seed_base_tables(con: duckdb.DuckDBPyConnection, profile: str = "smoke") -> None:
    """创建 18 张 ODS 和 14 张 DIM 表。"""
    if profile not in PROFILES:
        raise ValueError(f"未知数据 profile: {profile}; 可选 {sorted(PROFILES)}")
    p = PROFILES[profile]
    sessions = max(p.recommend_requests // 5, 1)
    exposures = p.recommend_requests * 2
    plays = exposures * 4 // 5
    interactions = max(plays // 5, 1)
    searches = max(p.recommend_requests // 20, 1)
    ad_requests = max(p.recommend_requests // 3, 1)
    candidates = ad_requests * 3
    impressions = ad_requests * 9 // 10
    clicks = max(impressions // 20, 1)
    conversions = max(clicks // 5, 1)
    refunds = max(impressions // 100, 1)
    devices = max(p.users // 2, 20)
    categories = 12
    geos = 12
    channels = 6
    slots = 6
    experiments = 4
    audiences = 8

    # --------------------------- DIM -------------------------------------
    _run(con, f"""
        CREATE OR REPLACE TABLE dim_user AS
        SELECT i + 1 AS user_id,
               DATE '2025-01-01' + CAST(i % 365 AS INTEGER) AS register_date,
               CASE i % 4 WHEN 0 THEN 'CN' WHEN 1 THEN 'US' WHEN 2 THEN 'BR' ELSE 'ID' END AS country_code,
               CASE i % 4 WHEN 0 THEN '18-24' WHEN 1 THEN '25-34' WHEN 2 THEN '35-44' ELSE '45+' END AS age_bucket,
               (i % {audiences}) + 1 AS audience_id
        FROM range({p.users}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE dim_creator AS
        SELECT i + 1 AS creator_id, (i % {p.users}) + 1 AS user_id,
               CASE i % 3 WHEN 0 THEN 'head' WHEN 1 THEN 'growth' ELSE 'long_tail' END AS creator_tier
        FROM range({p.creators}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE dim_content_category AS
        SELECT i + 1 AS category_id, 'category_' || CAST(i + 1 AS VARCHAR) AS category_name
        FROM range({categories}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE dim_video AS
        SELECT i + 1 AS video_id, (i % {p.creators}) + 1 AS creator_id,
               (i % {categories}) + 1 AS category_id, 15 + CAST(i % 286 AS INTEGER) AS duration_sec,
               DATE '2026-01-01' + CAST(i % 180 AS INTEGER) AS publish_date,
               CASE WHEN i % 29 = 0 THEN 'restricted' ELSE 'active' END AS content_status
        FROM range({p.videos}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE dim_device AS
        SELECT i + 1 AS device_id,
               CASE i % 3 WHEN 0 THEN 'phone' WHEN 1 THEN 'tablet' ELSE 'desktop' END AS device_type,
               CASE i % 3 WHEN 0 THEN 'android' WHEN 1 THEN 'ios' ELSE 'web' END AS os
        FROM range({devices}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE dim_geo AS
        SELECT i + 1 AS geo_id,
               CASE i % 4 WHEN 0 THEN 'CN' WHEN 1 THEN 'US' WHEN 2 THEN 'BR' ELSE 'ID' END AS country_code,
               'region_' || CAST(i + 1 AS VARCHAR) AS region
        FROM range({geos}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE dim_channel AS
        SELECT i + 1 AS channel_id,
               CASE i % 6 WHEN 0 THEN 'organic' WHEN 1 THEN 'push' WHEN 2 THEN 'search'
                    WHEN 3 THEN 'social' WHEN 4 THEN 'partner' ELSE 'direct' END AS channel_name
        FROM range({channels}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE dim_advertiser AS
        SELECT i + 1 AS advertiser_id, 'advertiser_' || CAST(i + 1 AS VARCHAR) AS advertiser_name,
               CASE i % 4 WHEN 0 THEN 'game' WHEN 1 THEN 'retail'
                    WHEN 2 THEN 'finance' ELSE 'education' END AS industry
        FROM range({p.advertisers}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE dim_campaign AS
        SELECT i + 1 AS campaign_id, (i % {p.advertisers}) + 1 AS advertiser_id,
               5000.0 + (i % 20) * 500.0 AS budget,
               CASE i % 3 WHEN 0 THEN 'conversion' WHEN 1 THEN 'traffic' ELSE 'reach' END AS objective,
               'active' AS status
        FROM range({p.campaigns}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE dim_audience AS
        SELECT i + 1 AS audience_id, 'audience_' || CAST(i + 1 AS VARCHAR) AS audience_name,
               CASE i % 3 WHEN 0 THEN 'interest' WHEN 1 THEN 'lookalike' ELSE 'retarget' END AS strategy
        FROM range({audiences}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE dim_ad_group AS
        SELECT i + 1 AS ad_group_id, (i % {p.campaigns}) + 1 AS campaign_id,
               (i % {audiences}) + 1 AS audience_id,
               CASE i % 3 WHEN 0 THEN 'cpm' WHEN 1 THEN 'cpc' ELSE 'ocpc' END AS bid_type,
               0.5 + (i % 20) * 0.1 AS bid_value
        FROM range({p.ad_groups}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE dim_ad_creative AS
        SELECT i + 1 AS ad_creative_id, (i % {p.ad_groups}) + 1 AS ad_group_id,
               (i % {p.videos}) + 1 AS video_id,
               CASE i % 3 WHEN 0 THEN 'native_video' WHEN 1 THEN 'feed_card' ELSE 'post_roll' END AS creative_format,
               CASE WHEN i % 31 = 0 THEN 'paused' ELSE 'active' END AS status
        FROM range({p.ad_creatives}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE dim_ad_slot AS
        SELECT i + 1 AS ad_slot_id,
               CASE i % 3 WHEN 0 THEN 'feed' WHEN 1 THEN 'detail' ELSE 'post_roll' END AS slot_name,
               CASE i % 2 WHEN 0 THEN 'recommend' ELSE 'content' END AS scene,
               0.01 + (i % 6) * 0.005 AS floor_price
        FROM range({slots}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE dim_experiment AS
        SELECT i + 1 AS experiment_id, 'monetization_exp_' || CAST(i + 1 AS VARCHAR) AS experiment_name,
               CASE i % 2 WHEN 0 THEN 'control' ELSE 'treatment' END AS variant
        FROM range({experiments}) t(i)
    """)

    # --------------------------- ODS traffic -----------------------------
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_user_session AS
        SELECT i + 1 AS session_id, (i % {p.users}) + 1 AS user_id,
               (i % {devices}) + 1 AS device_id, (i % {channels}) + 1 AS channel_id,
               TIMESTAMP '2026-08-01 00:00:00' + (i % ({p.days} * 86400)) * INTERVAL 1 SECOND AS start_time,
               TIMESTAMP '2026-08-01 00:05:00' + (i % ({p.days} * 86400)) * INTERVAL 1 SECOND AS end_time,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({sessions}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_recommend_request AS
        SELECT i + 1 AS request_id, (i % {sessions}) + 1 AS session_id,
               (i % {p.users}) + 1 AS user_id, (i % {devices}) + 1 AS device_id,
               (i % {geos}) + 1 AS geo_id, (i % {channels}) + 1 AS channel_id,
               (i % {experiments}) + 1 AS experiment_id,
               TIMESTAMP '2026-08-01 00:00:00' + (i % ({p.days} * 86400)) * INTERVAL 1 SECOND AS request_time,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({p.recommend_requests}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_video_exposure AS
        SELECT i + 1 AS exposure_id, CAST(FLOOR(i / 2) AS BIGINT) + 1 AS request_id,
               (CAST(FLOOR(i / 2) AS BIGINT) % {p.users}) + 1 AS user_id,
               (i % {p.videos}) + 1 AS video_id, CAST(i % 20 AS INTEGER) + 1 AS position,
               TIMESTAMP '2026-08-01 00:00:01' + (i % ({p.days} * 86400)) * INTERVAL 1 SECOND AS exposure_time,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({exposures}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_video_play AS
        SELECT i + 1 AS play_id, i + 1 AS exposure_id, (i % {p.users}) + 1 AS user_id,
               (i % {p.videos}) + 1 AS video_id, 3.0 + (i % 120) AS play_duration_sec,
               LEAST(1.0, (3.0 + (i % 120)) / (15.0 + (i % 286))) AS completion_rate,
               TIMESTAMP '2026-08-01 00:00:02' + (i % ({p.days} * 86400)) * INTERVAL 1 SECOND AS play_time,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({plays}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_user_interaction AS
        SELECT i + 1 AS interaction_id, (i * 5) + 1 AS play_id,
               (i % {p.users}) + 1 AS user_id, (i % {p.videos}) + 1 AS video_id,
               CASE i % 3 WHEN 0 THEN 'like' WHEN 1 THEN 'comment' ELSE 'share' END AS interaction_type,
               TIMESTAMP '2026-08-01 00:00:05' + (i % ({p.days} * 86400)) * INTERVAL 1 SECOND AS event_time,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({interactions}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_search_event AS
        SELECT i + 1 AS search_id, (i % {sessions}) + 1 AS session_id,
               (i % {p.users}) + 1 AS user_id, 'query_' || CAST(i % 50 AS VARCHAR) AS query,
               CAST((i * 7) % 100 AS INTEGER) AS result_count,
               TIMESTAMP '2026-08-01 00:01:00' + (i % ({p.days} * 86400)) * INTERVAL 1 SECOND AS event_time,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({searches}) t(i)
    """)

    # --------------------------- ODS ads ---------------------------------
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_ad_request AS
        SELECT i + 1 AS ad_request_id, i * 3 + 1 AS request_id,
               (i % {p.users}) + 1 AS user_id, (i % {slots}) + 1 AS ad_slot_id,
               (i % {audiences}) + 1 AS audience_id,
               TIMESTAMP '2026-08-01 00:00:03' + (i % ({p.days} * 86400)) * INTERVAL 1 SECOND AS request_time,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({ad_requests}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_ad_candidate AS
        SELECT i + 1 AS candidate_id, CAST(FLOOR(i / 3) AS BIGINT) + 1 AS ad_request_id,
               (i % {p.ad_creatives}) + 1 AS ad_creative_id,
               (i % {p.ad_groups}) + 1 AS ad_group_id,
               (i % {p.campaigns}) + 1 AS campaign_id,
               (i % {p.advertisers}) + 1 AS advertiser_id,
               0.005 + (i % 100) / 1000.0 AS predicted_ctr,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({candidates}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_ad_bid AS
        SELECT i + 1 AS bid_id, i + 1 AS candidate_id,
               0.5 + (i % 30) * 0.1 AS bid_price, (i % 3 = 0) AS is_winner,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({candidates}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_ad_impression AS
        SELECT i + 1 AS ad_impression_id, i + 1 AS ad_request_id,
               (i % {p.users}) + 1 AS user_id, (i % {p.ad_creatives}) + 1 AS ad_creative_id,
               (i % {p.campaigns}) + 1 AS campaign_id,
               (i % {p.advertisers}) + 1 AS advertiser_id,
               (i % {slots}) + 1 AS ad_slot_id,
               TIMESTAMP '2026-08-01 00:00:04' + (i % ({p.days} * 86400)) * INTERVAL 1 SECOND AS impression_time,
               0.01 + (i % 25) * 0.002 AS cost,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({impressions}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_ad_click AS
        SELECT i + 1 AS ad_click_id, i * 20 + 1 AS ad_impression_id,
               ((i * 20) % {p.users}) + 1 AS user_id,
               ((i * 20) % {p.ad_creatives}) + 1 AS ad_creative_id,
               ((i * 20) % {p.campaigns}) + 1 AS campaign_id,
               TIMESTAMP '2026-08-01 00:00:10' + (i % ({p.days} * 86400)) * INTERVAL 1 SECOND AS click_time,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({clicks}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_ad_conversion AS
        SELECT i + 1 AS conversion_id, i * 5 + 1 AS ad_click_id,
               ((i * 100) % {p.users}) + 1 AS user_id,
               ((i * 100) % {p.ad_creatives}) + 1 AS ad_creative_id,
               ((i * 100) % {p.campaigns}) + 1 AS campaign_id,
               CASE i % 3 WHEN 0 THEN 'purchase' WHEN 1 THEN 'signup' ELSE 'install' END AS conversion_type,
               10.0 + (i % 80) AS conversion_value,
               TIMESTAMP '2026-08-01 00:03:00' + (i % ({p.days} * 86400)) * INTERVAL 1 SECOND AS conversion_time,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({conversions}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_ad_charge AS
        SELECT i + 1 AS charge_id, i + 1 AS ad_impression_id,
               (i % {p.advertisers}) + 1 AS advertiser_id,
               (i % {p.campaigns}) + 1 AS campaign_id,
               0.01 + (i % 25) * 0.002 AS amount,
               TIMESTAMP '2026-08-01 00:00:05' + (i % ({p.days} * 86400)) * INTERVAL 1 SECOND AS charge_time,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({impressions}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_ad_refund AS
        SELECT i + 1 AS refund_id, i * 100 + 1 AS charge_id,
               ((i * 100) % {p.advertisers}) + 1 AS advertiser_id,
               0.01 AS amount, 'invalid_traffic' AS reason,
               TIMESTAMP '2026-08-01 01:00:00' + (i % ({p.days} * 86400)) * INTERVAL 1 SECOND AS refund_time,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({refunds}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_budget_snapshot AS
        SELECT i * {p.days} + d + 1 AS snapshot_id, i + 1 AS campaign_id,
               5000.0 + (i % 20) * 500.0 AS budget,
               (d + 1) * (100.0 + (i % 30)) AS spent,
               DATE '2026-08-01' + CAST(d AS INTEGER) AS snapshot_date
        FROM range({p.campaigns}) c(i), range({p.days}) x(d)
    """)

    # --------------------------- ODS governance --------------------------
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_content_audit AS
        SELECT i + 1 AS audit_id, i + 1 AS video_id,
               CASE WHEN i % 29 = 0 THEN 'rejected' ELSE 'approved' END AS audit_status,
               CASE WHEN i % 29 = 0 THEN 0.9 ELSE 0.1 END AS risk_score,
               TIMESTAMP '2026-08-01 02:00:00' + (i % 86400) * INTERVAL 1 SECOND AS audit_time,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({p.videos}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_ad_audit AS
        SELECT i + 1 AS audit_id, i + 1 AS ad_creative_id,
               CASE WHEN i % 31 = 0 THEN 'rejected' ELSE 'approved' END AS audit_status,
               CASE WHEN i % 31 = 0 THEN 0.95 ELSE 0.08 END AS risk_score,
               TIMESTAMP '2026-08-01 02:30:00' + (i % 86400) * INTERVAL 1 SECOND AS audit_time,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({p.ad_creatives}) t(i)
    """)
    _run(con, f"""
        CREATE OR REPLACE TABLE ods_invalid_traffic_signal AS
        SELECT i + 1 AS signal_id, i * 50 + 1 AS request_id,
               ((i * 50) % {p.users}) + 1 AS user_id,
               CASE i % 3 WHEN 0 THEN 'rapid_click' WHEN 1 THEN 'device_farm' ELSE 'proxy' END AS signal_type,
               0.7 + (i % 30) / 100.0 AS risk_score,
               TIMESTAMP '2026-08-01 03:00:00' + (i % ({p.days} * 86400)) * INTERVAL 1 SECOND AS event_time,
               DATE '2026-08-01' + CAST(i % {p.days} AS INTEGER) AS event_date
        FROM range({max(p.recommend_requests // 50, 1)}) t(i)
    """)
