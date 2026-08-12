# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Governance analysis pipeline, dependency scheduling, and snapshot assembly."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from sqlgraph.analyze.anomaly import ANOMALY_VERSION, analyze_anomalies
from sqlgraph.analyze.basic_metrics import (
    BASIC_METRICS_VERSION,
    BasicGovernanceMetrics,
    analyze_basic_metrics,
)
from sqlgraph.analyze.cache import AnalysisCache, fingerprint_payload
from sqlgraph.analyze.communities import (
    BRIDGE_SCORE_VERSION,
    COMMUNITY_VERSION,
    CommunityAnalysisResult,
    analyze_communities,
)
from sqlgraph.analyze.config import AnalysisConfig
from sqlgraph.analyze.consistency import (
    CONSISTENCY_VERSION,
    ConsistencyAnalysisResult,
    analyze_consistency,
)
from sqlgraph.analyze.contracts import (
    ANALYSIS_VERSION,
    AnalysisManifest,
    AnalysisView,
    GovernanceSnapshot,
    MetricResult,
    MetricStatus,
    thaw,
)
from sqlgraph.analyze.embeddings import EMBEDDING_VERSION
from sqlgraph.analyze.impact import (
    BLAST_SCORE_VERSION,
    IMPACT_VERSION,
    ImpactAnalysisResult,
    analyze_impact,
)
from sqlgraph.analyze.inventory import (
    ExternalSchemaInventory,
    compute_coverage,
    build_lineage_inventory,
    load_external_schema_csv,
)
from sqlgraph.analyze.lineage_metrics import FIELD_LINEAGE_VERSION
from sqlgraph.analyze.loader import load_analysis_view
from sqlgraph.analyze.motifs import MOTIF_VERSION, MotifAnalysisResult, analyze_motifs
from sqlgraph.analyze.output import normalize_for_output, write_governance_output
from sqlgraph.analyze.scoring import PRODUCT_SCORE_VERSION
from sqlgraph.analyze.similarity import (
    SIMILARITY_VERSION,
    SimilarityAnalysisResult,
    analyze_similarity,
)
from sqlgraph.analyze.sql_complexity import (
    COMPLEXITY_SCORE_VERSION,
    SqlComplexityResult,
    analyze_sql_complexity,
)
from sqlgraph.analyze.table_graph import TableGraph, TableGraphEdge, build_table_graph
from sqlgraph.analyze.topology import (
    TOPOLOGY_VERSION,
    TopologyAnalysisResult,
    analyze_topology,
)
from sqlgraph.model import PropertyGraph


PIPELINE_VERSION = "1.0"

_SCHEDULE = (
    "inventory",
    "basic",
    "sql_complexity",
    "topology",
    "impact",
    "communities",
    "consistency",
    "similarity",
    "motifs",
    "anomaly",
)
_ALIASES = {
    "overview": "basic",
    "field_lineage": "basic",
    "lineage": "basic",
    "sql": "sql_complexity",
    "complexity": "sql_complexity",
    "community": "communities",
    "embedding": "similarity",
    "embeddings": "similarity",
    "anomalies": "anomaly",
}


