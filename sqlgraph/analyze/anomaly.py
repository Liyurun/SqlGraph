# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Explainable rule-based and optional model anomaly analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, Mapping, Sequence

from sqlgraph.analyze.basic_metrics import BasicGovernanceMetrics
from sqlgraph.analyze.communities import (
    CommunityAnalysisResult,
    analyze_communities,
)
from sqlgraph.analyze.config import AnalysisConfig
from sqlgraph.analyze.contracts import MetricResult, MetricStatus, freeze, thaw
from sqlgraph.analyze.impact import ImpactAnalysisResult, analyze_impact
from sqlgraph.analyze.table_graph import TableGraph
from sqlgraph.analyze.topology import TopologyAnalysisResult, analyze_topology


ANOMALY_VERSION = "1.0"
ANOMALY_FEATURE_VERSION = "1.0"
RULE_ANOMALY_WEIGHTS: Mapping[str, float] = {
    "high_in_degree": 0.12,
    "high_out_degree": 0.12,
    "layer_drift": 0.14,
    "impact_entropy": 0.12,
    "unknown_lineage": 0.14,
    "multi_producer": 0.12,
    "cycle_member": 0.12,
    "cross_layer_violation": 0.12,
}


@dataclass(frozen=True)
class AnomalyAnalysisResult:
    """Task 10 result bundle for anomaly scores."""

    summary: Mapping[str, MetricResult] = field(default_factory=dict)
    rule_based: MetricResult = field(
        default_factory=lambda: MetricResult(
            name="rule_based_anomaly",
            status=MetricStatus.SUCCESS,
            value={"table_count": 0, "records": ()},
            algorithm="anomaly.empty_graph",
            version=ANOMALY_VERSION,
        )
    )
    unsupervised_model: MetricResult = field(
        default_factory=lambda: MetricResult(
            name="unsupervised_anomaly_model",
            status=MetricStatus.SKIPPED,
            reason="not enough samples for model training",
            value={"records": (), "training_summary": {"sample_count": 0}},
            algorithm="anomaly.isolation_forest",
            version=ANOMALY_VERSION,
        )
    )
    table_metrics: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", freeze(self.summary))
        object.__setattr__(
            self,
            "table_metrics",
            tuple(freeze(item) for item in self.table_metrics),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                name: result.to_dict() for name, result in self.summary.items()
            },
            "rule_based": self.rule_based.to_dict(),
            "unsupervised_model": self.unsupervised_model.to_dict(),
            "table_metrics": [thaw(item) for item in self.table_metrics],
        }


def analyze_anomalies(
    table_graph: TableGraph,
    config: AnalysisConfig | None = None,
    *,
    topology: TopologyAnalysisResult | None = None,
    impact: ImpactAnalysisResult | None = None,
    communities: CommunityAnalysisResult | None = None,
    basic_metrics: BasicGovernanceMetrics | None = None,
    enable_model: bool = True,
) -> AnomalyAnalysisResult:
    """Compute Task 10 anomaly metrics without mutating graph inputs."""
    config = config or AnalysisConfig()
    topology = topology or analyze_topology(table_graph, config=config)
    impact = impact or analyze_impact(
        table_graph,
        topology=topology,
        config=config,
    )
    communities = communities or analyze_communities(
        table_graph,
        topology=topology,
        impact=impact,
        config=config,
    )
    rule_records, missing_feature_names = _rule_records(
        table_graph,
        topology,
        impact,
        communities,
        basic_metrics,
        config,
    )
    rule_metric = _rule_metric(rule_records, missing_feature_names, config)
    model_metric, table_metrics = _model_metric(rule_records, config, enable_model)
    return AnomalyAnalysisResult(
        summary=_summary_metrics(rule_metric, model_metric, table_metrics),
        rule_based=rule_metric,
        unsupervised_model=model_metric,
        table_metrics=table_metrics,
    )


