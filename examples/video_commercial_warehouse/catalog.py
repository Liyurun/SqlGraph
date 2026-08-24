"""视频平台商业化数仓的权威表与任务目录。

Catalog 是 94 张表和 62 个任务的唯一真相源。SQL 文件、运行顺序、依赖图和
可视化元数据均从这里派生，避免文件名、任务声明和实际 SQL 三套定义漂移。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass


DOMAINS = {
    "content",
    "user",
    "traffic",
    "recommendation",
    "ad_inventory",
    "ad_delivery",
    "attribution",
    "billing",
    "experiment",
    "risk",
}


@dataclass(frozen=True)
class TableSpec:
    name: str
    layer: str
    domain: str
    columns: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["columns"] = [list(column) for column in self.columns]
        return data


@dataclass(frozen=True)
class TaskSpec:
    order: int
    target: str
    layer: str
    domain: str
    dependencies: tuple[str, ...]
    select_sql: str
    description: str

    @property
    def sql(self) -> str:
        return (
            f"-- {self.layer} / {self.domain}: {self.description}\n"
            f"CREATE OR REPLACE TABLE {self.target} AS\n"
            f"{self.select_sql.strip()};\n"
        )

    def to_dict(self) -> dict:
        return {
            "order": self.order,
            "target": self.target,
            "layer": self.layer,
            "domain": self.domain,
            "dependencies": list(self.dependencies),
            "description": self.description,
            "file": f"{self.order:03d}_{self.target}.sql",
        }


def _columns(spec: str) -> tuple[tuple[str, str], ...]:
    """把 ``name:TYPE,name:TYPE`` 转为不可变 schema 声明。"""
    columns = []
    for item in spec.split(","):
        name, separator, data_type = item.partition(":")
        if not separator:
            raise ValueError(f"非法字段声明: {item}")
        columns.append((name, data_type))
    return tuple(columns)


def _base(name: str, layer: str, domain: str, columns: str) -> TableSpec:
    return TableSpec(name, layer, domain, _columns(columns))


_ODS = [
    _base("ods_recommend_request", "ODS", "recommendation",
          "request_id:BIGINT,session_id:BIGINT,user_id:BIGINT,device_id:BIGINT,"
          "geo_id:BIGINT,channel_id:BIGINT,experiment_id:BIGINT,request_time:TIMESTAMP,event_date:DATE"),
    _base("ods_video_exposure", "ODS", "traffic",
          "exposure_id:BIGINT,request_id:BIGINT,user_id:BIGINT,video_id:BIGINT,"
          "position:INTEGER,exposure_time:TIMESTAMP,event_date:DATE"),
    _base("ods_video_play", "ODS", "traffic",
          "play_id:BIGINT,exposure_id:BIGINT,user_id:BIGINT,video_id:BIGINT,"
          "play_duration_sec:DOUBLE,completion_rate:DOUBLE,play_time:TIMESTAMP,event_date:DATE"),
    _base("ods_user_interaction", "ODS", "content",
          "interaction_id:BIGINT,play_id:BIGINT,user_id:BIGINT,video_id:BIGINT,"
          "interaction_type:VARCHAR,event_time:TIMESTAMP,event_date:DATE"),
    _base("ods_search_event", "ODS", "traffic",
          "search_id:BIGINT,session_id:BIGINT,user_id:BIGINT,query:VARCHAR,"
          "result_count:INTEGER,event_time:TIMESTAMP,event_date:DATE"),
    _base("ods_user_session", "ODS", "user",
          "session_id:BIGINT,user_id:BIGINT,device_id:BIGINT,channel_id:BIGINT,"
          "start_time:TIMESTAMP,end_time:TIMESTAMP,event_date:DATE"),
    _base("ods_ad_request", "ODS", "ad_inventory",
          "ad_request_id:BIGINT,request_id:BIGINT,user_id:BIGINT,ad_slot_id:BIGINT,"
          "audience_id:BIGINT,request_time:TIMESTAMP,event_date:DATE"),
    _base("ods_ad_candidate", "ODS", "ad_inventory",
          "candidate_id:BIGINT,ad_request_id:BIGINT,ad_creative_id:BIGINT,"
          "ad_group_id:BIGINT,campaign_id:BIGINT,advertiser_id:BIGINT,"
          "predicted_ctr:DOUBLE,event_date:DATE"),
    _base("ods_ad_bid", "ODS", "ad_delivery",
          "bid_id:BIGINT,candidate_id:BIGINT,bid_price:DOUBLE,is_winner:BOOLEAN,event_date:DATE"),
    _base("ods_ad_impression", "ODS", "ad_delivery",
          "ad_impression_id:BIGINT,ad_request_id:BIGINT,user_id:BIGINT,"
          "ad_creative_id:BIGINT,campaign_id:BIGINT,advertiser_id:BIGINT,"
          "ad_slot_id:BIGINT,impression_time:TIMESTAMP,cost:DOUBLE,event_date:DATE"),
    _base("ods_ad_click", "ODS", "ad_delivery",
          "ad_click_id:BIGINT,ad_impression_id:BIGINT,user_id:BIGINT,"
          "ad_creative_id:BIGINT,campaign_id:BIGINT,click_time:TIMESTAMP,event_date:DATE"),
    _base("ods_ad_conversion", "ODS", "attribution",
          "conversion_id:BIGINT,ad_click_id:BIGINT,user_id:BIGINT,"
          "ad_creative_id:BIGINT,campaign_id:BIGINT,conversion_type:VARCHAR,"
          "conversion_value:DOUBLE,conversion_time:TIMESTAMP,event_date:DATE"),
    _base("ods_ad_charge", "ODS", "billing",
          "charge_id:BIGINT,ad_impression_id:BIGINT,advertiser_id:BIGINT,"
          "campaign_id:BIGINT,amount:DOUBLE,charge_time:TIMESTAMP,event_date:DATE"),
    _base("ods_ad_refund", "ODS", "billing",
          "refund_id:BIGINT,charge_id:BIGINT,advertiser_id:BIGINT,"
          "amount:DOUBLE,reason:VARCHAR,refund_time:TIMESTAMP,event_date:DATE"),
    _base("ods_budget_snapshot", "ODS", "billing",
          "snapshot_id:BIGINT,campaign_id:BIGINT,budget:DOUBLE,spent:DOUBLE,snapshot_date:DATE"),
    _base("ods_content_audit", "ODS", "risk",
          "audit_id:BIGINT,video_id:BIGINT,audit_status:VARCHAR,"
          "risk_score:DOUBLE,audit_time:TIMESTAMP,event_date:DATE"),
    _base("ods_ad_audit", "ODS", "risk",
          "audit_id:BIGINT,ad_creative_id:BIGINT,audit_status:VARCHAR,"
          "risk_score:DOUBLE,audit_time:TIMESTAMP,event_date:DATE"),
    _base("ods_invalid_traffic_signal", "ODS", "risk",
          "signal_id:BIGINT,request_id:BIGINT,user_id:BIGINT,signal_type:VARCHAR,"
          "risk_score:DOUBLE,event_time:TIMESTAMP,event_date:DATE"),
]

_DIM = [
    _base("dim_user", "DIM", "user",
          "user_id:BIGINT,register_date:DATE,country_code:VARCHAR,age_bucket:VARCHAR,audience_id:BIGINT"),
    _base("dim_creator", "DIM", "content",
          "creator_id:BIGINT,user_id:BIGINT,creator_tier:VARCHAR"),
    _base("dim_video", "DIM", "content",
          "video_id:BIGINT,creator_id:BIGINT,category_id:BIGINT,"
          "duration_sec:INTEGER,publish_date:DATE,content_status:VARCHAR"),
    _base("dim_content_category", "DIM", "content",
          "category_id:BIGINT,category_name:VARCHAR"),
    _base("dim_device", "DIM", "user",
          "device_id:BIGINT,device_type:VARCHAR,os:VARCHAR"),
    _base("dim_geo", "DIM", "user",
          "geo_id:BIGINT,country_code:VARCHAR,region:VARCHAR"),
    _base("dim_channel", "DIM", "traffic",
          "channel_id:BIGINT,channel_name:VARCHAR"),
    _base("dim_advertiser", "DIM", "billing",
          "advertiser_id:BIGINT,advertiser_name:VARCHAR,industry:VARCHAR"),
    _base("dim_campaign", "DIM", "ad_delivery",
          "campaign_id:BIGINT,advertiser_id:BIGINT,budget:DOUBLE,objective:VARCHAR,status:VARCHAR"),
    _base("dim_ad_group", "DIM", "ad_delivery",
          "ad_group_id:BIGINT,campaign_id:BIGINT,audience_id:BIGINT,bid_type:VARCHAR,bid_value:DOUBLE"),
    _base("dim_ad_creative", "DIM", "ad_delivery",
          "ad_creative_id:BIGINT,ad_group_id:BIGINT,video_id:BIGINT,"
          "creative_format:VARCHAR,status:VARCHAR"),
    _base("dim_ad_slot", "DIM", "ad_inventory",
          "ad_slot_id:BIGINT,slot_name:VARCHAR,scene:VARCHAR,floor_price:DOUBLE"),
    _base("dim_experiment", "DIM", "experiment",
          "experiment_id:BIGINT,experiment_name:VARCHAR,variant:VARCHAR"),
    _base("dim_audience", "DIM", "experiment",
          "audience_id:BIGINT,audience_name:VARCHAR,strategy:VARCHAR"),
]

BASE_TABLES: dict[str, TableSpec] = {
    table.name: table for table in [*_ODS, *_DIM]
}


def _task(
    order: int,
    target: str,
    layer: str,
    domain: str,
    dependencies: tuple[str, ...],
    select_sql: str,
    description: str,
) -> TaskSpec:
    return TaskSpec(order, target, layer, domain, dependencies, select_sql, description)


def _stg_tasks() -> list[TaskSpec]:
    tasks = []
    for index, source in enumerate(_ODS, start=1):
        target = source.name.replace("ods_", "stg_", 1)
        tasks.append(_task(
            index,
            target,
            "STG",
            source.domain,
            (source.name,),
            f"SELECT DISTINCT * FROM {source.name}",
            f"标准化 {source.name} 并去除完全重复记录",
        ))
    return tasks


_DWD_TASKS = [
    _task(19, "dwd_recommend_request_fact", "DWD", "recommendation",
          ("stg_recommend_request", "dim_user", "dim_device", "dim_geo", "dim_channel", "dim_experiment"),
          """
          SELECT r.*, u.age_bucket, d.device_type, d.os, g.country_code, g.region,
                 c.channel_name, e.variant AS experiment_variant
          FROM stg_recommend_request r
          LEFT JOIN dim_user u ON r.user_id = u.user_id
          LEFT JOIN dim_device d ON r.device_id = d.device_id
          LEFT JOIN dim_geo g ON r.geo_id = g.geo_id
          LEFT JOIN dim_channel c ON r.channel_id = c.channel_id
          LEFT JOIN dim_experiment e ON r.experiment_id = e.experiment_id
          """, "推荐请求明细宽表"),
    _task(20, "dwd_video_exposure_fact", "DWD", "traffic",
          ("stg_video_exposure", "dim_video", "dim_creator", "dim_content_category"),
          """
          SELECT x.*, v.creator_id, v.category_id, v.duration_sec,
                 cr.creator_tier, cc.category_name
          FROM stg_video_exposure x
          LEFT JOIN dim_video v ON x.video_id = v.video_id
          LEFT JOIN dim_creator cr ON v.creator_id = cr.creator_id
          LEFT JOIN dim_content_category cc ON v.category_id = cc.category_id
          """, "视频曝光明细宽表"),
    _task(21, "dwd_video_play_fact", "DWD", "traffic",
          ("stg_video_play", "dim_video"),
          """
          SELECT p.*, v.creator_id, v.category_id, v.duration_sec,
                 CASE WHEN p.completion_rate >= 0.9 THEN 1 ELSE 0 END AS is_complete_play,
                 CASE WHEN p.play_duration_sec >= 5 THEN 1 ELSE 0 END AS is_valid_play
          FROM stg_video_play p
          LEFT JOIN dim_video v ON p.video_id = v.video_id
          """, "视频播放及有效播放事实"),
    _task(22, "dwd_user_interaction_fact", "DWD", "content",
          ("stg_user_interaction", "dim_video"),
          """
          SELECT i.*, v.creator_id, v.category_id,
                 CASE WHEN i.interaction_type = 'like' THEN 1 ELSE 0 END AS is_like,
                 CASE WHEN i.interaction_type = 'comment' THEN 1 ELSE 0 END AS is_comment,
                 CASE WHEN i.interaction_type = 'share' THEN 1 ELSE 0 END AS is_share
          FROM stg_user_interaction i
          LEFT JOIN dim_video v ON i.video_id = v.video_id
          """, "用户互动明细"),
    _task(23, "dwd_search_fact", "DWD", "traffic",
          ("stg_search_event",),
          """
          SELECT *, LENGTH(query) AS query_length,
                 CASE WHEN result_count > 0 THEN 1 ELSE 0 END AS has_result
          FROM stg_search_event
          """, "搜索行为事实"),
    _task(24, "dwd_session_fact", "DWD", "user",
          ("stg_user_session", "dim_device", "dim_channel"),
          """
          SELECT s.*, d.device_type, d.os, c.channel_name,
                 DATE_DIFF('second', s.start_time, s.end_time) AS session_duration_sec
          FROM stg_user_session s
          LEFT JOIN dim_device d ON s.device_id = d.device_id
          LEFT JOIN dim_channel c ON s.channel_id = c.channel_id
          """, "用户会话事实"),
    _task(25, "dwd_ad_opportunity_fact", "DWD", "ad_inventory",
          ("stg_ad_request", "dim_ad_slot", "dim_audience"),
          """
          SELECT r.*, s.slot_name, s.scene, s.floor_price, a.audience_name
          FROM stg_ad_request r
          LEFT JOIN dim_ad_slot s ON r.ad_slot_id = s.ad_slot_id
          LEFT JOIN dim_audience a ON r.audience_id = a.audience_id
          """, "广告机会明细"),
    _task(26, "dwd_ad_candidate_fact", "DWD", "ad_inventory",
          ("stg_ad_candidate", "dim_ad_creative", "dim_ad_group"),
          """
          SELECT c.*, cr.video_id, cr.creative_format, g.bid_type, g.bid_value
          FROM stg_ad_candidate c
          LEFT JOIN dim_ad_creative cr ON c.ad_creative_id = cr.ad_creative_id
          LEFT JOIN dim_ad_group g ON c.ad_group_id = g.ad_group_id
          """, "广告候选召回明细"),
    _task(27, "dwd_ad_auction_fact", "DWD", "ad_delivery",
          ("stg_ad_bid", "dwd_ad_candidate_fact"),
          """
          SELECT b.*, c.ad_request_id, c.ad_creative_id, c.ad_group_id,
                 c.campaign_id, c.advertiser_id, c.predicted_ctr,
                 b.bid_price * c.predicted_ctr AS rank_score
          FROM stg_ad_bid b
          JOIN dwd_ad_candidate_fact c ON b.candidate_id = c.candidate_id
          """, "竞价与胜出事实"),
    _task(28, "dwd_ad_delivery_fact", "DWD", "ad_delivery",
          ("stg_ad_impression", "dim_campaign", "dim_ad_creative", "dim_ad_slot"),
          """
          SELECT i.*, c.objective, cr.ad_group_id, cr.video_id, cr.creative_format,
                 s.scene, s.floor_price
          FROM stg_ad_impression i
          LEFT JOIN dim_campaign c ON i.campaign_id = c.campaign_id
          LEFT JOIN dim_ad_creative cr ON i.ad_creative_id = cr.ad_creative_id
          LEFT JOIN dim_ad_slot s ON i.ad_slot_id = s.ad_slot_id
          """, "广告曝光投放事实"),
    _task(29, "dwd_ad_click_fact", "DWD", "ad_delivery",
          ("stg_ad_click", "dwd_ad_delivery_fact"),
          """
          SELECT c.*, i.ad_request_id, i.advertiser_id, i.ad_slot_id,
                 i.cost, i.impression_time,
                 DATE_DIFF('second', i.impression_time, c.click_time) AS click_delay_sec
          FROM stg_ad_click c
          JOIN dwd_ad_delivery_fact i ON c.ad_impression_id = i.ad_impression_id
          """, "广告点击事实"),
    _task(30, "dwd_ad_conversion_fact", "DWD", "attribution",
          ("stg_ad_conversion", "dwd_ad_click_fact"),
          """
          SELECT c.*, k.ad_impression_id, k.advertiser_id, k.ad_slot_id,
                 DATE_DIFF('second', k.click_time, c.conversion_time) AS conversion_delay_sec
          FROM stg_ad_conversion c
          JOIN dwd_ad_click_fact k ON c.ad_click_id = k.ad_click_id
          """, "广告转化事实"),
    _task(31, "dwd_attribution_touch_fact", "DWD", "attribution",
          ("dwd_ad_click_fact", "dwd_ad_conversion_fact"),
          """
          SELECT c.ad_click_id AS touch_id, c.ad_impression_id, c.user_id,
                 c.ad_creative_id, c.campaign_id, c.advertiser_id,
                 v.conversion_id, COALESCE(v.conversion_value, 0) AS conversion_value,
                 CASE WHEN v.conversion_id IS NULL THEN 0 ELSE 1 END AS is_converted,
                 c.event_date
          FROM dwd_ad_click_fact c
          LEFT JOIN dwd_ad_conversion_fact v ON c.ad_click_id = v.ad_click_id
          """, "点击到转化的归因触点"),
    _task(32, "dwd_ad_attribution_wide", "DWD", "attribution",
          ("dwd_ad_delivery_fact", "dwd_ad_click_fact", "dwd_ad_conversion_fact"),
          """
          SELECT i.ad_impression_id, i.ad_request_id, i.user_id, i.ad_creative_id,
                 i.ad_group_id, i.campaign_id, i.advertiser_id, i.ad_slot_id,
                 i.cost, i.event_date,
                 CASE WHEN c.ad_click_id IS NULL THEN 0 ELSE 1 END AS is_clicked,
                 CASE WHEN v.conversion_id IS NULL THEN 0 ELSE 1 END AS is_converted,
                 COALESCE(v.conversion_value, 0) AS conversion_value
          FROM dwd_ad_delivery_fact i
          LEFT JOIN dwd_ad_click_fact c ON i.ad_impression_id = c.ad_impression_id
          LEFT JOIN dwd_ad_conversion_fact v ON c.ad_click_id = v.ad_click_id
          """, "曝光点击转化归因宽表"),
    _task(33, "dwd_billing_fact", "DWD", "billing",
          ("stg_ad_charge", "dim_advertiser", "dim_campaign"),
          """
          SELECT c.*, a.industry, p.objective
          FROM stg_ad_charge c
          LEFT JOIN dim_advertiser a ON c.advertiser_id = a.advertiser_id
          LEFT JOIN dim_campaign p ON c.campaign_id = p.campaign_id
          """, "广告扣费事实"),
    _task(34, "dwd_refund_fact", "DWD", "billing",
          ("stg_ad_refund", "dwd_billing_fact"),
          """
          SELECT r.*, b.campaign_id, b.event_date AS charge_date
          FROM stg_ad_refund r
          LEFT JOIN dwd_billing_fact b ON r.charge_id = b.charge_id
          """, "广告退款事实"),
    _task(35, "dwd_budget_fact", "DWD", "billing",
          ("stg_budget_snapshot", "dim_campaign"),
          """
          SELECT b.*, c.advertiser_id, c.objective, c.status,
                 b.spent / NULLIF(b.budget, 0) AS pacing_ratio
          FROM stg_budget_snapshot b
          LEFT JOIN dim_campaign c ON b.campaign_id = c.campaign_id
          """, "预算与消耗节奏事实"),
    _task(36, "dwd_risk_event_fact", "DWD", "risk",
          ("stg_content_audit", "stg_ad_audit", "stg_invalid_traffic_signal"),
          """
          SELECT audit_id AS risk_event_id, 'video' AS entity_type, video_id AS entity_id,
                 audit_status AS risk_type, risk_score, event_date
          FROM stg_content_audit
          UNION ALL
          SELECT audit_id, 'ad_creative', ad_creative_id, audit_status, risk_score, event_date
          FROM stg_ad_audit
          UNION ALL
          SELECT signal_id, 'request', request_id, signal_type, risk_score, event_date
          FROM stg_invalid_traffic_signal
          """, "内容、广告与无效流量统一风险事实"),
]

_DWS_TASKS = [
    _task(37, "dws_video_traffic_daily", "DWS", "traffic",
          ("dwd_video_exposure_fact", "dwd_video_play_fact", "dwd_user_interaction_fact"),
          """
          WITH e AS (
            SELECT video_id, event_date, COUNT(*) AS exposure_count
            FROM dwd_video_exposure_fact GROUP BY video_id, event_date
          ), p AS (
            SELECT video_id, event_date, COUNT(*) AS play_count,
                   SUM(is_valid_play) AS valid_play_count,
                   AVG(completion_rate) AS avg_completion_rate
            FROM dwd_video_play_fact GROUP BY video_id, event_date
          ), i AS (
            SELECT video_id, event_date, COUNT(*) AS interaction_count
            FROM dwd_user_interaction_fact GROUP BY video_id, event_date
          )
          SELECT e.video_id, e.event_date, e.exposure_count,
                 COALESCE(p.play_count, 0) AS play_count,
                 COALESCE(p.valid_play_count, 0) AS valid_play_count,
                 COALESCE(p.avg_completion_rate, 0) AS avg_completion_rate,
                 COALESCE(i.interaction_count, 0) AS interaction_count
          FROM e LEFT JOIN p USING(video_id, event_date)
          LEFT JOIN i USING(video_id, event_date)
          """, "视频流量效率日报"),
    _task(38, "dws_creator_traffic_daily", "DWS", "content",
          ("dws_video_traffic_daily", "dim_video"),
          """
          SELECT v.creator_id, d.event_date, SUM(d.exposure_count) AS exposure_count,
                 SUM(d.play_count) AS play_count, SUM(d.interaction_count) AS interaction_count,
                 AVG(d.avg_completion_rate) AS avg_completion_rate
          FROM dws_video_traffic_daily d
          JOIN dim_video v ON d.video_id = v.video_id
          GROUP BY v.creator_id, d.event_date
          """, "作者流量日报"),
    _task(39, "dws_user_engagement_daily", "DWS", "user",
          ("dwd_video_play_fact", "dwd_user_interaction_fact"),
          """
          WITH p AS (
            SELECT user_id, event_date, COUNT(*) AS play_count,
                   SUM(play_duration_sec) AS play_duration_sec
            FROM dwd_video_play_fact GROUP BY user_id, event_date
          ), i AS (
            SELECT user_id, event_date, COUNT(*) AS interaction_count
            FROM dwd_user_interaction_fact GROUP BY user_id, event_date
          )
          SELECT p.user_id, p.event_date, p.play_count, p.play_duration_sec,
                 COALESCE(i.interaction_count, 0) AS interaction_count
          FROM p LEFT JOIN i USING(user_id, event_date)
          """, "用户参与度日报"),
    _task(40, "dws_channel_traffic_daily", "DWS", "traffic",
          ("dwd_recommend_request_fact", "dwd_video_exposure_fact"),
          """
          SELECT r.channel_id, r.channel_name, r.event_date,
                 COUNT(DISTINCT r.request_id) AS request_count,
                 COUNT(e.exposure_id) AS exposure_count
          FROM dwd_recommend_request_fact r
          LEFT JOIN dwd_video_exposure_fact e ON r.request_id = e.request_id
          GROUP BY r.channel_id, r.channel_name, r.event_date
          """, "渠道流量日报"),
    _task(41, "dws_category_traffic_daily", "DWS", "content",
          ("dwd_video_exposure_fact", "dwd_video_play_fact"),
          """
          SELECT e.category_id, e.category_name, e.event_date,
                 COUNT(DISTINCT e.exposure_id) AS exposure_count,
                 COUNT(DISTINCT p.play_id) AS play_count,
                 AVG(p.completion_rate) AS avg_completion_rate
          FROM dwd_video_exposure_fact e
          LEFT JOIN dwd_video_play_fact p ON e.exposure_id = p.exposure_id
          GROUP BY e.category_id, e.category_name, e.event_date
          """, "内容分类流量日报"),
    _task(42, "dws_ad_slot_funnel_daily", "DWS", "ad_inventory",
          ("dwd_ad_opportunity_fact", "dwd_ad_delivery_fact", "dwd_ad_click_fact", "dwd_ad_conversion_fact"),
          """
          WITH o AS (
            SELECT ad_slot_id, event_date, COUNT(*) AS request_count
            FROM dwd_ad_opportunity_fact GROUP BY ad_slot_id, event_date
          ), i AS (
            SELECT ad_slot_id, event_date, COUNT(*) AS impression_count
            FROM dwd_ad_delivery_fact GROUP BY ad_slot_id, event_date
          ), c AS (
            SELECT ad_slot_id, event_date, COUNT(*) AS click_count
            FROM dwd_ad_click_fact GROUP BY ad_slot_id, event_date
          ), v AS (
            SELECT ad_slot_id, event_date, COUNT(*) AS conversion_count
            FROM dwd_ad_conversion_fact GROUP BY ad_slot_id, event_date
          )
          SELECT o.ad_slot_id, o.event_date, o.request_count,
                 COALESCE(i.impression_count,0) AS impression_count,
                 COALESCE(c.click_count,0) AS click_count,
                 COALESCE(v.conversion_count,0) AS conversion_count,
                 COALESCE(i.impression_count,0)::DOUBLE / NULLIF(o.request_count,0) AS fill_rate
          FROM o LEFT JOIN i USING(ad_slot_id,event_date)
          LEFT JOIN c USING(ad_slot_id,event_date)
          LEFT JOIN v USING(ad_slot_id,event_date)
          """, "广告位请求到转化漏斗"),
    _task(43, "dws_campaign_delivery_daily", "DWS", "ad_delivery",
          ("dwd_ad_attribution_wide",),
          """
          SELECT campaign_id, advertiser_id, event_date,
                 COUNT(*) AS impression_count, SUM(is_clicked) AS click_count,
                 SUM(is_converted) AS conversion_count, SUM(cost) AS spend,
                 SUM(conversion_value) AS conversion_value
          FROM dwd_ad_attribution_wide
          GROUP BY campaign_id, advertiser_id, event_date
          """, "计划投放效果日报"),
    _task(44, "dws_creative_performance_daily", "DWS", "ad_delivery",
          ("dwd_ad_attribution_wide", "dim_ad_creative"),
          """
          SELECT w.ad_creative_id, c.ad_group_id, w.campaign_id, w.advertiser_id,
                 w.event_date, COUNT(*) AS impression_count,
                 SUM(w.is_clicked) AS click_count, SUM(w.is_converted) AS conversion_count,
                 SUM(w.cost) AS spend, SUM(w.conversion_value) AS conversion_value,
                 ROUND(SUM(w.is_clicked) * 100.0 / NULLIF(COUNT(*),0), 6) AS ctr,
                 SUM(w.is_converted)::DOUBLE / NULLIF(SUM(w.is_clicked),0) AS cvr
          FROM dwd_ad_attribution_wide w
          LEFT JOIN dim_ad_creative c ON w.ad_creative_id = c.ad_creative_id
          GROUP BY w.ad_creative_id, c.ad_group_id, w.campaign_id, w.advertiser_id, w.event_date
          """, "素材效果日报（故意保留百分数 CTR 作为治理场景）"),
    _task(45, "dws_advertiser_performance_daily", "DWS", "billing",
          ("dws_campaign_delivery_daily",),
          """
          SELECT advertiser_id, event_date, SUM(impression_count) AS impression_count,
                 SUM(click_count) AS click_count, SUM(conversion_count) AS conversion_count,
                 SUM(spend) AS spend, SUM(conversion_value) AS conversion_value
          FROM dws_campaign_delivery_daily GROUP BY advertiser_id, event_date
          """, "广告主效果日报"),
    _task(46, "dws_audience_performance_daily", "DWS", "experiment",
          ("dwd_ad_attribution_wide", "dim_user"),
          """
          SELECT u.audience_id, w.event_date, COUNT(*) AS impression_count,
                 SUM(w.is_clicked) AS click_count, SUM(w.is_converted) AS conversion_count,
                 SUM(w.cost) AS spend
          FROM dwd_ad_attribution_wide w
          LEFT JOIN dim_user u ON w.user_id = u.user_id
          GROUP BY u.audience_id, w.event_date
          """, "受众效果日报"),
    _task(47, "dws_experiment_daily", "DWS", "experiment",
          ("dwd_recommend_request_fact", "dwd_video_exposure_fact", "dwd_ad_opportunity_fact"),
          """
          SELECT r.experiment_id, r.experiment_variant, r.event_date,
                 COUNT(DISTINCT r.request_id) AS request_count,
                 COUNT(DISTINCT e.exposure_id) AS video_exposure_count,
                 COUNT(DISTINCT a.ad_request_id) AS ad_request_count
          FROM dwd_recommend_request_fact r
          LEFT JOIN dwd_video_exposure_fact e ON r.request_id = e.request_id
          LEFT JOIN dwd_ad_opportunity_fact a ON r.request_id = a.request_id
          GROUP BY r.experiment_id, r.experiment_variant, r.event_date
          """, "实验流量与广告机会日报"),
    _task(48, "dws_monetization_funnel_daily", "DWS", "ad_inventory",
          ("dwd_ad_opportunity_fact", "dwd_ad_candidate_fact", "dwd_ad_auction_fact",
           "dwd_ad_delivery_fact", "dwd_ad_click_fact", "dwd_ad_conversion_fact"),
          """
          SELECT o.event_date, COUNT(DISTINCT o.ad_request_id) AS request_count,
                 COUNT(DISTINCT c.candidate_id) AS candidate_count,
                 COUNT(DISTINCT CASE WHEN a.is_winner THEN a.bid_id END) AS win_count,
                 COUNT(DISTINCT i.ad_impression_id) AS impression_count,
                 COUNT(DISTINCT k.ad_click_id) AS click_count,
                 COUNT(DISTINCT v.conversion_id) AS conversion_count
          FROM dwd_ad_opportunity_fact o
          LEFT JOIN dwd_ad_candidate_fact c ON o.ad_request_id = c.ad_request_id
          LEFT JOIN dwd_ad_auction_fact a ON c.candidate_id = a.candidate_id
          LEFT JOIN dwd_ad_delivery_fact i ON o.ad_request_id = i.ad_request_id
          LEFT JOIN dwd_ad_click_fact k ON i.ad_impression_id = k.ad_impression_id
          LEFT JOIN dwd_ad_conversion_fact v ON k.ad_click_id = v.ad_click_id
          GROUP BY o.event_date
          """, "商业化全漏斗日报"),
    _task(49, "dws_revenue_daily", "DWS", "billing",
          ("dwd_billing_fact", "dwd_refund_fact"),
          """
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
          FROM c LEFT JOIN r USING(advertiser_id,event_date)
          """, "平台广告收入日报"),
    _task(50, "dws_roi_daily", "DWS", "attribution",
          ("dws_campaign_delivery_daily",),
          """
          SELECT campaign_id, advertiser_id, event_date, spend, conversion_value,
                 conversion_value / NULLIF(spend,0) AS roi
          FROM dws_campaign_delivery_daily
          """, "计划 ROI 日报"),
    _task(51, "dws_budget_pacing_daily", "DWS", "billing",
          ("dwd_budget_fact", "dws_campaign_delivery_daily"),
          """
          SELECT b.campaign_id, b.advertiser_id, b.snapshot_date AS event_date,
                 b.budget, b.spent AS snapshot_spent,
                 COALESCE(d.spend,0) AS actual_spend,
                 COALESCE(d.spend,0) / NULLIF(b.budget,0) AS pacing_ratio
          FROM dwd_budget_fact b
          LEFT JOIN dws_campaign_delivery_daily d
            ON b.campaign_id = d.campaign_id AND b.snapshot_date = d.event_date
          """, "预算节奏日报"),
    _task(52, "dws_risk_daily", "DWS", "risk",
          ("dwd_risk_event_fact",),
          """
          SELECT entity_type, event_date, COUNT(*) AS signal_count,
                 SUM(CASE WHEN risk_score >= 0.8 THEN 1 ELSE 0 END) AS high_risk_count,
                 AVG(risk_score) AS avg_risk_score
          FROM dwd_risk_event_fact GROUP BY entity_type, event_date
          """, "内容、广告与流量风险日报"),
]

_ADS_TASKS = [
    _task(53, "ads_traffic_overview", "ADS", "traffic",
          ("dws_channel_traffic_daily", "dws_video_traffic_daily"),
          """
          SELECT c.event_date, SUM(c.request_count) AS request_count,
                 SUM(c.exposure_count) AS exposure_count,
                 SUM(v.play_count) AS play_count,
                 SUM(v.valid_play_count) AS valid_play_count
          FROM dws_channel_traffic_daily c
          LEFT JOIN dws_video_traffic_daily v ON c.event_date = v.event_date
          GROUP BY c.event_date
          """, "平台流量总览"),
    _task(54, "ads_creator_dashboard", "ADS", "content",
          ("dws_creator_traffic_daily", "dim_creator"),
          """
          SELECT d.*, c.creator_tier,
                 d.interaction_count::DOUBLE / NULLIF(d.play_count,0) AS interaction_rate
          FROM dws_creator_traffic_daily d
          LEFT JOIN dim_creator c ON d.creator_id = c.creator_id
          """, "作者流量与互动看板"),
    _task(55, "ads_content_efficiency_report", "ADS", "content",
          ("dws_category_traffic_daily",),
          """
          SELECT *, play_count::DOUBLE / NULLIF(exposure_count,0) AS play_rate
          FROM dws_category_traffic_daily
          """, "内容分类效率报告"),
    _task(56, "ads_ad_operation_dashboard", "ADS", "ad_inventory",
          ("dws_monetization_funnel_daily", "dws_revenue_daily"),
          """
          WITH revenue AS (
            SELECT event_date, SUM(net_revenue) AS net_revenue
            FROM dws_revenue_daily GROUP BY event_date
          )
          SELECT f.*, COALESCE(r.net_revenue,0) AS net_revenue,
                 f.impression_count::DOUBLE / NULLIF(f.request_count,0) AS fill_rate,
                 COALESCE(r.net_revenue,0) * 1000.0 / NULLIF(f.impression_count,0) AS ecpm
          FROM dws_monetization_funnel_daily f
          LEFT JOIN revenue r ON f.event_date = r.event_date
          """, "广告运营总览"),
    _task(57, "ads_advertiser_report", "ADS", "billing",
          ("dws_advertiser_performance_daily", "dws_revenue_daily", "dim_advertiser"),
          """
          SELECT p.*, a.advertiser_name, a.industry, r.net_revenue,
                 p.conversion_value / NULLIF(p.spend,0) AS roi
          FROM dws_advertiser_performance_daily p
          LEFT JOIN dws_revenue_daily r USING(advertiser_id,event_date)
          LEFT JOIN dim_advertiser a USING(advertiser_id)
          """, "广告主经营报告"),
    _task(58, "ads_campaign_monitor", "ADS", "ad_delivery",
          ("dws_campaign_delivery_daily", "dws_budget_pacing_daily", "dim_campaign"),
          """
          SELECT d.*, c.objective, c.status, b.budget, b.pacing_ratio,
                 d.click_count::DOUBLE / NULLIF(d.impression_count,0) AS ctr,
                 d.conversion_count::DOUBLE / NULLIF(d.click_count,0) AS cvr
          FROM dws_campaign_delivery_daily d
          LEFT JOIN dws_budget_pacing_daily b USING(campaign_id,advertiser_id,event_date)
          LEFT JOIN dim_campaign c USING(campaign_id,advertiser_id)
          """, "计划投放与预算监控"),
    _task(59, "ads_creative_report", "ADS", "ad_delivery",
          ("dws_creative_performance_daily", "dim_ad_creative"),
          """
          SELECT p.*, c.creative_format,
                 CASE
                   WHEN p.ctr >= 0.05 THEN 'A_excellent'
                   WHEN p.ctr >= 0.03 THEN 'B_good'
                   WHEN p.ctr >= 0.01 THEN 'C_normal'
                   ELSE 'D_poor'
                 END AS ctr_level,
                 RANK() OVER (
                   PARTITION BY p.advertiser_id, p.event_date ORDER BY p.ctr DESC
                 ) AS ctr_rank
          FROM dws_creative_performance_daily p
          LEFT JOIN dim_ad_creative c USING(ad_creative_id,ad_group_id)
          """, "素材效果与 CTR 分级报告"),
    _task(60, "ads_revenue_dashboard", "ADS", "billing",
          ("dws_revenue_daily", "dws_roi_daily"),
          """
          SELECT r.event_date, SUM(r.gross_revenue) AS gross_revenue,
                 SUM(r.refund_amount) AS refund_amount, SUM(r.net_revenue) AS net_revenue,
                 AVG(i.roi) AS avg_roi
          FROM dws_revenue_daily r
          LEFT JOIN dws_roi_daily i ON r.event_date = i.event_date
          GROUP BY r.event_date
          """, "商业收入与 ROI 驾驶舱"),
    _task(61, "ads_experiment_report", "ADS", "experiment",
          ("dws_experiment_daily",),
          """
          SELECT *, ad_request_count::DOUBLE / NULLIF(request_count,0) AS ad_request_rate,
                 video_exposure_count::DOUBLE / NULLIF(request_count,0) AS exposure_per_request
          FROM dws_experiment_daily
          """, "实验流量与商业化效果报告"),
    _task(62, "ads_risk_dashboard", "ADS", "risk",
          ("dws_risk_daily",),
          """
          SELECT *, high_risk_count::DOUBLE / NULLIF(signal_count,0) AS high_risk_rate,
                 CASE WHEN avg_risk_score >= 0.8 THEN 'critical'
                      WHEN avg_risk_score >= 0.5 THEN 'warning'
                      ELSE 'normal' END AS risk_level
          FROM dws_risk_daily
          """, "商业化质量与风险驾驶舱"),
]

TASKS: tuple[TaskSpec, ...] = tuple([
    *_stg_tasks(),
    *_DWD_TASKS,
    *_DWS_TASKS,
    *_ADS_TASKS,
])

ALL_TABLES: tuple[str, ...] = tuple([*BASE_TABLES, *(task.target for task in TASKS)])


def layer_counts() -> dict[str, int]:
    counts = Counter(table.layer for table in BASE_TABLES.values())
    counts.update(task.layer for task in TASKS)
    return dict(counts)


def validate_catalog() -> None:
    """验证规模、唯一性、依赖存在性和拓扑顺序。"""
    if len(BASE_TABLES) != 32 or len(TASKS) != 62 or len(ALL_TABLES) != 94:
        raise ValueError("catalog 规模必须为 32 基础表 + 62 派生表 = 94 表")
    if len(set(ALL_TABLES)) != len(ALL_TABLES):
        raise ValueError("catalog 存在重复表名")
    if set(layer_counts()) != {"ODS", "STG", "DIM", "DWD", "DWS", "ADS"}:
        raise ValueError("catalog 层级不完整")
    if {table.domain for table in BASE_TABLES.values()} | {task.domain for task in TASKS} != DOMAINS:
        raise ValueError("catalog 业务主题不完整")

    available = set(BASE_TABLES)
    for task in TASKS:
        missing = set(task.dependencies) - available
        if missing:
            raise ValueError(f"{task.target} 依赖未定义或顺序错误: {sorted(missing)}")
        available.add(task.target)


validate_catalog()