def run_governance_analysis(
    source: PropertyGraph | str | Path | Mapping[str, Any],
    *,
    config: AnalysisConfig | None = None,
    external_schema: ExternalSchemaInventory | str | Path | None = None,
    parse_diagnostics: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    output_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
) -> GovernanceSnapshot:
    """Run selected governance metrics and return a versioned snapshot.

    The pipeline always builds an immutable :class:`AnalysisView` and isolated
    projections. Non-critical metric failures become failed metric envelopes
    when ``config.allow_degraded`` is true; projection or input-contract
    failures still raise because downstream results would be misleading.
    """
    config = config or AnalysisConfig()
    started = perf_counter()
    view = load_analysis_view(source)
    external = _load_external_schema(external_schema)
    fingerprints = _input_fingerprints(view, config, external, parse_diagnostics)
    cache = AnalysisCache(cache_dir) if cache_dir is not None else None
    cache_stats: dict[str, Any] = {
        "enabled": cache is not None,
        "context_key": fingerprints["context_fingerprint"],
        "metrics": {},
        "projections": {},
    }

    if cache is not None:
        cached_snapshot = cache.load_metric(
            "governance_snapshot",
            fingerprints["context_fingerprint"],
        )
        if cached_snapshot is not None:
            cache_stats["metrics"]["governance_snapshot"] = "hit"
            snapshot = governance_snapshot_from_dict(cached_snapshot)
            snapshot = _with_manifest_metadata(snapshot, {"cache": cache_stats})
            if output_dir is not None:
                write_governance_output(snapshot, output_dir)
            return snapshot
        cache_stats["metrics"]["governance_snapshot"] = "miss"

    requested = _selected_metrics(config)
    table_graph = _load_or_build_table_graph(view, cache, fingerprints, cache_stats)

    lineage_inventory = build_lineage_inventory(view)
    coverage = compute_coverage(view, external)
    results: dict[str, Any] = {}
    metric_entries: list[MetricResult] = []

    def should_run(name: str, *dependents: str) -> bool:
        return name in requested or bool(set(dependents) & requested)

    if should_run("inventory"):
        payload = {
            "lineage_inventory": lineage_inventory.to_dict(),
            "external_schema": None if external is None else external.to_dict(),
            "asset_coverage": coverage.to_dict(),
        }
        results["inventory"] = payload
        metric_entries.append(_status_envelope("inventory", payload))

    basic = None
    if should_run("basic", "consistency", "anomaly"):
        basic = _run_metric(
            "basic",
            lambda: analyze_basic_metrics(
                view,
                table_graph=table_graph,
                config=config,
                parse_diagnostics=parse_diagnostics,
            ),
            config,
            metric_entries,
        )
        if isinstance(basic, BasicGovernanceMetrics):
            results["basic"] = basic

    sql_complexity = None
    if should_run("sql_complexity"):
        sql_complexity = _run_metric(
            "sql_complexity",
            lambda: analyze_sql_complexity(view, config=config),
            config,
            metric_entries,
        )
        if isinstance(sql_complexity, tuple):
            results["sql_complexity"] = sql_complexity

    topology = None
    if should_run(
        "topology",
        "impact",
        "communities",
        "consistency",
        "similarity",
        "motifs",
        "anomaly",
    ):
        topology = _run_metric(
            "topology",
            lambda: analyze_topology(table_graph, config=config),
            config,
            metric_entries,
        )
        if isinstance(topology, TopologyAnalysisResult):
            results["topology"] = topology

    impact = None
    if should_run("impact", "communities", "anomaly"):
        impact = _run_metric(
            "impact",
            lambda: analyze_impact(
                table_graph,
                topology=topology if isinstance(topology, TopologyAnalysisResult) else None,
                config=config,
            ),
            config,
            metric_entries,
        )
        if isinstance(impact, ImpactAnalysisResult):
            results["impact"] = impact

    communities = None
    if should_run("communities", "similarity", "motifs", "anomaly"):
        communities = _run_metric(
            "communities",
            lambda: analyze_communities(
                table_graph,
                topology=topology if isinstance(topology, TopologyAnalysisResult) else None,
                impact=impact if isinstance(impact, ImpactAnalysisResult) else None,
                config=config,
            ),
            config,
            metric_entries,
        )
        if isinstance(communities, CommunityAnalysisResult):
            results["communities"] = communities

    consistency = None
    if should_run("consistency"):
        consistency = _run_metric(
            "consistency",
            lambda: analyze_consistency(
                view,
                table_graph=table_graph,
                basic_metrics=basic if isinstance(basic, BasicGovernanceMetrics) else None,
                topology_table_metrics=(
                    topology.table_metrics
                    if isinstance(topology, TopologyAnalysisResult)
                    else None
                ),
                config=config,
            ),
            config,
            metric_entries,
        )
        if isinstance(consistency, ConsistencyAnalysisResult):
            results["consistency"] = consistency

    similarity = None
    if should_run("similarity"):
        similarity = _run_metric(
            "similarity",
            lambda: analyze_similarity(
                table_graph,
                view=view,
                topology=topology if isinstance(topology, TopologyAnalysisResult) else None,
                communities=(
                    communities
                    if isinstance(communities, CommunityAnalysisResult)
                    else None
                ),
                config=config,
            ),
            config,
            metric_entries,
        )
        if isinstance(similarity, SimilarityAnalysisResult):
            results["similarity"] = similarity

    motifs = None
    if should_run("motifs"):
        motifs = _run_metric(
            "motifs",
            lambda: analyze_motifs(
                table_graph,
                topology=topology if isinstance(topology, TopologyAnalysisResult) else None,
                config=config,
                communities_by_table=_communities_by_table(communities),
            ),
            config,
            metric_entries,
        )
        if isinstance(motifs, MotifAnalysisResult):
            results["motifs"] = motifs

    anomaly = None
    if should_run("anomaly"):
        anomaly = _run_metric(
            "anomaly",
            lambda: analyze_anomalies(
                table_graph,
                config=config,
                topology=topology if isinstance(topology, TopologyAnalysisResult) else None,
                impact=impact if isinstance(impact, ImpactAnalysisResult) else None,
                communities=(
                    communities
                    if isinstance(communities, CommunityAnalysisResult)
                    else None
                ),
                basic_metrics=basic if isinstance(basic, BasicGovernanceMetrics) else None,
            ),
            config,
            metric_entries,
        )
        if anomaly is not None:
            results["anomaly"] = anomaly

    _record_skip_entries(metric_entries)

    snapshot = _build_snapshot(
        view=view,
        config=config,
        fingerprints=fingerprints,
        cache_stats=cache_stats,
        duration_ms=round((perf_counter() - started) * 1000.0, 3),
        table_graph=table_graph,
        lineage_inventory=lineage_inventory.to_dict(),
        coverage=coverage.to_dict(),
        metric_entries=metric_entries,
        results=results,
    )
    if cache is not None:
        cache.store_metric(
            "governance_snapshot",
            fingerprints["context_fingerprint"],
            snapshot.to_dict(),
        )
    if output_dir is not None:
        write_governance_output(snapshot, output_dir)
    return snapshot