def _rule_records(
    table_graph: TableGraph,
    topology: TopologyAnalysisResult,
    impact: ImpactAnalysisResult,
    communities: CommunityAnalysisResult,
    basic_metrics: BasicGovernanceMetrics | None,
    config: AnalysisConfig,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...]]:
    topology_by_table = {
        str(item["table_id"]): thaw(item) for item in topology.table_metrics
    }
    impact_by_table = {
        str(item["table_id"]): thaw(item) for item in impact.table_metrics
    }
    community_by_table = {
        str(item["table_id"]): thaw(item) for item in communities.table_metrics
    }
    basic_by_table, unknown_by_table, missing_features = _basic_feature_indexes(
        basic_metrics
    )
    violation_counts = _layer_violation_counts(topology)

    max_in = max((int(table_graph.in_degree.get(tid, 0)) for tid in table_graph.nodes), default=0)
    max_out = max((int(table_graph.out_degree.get(tid, 0)) for tid in table_graph.nodes), default=0)
    max_drift = max(
        (
            int(item.get("layer_drift_abs", 0) or 0)
            for item in topology_by_table.values()
        ),
        default=0,
    )
    max_entropy = max(
        (
            float(item.get("impact_entropy", 0.0) or 0.0)
            for item in impact_by_table.values()
        ),
        default=0.0,
    )
    max_violation = max(violation_counts.values(), default=0)

    records: list[dict[str, Any]] = []
    for table_id in table_graph.nodes:
        basic = basic_by_table.get(table_id)
        topology_item = topology_by_table.get(table_id, {})
        impact_item = impact_by_table.get(table_id, {})
        community_item = community_by_table.get(table_id, {})
        field_count = None if basic is None else int(basic.get("field_count", 0))
        unknown_count = unknown_by_table.get(table_id)

        feature_values: dict[str, float | None] = {
            "high_in_degree": _normalize(
                int(table_graph.in_degree.get(table_id, 0)),
                max_in,
                config.float_precision,
            ),
            "high_out_degree": _normalize(
                int(table_graph.out_degree.get(table_id, 0)),
                max_out,
                config.float_precision,
            ),
            "layer_drift": _normalize(
                int(topology_item.get("layer_drift_abs", 0) or 0),
                max_drift,
                config.float_precision,
            ),
            "impact_entropy": _normalize(
                float(impact_item.get("impact_entropy", 0.0) or 0.0),
                max_entropy,
                config.float_precision,
            ),
            "unknown_lineage": (
                None
                if unknown_count is None or field_count is None
                else _ratio(unknown_count, max(field_count, 1), config.float_precision)
            ),
            "multi_producer": (
                None
                if basic is None
                else (1.0 if bool(basic.get("multi_producer")) else 0.0)
            ),
            "cycle_member": (
                1.0 if bool(topology_item.get("is_cycle_member")) else 0.0
            ),
            "cross_layer_violation": _normalize(
                violation_counts.get(table_id, 0),
                max_violation,
                config.float_precision,
            ),
        }
        contributions, score, score_status = _rule_score(
            feature_values,
            config,
        )
        records.append(
            {
                "table_id": table_id,
                "table_name": _table_full_name(
                    table_graph.nodes_by_id.get(table_id, {})
                ),
                "rule_anomaly_score": score,
                "rule_anomaly_status": score_status,
                "rule_anomaly_version": _rule_score_version(config),
                "feature_values": feature_values,
                "feature_contributions": contributions,
                "feature_weights": {
                    name: RULE_ANOMALY_WEIGHTS[name]
                    for name, value in feature_values.items()
                    if value is not None
                },
                "missing_features": tuple(
                    sorted(name for name, value in feature_values.items() if value is None)
                ),
                "raw_features": {
                    "in_degree": int(table_graph.in_degree.get(table_id, 0)),
                    "out_degree": int(table_graph.out_degree.get(table_id, 0)),
                    "layer_drift_abs": topology_item.get("layer_drift_abs"),
                    "impact_entropy": impact_item.get("impact_entropy"),
                    "unknown_source_column_count": unknown_count,
                    "field_count": field_count,
                    "multi_producer": None if basic is None else bool(basic.get("multi_producer")),
                    "is_cycle_member": bool(topology_item.get("is_cycle_member")),
                    "cross_layer_violation_count": violation_counts.get(table_id, 0),
                    "bridge_score": community_item.get("bridge_score"),
                },
            }
        )

    records.sort(
        key=lambda item: (
            -float(item["rule_anomaly_score"] or 0.0),
            str(item["table_id"]),
        )
    )
    return tuple(records), tuple(sorted(missing_features))


def _rule_score(
    feature_values: Mapping[str, float | None],
    config: AnalysisConfig,
) -> tuple[dict[str, float], float | None, str]:
    available = {
        name: float(value)
        for name, value in feature_values.items()
        if value is not None
    }
    total_weight = sum(RULE_ANOMALY_WEIGHTS[name] for name in available)
    if total_weight == 0:
        return {}, None, "unavailable"
    contributions = {
        name: round(
            (available[name] * RULE_ANOMALY_WEIGHTS[name]) / total_weight,
            config.float_precision,
        )
        for name in sorted(available)
    }
    score = round(sum(contributions.values()), config.float_precision)
    status = "success" if len(available) == len(RULE_ANOMALY_WEIGHTS) else "degraded"
    return contributions, score, status


