# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""SQL complexity metrics computed without modifying the lineage graph."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

import sqlglot
from sqlglot import exp

from sqlgraph.analyze.config import AnalysisConfig
from sqlgraph.analyze.contracts import (
    AnalysisView,
    MetricResult,
    MetricStatus,
    freeze,
)


COMPLEXITY_SCORE_VERSION = "1.0"
COMPLEXITY_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "read_table_count": 1.0,
        "join_count": 2.0,
        "cte_count": 1.5,
        "union_count": 1.5,
        "window_count": 2.0,
        "aggregate_count": 1.0,
        "json_extract_count": 1.0,
        "output_column_count": 0.2,
        "transform_count": 0.5,
        "select_star_count": 5.0,
    }
)

_AST_FEATURES = (
    "join_count",
    "cte_count",
    "union_count",
    "window_count",
    "aggregate_count",
    "json_extract_count",
    "select_star_count",
)
_JSON_FUNCTION_NAMES = {
    "from_json",
    "get_json_object",
    "json_extract",
    "json_extract_scalar",
    "json_query",
    "json_value",
}


@dataclass(frozen=True)
class SqlComplexityResult:
    """Complexity result for one SQL node."""

    sql_id: str
    sql_name: str
    status: MetricStatus
    features: Mapping[str, MetricResult]
    complexity_score: MetricResult
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", freeze(self.features))
        if self.status != MetricStatus.SUCCESS and self.reason is None:
            raise ValueError("non-success SQL complexity results require a reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sql_id": self.sql_id,
            "sql_name": self.sql_name,
            "status": self.status.value,
            "reason": self.reason,
            "features": {
                name: result.to_dict()
                for name, result in self.features.items()
            },
            "complexity_score": self.complexity_score.to_dict(),
        }


def analyze_sql_complexity(
    view: AnalysisView,
    config: AnalysisConfig | None = None,
) -> tuple[SqlComplexityResult, ...]:
    """Analyze every SQL node in stable ID order.

    AST-derived features are unavailable when SQL content is missing or cannot
    be parsed. Graph-derived features remain useful in that case, so the
    per-SQL result is degraded rather than filled with false zero values.
    """
    config = config or AnalysisConfig()
    edge_index = _build_edge_index(view)
    results = [
        _analyze_sql_node(node, edge_index, config)
        for node in view.iter_nodes("sql")
    ]
    return tuple(sorted(results, key=lambda item: item.sql_id))


def _analyze_sql_node(
    sql_node: Mapping[str, Any],
    edge_index: Mapping[str, Any],
    config: AnalysisConfig,
) -> SqlComplexityResult:
    sql_id = str(sql_node["id"])
    sql_name = str(sql_node.get("name") or sql_id)
    features = _graph_features(sql_id, edge_index)
    sql_content = sql_node.get("sql_content")

    if not isinstance(sql_content, str) or not sql_content.strip():
        reason = "SQL content is not available; AST features were not inferred"
        features.update(_unavailable_ast_features(reason))
        score = _unavailable_score(reason, config)
        return SqlComplexityResult(
            sql_id=sql_id,
            sql_name=sql_name,
            status=MetricStatus.DEGRADED,
            features=features,
            complexity_score=score,
            reason=reason,
        )

    dialect = sql_node.get("dialect")
    read_dialect = dialect if isinstance(dialect, str) and dialect.strip() else None
    try:
        statements = [
            statement
            for statement in sqlglot.parse(sql_content, read=read_dialect)
            if statement is not None
        ]
    except Exception as exc:
        reason = f"SQL AST parsing failed: {type(exc).__name__}"
        features.update(_unavailable_ast_features(reason))
        score = _unavailable_score(reason, config)
        return SqlComplexityResult(
            sql_id=sql_id,
            sql_name=sql_name,
            status=MetricStatus.DEGRADED,
            features=features,
            complexity_score=score,
            reason=reason,
        )

    ast_counts = _count_ast_features(statements)
    features.update(
        {
            name: MetricResult(
                name=name,
                status=MetricStatus.SUCCESS,
                value=value,
                algorithm="sqlglot_ast_count",
                version=COMPLEXITY_SCORE_VERSION,
            )
            for name, value in ast_counts.items()
        }
    )
    score_value = _calculate_score(features, config.float_precision)
    score = MetricResult(
        name="sql_complexity_score",
        status=MetricStatus.SUCCESS,
        value=score_value,
        algorithm="weighted_sum",
        version=_complexity_version(config),
        parameters={"weights": dict(COMPLEXITY_WEIGHTS)},
    )
    return SqlComplexityResult(
        sql_id=sql_id,
        sql_name=sql_name,
        status=MetricStatus.SUCCESS,
        features=features,
        complexity_score=score,
    )