analyze_governance = run_governance_analysis


def governance_snapshot_from_dict(payload: Mapping[str, Any]) -> GovernanceSnapshot:
    """Rehydrate a governance snapshot from a cached JSON-compatible payload."""
    manifest = _manifest_from_dict(payload["manifest"])
    return GovernanceSnapshot(
        manifest=manifest,
        summary=payload.get("summary", {}),
        metrics=tuple(_metric_from_dict(item) for item in payload.get("metrics", ())),
        table_metrics=tuple(payload.get("table_metrics", ())),
        column_metrics=tuple(payload.get("column_metrics", ())),
        sql_metrics=tuple(payload.get("sql_metrics", ())),
        transform_metrics=tuple(payload.get("transform_metrics", ())),
        layer_matrix=tuple(payload.get("layer_matrix", ())),
        community_matrix=tuple(payload.get("community_matrix", ())),
        violations=tuple(payload.get("violations", ())),
        consistency_groups=tuple(payload.get("consistency_groups", ())),
        similarity_candidates=tuple(payload.get("similarity_candidates", ())),
        motif_records=tuple(payload.get("motif_records", ())),
        anomaly_metrics=tuple(payload.get("anomaly_metrics", ())),
    )


def _load_external_schema(
    external_schema: ExternalSchemaInventory | str | Path | None,
) -> ExternalSchemaInventory | None:
    if external_schema is None:
        return None
    if isinstance(external_schema, ExternalSchemaInventory):
        return external_schema
    return load_external_schema_csv(external_schema)


