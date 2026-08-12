# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Consistency and metric-definition drift analysis over Transform nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Sequence

from sqlgraph.analyze.basic_metrics import BasicGovernanceMetrics, analyze_basic_metrics
from sqlgraph.analyze.config import AnalysisConfig
from sqlgraph.analyze.contracts import AnalysisView, MetricResult, MetricStatus, freeze, thaw
from sqlgraph.analyze.scoring import ProductScoreResult, analyze_product_scores
from sqlgraph.analyze.table_graph import TableGraph, build_table_graph


CONSISTENCY_VERSION = "1.0"
_DEFAULT_METRIC_PATTERNS = (
    "amount",
    "avg",
    "cnt",
    "count",
    "gmv",
    "metric",
    "rate",
    "ratio",
    "revenue",
    "score",
    "sum",
    "total",
)
_AGGREGATE_FUNCTIONS = (
    "approx_count_distinct",
    "count_distinct",
    "count",
    "sum",
    "avg",
    "average",
    "min",
    "max",
)


@dataclass(frozen=True)
class ConsistencyAnalysisResult:
    """Task 8 result bundle for consistency and maturity metrics."""

    summary: Mapping[str, MetricResult] = field(default_factory=dict)
    duplicate_expressions: tuple[Mapping[str, Any], ...] = ()
    same_name_different_logic: tuple[Mapping[str, Any], ...] = ()
    same_logic_different_names: tuple[Mapping[str, Any], ...] = ()
    metric_candidates: tuple[Mapping[str, Any], ...] = ()
    transform_metrics: tuple[Mapping[str, Any], ...] = ()
    product_score: ProductScoreResult | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", freeze(self.summary))
        for name in (
            "duplicate_expressions",
            "same_name_different_logic",
            "same_logic_different_names",
            "metric_candidates",
            "transform_metrics",
        ):
            object.__setattr__(
                self,
                name,
                tuple(freeze(item) for item in getattr(self, name)),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                name: metric.to_dict() for name, metric in self.summary.items()
            },
            "duplicate_expressions": [thaw(item) for item in self.duplicate_expressions],
            "same_name_different_logic": [
                thaw(item) for item in self.same_name_different_logic
            ],
            "same_logic_different_names": [
                thaw(item) for item in self.same_logic_different_names
            ],
            "metric_candidates": [thaw(item) for item in self.metric_candidates],
            "transform_metrics": [thaw(item) for item in self.transform_metrics],
            "product_score": None if self.product_score is None else self.product_score.to_dict(),
        }


def analyze_consistency(
    view: AnalysisView,
    *,
    table_graph: TableGraph | None = None,
    basic_metrics: BasicGovernanceMetrics | None = None,
    topology_table_metrics: Sequence[Mapping[str, Any]] | None = None,
    config: AnalysisConfig | None = None,
) -> ConsistencyAnalysisResult:
    """Analyze Transform fingerprint consistency without mutating the graph."""
    config = config or AnalysisConfig()
    table_graph = table_graph or build_table_graph(view)
    basic_metrics = basic_metrics or analyze_basic_metrics(
        view,
        table_graph=table_graph,
        config=config,
    )
    indexes = _build_indexes(view)
    transform_metrics = _transform_metrics(indexes)
    duplicate_expressions = _duplicate_expressions(transform_metrics)
    same_name = _same_name_different_logic(transform_metrics)
    same_logic = _same_logic_different_names(transform_metrics)
    metric_candidates = _metric_candidates(transform_metrics, config)
    product_score = analyze_product_scores(
        table_graph,
        basic_metrics=basic_metrics,
        topology_table_metrics=topology_table_metrics,
        config=config,
    )
    summary_values = {
        "transform_metric_count": len(transform_metrics),
        "duplicate_expression_group_count": len(duplicate_expressions),
        "same_name_different_logic_count": len(same_name),
        "same_logic_different_names_count": len(same_logic),
        "metric_candidate_count": len(metric_candidates),
    }
    summary = {
        name: _success_metric(name, value)
        for name, value in sorted(summary_values.items())
    }
    return ConsistencyAnalysisResult(
        summary=summary,
        duplicate_expressions=tuple(duplicate_expressions),
        same_name_different_logic=tuple(same_name),
        same_logic_different_names=tuple(same_logic),
        metric_candidates=tuple(metric_candidates),
        transform_metrics=tuple(transform_metrics),
        product_score=product_score,
    )