def _build_edge_index(view: AnalysisView) -> Mapping[str, Any]:
    reads: dict[str, set[str]] = {}
    writes: dict[str, set[str]] = {}
    contains: dict[str, set[str]] = {}
    columns_by_table: dict[str, set[str]] = {}

    for edge in view.edges:
        source = str(edge["source"])
        target = str(edge["target"])
        edge_type = edge["type"]
        if edge_type == "reads_from":
            reads.setdefault(source, set()).add(target)
        elif edge_type == "writes_to":
            writes.setdefault(source, set()).add(target)
        elif edge_type == "contains":
            target_node = view.get_node(target)
            if target_node and target_node.get("node_type") == "transform":
                contains.setdefault(source, set()).add(target)
        elif edge_type == "has_column":
            target_node = view.get_node(target)
            if target_node and target_node.get("node_type") == "column":
                columns_by_table.setdefault(source, set()).add(target)

    return {
        "reads": reads,
        "writes": writes,
        "contains": contains,
        "columns_by_table": columns_by_table,
    }


def _graph_features(
    sql_id: str,
    edge_index: Mapping[str, Any],
) -> dict[str, MetricResult]:
    reads = edge_index["reads"].get(sql_id, set())
    target_tables = edge_index["writes"].get(sql_id, set())
    output_columns: set[str] = set()
    for table_id in target_tables:
        output_columns.update(edge_index["columns_by_table"].get(table_id, set()))
    transforms = edge_index["contains"].get(sql_id, set())

    values = {
        "read_table_count": len(reads),
        "output_column_count": len(output_columns),
        "transform_count": len(transforms),
    }
    return {
        name: MetricResult(
            name=name,
            status=MetricStatus.SUCCESS,
            value=value,
            algorithm="lineage_graph_count",
            version=COMPLEXITY_SCORE_VERSION,
        )
        for name, value in values.items()
    }


def _count_ast_features(statements: list[exp.Expression]) -> dict[str, int]:
    counts = {
        "join_count": 0,
        "cte_count": 0,
        "union_count": 0,
        "window_count": 0,
        "aggregate_count": 0,
        "json_extract_count": 0,
        "select_star_count": 0,
    }
    for statement in statements:
        counts["join_count"] += sum(1 for _ in statement.find_all(exp.Join))
        counts["cte_count"] += sum(1 for _ in statement.find_all(exp.CTE))
        counts["union_count"] += sum(1 for _ in statement.find_all(exp.Union))
        counts["window_count"] += sum(1 for _ in statement.find_all(exp.Window))
        counts["aggregate_count"] += sum(
            1 for _ in statement.find_all(exp.AggFunc)
        )
        counts["json_extract_count"] += sum(
            1 for node in statement.walk() if _is_json_extract(node)
        )
        counts["select_star_count"] += sum(
            _projection_is_star(projection)
            for select in statement.find_all(exp.Select)
            for projection in select.expressions
        )
    return counts


def _is_json_extract(node: exp.Expression) -> bool:
    if isinstance(node, (exp.JSONExtract, exp.JSONExtractScalar)):
        return True
    if not isinstance(node, exp.Func):
        return False
    names = {
        str(getattr(node, "key", "")).lower(),
        str(getattr(node, "name", "")).lower(),
        type(node).__name__.lower(),
    }
    normalized = {name.replace("_", "") for name in names if name}
    targets = {name.replace("_", "") for name in _JSON_FUNCTION_NAMES}
    return bool(normalized & targets)


def _projection_is_star(projection: exp.Expression) -> int:
    expression = projection.unalias()
    if isinstance(expression, exp.Star):
        return 1
    if isinstance(expression, exp.Column) and expression.is_star:
        return 1
    return 0


def _unavailable_ast_features(reason: str) -> dict[str, MetricResult]:
    return {
        name: MetricResult(
            name=name,
            status=MetricStatus.UNAVAILABLE,
            reason=reason,
            algorithm="sqlglot_ast_count",
            version=COMPLEXITY_SCORE_VERSION,
        )
        for name in _AST_FEATURES
    }


def _unavailable_score(
    reason: str,
    config: AnalysisConfig,
) -> MetricResult:
    return MetricResult(
        name="sql_complexity_score",
        status=MetricStatus.UNAVAILABLE,
        reason=reason,
        algorithm="weighted_sum",
        version=_complexity_version(config),
        parameters={"weights": dict(COMPLEXITY_WEIGHTS)},
    )


def _calculate_score(
    features: Mapping[str, MetricResult],
    precision: int,
) -> float:
    score = sum(
        float(features[name].value) * weight
        for name, weight in COMPLEXITY_WEIGHTS.items()
    )
    return round(score, precision)


def _complexity_version(config: AnalysisConfig) -> str:
    versions = dict(config.algorithm_versions)
    return versions.get("complexity_score", COMPLEXITY_SCORE_VERSION)
