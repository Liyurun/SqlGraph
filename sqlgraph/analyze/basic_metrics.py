# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Basic warehouse governance metrics over immutable analysis views."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from sqlgraph.analyze.config import AnalysisConfig
from sqlgraph.analyze.contracts import (
    AnalysisView,
    MetricResult,
    MetricStatus,
    freeze,
    thaw,
)
from sqlgraph.analyze.lineage_metrics import (
    FieldLineageResult,
    analyze_field_lineage,
)
from sqlgraph.analyze.table_graph import TableGraph, build_table_graph


BASIC_METRICS_VERSION = "1.0"


@dataclass(frozen=True)
class BasicGovernanceMetrics:
    """Task 3 result bundle for basic governance statistics."""

    overview: Mapping[str, MetricResult] = field(default_factory=dict)
    layer_distribution: tuple[Mapping[str, Any], ...] = ()
    layer_matrix: tuple[Mapping[str, Any], ...] = ()
    production_consumption: Mapping[str, Any] = field(default_factory=dict)
    field_lineage: FieldLineageResult = field(default_factory=FieldLineageResult)
    parse_diagnostics: Mapping[str, MetricResult] = field(default_factory=dict)
    table_metrics: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "overview", freeze(self.overview))
        object.__setattr__(
            self,
            "layer_distribution",
            tuple(freeze(item) for item in self.layer_distribution),
        )
        object.__setattr__(
            self,
            "layer_matrix",
            tuple(freeze(item) for item in self.layer_matrix),
        )
        object.__setattr__(
            self,
            "production_consumption",
            freeze(self.production_consumption),
        )
        object.__setattr__(
            self,
            "parse_diagnostics",
            freeze(self.parse_diagnostics),
        )
        object.__setattr__(
            self,
            "table_metrics",
            tuple(freeze(item) for item in self.table_metrics),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "overview": {
                name: result.to_dict()
                for name, result in self.overview.items()
            },
            "layer_distribution": [thaw(item) for item in self.layer_distribution],
            "layer_matrix": [thaw(item) for item in self.layer_matrix],
            "production_consumption": thaw(self.production_consumption),
            "field_lineage": self.field_lineage.to_dict(),
            "parse_diagnostics": {
                name: result.to_dict()
                for name, result in self.parse_diagnostics.items()
            },
            "table_metrics": [thaw(item) for item in self.table_metrics],
        }


def analyze_basic_metrics(
    view: AnalysisView,
    table_graph: TableGraph | None = None,
    config: AnalysisConfig | None = None,
    parse_diagnostics: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    top_n: int = 10,
) -> BasicGovernanceMetrics:
    """Compute Task 3 governance metrics without modifying the input graph."""
    config = config or AnalysisConfig()
    table_graph = table_graph or build_table_graph(view)
    indexes = _build_indexes(view, table_graph, config)
    field_lineage = analyze_field_lineage(view, config=config)

    overview = _overview_metrics(view, table_graph, indexes, config)
    table_metrics = _table_metrics(table_graph, indexes)
    layer_distribution, layer_matrix = _layer_metrics(table_graph, indexes, config)
    production = _production_consumption(table_metrics, top_n)
    diagnostics = _parse_diagnostic_metrics(parse_diagnostics, config)

    return BasicGovernanceMetrics(
        overview=overview,
        layer_distribution=layer_distribution,
        layer_matrix=layer_matrix,
        production_consumption=production,
        field_lineage=field_lineage,
        parse_diagnostics=diagnostics,
        table_metrics=table_metrics,
    )