def _input_fingerprints(
    view: AnalysisView,
    config: AnalysisConfig,
    external_schema: ExternalSchemaInventory | None,
    parse_diagnostics: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    algorithm_versions = _algorithm_versions(config)
    asset_payload = None if external_schema is None else external_schema.to_dict()
    diagnostics_payload = None if parse_diagnostics is None else thaw(parse_diagnostics)
    fingerprints = {
        "graph_fingerprint": view.graph_fingerprint,
        "config_fingerprint": config.fingerprint(),
        "asset_fingerprint": fingerprint_payload(asset_payload),
        "diagnostics_fingerprint": fingerprint_payload(diagnostics_payload),
        "algorithm_fingerprint": fingerprint_payload(algorithm_versions),
        "algorithm_versions": algorithm_versions,
    }
    fingerprints["context_fingerprint"] = fingerprint_payload(
        {
            "graph": fingerprints["graph_fingerprint"],
            "config": fingerprints["config_fingerprint"],
            "assets": fingerprints["asset_fingerprint"],
            "diagnostics": fingerprints["diagnostics_fingerprint"],
            "algorithms": fingerprints["algorithm_fingerprint"],
        }
    )
    return fingerprints


def _algorithm_versions(config: AnalysisConfig) -> dict[str, str]:
    versions = {name: version for name, version in config.algorithm_versions}
    versions.update(
        {
            "pipeline": PIPELINE_VERSION,
            "basic_metrics": BASIC_METRICS_VERSION,
            "field_lineage": FIELD_LINEAGE_VERSION,
            "sql_complexity": COMPLEXITY_SCORE_VERSION,
            "topology": TOPOLOGY_VERSION,
            "impact": IMPACT_VERSION,
            "blast_score": BLAST_SCORE_VERSION,
            "communities": COMMUNITY_VERSION,
            "bridge_score": BRIDGE_SCORE_VERSION,
            "consistency": CONSISTENCY_VERSION,
            "product_score": PRODUCT_SCORE_VERSION,
            "similarity": SIMILARITY_VERSION,
            "embeddings": EMBEDDING_VERSION,
            "motifs": MOTIF_VERSION,
            "anomaly": ANOMALY_VERSION,
        }
    )
    return {name: versions[name] for name in sorted(versions)}


def _selected_metrics(config: AnalysisConfig) -> set[str]:
    raw = {metric.strip().lower() for metric in config.metrics}
    if "all" in raw:
        return set(_SCHEDULE)
    return {_ALIASES.get(metric, metric) for metric in raw}


def _record_skip_entries(metric_entries: list[MetricResult]) -> None:
    recorded = {metric.name for metric in metric_entries}
    for name in _SCHEDULE:
        if name not in recorded:
            metric_entries.append(
                MetricResult(
                    name=name,
                    status=MetricStatus.SKIPPED,
                    reason="metric was not selected by configuration",
                    algorithm="pipeline.metric_selection",
                    version=PIPELINE_VERSION,
                )
            )


def _load_or_build_table_graph(
    view: AnalysisView,
    cache: AnalysisCache | None,
    fingerprints: Mapping[str, Any],
    cache_stats: dict[str, Any],
) -> TableGraph:
    cache_key = str(fingerprints["context_fingerprint"])
    if cache is not None:
        cached = cache.load_projection("table_graph", cache_key)
        if cached is not None:
            cache_stats["projections"]["table_graph"] = "hit"
            return _table_graph_from_payload(cached)
        cache_stats["projections"]["table_graph"] = "miss"
    table_graph = build_table_graph(view)
    if cache is not None:
        cache.store_projection("table_graph", cache_key, _table_graph_payload(table_graph))
    return table_graph


def _table_graph_payload(table_graph: TableGraph) -> dict[str, Any]:
    return {
        "nodes": list(table_graph.nodes),
        "edges": [
            {
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "field_weight": edge.field_weight,
                "sql_weight": edge.sql_weight,
            }
            for edge in table_graph.edges
        ],
        "nodes_by_id": {
            node_id: thaw(table_graph.nodes_by_id.get(node_id, {}))
            for node_id in table_graph.nodes
        },
    }


def _table_graph_from_payload(payload: Mapping[str, Any]) -> TableGraph:
    nodes = tuple(str(node_id) for node_id in payload.get("nodes", ()))
    edges = tuple(
        TableGraphEdge(
            source_id=str(edge["source_id"]),
            target_id=str(edge["target_id"]),
            field_weight=int(edge.get("field_weight", 0)),
            sql_weight=int(edge.get("sql_weight", 0)),
        )
        for edge in payload.get("edges", ())
    )
    node_index = {node_id: index for index, node_id in enumerate(nodes)}
    adjacency_builder: dict[str, list[TableGraphEdge]] = {node_id: [] for node_id in nodes}
    in_degree = {node_id: 0 for node_id in nodes}
    out_degree = {node_id: 0 for node_id in nodes}
    for edge in edges:
        adjacency_builder.setdefault(edge.source_id, []).append(edge)
        out_degree[edge.source_id] = out_degree.get(edge.source_id, 0) + 1
        in_degree[edge.target_id] = in_degree.get(edge.target_id, 0) + 1
    nodes_by_id = {
        str(node_id): dict(node)
        for node_id, node in payload.get("nodes_by_id", {}).items()
    }
    return TableGraph(
        nodes=nodes,
        edges=edges,
        node_index=node_index,
        adjacency={node_id: tuple(items) for node_id, items in adjacency_builder.items()},
        in_degree=in_degree,
        out_degree=out_degree,
        nodes_by_id=nodes_by_id,
    )


def _run_metric(
    name: str,
    callback: Callable[[], Any],
    config: AnalysisConfig,
    metric_entries: list[MetricResult],
) -> Any:
    try:
        result = callback()
    except Exception as exc:
        reason = f"{type(exc).__name__}: metric execution failed"
        failed = MetricResult(
            name=name,
            status=MetricStatus.FAILED,
            reason=reason,
            algorithm=f"pipeline.{name}",
            version=PIPELINE_VERSION,
        )
        metric_entries.append(failed)
        if not config.allow_degraded:
            raise RuntimeError(reason) from exc
        return None
    metric_entries.append(_status_envelope(name, _payload_for_status(result)))
    return result


def _payload_for_status(result: Any) -> Any:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, tuple):
        return [
            item.to_dict() if hasattr(item, "to_dict") else thaw(item)
            for item in result
        ]
    return thaw(result)