def _rule_metric(
    records: tuple[Mapping[str, Any], ...],
    missing_feature_names: tuple[str, ...],
    config: AnalysisConfig,
) -> MetricResult:
    status = MetricStatus.DEGRADED if missing_feature_names else MetricStatus.SUCCESS
    reason = (
        "basic metrics were not provided; unavailable features were excluded: "
        + ", ".join(missing_feature_names)
        if missing_feature_names
        else None
    )
    return MetricResult(
        name="rule_based_anomaly",
        status=status,
        value={
            "table_count": len(records),
            "records": records,
            "feature_version": ANOMALY_FEATURE_VERSION,
            "feature_weights": dict(sorted(RULE_ANOMALY_WEIGHTS.items())),
            "missing_feature_names": missing_feature_names,
        },
        reason=reason,
        algorithm="anomaly.rule_weighted_features",
        version=ANOMALY_VERSION,
        parameters={
            "normalization": "per-run-max",
            "float_precision": config.float_precision,
        },
    )


def _model_metric(
    rule_records: tuple[dict[str, Any], ...],
    config: AnalysisConfig,
    enable_model: bool,
) -> tuple[MetricResult, tuple[Mapping[str, Any], ...]]:
    base_records = [dict(record) for record in rule_records]
    if not enable_model:
        return _skipped_model(
            base_records,
            "unsupervised anomaly model is disabled",
            config,
        )
    if len(base_records) < 4:
        return _skipped_model(
            base_records,
            "at least 4 table samples are required for model training",
            config,
        )
    if len(base_records) > config.resource_budget.exact_algorithm_max_nodes:
        return _skipped_model(
            base_records,
            "table graph exceeds model training sample budget",
            config,
        )

    isolation_forest = _load_isolation_forest()
    if isolation_forest is None:
        return _skipped_model(
            base_records,
            "scikit-learn is not installed",
            config,
        )

    feature_names = tuple(sorted(RULE_ANOMALY_WEIGHTS))
    matrix = [
        [
            float(record["feature_values"].get(name) or 0.0)
            for name in feature_names
        ]
        for record in base_records
    ]
    model = isolation_forest(
        n_estimators=100,
        contamination="auto",
        random_state=config.random_seed,
    )
    model.fit(matrix)
    raw_scores = [-float(score) for score in model.score_samples(matrix)]
    labels = [int(label) for label in model.predict(matrix)]
    normalized_scores = _normalize_scores(raw_scores, config.float_precision)
    if not (len(base_records) == len(raw_scores) == len(normalized_scores) == len(labels)):
        raise RuntimeError("anomaly model produced inconsistent result lengths")
    model_records: list[dict[str, Any]] = []
    for record, raw_score, normalized, label in zip(
        base_records,
        raw_scores,
        normalized_scores,
        labels,
    ):
        record["model_anomaly_score"] = normalized
        record["model_raw_score"] = round(raw_score, config.float_precision)
        record["model_anomaly_label"] = "outlier" if label == -1 else "inlier"
        record["model_feature_version"] = ANOMALY_FEATURE_VERSION
        model_records.append(record)
    model_records.sort(
        key=lambda item: (
            -float(item.get("model_anomaly_score") or 0.0),
            str(item["table_id"]),
        )
    )
    metric = MetricResult(
        name="unsupervised_anomaly_model",
        status=MetricStatus.SUCCESS,
        value={
            "records": tuple(
                {
                    "table_id": record["table_id"],
                    "model_anomaly_score": record["model_anomaly_score"],
                    "model_raw_score": record["model_raw_score"],
                    "model_anomaly_label": record["model_anomaly_label"],
                }
                for record in model_records
            ),
            "feature_names": feature_names,
            "feature_version": ANOMALY_FEATURE_VERSION,
            "parameters": {
                "backend": "sklearn.ensemble.IsolationForest",
                "n_estimators": 100,
                "contamination": "auto",
                "random_seed": config.random_seed,
            },
            "training_summary": {
                "sample_count": len(model_records),
                "feature_count": len(feature_names),
                "outlier_count": sum(
                    1 for record in model_records
                    if record["model_anomaly_label"] == "outlier"
                ),
            },
        },
        algorithm="anomaly.isolation_forest",
        version=ANOMALY_VERSION,
        parameters={
            "feature_version": ANOMALY_FEATURE_VERSION,
            "random_seed": config.random_seed,
        },
    )
    return metric, tuple(model_records)


def _skipped_model(
    records: list[dict[str, Any]],
    reason: str,
    config: AnalysisConfig,
) -> tuple[MetricResult, tuple[Mapping[str, Any], ...]]:
    for record in records:
        record["model_anomaly_score"] = None
        record["model_raw_score"] = None
        record["model_anomaly_label"] = None
        record["model_feature_version"] = ANOMALY_FEATURE_VERSION
    metric = MetricResult(
        name="unsupervised_anomaly_model",
        status=MetricStatus.SKIPPED,
        value={
            "records": (),
            "feature_names": tuple(sorted(RULE_ANOMALY_WEIGHTS)),
            "feature_version": ANOMALY_FEATURE_VERSION,
            "parameters": {
                "backend": "sklearn.ensemble.IsolationForest",
                "random_seed": config.random_seed,
            },
            "training_summary": {
                "sample_count": len(records),
                "feature_count": len(RULE_ANOMALY_WEIGHTS),
                "outlier_count": 0,
            },
        },
        reason=reason,
        algorithm="anomaly.isolation_forest",
        version=ANOMALY_VERSION,
        parameters={
            "feature_version": ANOMALY_FEATURE_VERSION,
            "random_seed": config.random_seed,
        },
    )
    return metric, tuple(records)