def _build_indexes(
    view: AnalysisView,
    table_graph: TableGraph,
    config: AnalysisConfig,
) -> dict[str, Any]:
    tables = {str(node["id"]): dict(node) for node in view.iter_nodes("table")}
    columns = {str(node["id"]): dict(node) for node in view.iter_nodes("column")}
    transforms = {
        str(node["id"]): dict(node)
        for node in view.iter_nodes("transform")
    }
    sql_nodes = {str(node["id"]): dict(node) for node in view.iter_nodes("sql")}

    columns_by_table: dict[str, set[str]] = {}
    for column_id, column in columns.items():
        table_id = column.get("table_id")
        if table_id is not None:
            columns_by_table.setdefault(str(table_id), set()).add(column_id)

    sql_reads: dict[str, set[str]] = {}
    sql_writes: dict[str, set[str]] = {}
    producer_sql_by_table: dict[str, set[str]] = {}
    read_count_by_table: dict[str, int] = {node_id: 0 for node_id in table_graph.nodes}
    write_count_by_table: dict[str, int] = {node_id: 0 for node_id in table_graph.nodes}

    for edge in view.edges:
        source = str(edge["source"])
        target = str(edge["target"])
        edge_type = str(edge["type"])
        if edge_type == "reads_from" and target in table_graph.node_index:
            sql_reads.setdefault(source, set()).add(target)
            read_count_by_table[target] = read_count_by_table.get(target, 0) + 1
        elif edge_type == "writes_to" and target in table_graph.node_index:
            sql_writes.setdefault(source, set()).add(target)
            producer_sql_by_table.setdefault(target, set()).add(source)
            write_count_by_table[target] = write_count_by_table.get(target, 0) + 1

    layers = {
        table_id: _match_layer(table_graph.nodes_by_id.get(table_id, {}), config)
        for table_id in table_graph.nodes
    }

    return {
        "tables": tables,
        "columns": columns,
        "transforms": transforms,
        "sql_nodes": sql_nodes,
        "columns_by_table": columns_by_table,
        "sql_reads": sql_reads,
        "sql_writes": sql_writes,
        "producer_sql_by_table": producer_sql_by_table,
        "read_count_by_table": read_count_by_table,
        "write_count_by_table": write_count_by_table,
        "layers": layers,
    }


def _overview_metrics(
    view: AnalysisView,
    table_graph: TableGraph,
    indexes: Mapping[str, Any],
    config: AnalysisConfig,
) -> dict[str, MetricResult]:
    table_nodes = list(view.iter_nodes("table"))
    physical_table_ids = set(table_graph.nodes)
    physical_column_count = sum(
        1
        for column in indexes["columns"].values()
        if str(column.get("table_id")) in physical_table_ids
    )
    overview = {
        "sql_count": len(indexes["sql_nodes"]),
        "table_count": len(table_nodes),
        "physical_table_count": table_graph.node_count,
        "logical_table_count": sum(
            1 for node in table_nodes if node.get("logic_fingerprint")
        ),
        "cte_table_count": sum(1 for node in table_nodes if node.get("is_cte")),
        "column_count": len(indexes["columns"]),
        "physical_column_count": physical_column_count,
        "transform_count": len(indexes["transforms"]),
        "table_lineage_edge_count": table_graph.edge_count,
        "field_dependency_edge_count": sum(
            1 for _ in view.iter_edges("compute_dependency")
        ),
        "average_fields_per_physical_table": _ratio(
            physical_column_count, table_graph.node_count, config.float_precision
        ),
        "average_upstream_count": _ratio(
            sum(table_graph.in_degree.values()),
            table_graph.node_count,
            config.float_precision,
        ),
        "average_downstream_count": _ratio(
            sum(table_graph.out_degree.values()),
            table_graph.node_count,
            config.float_precision,
        ),
    }
    return {
        name: _success_metric(name, value)
        for name, value in sorted(overview.items())
    }