def _status_envelope(name: str, payload: Any) -> MetricResult:
    statuses, reasons = _collect_statuses(payload)
    status = _aggregate_status(statuses)
    reason = None if status == MetricStatus.SUCCESS else "; ".join(reasons[:3])
    if status != MetricStatus.SUCCESS and not reason:
        reason = f"{name} completed with non-success child metrics"
    return MetricResult(
        name=name,
        status=status,
        value={"record_count": _record_count(payload)},
        reason=reason,
        algorithm=f"pipeline.{name}",
        version=PIPELINE_VERSION,
    )


def _collect_statuses(payload: Any) -> tuple[list[MetricStatus], list[str]]:
    statuses: list[MetricStatus] = []
    reasons: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            if "name" in value and "status" in value:
                try:
                    status = MetricStatus(str(value["status"]))
                except ValueError:
                    status = MetricStatus.FAILED
                statuses.append(status)
                reason = value.get("reason")
                if status != MetricStatus.SUCCESS and reason:
                    reasons.append(str(reason))
            for item in value.values():
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(payload)
    return statuses, sorted(set(reasons))


def _aggregate_status(statuses: Sequence[MetricStatus]) -> MetricStatus:
    if not statuses:
        return MetricStatus.SUCCESS
    if any(status == MetricStatus.FAILED for status in statuses):
        return MetricStatus.FAILED
    if all(status == MetricStatus.SKIPPED for status in statuses):
        return MetricStatus.SKIPPED
    if any(
        status in {MetricStatus.DEGRADED, MetricStatus.SKIPPED, MetricStatus.UNAVAILABLE}
        for status in statuses
    ):
        return MetricStatus.DEGRADED
    return MetricStatus.SUCCESS


