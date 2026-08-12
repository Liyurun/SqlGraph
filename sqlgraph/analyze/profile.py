# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Dashboard projection for offline warehouse governance profiles."""
from __future__ import annotations

from pathlib import Path
from time import strftime
from typing import Any, Iterable, Mapping

from sqlgraph.analyze.contracts import GovernanceSnapshot
from sqlgraph.analyze.output import stable_json_dumps

DASHBOARD_VERSION = 1
DEFAULT_TOP_N = 20


def build_dashboard(
    snapshot: GovernanceSnapshot,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Any]:
    """Project a governance snapshot into a compact six-section dashboard."""
    payload = snapshot.to_dict()
    summary = _mapping(payload.get("summary"))
    basic = _mapping(summary.get("basic"))
    topology = _mapping(summary.get("topology"))
    impact = _mapping(summary.get("impact"))
    communities = _mapping(summary.get("communities"))
    consistency = _mapping(summary.get("consistency"))
    anomaly = _mapping(summary.get("anomaly"))

    table_metrics = _records(payload.get("table_metrics"))
    sql_metrics = [_sql_row(row) for row in _records(payload.get("sql_metrics"))]
    layer_matrix = _records(payload.get("layer_matrix"))
    community_matrix = _records(payload.get("community_matrix"))
    violations = _records(payload.get("violations"))
    consistency_groups = _records(payload.get("consistency_groups"))
    similarity_candidates = _records(payload.get("similarity_candidates"))
    motifs = _records(payload.get("motif_records"))

    overview_metrics = _mapping(basic.get("overview"))
    field_lineage = _mapping(_mapping(basic.get("field_lineage")).get("summary"))
    production = _mapping(basic.get("production_consumption"))

    dashboard = {
        "version": DASHBOARD_VERSION,
        "generated_at": strftime("%Y-%m-%dT%H:%M:%S"),
        "source": {
            "analysis_manifest": payload.get("manifest", {}),
            "metric_statuses": _mapping(payload.get("manifest")).get(
                "metric_statuses",
                {},
            ),
        },
        "overview": {
            "cards": {
                "sql_count": _metric_value(overview_metrics, "sql_count", 0),
                "table_count": _metric_value(
                    overview_metrics,
                    "physical_table_count",
                    _metric_value(overview_metrics, "table_count", len(table_metrics)),
                ),
                "logical_table_count": _metric_value(
                    overview_metrics,
                    "logical_table_count",
                    0,
                ),
                "cte_table_count": _metric_value(overview_metrics, "cte_table_count", 0),
                "column_count": _metric_value(overview_metrics, "column_count", 0),
                "transform_count": _metric_value(overview_metrics, "transform_count", 0),
                "table_lineage_edges": _metric_value(
                    overview_metrics,
                    "table_lineage_edge_count",
                    0,
                ),
                "field_dependency_edges": _metric_value(
                    overview_metrics,
                    "field_dependency_edge_count",
                    0,
                ),
                "average_fields_per_table": _metric_value(
                    overview_metrics,
                    "average_fields_per_physical_table",
                ),
                "average_upstream_count": _metric_value(
                    overview_metrics,
                    "average_upstream_count",
                ),
                "average_downstream_count": _metric_value(
                    overview_metrics,
                    "average_downstream_count",
                ),
                "field_lineage_coverage": _metric_value(
                    field_lineage,
                    "physical_source_coverage_ratio",
                ),
            },
            "layerDistribution": _records(basic.get("layer_distribution")),
            "nodeHealth": {
                "parseDiagnostics": _metric_values(_mapping(basic.get("parse_diagnostics"))),
                "fieldLineage": _metric_values(field_lineage),
            },
        },
        "layerHealth": {
            "topologySummary": _metric_values(topology),
            "layerDistribution": _records(basic.get("layer_distribution")),
            "layerMatrix": layer_matrix,
            "topLayerDriftTables": _top_numeric(
                table_metrics,
                "layer_drift_abs",
                top_n,
            ),
            "violations": violations[:top_n],
            "topGraphDepthTables": _top_numeric(
                table_metrics,
                "graph_layer_max",
                top_n,
            ),
        },
        "coreAssets": {
            "topBlastScoreTables": _top_numeric(table_metrics, "blast_score", top_n),
            "topPagerankTables": _top_numeric(table_metrics, "pagerank_reverse", top_n),
            "topAuthorityTables": _top_numeric(table_metrics, "hits_authority", top_n),
            "topKCoreTables": _top_numeric(table_metrics, "k_core", top_n),
            "topDownstreamTables": _top_numeric(table_metrics, "out_degree", top_n),
            "topProductScoreTables": _top_numeric(table_metrics, "product_score", top_n),
            "impactSummary": _metric_values(impact),
            "topReadTables": _top_numeric(table_metrics, "read_count", top_n),
            "topWriteTables": _top_numeric(table_metrics, "write_count", top_n),
        },
        "domains": {
            "communitySummary": _metric_values(communities),
            "communityMatrix": community_matrix,
            "topBridgeTables": _top_numeric(table_metrics, "bridge_score", top_n),
            "topImpactEntropyTables": _top_numeric(
                table_metrics,
                "impact_entropy",
                top_n,
            ),
        },
        "riskAssets": {
            "productionConsumption": production,
            "noUpstreamTables": _flagged(table_metrics, "no_upstream", top_n),
            "noDownstreamTables": _flagged(table_metrics, "no_downstream", top_n),
            "multiProducerTables": _flagged(table_metrics, "multi_producer", top_n),
            "topSqlComplexity": _top_numeric(sql_metrics, "complexity_score", top_n),
            "topAnomalyTables": _top_numeric(
                table_metrics,
                "rule_anomaly_score",
                top_n,
            ),
            "topWideTables": _top_numeric(table_metrics, "field_count", top_n),
            "motifs": motifs[:top_n],
            "anomalySummary": _metric_values(anomaly),
        },
        "consistency": {
            "summary": _metric_values(consistency),
            "groups": consistency_groups[:top_n],
            "similarityCandidates": _top_numeric(
                similarity_candidates,
                "similarity_score",
                top_n,
            ),
            "duplicateExpressions": _where(
                consistency_groups,
                "group_type",
                "duplicate_expression",
                top_n,
            ),
            "sameNameDifferentLogic": _where(
                consistency_groups,
                "group_type",
                "same_name_different_logic",
                top_n,
            ),
            "sameLogicDifferentNames": _where(
                consistency_groups,
                "group_type",
                "same_logic_different_names",
                top_n,
            ),
            "metricCandidates": _where(
                consistency_groups,
                "group_type",
                "metric_candidate",
                top_n,
            ),
        },
    }
    return dashboard