def _build_indexes(view: AnalysisView) -> dict[str, Any]:
    tables = {str(node["id"]): dict(node) for node in view.iter_nodes("table")}
    columns = {str(node["id"]): dict(node) for node in view.iter_nodes("column")}
    transforms = {str(node["id"]): dict(node) for node in view.iter_nodes("transform")}
    sql_nodes = {str(node["id"]): dict(node) for node in view.iter_nodes("sql")}

    columns_by_table: dict[str, set[str]] = {}
    for column_id, column in columns.items():
        table_id = column.get("table_id")
        if table_id is not None:
            columns_by_table.setdefault(str(table_id), set()).add(column_id)

    transform_outputs: dict[str, set[str]] = {}
    transform_sources: dict[str, set[str]] = {}
    transform_sqls: dict[str, set[str]] = {}
    producer_sql_by_table: dict[str, set[str]] = {}
    reads_by_sql: dict[str, set[str]] = {}

    for edge in view.edges:
        source = str(edge["source"])
        target = str(edge["target"])
        edge_type = str(edge["type"])
        if edge_type == "produces" and source in transforms and target in columns:
            transform_outputs.setdefault(source, set()).add(target)
        elif edge_type == "compute_dependency" and source in columns and target in transforms:
            transform_sources.setdefault(target, set()).add(source)
        elif edge_type == "contains" and source in sql_nodes and target in transforms:
            transform_sqls.setdefault(target, set()).add(source)
        elif edge_type == "writes_to" and source in sql_nodes and target in tables:
            producer_sql_by_table.setdefault(target, set()).add(source)
        elif edge_type == "reads_from" and source in sql_nodes and target in tables:
            reads_by_sql.setdefault(source, set()).add(target)

    for transform_id, output_columns in transform_outputs.items():
        for column_id in output_columns:
            table_id = columns.get(column_id, {}).get("table_id")
            if table_id is not None:
                transform_sqls.setdefault(transform_id, set()).update(
                    producer_sql_by_table.get(str(table_id), set())
                )

    return {
        "tables": tables,
        "columns": columns,
        "transforms": transforms,
        "sql_nodes": sql_nodes,
        "columns_by_table": columns_by_table,
        "transform_outputs": transform_outputs,
        "transform_sources": transform_sources,
        "transform_sqls": transform_sqls,
        "producer_sql_by_table": producer_sql_by_table,
        "reads_by_sql": reads_by_sql,
    }