def _record_count(payload: Any) -> int:
    if isinstance(payload, Mapping):
        return sum(
            len(value)
            for value in payload.values()
            if isinstance(value, (list, tuple))
        )
    if isinstance(payload, (list, tuple)):
        return len(payload)
    return 1


def _build_snapshot(
    *,
    view: AnalysisView,
    config: AnalysisConfig,
    fingerprints: Mapping[str, Any],
    cache_stats: Mapping[str, Any],
    duration_ms: float,
    table_graph: TableGraph,
    lineage_inventory: Mapping[str, Any],
    coverage: Mapping[str, Any],
    metric_entries: Sequence[MetricResult],
    results: Mapping[str, Any],
) -> GovernanceSnapshot:
    metric_statuses = {metric.name: metric.status for metric in metric_entries}
    manifest = AnalysisManifest(
        graph_fingerprint=view.graph_fingerprint,
        config_fingerprint=config.fingerprint(),
        analysis_version=ANALYSIS_VERSION,
        input_kind=view.input_kind,
        random_seed=config.random_seed,
        float_precision=config.float_precision,
        completed_metrics=tuple(
            metric.name for metric in metric_entries
            if metric.status == MetricStatus.SUCCESS
        ),
        degraded_metrics=tuple(
            metric.name for metric in metric_entries
            if metric.status == MetricStatus.DEGRADED
        ),
        skipped_metrics=tuple(
            metric.name for metric in metric_entries
            if metric.status == MetricStatus.SKIPPED
        ),
        failed_metrics=tuple(
            metric.name for metric in metric_entries
            if metric.status == MetricStatus.FAILED
        ),
        metric_statuses=metric_statuses,
        metadata={
            "input": {
                "source_path": view.source_path,
                "node_count": len(view.nodes),
                "edge_count": len(view.edges),
                "asset_fingerprint": fingerprints["asset_fingerprint"],
                "diagnostics_fingerprint": fingerprints["diagnostics_fingerprint"],
            },
            "config": config.to_dict(),
            "algorithm_versions": fingerprints["algorithm_versions"],
            "algorithm_fingerprint": fingerprints["algorithm_fingerprint"],
            "resource_budget": config.resource_budget.__dict__,
            "cache": cache_stats,
            "execution": {
                "duration_ms": duration_ms,
                "allow_degraded": config.allow_degraded,
            },
        },
    )
    basic = results.get("basic")
    topology = results.get("topology")
    impact = results.get("impact")
    communities = results.get("communities")
    consistency = results.get("consistency")
    similarity = results.get("similarity")
    motifs = results.get("motifs")
    anomaly = results.get("anomaly")

    summary = _summary_payload(
        table_graph=table_graph,
        lineage_inventory=lineage_inventory,
        coverage=coverage,
        results=results,
    )
    return GovernanceSnapshot(
        manifest=manifest,
        summary=normalize_for_output(summary, precision=config.float_precision),
        metrics=tuple(metric_entries),
        table_metrics=_combined_table_metrics(
            table_graph,
            basic=basic,
            topology=topology,
            impact=impact,
            communities=communities,
            similarity=similarity,
            motifs=motifs,
            anomaly=anomaly,
            consistency=consistency,
            precision=config.float_precision,
        ),
        column_metrics=_column_metrics(basic, config.float_precision),
        sql_metrics=_sql_metrics(results.get("sql_complexity"), config.float_precision),
        transform_metrics=_transform_metrics(consistency, config.float_precision),
        layer_matrix=_layer_matrix(basic, config.float_precision),
        community_matrix=_community_matrix(communities, config.float_precision),
        violations=_violations(topology, config.float_precision),
        consistency_groups=_consistency_groups(consistency, config.float_precision),
        similarity_candidates=_similarity_candidates(similarity, config.float_precision),
        motif_records=_motif_records(motifs, config.float_precision),
        anomaly_metrics=_anomaly_metrics(anomaly, config.float_precision),
    )