def _basic_feature_indexes(
    basic_metrics: BasicGovernanceMetrics | None,
) -> tuple[dict[str, Mapping[str, Any]], dict[str, int], set[str]]:
    missing: set[str] = set()
    if basic_metrics is None:
        missing.update({"unknown_lineage", "multi_producer"})
        return {}, {}, missing
    basic_by_table = {
        str(item["table_id"]): thaw(item) for item in basic_metrics.table_metrics
    }
    unknown_by_table = {table_id: 0 for table_id in basic_by_table}
    for column in basic_metrics.field_lineage.column_metrics:
        item = thaw(column)
        table_id = str(item.get("table_id", ""))
        if table_id:
            unknown_by_table[table_id] = unknown_by_table.get(table_id, 0) + int(
                item.get("unknown_source_count", 0) or 0
            )
    return basic_by_table, unknown_by_table, missing


def _layer_violation_counts(
    topology: TopologyAnalysisResult,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for violation in topology.layer_violations:
        item = thaw(violation)
        for key in ("source_table_id", "target_table_id"):
            table_id = str(item.get(key, ""))
            if table_id:
                counts[table_id] = counts.get(table_id, 0) + 1
    return counts


def _summary_metrics(
    rule_metric: MetricResult,
    model_metric: MetricResult,
    table_metrics: tuple[Mapping[str, Any], ...],
) -> dict[str, MetricResult]:
    top_rule = [
        {
            "table_id": str(item["table_id"]),
            "table_name": str(item["table_name"]),
            "rule_anomaly_score": item["rule_anomaly_score"],
        }
        for item in sorted(
            table_metrics,
            key=lambda record: (
                -float(record.get("rule_anomaly_score") or 0.0),
                str(record["table_id"]),
            ),
        )[:10]
        if item.get("rule_anomaly_score") is not None
    ]
    model_rows = [
        item for item in table_metrics
        if item.get("model_anomaly_score") is not None
    ]
    top_model = [
        {
            "table_id": str(item["table_id"]),
            "table_name": str(item["table_name"]),
            "model_anomaly_score": item["model_anomaly_score"],
        }
        for item in sorted(
            model_rows,
            key=lambda record: (
                -float(record.get("model_anomaly_score") or 0.0),
                str(record["table_id"]),
            ),
        )[:10]
    ]
    return {
        "rule_anomaly_table_count": _success_metric(
            "rule_anomaly_table_count",
            len(table_metrics),
        ),
        "rule_anomaly_status": _success_metric(
            "rule_anomaly_status",
            rule_metric.status.value,
        ),
        "model_anomaly_status": _success_metric(
            "model_anomaly_status",
            model_metric.status.value,
        ),
        "top_rule_anomaly_tables": _success_metric(
            "top_rule_anomaly_tables",
            top_rule,
        ),
        "top_model_anomaly_tables": _success_metric(
            "top_model_anomaly_tables",
            top_model,
        ),
    }


def _load_isolation_forest() -> Any | None:
    try:
        ensemble = import_module("sklearn.ensemble")
    except ImportError:
        return None
    return getattr(ensemble, "IsolationForest", None)


def _normalize_scores(
    values: Sequence[float],
    precision: int,
) -> tuple[float, ...]:
    if not values:
        return ()
    low = min(values)
    high = max(values)
    if high == low:
        return tuple(0.0 for _ in values)
    return tuple(round((value - low) / (high - low), precision) for value in values)


def _normalize(value: float | int, max_value: float | int, precision: int) -> float:
    if max_value <= 0:
        return 0.0
    return round(float(value) / float(max_value), precision)


def _ratio(numerator: int, denominator: int, precision: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, precision)


def _rule_score_version(config: AnalysisConfig) -> str:
    versions = dict(config.algorithm_versions)
    return versions.get("rule_anomaly_score", ANOMALY_VERSION)


def _success_metric(name: str, value: Any) -> MetricResult:
    return MetricResult(
        name=name,
        status=MetricStatus.SUCCESS,
        value=value,
        algorithm="anomaly.summary",
        version=ANOMALY_VERSION,
    )


def _table_full_name(table: Mapping[str, Any]) -> str:
    parts = [
        str(value)
        for value in (table.get("catalog"), table.get("schema_name"), table.get("name"))
        if value
    ]
    return ".".join(parts) if parts else str(table.get("name", ""))