def _transform_metrics(indexes: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for transform_id in sorted(indexes["transforms"]):
        transform = indexes["transforms"][transform_id]
        output_refs = [
            _column_ref(column_id, indexes)
            for column_id in sorted(indexes["transform_outputs"].get(transform_id, set()))
        ]
        source_refs = [
            _column_ref(column_id, indexes)
            for column_id in sorted(indexes["transform_sources"].get(transform_id, set()))
        ]
        output_field_names = sorted(
            {
                ref["column_name"]
                for ref in output_refs
                if ref["column_name"]
            }
            | ({str(transform.get("output_name"))} if transform.get("output_name") else set())
        )
        expression = str(transform.get("expression") or transform.get("name") or "")
        fingerprint = str(transform.get("fingerprint") or transform_id)
        sql_ids = sorted(indexes["transform_sqls"].get(transform_id, set()))
        target_table_ids = sorted({ref["table_id"] for ref in output_refs if ref["table_id"]})
        records.append(
            {
                "transform_id": transform_id,
                "fingerprint": fingerprint,
                "expression": expression,
                "expression_type": str(transform.get("expression_type") or ""),
                "op": str(transform.get("op") or ""),
                "output_name": str(transform.get("output_name") or ""),
                "output_field_names": output_field_names,
                "output_columns": output_refs,
                "source_columns": source_refs,
                "sql_ids": sql_ids,
                "target_table_ids": target_table_ids,
                "target_table_names": [
                    _table_full_name(indexes["tables"].get(table_id, {}))
                    for table_id in target_table_ids
                ],
                "aggregation_functions": _aggregation_functions(transform, expression),
                "filter_evidence": _filter_evidence(expression),
                "time_window_evidence": _time_window_evidence(transform, expression),
            }
        )
    return records


def _duplicate_expressions(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups = _group_by(records, "fingerprint")
    output: list[dict[str, Any]] = []
    for fingerprint, items in sorted(groups.items()):
        output_columns = _unique_dicts(
            ref for item in items for ref in item.get("output_columns", ())
        )
        sql_ids = sorted({sql_id for item in items for sql_id in item.get("sql_ids", ())})
        table_ids = sorted(
            {table_id for item in items for table_id in item.get("target_table_ids", ())}
        )
        field_names = sorted(
            {name for item in items for name in item.get("output_field_names", ()) if name}
        )
        occurrence_count = len(output_columns) if output_columns else len(items)
        if occurrence_count <= 1 and len(sql_ids) <= 1 and len(table_ids) <= 1:
            continue
        output.append(
            {
                "fingerprint": fingerprint,
                "candidate_type": "duplicate_expression",
                "transform_count": len(items),
                "occurrence_count": occurrence_count,
                "sql_count": len(sql_ids),
                "table_count": len(table_ids),
                "field_count": len(output_columns),
                "transform_ids": sorted(str(item["transform_id"]) for item in items),
                "sql_ids": sql_ids,
                "target_table_ids": table_ids,
                "target_table_names": sorted(
                    {
                        name
                        for item in items
                        for name in item.get("target_table_names", ())
                        if name
                    }
                ),
                "field_names": field_names,
                "output_columns": output_columns,
                "expressions": sorted({str(item.get("expression", "")) for item in items}),
            }
        )
    return sorted(output, key=lambda item: (item["fingerprint"], item["transform_ids"]))


def _same_name_different_logic(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    field_groups: dict[str, list[Mapping[str, Any]]] = {}
    for item in records:
        for field_name in item.get("output_field_names", ()):
            key = _normalize_name(str(field_name))
            if key:
                field_groups.setdefault(key, []).append(item)
    output: list[dict[str, Any]] = []
    for field_name, items in sorted(field_groups.items()):
        fingerprints = sorted({str(item["fingerprint"]) for item in items})
        if len(fingerprints) <= 1:
            continue
        output.append(
            {
                "field_name": field_name,
                "candidate_type": "same_name_different_logic",
                "is_business_error": False,
                "fingerprint_count": len(fingerprints),
                "fingerprints": fingerprints,
                "expressions": _fingerprint_expressions(items),
                "sql_ids": sorted({sql for item in items for sql in item.get("sql_ids", ())}),
                "target_table_ids": sorted(
                    {table for item in items for table in item.get("target_table_ids", ())}
                ),
                "output_columns": _unique_dicts(
                    ref for item in items for ref in item.get("output_columns", ())
                ),
            }
        )
    return output


def _same_logic_different_names(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups = _group_by(records, "fingerprint")
    output: list[dict[str, Any]] = []
    for fingerprint, items in sorted(groups.items()):
        field_names = sorted(
            {_normalize_name(name) for item in items for name in item.get("output_field_names", ()) if name}
        )
        if len(field_names) <= 1:
            continue
        output.append(
            {
                "fingerprint": fingerprint,
                "candidate_type": "same_logic_different_names",
                "is_business_error": False,
                "field_names": field_names,
                "transform_ids": sorted(str(item["transform_id"]) for item in items),
                "sql_ids": sorted({sql for item in items for sql in item.get("sql_ids", ())}),
                "target_table_ids": sorted(
                    {table for item in items for table in item.get("target_table_ids", ())}
                ),
                "output_columns": _unique_dicts(
                    ref for item in items for ref in item.get("output_columns", ())
                ),
                "expressions": sorted({str(item.get("expression", "")) for item in items}),
            }
        )
    return output


def _metric_candidates(
    records: Sequence[Mapping[str, Any]],
    config: AnalysisConfig,
) -> list[dict[str, Any]]:
    patterns = tuple(getattr(config, "metric_candidate_patterns", _DEFAULT_METRIC_PATTERNS))
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for item in records:
        for field_name in item.get("output_field_names", ()):
            normalized = _normalize_name(str(field_name))
            if normalized and _matches_metric_pattern(normalized, patterns):
                grouped.setdefault(normalized, []).append(item)
    output: list[dict[str, Any]] = []
    for metric_name, items in sorted(grouped.items()):
        fingerprints = sorted({str(item["fingerprint"]) for item in items})
        aggregations = _variant_values(items, "aggregation_functions")
        filters = _variant_values(items, "filter_evidence")
        windows = _variant_values(items, "time_window_evidence")
        has_drift = (
            len(fingerprints) > 1
            or len(aggregations) > 1
            or len(filters) > 1
            or len(windows) > 1
        )
        output.append(
            {
                "metric_name": metric_name,
                "candidate_type": "metric_definition_candidate",
                "candidate_only": True,
                "is_business_error": False,
                "has_drift_evidence": has_drift,
                "distinct_fingerprint_count": len(fingerprints),
                "fingerprints": fingerprints,
                "aggregation_functions": aggregations,
                "sql_ids": sorted({sql for item in items for sql in item.get("sql_ids", ())}),
                "target_table_ids": sorted(
                    {table for item in items for table in item.get("target_table_ids", ())}
                ),
                "field_names": sorted(
                    {name for item in items for name in item.get("output_field_names", ()) if name}
                ),
                "evidence": {
                    "filter_variants": filters,
                    "time_window_variants": windows,
                    "expressions": _fingerprint_expressions(items),
                },
            }
        )
    return output


def _aggregation_functions(transform: Mapping[str, Any], expression: str) -> list[str]:
    found = {
        match.group(1).lower()
        for match in re.finditer(
            r"\b(" + "|".join(re.escape(name) for name in _AGGREGATE_FUNCTIONS) + r")\s*\(",
            expression,
            flags=re.IGNORECASE,
        )
    }
    expression_type = str(transform.get("expression_type") or "").lower()
    op = str(transform.get("op") or "").lower()
    if expression_type == "agg" and op:
        found.add(op)
    elif expression_type == "agg" and not found:
        found.add("agg")
    return sorted(found) or ["none"]


def _filter_evidence(expression: str) -> list[str]:
    lower = expression.lower()
    evidence: set[str] = set()
    if "case when" in lower:
        evidence.add("case_when")
    if re.search(r"\bif\s*\(", lower):
        evidence.add("if")
    if re.search(r"\bwhere\b", lower):
        evidence.add("where")
    if re.search(r"\bfilter\s*\(", lower):
        evidence.add("filter")
    return sorted(evidence) or ["none"]


def _time_window_evidence(transform: Mapping[str, Any], expression: str) -> list[str]:
    lower = expression.lower()
    evidence: set[str] = set()
    if str(transform.get("expression_type") or "").lower() == "window":
        evidence.add("window")
    if " over" in lower or "over(" in lower:
        evidence.add("window")
    if re.search(r"\b(interval|between|date_sub|date_add|timestamp|dt|date)\b", lower):
        evidence.add("time_filter")
    return sorted(evidence) or ["none"]


def _variant_values(items: Sequence[Mapping[str, Any]], key: str) -> list[str]:
    values = sorted({str(value) for item in items for value in item.get(key, ())})
    return values or ["none"]


def _column_ref(column_id: str, indexes: Mapping[str, Any]) -> dict[str, str]:
    column = indexes["columns"].get(column_id, {})
    table_id = str(column.get("table_id") or "")
    table = indexes["tables"].get(table_id, {})
    return {
        "column_id": column_id,
        "column_name": str(column.get("name") or ""),
        "table_id": table_id,
        "table_name": _table_full_name(table),
    }


def _fingerprint_expressions(items: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    pairs = {
        (str(item.get("fingerprint", "")), str(item.get("expression", "")))
        for item in items
    }
    return [
        {"fingerprint": fingerprint, "expression": expression}
        for fingerprint, expression in sorted(pairs)
    ]


def _group_by(
    records: Sequence[Mapping[str, Any]],
    key: str,
) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record[key]), []).append(record)
    return grouped


def _unique_dicts(items) -> list[dict[str, Any]]:
    seen: set[tuple[tuple[str, Any], ...]] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        plain = dict(item)
        key = tuple(sorted(plain.items()))
        if key in seen:
            continue
        seen.add(key)
        output.append(plain)
    return sorted(output, key=lambda value: tuple((k, str(v)) for k, v in sorted(value.items())))


def _matches_metric_pattern(name: str, patterns: Sequence[str]) -> bool:
    lower = name.lower()
    return any(str(pattern).lower() in lower for pattern in patterns if str(pattern).strip())


def _normalize_name(name: str) -> str:
    return name.strip().lower()


def _table_full_name(table: Mapping[str, Any]) -> str:
    parts = [
        str(value)
        for value in (table.get("catalog"), table.get("schema_name"), table.get("name"))
        if value
    ]
    return ".".join(parts) if parts else str(table.get("name", ""))


def _success_metric(name: str, value: Any) -> MetricResult:
    return MetricResult(
        name=name,
        status=MetricStatus.SUCCESS,
        value=value,
        algorithm="transform_fingerprint_consistency",
        version=CONSISTENCY_VERSION,
    )
