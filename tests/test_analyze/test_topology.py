# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Synthetic-data tests for Task 5 topology and graph-layer metrics."""

from __future__ import annotations

from copy import deepcopy

from sqlgraph.analyze import (
    AnalysisConfig,
    MetricStatus,
    analyze_topology,
    build_table_graph,
    load_analysis_view,
)
import sqlgraph.analyze.topology as topology_module
from sqlgraph.model import Edge, EdgeType, PropertyGraph, TableNode


def _graph(
    edges: list[tuple[str, str]],
    names: dict[str, str] | None = None,
    extra_tables: tuple[str, ...] = (),
) -> PropertyGraph:
    names = names or {}
    graph = PropertyGraph()
    table_ids = set(extra_tables)
    for source, target in edges:
        table_ids.add(source)
        table_ids.add(target)
    for table_id in sorted(table_ids):
        graph.add_node(
            TableNode(
                id=table_id,
                name=names.get(table_id, table_id),
                schema_name="synthetic_dw",
            )
        )
    for index, (source, target) in enumerate(edges):
        graph.add_edge(
            Edge(
                id=f"tl_{index}_{source}_{target}",
                source_id=source,
                target_id=target,
                edge_type=EdgeType.TABLE_LINEAGE,
            )
        )
    return graph


def _analyze_graph(
    edges: list[tuple[str, str]],
    names: dict[str, str] | None = None,
    extra_tables: tuple[str, ...] = (),
    config: AnalysisConfig | None = None,
):
    graph = _graph(edges, names=names, extra_tables=extra_tables)
    table_graph = build_table_graph(load_analysis_view(graph))
    return graph, analyze_topology(table_graph, config=config)


def _summary_values(result):
    return {name: metric.value for name, metric in result.summary.items()}


def _table_metrics(result):
    return {item["table_id"]: item for item in result.table_metrics}


def test_components_cycle_members_and_scc_dag_are_stable():
    _graph_obj, result = _analyze_graph(
        [
            ("ta", "tb"),
            ("tb", "tc"),
            ("tc", "tb"),
            ("te", "tf"),
        ],
        extra_tables=("t_iso",),
    )
    summary = _summary_values(result)

    assert summary["weak_component_count"] == 3
    assert summary["strong_component_count"] == 5
    assert summary["cycle_member_count"] == 2
    assert summary["scc_dag_edge_count"] == 2

    metrics = _table_metrics(result)
    assert metrics["tb"]["is_cycle_member"] is True
    assert metrics["tc"]["is_cycle_member"] is True
    assert metrics["tb"]["strong_component_id"] == metrics["tc"]["strong_component_id"]
    assert metrics["ta"]["strong_component_id"] != metrics["tb"]["strong_component_id"]

    dag_edges = {
        (item["source_component_id"], item["target_component_id"])
        for item in result.scc_dag_edges
    }
    assert len(dag_edges) == 2
    assert all(source != target for source, target in dag_edges)


def test_graph_layer_min_and_max_follow_source_to_target_direction():
    _graph_obj, result = _analyze_graph(
        [
            ("ta", "tb"),
            ("ta", "tc"),
            ("tb", "td"),
            ("tc", "td"),
            ("te", "td"),
        ]
    )
    metrics = _table_metrics(result)

    assert metrics["ta"]["graph_layer_min"] == 0
    assert metrics["ta"]["graph_layer_max"] == 0
    assert metrics["tb"]["graph_layer_min"] == 1
    assert metrics["tc"]["graph_layer_max"] == 1
    assert metrics["td"]["graph_layer_min"] == 1
    assert metrics["td"]["graph_layer_max"] == 2