def _summary_payload(
    *,
    table_graph: TableGraph,
    lineage_inventory: Mapping[str, Any],
    coverage: Mapping[str, Any],
    results: Mapping[str, Any],
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "inventory": {
            "lineage_inventory": lineage_inventory,
            "asset_coverage": coverage,
        },
        "table_graph": table_graph.to_dict(),
    }
    for name in _SCHEDULE:
        result = results.get(name)
        if result is None:
            continue
        payload = _payload_for_status(result)
        if isinstance(payload, Mapping):
            summary[name] = payload.get("summary", payload)
        else:
            summary[name] = {"records": payload}
    return summary


def _combined_table_metrics(
    table_graph: TableGraph,
    *,
    basic: Any,
    topology: Any,
    impact: Any,
    communities: Any,
    similarity: Any,
    motifs: Any,
    anomaly: Any,
    consistency: Any,
    precision: int,
) -> tuple[Mapping[str, Any], ...]:
    records: dict[str, dict[str, Any]] = {
        table_id: {
            "table_id": table_id,
            "table_name": _table_full_name(table_graph.nodes_by_id.get(table_id, {})),
        }
        for table_id in table_graph.nodes
    }

    def merge(source: str, rows: Sequence[Mapping[str, Any]]) -> None:
        for row in rows:
            table_id = str(row.get("table_id", ""))
            if not table_id:
                continue
            target = records.setdefault(table_id, {"table_id": table_id})
            for key, value in thaw(row).items():
                if key in {"table_id"}:
                    continue
                if key not in target or target[key] == value:
                    target[key] = value
                else:
                    target[f"{source}_{key}"] = value

    if isinstance(basic, BasicGovernanceMetrics):
        merge("basic", basic.table_metrics)
    if isinstance(topology, TopologyAnalysisResult):
        merge("topology", topology.table_metrics)
    if isinstance(impact, ImpactAnalysisResult):
        merge("impact", impact.table_metrics)
    if isinstance(communities, CommunityAnalysisResult):
        merge("community", communities.table_metrics)
    if isinstance(similarity, SimilarityAnalysisResult):
        merge("similarity", similarity.table_metrics)
    if isinstance(motifs, MotifAnalysisResult):
        merge("motif", motifs.table_metrics)
    if hasattr(anomaly, "table_metrics"):
        merge("anomaly", anomaly.table_metrics)
    if isinstance(consistency, ConsistencyAnalysisResult) and consistency.product_score:
        merge("product", consistency.product_score.table_scores)
    normalized = [
        normalize_for_output(record, precision=precision)
        for _, record in sorted(records.items())
    ]
    return tuple(normalized)


def _column_metrics(basic: Any, precision: int) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(basic, BasicGovernanceMetrics):
        return ()
    return tuple(
        normalize_for_output(item, precision=precision)
        for item in basic.field_lineage.column_metrics
    )


def _sql_metrics(sql_complexity: Any, precision: int) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(sql_complexity, tuple):
        return ()
    return tuple(
        normalize_for_output(item.to_dict(), precision=precision)
        for item in sql_complexity
        if isinstance(item, SqlComplexityResult)
    )


