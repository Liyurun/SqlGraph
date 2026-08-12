# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Synthetic-data tests for Task 7 community and bridge metrics."""

from __future__ import annotations

from copy import deepcopy

from sqlgraph.analyze import (
    AnalysisConfig,
    MetricStatus,
    analyze_communities,
    build_table_graph,
    load_analysis_view,
)
import sqlgraph.analyze.communities as communities_module
from sqlgraph.model import Edge, EdgeType, PropertyGraph, TableNode


def _graph(
    edges: list[tuple[str, str]],
    names: dict[str, str] | None = None,
) -> PropertyGraph:
    names = names or {}
    graph = PropertyGraph()
    table_ids = sorted({table_id for edge in edges for table_id in edge})
    for table_id in table_ids:
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


def _cluster_graph() -> PropertyGraph:
    return _graph(
        [
            ("t_a1", "t_a2"),
            ("t_a1", "t_a3"),
            ("t_a2", "t_a3"),
            ("t_b1", "t_b2"),
            ("t_b1", "t_b3"),
            ("t_b2", "t_b3"),
            ("t_a3", "t_b1"),
        ],
        names={
            "t_a1": "dwd_a1",
            "t_a2": "dwd_a2",
            "t_a3": "dwd_a3",
            "t_b1": "ads_b1",
            "t_b2": "ads_b2",
            "t_b3": "ads_b3",
        },
    )


def _table_graph(graph: PropertyGraph):
    return build_table_graph(load_analysis_view(graph))


def test_label_propagation_is_deterministic_and_relabels_stably():
    table_graph = _table_graph(_cluster_graph())
    config = AnalysisConfig(random_seed=123)

    first = analyze_communities(table_graph, config=config)
    second = analyze_communities(table_graph, config=config)

    assert first.to_dict() == second.to_dict()
    assert first.community_detection.status == MetricStatus.SUCCESS
    assert first.community_detection.value["backend"] == "label_propagation"
    assert len(first.communities) == 2
    assert [item["community_id"] for item in first.communities] == [
        "community_0000",
        "community_0001",
    ]
    assert sorted(item["size"] for item in first.communities) == [3, 3]


def test_louvain_backend_missing_degrades_to_label_propagation(monkeypatch):
    monkeypatch.setattr(
        communities_module,
        "_load_networkx_louvain",
        lambda: None,
    )
    table_graph = _table_graph(_cluster_graph())
    config = AnalysisConfig(community_backend="louvain")

    result = analyze_communities(table_graph, config=config)

    assert result.community_detection.status == MetricStatus.DEGRADED
    assert result.community_detection.value["requested_backend"] == "louvain"
    assert result.community_detection.value["backend"] == "label_propagation"
    assert "louvain backend is not available" in result.community_detection.reason


def test_cross_community_edge_ratio_and_dependency_matrix_are_directional():
    table_graph = _table_graph(_cluster_graph())
    result = analyze_communities(table_graph)
    coupling = result.coupling.value

    assert coupling["edge_count"] == table_graph.edge_count
    assert coupling["cross_community_edge_count"] == 1
    assert coupling["cross_community_edge_ratio"] == round(1 / 7, 8)
    assert sum(item["edge_count"] for item in result.dependency_matrix) == 7
    assert any(
        item["source_community_id"] != item["target_community_id"]
        and item["edge_count"] == 1
        for item in result.dependency_matrix
    )


def test_bridge_score_and_node_removal_simulation_explain_bridge_tables():
    table_graph = _table_graph(_cluster_graph())

    result = analyze_communities(table_graph, top_k=3)
    top = result.table_metrics[0]
    removals = result.deletion_simulation.value

    assert top["table_id"] in {"t_a3", "t_b1"}
    assert top["bridge_score_status"] == "success"
    assert set(top["bridge_score_submetrics"]) == {
        "betweenness",
        "cross_community_contribution",
    }
    assert len(removals) == 3
    assert max(item["component_count_delta"] for item in removals) > 0
    assert result.summary["top_bridge_tables"].value[0]["table_id"] in {
        "t_a3",
        "t_b1",
    }


def test_community_analysis_does_not_mutate_graph_view_or_table_graph():
    graph = _cluster_graph()
    before_graph = deepcopy(graph.to_dict())
    view = load_analysis_view(graph)
    before_view = deepcopy(view.to_dict())
    table_graph = build_table_graph(view)
    before_table_graph = deepcopy(table_graph.to_dict())

    first = analyze_communities(table_graph).to_dict()
    second = analyze_communities(table_graph).to_dict()

    assert first == second
    assert graph.to_dict() == before_graph
    assert view.to_dict() == before_view
    assert table_graph.to_dict() == before_table_graph