def _table_metrics(
    table_graph: TableGraph,
    indexes: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for table_id in table_graph.nodes:
        node = table_graph.nodes_by_id.get(table_id, {})
        in_degree = int(table_graph.in_degree.get(table_id, 0))
        out_degree = int(table_graph.out_degree.get(table_id, 0))
        producer_count = len(indexes["producer_sql_by_table"].get(table_id, set()))
        records.append(
            {
                "table_id": table_id,
                "table_name": _table_full_name(node),
                "layer": indexes["layers"].get(table_id, "unknown"),
                "field_count": len(indexes["columns_by_table"].get(table_id, set())),
                "in_degree": in_degree,
                "out_degree": out_degree,
                "read_count": indexes["read_count_by_table"].get(table_id, 0),
                "write_count": indexes["write_count_by_table"].get(table_id, 0),
                "producer_count": producer_count,
                "no_upstream": in_degree == 0,
                "no_downstream": out_degree == 0,
                "multi_producer": producer_count > 1,
            }
        )
    return tuple(records)


def _layer_metrics(
    table_graph: TableGraph,
    indexes: Mapping[str, Any],
    config: AnalysisConfig,
) -> tuple[tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    by_layer: dict[str, dict[str, Any]] = {}

    def ensure(layer: str) -> dict[str, Any]:
        return by_layer.setdefault(
            layer,
            {
                "layer": layer,
                "table_count": 0,
                "field_count": 0,
                "sql_count": 0,
                "edge_count": 0,
                "no_downstream_table_count": 0,
                "multi_producer_table_count": 0,
            },
        )

    for table_id in table_graph.nodes:
        layer = indexes["layers"].get(table_id, "unknown")
        row = ensure(layer)
        row["table_count"] += 1
        row["field_count"] += len(indexes["columns_by_table"].get(table_id, set()))
        if table_graph.out_degree.get(table_id, 0) == 0:
            row["no_downstream_table_count"] += 1
        if len(indexes["producer_sql_by_table"].get(table_id, set())) > 1:
            row["multi_producer_table_count"] += 1

    sql_layers: dict[str, set[str]] = {}
    for sql_id, written_tables in indexes["sql_writes"].items():
        for table_id in written_tables:
            sql_layers.setdefault(sql_id, set()).add(
                indexes["layers"].get(table_id, "unknown")
            )
    for layers in sql_layers.values():
        for layer in layers:
            ensure(layer)["sql_count"] += 1

    matrix: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in table_graph.edges:
        source_layer = indexes["layers"].get(edge.source_id, "unknown")
        target_layer = indexes["layers"].get(edge.target_id, "unknown")
        ensure(source_layer)["edge_count"] += 1
        key = (source_layer, target_layer)
        item = matrix.setdefault(
            key,
            {
                "source_layer": source_layer,
                "target_layer": target_layer,
                "edge_count": 0,
                "field_weight": 0,
                "sql_weight": 0,
            },
        )
        item["edge_count"] += 1
        item["field_weight"] += edge.field_weight
        item["sql_weight"] += edge.sql_weight

    layer_order = _layer_order(config)
    distribution = tuple(
        by_layer[layer]
        for layer in sorted(by_layer, key=lambda value: layer_order.get(value, 999))
    )
    matrix_rows = tuple(
        matrix[key]
        for key in sorted(
            matrix,
            key=lambda item: (
                layer_order.get(item[0], 999),
                layer_order.get(item[1], 999),
                item,
            ),
        )
    )
    return distribution, matrix_rows


def _production_consumption(
    table_metrics: tuple[Mapping[str, Any], ...],
    top_n: int,
) -> dict[str, Any]:
    no_upstream = [item for item in table_metrics if item["no_upstream"]]
    no_downstream = [item for item in table_metrics if item["no_downstream"]]
    multi_producer = [item for item in table_metrics if item["multi_producer"]]

    return {
        "no_upstream_table_count": len(no_upstream),
        "no_downstream_table_count": len(no_downstream),
        "multi_producer_table_count": len(multi_producer),
        "no_upstream_tables": _table_refs(no_upstream),
        "no_downstream_tables": _table_refs(no_downstream),
        "multi_producer_tables": _table_refs(multi_producer),
        "high_in_degree_tables": _top_tables(table_metrics, "in_degree", top_n),
        "high_out_degree_tables": _top_tables(table_metrics, "out_degree", top_n),
        "read_top_n": _top_tables(table_metrics, "read_count", top_n),
        "write_top_n": _top_tables(table_metrics, "write_count", top_n),
    }


def _parse_diagnostic_metrics(
    diagnostics: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    config: AnalysisConfig,
) -> dict[str, MetricResult]:
    names = (
        "parse_total_count",
        "parse_success_count",
        "parse_partial_count",
        "parse_failure_count",
        "parse_success_rate",
        "parse_warning_count",
        "unsupported_syntax_distribution",
    )
    if diagnostics is None:
        reason = "parse diagnostics were not provided"
        return {
            name: MetricResult(
                name=name,
                status=MetricStatus.UNAVAILABLE,
                reason=reason,
                algorithm="parse_diagnostics",
                version=BASIC_METRICS_VERSION,
            )
            for name in names
        }

    counts = _diagnostic_counts(diagnostics)
    total = counts["total"]
    success_rate = _ratio(counts["success"], total, config.float_precision)
    values: dict[str, Any] = {
        "parse_total_count": total,
        "parse_success_count": counts["success"],
        "parse_partial_count": counts["partial"],
        "parse_failure_count": counts["failed"],
        "parse_success_rate": success_rate,
        "parse_warning_count": counts["warnings"],
        "unsupported_syntax_distribution": counts["unsupported"],
    }
    return {
        name: MetricResult(
            name=name,
            status=MetricStatus.SUCCESS,
            value=value,
            algorithm="parse_diagnostics",
            version=BASIC_METRICS_VERSION,
        )
        for name, value in values.items()
    }


def _diagnostic_counts(
    diagnostics: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if isinstance(diagnostics, Mapping):
        success = int(_first_present(diagnostics, ("success", "success_count"), 0))
        partial = int(
            _first_present(
                diagnostics,
                ("partial", "partial_count", "partial_success_count"),
                0,
            )
        )
        failed = int(
            _first_present(
                diagnostics,
                ("failed", "failure", "failure_count", "failed_count"),
                0,
            )
        )
        total = int(
            _first_present(
                diagnostics,
                ("total", "total_count", "sql_count"),
                success + partial + failed,
            )
        )
        warnings = diagnostics.get("warnings", diagnostics.get("warning_count", 0))
        return {
            "total": total,
            "success": success,
            "partial": partial,
            "failed": failed,
            "warnings": _count_items(warnings),
            "unsupported": _unsupported_distribution(
                diagnostics.get("unsupported_syntax", {})
            ),
        }

    success = partial = failed = warnings = 0
    unsupported: dict[str, int] = {}
    total = 0
    for item in diagnostics:
        if not isinstance(item, Mapping):
            continue
        total += 1
        status = str(item.get("status", "")).lower()
        if status in {"success", "succeeded", "ok"}:
            success += 1
        elif status in {"partial", "partial_success", "degraded"}:
            partial += 1
        elif status in {"failed", "failure", "error"}:
            failed += 1
        warnings += _count_items(item.get("warnings", item.get("warning_count", 0)))
        for key, value in _unsupported_distribution(
            item.get("unsupported_syntax", {})
        ).items():
            unsupported[key] = unsupported.get(key, 0) + value
    return {
        "total": total,
        "success": success,
        "partial": partial,
        "failed": failed,
        "warnings": warnings,
        "unsupported": dict(sorted(unsupported.items())),
    }


def _first_present(
    mapping: Mapping[str, Any],
    names: tuple[str, ...],
    default: Any,
) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return default


def _unsupported_distribution(value: Any) -> dict[str, int]:
    if isinstance(value, Mapping):
        return {
            str(key): int(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, str):
        return {value: 1}
    if isinstance(value, Sequence):
        counts: dict[str, int] = {}
        for item in value:
            key = str(item)
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))
    return {}


def _count_items(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return 1 if value else 0
    if isinstance(value, Sequence):
        return len(value)
    return 0


def _top_tables(
    table_metrics: tuple[Mapping[str, Any], ...],
    key: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = [
        item for item in table_metrics
        if int(item.get(key, 0)) > 0
    ]
    rows.sort(key=lambda item: (-int(item[key]), str(item["table_id"])))
    return [
        {
            "table_id": str(item["table_id"]),
            "table_name": str(item["table_name"]),
            "layer": str(item["layer"]),
            key: int(item[key]),
        }
        for item in rows[:limit]
    ]


def _table_refs(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "table_id": str(item["table_id"]),
            "table_name": str(item["table_name"]),
            "layer": str(item["layer"]),
        }
        for item in sorted(rows, key=lambda row: str(row["table_id"]))
    ]


def _match_layer(table: Mapping[str, Any], config: AnalysisConfig) -> str:
    full_name = _table_full_name(table).lower()
    for layer, pattern in config.layer_patterns:
        normalized_pattern = str(pattern).lower()
        if normalized_pattern and normalized_pattern in full_name:
            return str(layer)
    return "unknown"


def _layer_order(config: AnalysisConfig) -> dict[str, int]:
    order: dict[str, int] = {}
    for index, (layer, _) in enumerate(config.layer_patterns):
        order.setdefault(str(layer), index)
    order.setdefault("unknown", len(order) + 1)
    return order


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
        algorithm="lineage_graph_count",
        version=BASIC_METRICS_VERSION,
    )


def _ratio(numerator: int, denominator: int, precision: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, precision)