def _transform_metrics(
    consistency: Any,
    precision: int,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(consistency, ConsistencyAnalysisResult):
        return ()
    return tuple(
        normalize_for_output(item, precision=precision)
        for item in consistency.transform_metrics
    )


def _layer_matrix(basic: Any, precision: int) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(basic, BasicGovernanceMetrics):
        return ()
    return tuple(
        normalize_for_output(item, precision=precision)
        for item in basic.layer_matrix
    )


def _community_matrix(
    communities: Any,
    precision: int,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(communities, CommunityAnalysisResult):
        return ()
    return tuple(
        normalize_for_output(item, precision=precision)
        for item in communities.dependency_matrix
    )


def _violations(topology: Any, precision: int) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(topology, TopologyAnalysisResult):
        return ()
    return tuple(
        normalize_for_output(item, precision=precision)
        for item in topology.layer_violations
    )


def _consistency_groups(
    consistency: Any,
    precision: int,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(consistency, ConsistencyAnalysisResult):
        return ()
    groups: list[Mapping[str, Any]] = []
    for group_type, rows in (
        ("duplicate_expression", consistency.duplicate_expressions),
        ("same_name_different_logic", consistency.same_name_different_logic),
        ("same_logic_different_names", consistency.same_logic_different_names),
        ("metric_candidate", consistency.metric_candidates),
    ):
        for row in rows:
            item = {"group_type": group_type}
            item.update(thaw(row))
            groups.append(item)
    return tuple(
        normalize_for_output(item, precision=precision)
        for item in sorted(groups, key=lambda item: repr(item))
    )


def _similarity_candidates(
    similarity: Any,
    precision: int,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(similarity, SimilarityAnalysisResult):
        return ()
    return tuple(
        normalize_for_output(item, precision=precision)
        for item in similarity.similarity_candidates
    )


def _motif_records(motifs: Any, precision: int) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(motifs, MotifAnalysisResult):
        return ()
    return tuple(
        normalize_for_output(item, precision=precision)
        for item in motifs.motif_records
    )


def _anomaly_metrics(anomaly: Any, precision: int) -> tuple[Mapping[str, Any], ...]:
    if not hasattr(anomaly, "table_metrics"):
        return ()
    return tuple(
        normalize_for_output(item, precision=precision)
        for item in anomaly.table_metrics
    )


def _communities_by_table(communities: Any) -> Mapping[str, str] | None:
    if not isinstance(communities, CommunityAnalysisResult):
        return None
    value = communities.community_detection.value
    mapping = value.get("communities_by_table") if isinstance(value, Mapping) else None
    if not isinstance(mapping, Mapping):
        return None
    return {str(key): str(value) for key, value in mapping.items()}


def _manifest_from_dict(data: Mapping[str, Any]) -> AnalysisManifest:
    statuses = {
        str(name): MetricStatus(str(status))
        for name, status in data.get("metric_statuses", {}).items()
    }
    return AnalysisManifest(
        graph_fingerprint=str(data["graph_fingerprint"]),
        config_fingerprint=str(data["config_fingerprint"]),
        schema_version=str(data.get("schema_version", "1.0")),
        analysis_version=str(data.get("analysis_version", ANALYSIS_VERSION)),
        input_kind=str(data.get("input_kind", "property_graph")),
        random_seed=int(data.get("random_seed", 42)),
        float_precision=int(data.get("float_precision", 8)),
        completed_metrics=tuple(data.get("completed_metrics", ())),
        degraded_metrics=tuple(data.get("degraded_metrics", ())),
        skipped_metrics=tuple(data.get("skipped_metrics", ())),
        failed_metrics=tuple(data.get("failed_metrics", ())),
        metric_statuses=statuses,
        metadata=data.get("metadata", {}),
    )


def _metric_from_dict(data: Mapping[str, Any]) -> MetricResult:
    return MetricResult(
        name=str(data["name"]),
        status=MetricStatus(str(data["status"])),
        value=data.get("value"),
        reason=data.get("reason"),
        algorithm=data.get("algorithm"),
        version=data.get("version"),
        parameters=data.get("parameters", {}),
    )


def _with_manifest_metadata(
    snapshot: GovernanceSnapshot,
    metadata_update: Mapping[str, Any],
) -> GovernanceSnapshot:
    metadata = thaw(snapshot.manifest.metadata)
    metadata.update(thaw(metadata_update))
    manifest = replace(snapshot.manifest, metadata=metadata)
    return replace(snapshot, manifest=manifest)


def _table_full_name(table: Mapping[str, Any]) -> str:
    name = str(table.get("name") or table.get("id") or "")
    schema_name = table.get("schema_name")
    catalog = table.get("catalog")
    parts = [str(part) for part in (catalog, schema_name, name) if part]
    return ".".join(parts) if parts else name
