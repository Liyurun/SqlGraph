# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Column-level lineage quality metrics for governance analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from sqlgraph.analyze.config import AnalysisConfig
from sqlgraph.analyze.contracts import (
    AnalysisView,
    MetricResult,
    MetricStatus,
    freeze,
    thaw,
)


FIELD_LINEAGE_VERSION = "1.0"
_PHYSICAL_SOURCE_TYPES = {"passthrough", "derived", "aggregate", "window"}
_DERIVED_TYPES = {
    "arithmetic",
    "case_when",
    "cast",
    "coalesce",
    "function",
    "union",
}


@dataclass(frozen=True)
class FieldLineageResult:
    """Summary and per-column lineage quality metrics."""

    summary: Mapping[str, MetricResult] = field(default_factory=dict)
    column_metrics: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", freeze(self.summary))
        object.__setattr__(
            self,
            "column_metrics",
            tuple(freeze(item) for item in self.column_metrics),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                name: result.to_dict()
                for name, result in self.summary.items()
            },
            "column_metrics": [thaw(item) for item in self.column_metrics],
        }


def analyze_field_lineage(
    view: AnalysisView,
    config: AnalysisConfig | None = None,
    high_reuse_threshold: int = 2,
) -> FieldLineageResult:
    """Compute output-column lineage quality without mutating the graph."""
    config = config or AnalysisConfig()
    indexes = _build_indexes(view)
    output_columns = _output_column_ids(indexes)

    source_use_count = _source_use_count(indexes)
    fingerprint_output_count = _fingerprint_output_count(indexes)

    column_records: list[dict[str, Any]] = []
    counters = {
        "output_column_count": len(output_columns),
        "parsed_output_column_count": 0,
        "physical_source_column_count": 0,
        "passthrough_column_count": 0,
        "derived_column_count": 0,
        "aggregate_column_count": 0,
        "window_column_count": 0,
        "literal_column_count": 0,
        "function_column_count": 0,
        "unknown_source_column_count": 0,
        "lineage_breakpoint_column_count": 0,
        "high_reuse_column_count": 0,
    }

    for column_id in output_columns:
        record = _classify_column(
            column_id,
            indexes,
            source_use_count,
            fingerprint_output_count,
            high_reuse_threshold,
        )
        column_records.append(record)

        if record["is_parsed"]:
            counters["parsed_output_column_count"] += 1
        if record["has_physical_source"]:
            counters["physical_source_column_count"] += 1
        if record["classification"] == "passthrough":
            counters["passthrough_column_count"] += 1
        elif record["classification"] == "aggregate":
            counters["aggregate_column_count"] += 1
        elif record["classification"] == "window":
            counters["window_column_count"] += 1
        elif record["classification"] == "literal":
            counters["literal_column_count"] += 1
        elif record["classification"] == "function":
            counters["function_column_count"] += 1
        elif record["classification"] == "derived":
            counters["derived_column_count"] += 1
        if record["has_unknown_source"]:
            counters["unknown_source_column_count"] += 1
        if record["lineage_breakpoint"]:
            counters["lineage_breakpoint_column_count"] += 1
        if record["is_high_reuse"]:
            counters["high_reuse_column_count"] += 1

    output_count = counters["output_column_count"]
    parsed_count = counters["parsed_output_column_count"]
    physical_count = counters["physical_source_column_count"]
    counters["parsed_output_coverage_ratio"] = _ratio(
        parsed_count, output_count, config.float_precision
    )
    counters["physical_source_coverage_ratio"] = _ratio(
        physical_count, output_count, config.float_precision
    )

    summary = {
        name: _metric(name, value)
        for name, value in sorted(counters.items())
    }
    return FieldLineageResult(
        summary=summary,
        column_metrics=tuple(sorted(column_records, key=lambda item: item["column_id"])),
    )


def _build_indexes(view: AnalysisView) -> dict[str, Any]:
    tables = {str(node["id"]): dict(node) for node in view.iter_nodes("table")}
    columns = {str(node["id"]): dict(node) for node in view.iter_nodes("column")}
    transforms = {
        str(node["id"]): dict(node)
        for node in view.iter_nodes("transform")
    }

    columns_by_table: dict[str, set[str]] = {}
    for column_id, column in columns.items():
        table_id = column.get("table_id")
        if table_id is not None:
            columns_by_table.setdefault(str(table_id), set()).add(column_id)

    producer_tables: set[str] = set()
    direct_sources: dict[str, set[str]] = {}
    transform_sources: dict[str, set[str]] = {}
    produced_by: dict[str, set[str]] = {}

    for edge in view.edges:
        edge_type = str(edge["type"])
        source = str(edge["source"])
        target = str(edge["target"])
        if edge_type == "writes_to" and target in tables:
            producer_tables.add(target)
        elif edge_type == "compute_dependency":
            if source in columns and target in columns:
                direct_sources.setdefault(target, set()).add(source)
            elif source in columns and target in transforms:
                transform_sources.setdefault(target, set()).add(source)
        elif edge_type == "produces" and source in transforms and target in columns:
            produced_by.setdefault(target, set()).add(source)

    return {
        "tables": tables,
        "columns": columns,
        "transforms": transforms,
        "columns_by_table": columns_by_table,
        "producer_tables": producer_tables,
        "direct_sources": direct_sources,
        "transform_sources": transform_sources,
        "produced_by": produced_by,
    }


