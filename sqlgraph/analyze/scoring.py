# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Versioned product maturity scoring for governance analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from sqlgraph.analyze.basic_metrics import BasicGovernanceMetrics
from sqlgraph.analyze.config import AnalysisConfig
from sqlgraph.analyze.contracts import MetricResult, MetricStatus, freeze, thaw
from sqlgraph.analyze.table_graph import TableGraph


PRODUCT_SCORE_VERSION = "1.0"
PRODUCT_SCORE_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "supply_importance": 0.25,
        "downstream_direct": 0.20,
        "field_quality": 0.25,
        "reuse": 0.10,
        "risk_inverse": 0.20,
    }
)


@dataclass(frozen=True)
class ProductScoreResult:
    """Product Score result with explicit degradation metadata."""

    summary: MetricResult
    table_scores: tuple[Mapping[str, Any], ...] = ()
    missing_submetrics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "table_scores",
            tuple(freeze(item) for item in self.table_scores),
        )
        object.__setattr__(
            self,
            "missing_submetrics",
            tuple(sorted(str(item) for item in self.missing_submetrics)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary.to_dict(),
            "table_scores": [thaw(item) for item in self.table_scores],
            "missing_submetrics": list(self.missing_submetrics),
        }


def analyze_product_scores(
    table_graph: TableGraph,
    *,
    basic_metrics: BasicGovernanceMetrics | None = None,
    topology_table_metrics: Sequence[Mapping[str, Any]] | None = None,
    config: AnalysisConfig | None = None,
) -> ProductScoreResult:
    """Compute Product Score v1 without treating missing inputs as zero."""
    config = config or AnalysisConfig()
    topology_by_table = {
        str(item.get("table_id")): item for item in (topology_table_metrics or ())
    }
    basic_by_table = {
        str(item.get("table_id")): item for item in (basic_metrics.table_metrics if basic_metrics else ())
    }
    lineage_by_table = _lineage_quality_by_table(basic_metrics)
    pagerank_by_table = _pagerank_reverse(topology_by_table)
    max_out_degree = max((int(value) for value in table_graph.out_degree.values()), default=0)

    global_missing: set[str] = set()
    if not pagerank_by_table:
        global_missing.add("pagerank_reverse")
    if basic_metrics is None:
        global_missing.update({"field_lineage_quality", "producer_risk"})

    records: list[dict[str, Any]] = []
    for table_id in table_graph.nodes:
        table = table_graph.nodes_by_id.get(table_id, {})
        basic = basic_by_table.get(table_id, {})
        lineage = lineage_by_table.get(table_id, {})
        missing = set(global_missing)

        supply = pagerank_by_table.get(table_id)
        if supply is None:
            missing.add("pagerank_reverse")

        downstream = _ratio(
            int(table_graph.out_degree.get(table_id, 0)),
            max_out_degree,
            config.float_precision,
        )
        field_quality = _lineage_ratio(lineage, "physical_source_count", "output_count", config)
        if field_quality is None:
            missing.add("field_lineage_quality")
        reuse = _lineage_ratio(lineage, "high_reuse_count", "output_count", config)
        if reuse is None:
            missing.add("reuse")
        risk_penalty = _risk_penalty(basic, lineage, config)
        if risk_penalty is None:
            missing.add("risk_penalty")
        risk_inverse = None if risk_penalty is None else round(1.0 - risk_penalty, config.float_precision)

        submetrics = {
            "supply_importance": supply,
            "downstream_direct": downstream,
            "field_quality": field_quality,
            "reuse": reuse,
            "risk_inverse": risk_inverse,
        }
        score = _weighted_score(submetrics, config.float_precision)
        status = "success" if not missing else "degraded"
        records.append(
            {
                "table_id": table_id,
                "table_name": _table_full_name(table),
                "product_score": score,
                "score_status": status,
                "formula_version": _product_score_version(config),
                "degraded_formula": bool(missing),
                "missing_submetrics": sorted(missing),
                "submetrics": submetrics,
                "penalties": {
                    "multi_producer": bool(basic.get("multi_producer", False)),
                    "unknown_source_ratio": _lineage_ratio(
                        lineage, "unknown_source_count", "output_count", config
                    ),
                    "lineage_breakpoint_ratio": _lineage_ratio(
                        lineage, "lineage_breakpoint_count", "output_count", config
                    ),
                    "risk_penalty": risk_penalty,
                },
                "weights_used": {
                    key: PRODUCT_SCORE_WEIGHTS[key]
                    for key, value in submetrics.items()
                    if value is not None
                },
            }
        )

    records.sort(
        key=lambda item: (
            item["product_score"] is None,
            -float(item["product_score"] or 0.0),
            str(item["table_id"]),
        )
    )
    missing_all = tuple(sorted({m for item in records for m in item["missing_submetrics"]}))
    summary_value = _summary_value(records, config)
    if missing_all and not config.allow_degraded:
        summary = MetricResult(
            name="product_score",
            status=MetricStatus.UNAVAILABLE,
            reason="required product score submetrics are missing: " + ", ".join(missing_all),
            algorithm="weighted_sum",
            version=_product_score_version(config),
            parameters={"weights": dict(PRODUCT_SCORE_WEIGHTS)},
        )
    elif missing_all:
        summary = MetricResult(
            name="product_score",
            status=MetricStatus.DEGRADED,
            value=summary_value,
            reason="required product score submetrics are missing: " + ", ".join(missing_all),
            algorithm="weighted_sum_degraded",
            version=_product_score_version(config),
            parameters={"weights": dict(PRODUCT_SCORE_WEIGHTS)},
        )
    else:
        summary = MetricResult(
            name="product_score",
            status=MetricStatus.SUCCESS,
            value=summary_value,
            algorithm="weighted_sum",
            version=_product_score_version(config),
            parameters={"weights": dict(PRODUCT_SCORE_WEIGHTS)},
        )
    return ProductScoreResult(
        summary=summary,
        table_scores=tuple(records),
        missing_submetrics=missing_all,
    )


def _lineage_quality_by_table(
    basic_metrics: BasicGovernanceMetrics | None,
) -> dict[str, dict[str, int]]:
    if basic_metrics is None:
        return {}
    grouped: dict[str, dict[str, int]] = {}
    for column in basic_metrics.field_lineage.column_metrics:
        table_id = str(column.get("table_id", ""))
        if not table_id:
            continue
        item = grouped.setdefault(
            table_id,
            {
                "output_count": 0,
                "physical_source_count": 0,
                "high_reuse_count": 0,
                "unknown_source_count": 0,
                "lineage_breakpoint_count": 0,
            },
        )
        item["output_count"] += 1
        if column.get("has_physical_source"):
            item["physical_source_count"] += 1
        if column.get("is_high_reuse"):
            item["high_reuse_count"] += 1
        if column.get("has_unknown_source"):
            item["unknown_source_count"] += 1
        if column.get("lineage_breakpoint"):
            item["lineage_breakpoint_count"] += 1
    return grouped


def _pagerank_reverse(
    topology_by_table: Mapping[str, Mapping[str, Any]],
) -> dict[str, float]:
    values = {
        table_id: item.get("pagerank_reverse")
        for table_id, item in topology_by_table.items()
        if item.get("pagerank_reverse") is not None
    }
    if not values:
        return {}
    max_value = max(float(value) for value in values.values())
    if max_value <= 0:
        return {table_id: 0.0 for table_id in sorted(values)}
    return {
        table_id: float(value) / max_value
        for table_id, value in sorted(values.items())
    }


def _risk_penalty(
    basic: Mapping[str, Any],
    lineage: Mapping[str, int],
    config: AnalysisConfig,
) -> float | None:
    if not basic and not lineage:
        return None
    output_count = int(lineage.get("output_count", 0))
    unknown_ratio = _ratio(int(lineage.get("unknown_source_count", 0)), output_count, config.float_precision)
    breakpoint_ratio = _ratio(
        int(lineage.get("lineage_breakpoint_count", 0)), output_count, config.float_precision
    )
    if unknown_ratio is None and breakpoint_ratio is None and "multi_producer" not in basic:
        return None
    parts = [1.0 if basic.get("multi_producer") else 0.0]
    parts.append(unknown_ratio if unknown_ratio is not None else 0.0)
    parts.append(breakpoint_ratio if breakpoint_ratio is not None else 0.0)
    return round(sum(parts) / len(parts), config.float_precision)


def _lineage_ratio(
    lineage: Mapping[str, int],
    numerator_key: str,
    denominator_key: str,
    config: AnalysisConfig,
) -> float | None:
    if not lineage:
        return None
    return _ratio(
        int(lineage.get(numerator_key, 0)),
        int(lineage.get(denominator_key, 0)),
        config.float_precision,
    )


def _weighted_score(
    submetrics: Mapping[str, float | None],
    precision: int,
) -> float | None:
    used = [
        (PRODUCT_SCORE_WEIGHTS[name], float(value))
        for name, value in submetrics.items()
        if value is not None
    ]
    if not used:
        return None
    weight_sum = sum(weight for weight, _value in used)
    raw = sum(weight * value for weight, value in used) / weight_sum
    return round(raw * 100.0, precision)


def _summary_value(
    records: Sequence[Mapping[str, Any]],
    config: AnalysisConfig,
) -> dict[str, Any]:
    scores = [float(item["product_score"]) for item in records if item.get("product_score") is not None]
    return {
        "formula_version": _product_score_version(config),
        "scored_table_count": len(scores),
        "table_count": len(records),
        "average_product_score": None if not scores else round(sum(scores) / len(scores), config.float_precision),
        "degraded_table_count": sum(1 for item in records if item.get("score_status") == "degraded"),
    }


def _product_score_version(config: AnalysisConfig) -> str:
    return dict(config.algorithm_versions).get("product_score", PRODUCT_SCORE_VERSION)


def _ratio(numerator: int, denominator: int, precision: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, precision)


def _table_full_name(table: Mapping[str, Any]) -> str:
    parts = [
        str(value)
        for value in (table.get("catalog"), table.get("schema_name"), table.get("name"))
        if value
    ]
    return ".".join(parts) if parts else str(table.get("name", ""))