def test_declared_layer_drift_uses_scaled_graph_buckets():
    config = AnalysisConfig(
        layer_patterns=(
            ("ods", "ods"),
            ("dwd", "dwd"),
            ("ads", "ads"),
        )
    )
    _graph_obj, result = _analyze_graph(
        [("t_ods", "t_dwd"), ("t_dwd", "t_ads")],
        names={
            "t_ods": "ods_events",
            "t_dwd": "dwd_orders",
            "t_ads": "ads_report",
        },
        config=config,
    )
    metrics = _table_metrics(result)

    assert metrics["t_ods"]["mapped_graph_layer"] == 0
    assert metrics["t_dwd"]["mapped_graph_layer"] == 1
    assert metrics["t_ads"]["mapped_graph_layer"] == 2
    assert metrics["t_ods"]["layer_drift"] == 0
    assert metrics["t_dwd"]["layer_drift"] == 0
    assert metrics["t_ads"]["layer_drift"] == 0


def test_configured_layer_violation_rules_emit_rule_and_severity():
    config = AnalysisConfig(
        layer_patterns=(("ods", "ods"), ("dwd", "dwd"), ("ads", "ads")),
        layer_violation_rules=(("ads", "ods", "no_ads_to_ods", "high"),),
    )
    _graph_obj, result = _analyze_graph(
        [("t_ads", "t_ods")],
        names={"t_ads": "ads_report", "t_ods": "ods_backfill"},
        config=config,
    )

    assert _summary_values(result)["layer_violation_count"] == 1
    violation = result.layer_violations[0]
    assert violation["rule_id"] == "no_ads_to_ods"
    assert violation["severity"] == "high"
    assert violation["source_table_id"] == "t_ads"
    assert violation["source_layer"] == "ads"
    assert violation["target_table_id"] == "t_ods"
    assert violation["target_layer"] == "ods"


def test_networkx_algorithms_preserve_direction_semantics_when_available():
    _graph_obj, result = _analyze_graph(
        [
            ("t_src", "t_mid_a"),
            ("t_src", "t_mid_b"),
            ("t_src", "t_sink"),
            ("t_mid_a", "t_sink"),
            ("t_mid_b", "t_sink"),
        ]
    )
    pagerank = result.graph_algorithms["pagerank"]
    hits = result.graph_algorithms["hits"]
    k_core = result.graph_algorithms["k_core"]

    if pagerank.status == MetricStatus.SKIPPED:
        assert pagerank.reason == "networkx is not installed"
        assert hits.status == MetricStatus.SKIPPED
        assert k_core.status == MetricStatus.SKIPPED
        return

    assert pagerank.status == MetricStatus.SUCCESS
    forward = pagerank.value["forward"]
    reverse = pagerank.value["reverse"]
    assert max(forward, key=forward.get) == "t_sink"
    assert max(reverse, key=reverse.get) == "t_src"

    assert hits.status == MetricStatus.SUCCESS
    hubs = hits.value["hub"]
    authorities = hits.value["authority"]
    assert max(hubs, key=hubs.get) == "t_src"
    assert max(authorities, key=authorities.get) == "t_sink"

    assert k_core.status == MetricStatus.SUCCESS
    assert set(k_core.value.values()) == {2}


def test_networkx_missing_skips_only_backend_dependent_metrics(monkeypatch):
    monkeypatch.setattr(topology_module, "_load_networkx", lambda: None)
    _graph_obj, result = _analyze_graph([("ta", "tb")])

    assert result.graph_algorithms["pagerank"].status == MetricStatus.SKIPPED
    assert result.graph_algorithms["hits"].status == MetricStatus.SKIPPED
    assert result.graph_algorithms["k_core"].status == MetricStatus.SKIPPED
    assert _summary_values(result)["strong_component_count"] == 2
    metrics = _table_metrics(result)
    assert metrics["ta"]["graph_layer_max"] == 0
    assert metrics["tb"]["graph_layer_max"] == 1
    assert metrics["ta"]["pagerank_forward"] is None


def test_topology_is_deterministic_and_does_not_mutate_input_graph():
    graph = _graph([("ta", "tb"), ("tb", "tc"), ("ta", "tc")])
    before_graph = deepcopy(graph.to_dict())
    view = load_analysis_view(graph)
    before_view = deepcopy(view.to_dict())
    table_graph = build_table_graph(view)

    first = analyze_topology(table_graph).to_dict()
    second = analyze_topology(table_graph).to_dict()

    assert first == second
    assert graph.to_dict() == before_graph
    assert view.to_dict() == before_view