def _output_column_ids(indexes: Mapping[str, Any]) -> tuple[str, ...]:
    output_columns: set[str] = set()
    for table_id in indexes["producer_tables"]:
        output_columns.update(indexes["columns_by_table"].get(table_id, set()))
    output_columns.update(indexes["direct_sources"].keys())
    output_columns.update(indexes["produced_by"].keys())
    return tuple(sorted(output_columns))


def _source_use_count(indexes: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sources in indexes["direct_sources"].values():
        for source in sources:
            counts[source] = counts.get(source, 0) + 1
    for sources in indexes["transform_sources"].values():
        for source in sources:
            counts[source] = counts.get(source, 0) + 1
    return counts


def _fingerprint_output_count(indexes: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for transforms in indexes["produced_by"].values():
        for transform_id in transforms:
            transform = indexes["transforms"].get(transform_id, {})
            fingerprint = str(transform.get("fingerprint") or transform_id)
            counts[fingerprint] = counts.get(fingerprint, 0) + 1
    return counts


def _classify_column(
    column_id: str,
    indexes: Mapping[str, Any],
    source_use_count: Mapping[str, int],
    fingerprint_output_count: Mapping[str, int],
    high_reuse_threshold: int,
) -> dict[str, Any]:
    column = indexes["columns"].get(column_id, {})
    table_id = str(column.get("table_id", ""))
    table = indexes["tables"].get(table_id, {})
    direct_sources = set(indexes["direct_sources"].get(column_id, set()))
    transforms = set(indexes["produced_by"].get(column_id, set()))
    transform_sources: set[str] = set()
    transform_types: set[str] = set()
    transform_fingerprints: set[str] = set()

    for transform_id in transforms:
        transform = indexes["transforms"].get(transform_id, {})
        transform_sources.update(indexes["transform_sources"].get(transform_id, set()))
        transform_type = str(transform.get("expression_type") or "").lower()
        if transform_type:
            transform_types.add(transform_type)
        fingerprint = str(transform.get("fingerprint") or transform_id)
        transform_fingerprints.add(fingerprint)

    all_sources = direct_sources | transform_sources
    physical_sources = {
        source_id
        for source_id in all_sources
        if _is_physical_source(source_id, indexes)
    }
    unknown_sources = {
        source_id
        for source_id in all_sources
        if _is_unknown_source(source_id, indexes)
    }
    is_parsed = bool(direct_sources or transforms)
    has_physical_source = bool(physical_sources)
    classification = _classification(direct_sources, transform_types, all_sources)
    lineage_breakpoint = (
        (not is_parsed)
        or bool(unknown_sources)
        or (
            is_parsed
            and classification in _PHYSICAL_SOURCE_TYPES
            and not has_physical_source
        )
    )
    is_high_reuse = any(
        source_use_count.get(source_id, 0) >= high_reuse_threshold
        for source_id in all_sources
    ) or any(
        fingerprint_output_count.get(fingerprint, 0) >= high_reuse_threshold
        for fingerprint in transform_fingerprints
    )

    return {
        "column_id": column_id,
        "column_name": str(column.get("name", "")),
        "table_id": table_id,
        "table_name": _table_full_name(table),
        "classification": classification,
        "is_parsed": is_parsed,
        "has_physical_source": has_physical_source,
        "has_unknown_source": bool(unknown_sources),
        "lineage_breakpoint": lineage_breakpoint,
        "is_high_reuse": is_high_reuse,
        "direct_source_count": len(direct_sources),
        "transform_source_count": len(transform_sources),
        "physical_source_count": len(physical_sources),
        "unknown_source_count": len(unknown_sources),
        "source_column_ids": sorted(all_sources),
        "transform_ids": sorted(transforms),
        "transform_types": sorted(transform_types),
    }


def _classification(
    direct_sources: set[str],
    transform_types: set[str],
    all_sources: set[str],
) -> str:
    if direct_sources and not transform_types:
        return "passthrough"
    if "literal" in transform_types and not all_sources:
        return "literal"
    if "window" in transform_types:
        return "window"
    if "agg" in transform_types:
        return "aggregate"
    if transform_types & _DERIVED_TYPES:
        return "derived"
    if transform_types:
        return "function"
    return "unparsed"


def _is_physical_source(source_id: str, indexes: Mapping[str, Any]) -> bool:
    column = indexes["columns"].get(source_id)
    if not column:
        return False
    table_id = column.get("table_id")
    table = indexes["tables"].get(str(table_id), {})
    if not table or bool(table.get("is_cte", False)):
        return False
    return not _is_unknown_table(table)


def _is_unknown_source(source_id: str, indexes: Mapping[str, Any]) -> bool:
    column = indexes["columns"].get(source_id)
    if not column:
        return True
    table = indexes["tables"].get(str(column.get("table_id")), {})
    return not table or _is_unknown_table(table)


def _is_unknown_table(table: Mapping[str, Any]) -> bool:
    candidates = (
        str(table.get("id", "")),
        str(table.get("name", "")),
        str(table.get("schema_name", "")),
        _table_full_name(table),
    )
    return any("unknown" in item.lower() for item in candidates)


def _table_full_name(table: Mapping[str, Any]) -> str:
    parts = [
        str(value)
        for value in (table.get("catalog"), table.get("schema_name"), table.get("name"))
        if value
    ]
    return ".".join(parts) if parts else str(table.get("name", ""))


def _metric(name: str, value: Any) -> MetricResult:
    return MetricResult(
        name=name,
        status=MetricStatus.SUCCESS,
        value=value,
        algorithm="lineage_graph_count",
        version=FIELD_LINEAGE_VERSION,
    )


def _ratio(numerator: int, denominator: int, precision: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, precision)