def write_profile_output(
    snapshot: GovernanceSnapshot,
    output_dir: str | Path,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, str]:
    """Write dashboard profile artifacts and return their paths."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    dashboard = build_dashboard(snapshot, top_n=top_n)
    dashboard_path = output_path / "dashboard.json"
    dashboard_path.write_text(
        stable_json_dumps(
            dashboard,
            precision=snapshot.manifest.float_precision,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"dashboard": str(dashboard_path)}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _metric_value(
    section: Mapping[str, Any],
    name: str,
    default: Any = None,
) -> Any:
    item = section.get(name)
    if isinstance(item, Mapping) and "value" in item:
        return item.get("value")
    if item is None:
        return default
    return item


def _metric_values(section: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name, item in sorted(section.items(), key=lambda pair: str(pair[0])):
        if isinstance(item, Mapping) and "value" in item:
            values[str(name)] = item.get("value")
        elif not isinstance(item, Mapping):
            values[str(name)] = item
    return values


def _record_value(row: Mapping[str, Any], key: str) -> Any:
    value = row.get(key)
    if isinstance(value, Mapping) and "value" in value:
        return value.get("value")
    return value


def _as_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _top_numeric(
    rows: Iterable[Mapping[str, Any]],
    key: str,
    limit: int,
) -> list[dict[str, Any]]:
    normalized: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        value = _as_number(_record_value(row, key))
        if value is None:
            continue
        item = dict(row)
        item[key] = _record_value(row, key)
        normalized.append((value, item))
    normalized.sort(
        key=lambda pair: (
            -pair[0],
            str(pair[1].get("table_name") or pair[1].get("sql_name") or ""),
            str(pair[1].get("table_id") or pair[1].get("sql_id") or ""),
        )
    )
    return [item for _, item in normalized[:limit]]


def _flagged(
    rows: Iterable[Mapping[str, Any]],
    key: str,
    limit: int,
) -> list[dict[str, Any]]:
    selected = [dict(row) for row in rows if bool(row.get(key))]
    selected.sort(
        key=lambda row: (
            str(row.get("table_name") or ""),
            str(row.get("table_id") or ""),
        )
    )
    return selected[:limit]


def _where(
    rows: Iterable[Mapping[str, Any]],
    key: str,
    value: str,
    limit: int,
) -> list[dict[str, Any]]:
    selected = [dict(row) for row in rows if str(row.get(key)) == value]
    return selected[:limit]


def _sql_row(row: Mapping[str, Any]) -> dict[str, Any]:
    features = _mapping(row.get("features"))
    return {
        "sql_id": row.get("sql_id"),
        "sql_name": row.get("sql_name"),
        "status": row.get("status"),
        "complexity_score": _record_value(row, "complexity_score"),
        "read_table_count": _metric_value(features, "read_table_count"),
        "join_count": _metric_value(features, "join_count"),
        "cte_count": _metric_value(features, "cte_count"),
        "union_count": _metric_value(features, "union_count"),
        "window_count": _metric_value(features, "window_count"),
        "aggregate_count": _metric_value(features, "aggregate_count"),
        "json_extract_count": _metric_value(features, "json_extract_count"),
        "select_star_count": _metric_value(features, "select_star_count"),
        "output_column_count": _metric_value(features, "output_column_count"),
        "transform_count": _metric_value(features, "transform_count"),
    }
