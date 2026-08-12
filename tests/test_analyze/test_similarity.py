# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Synthetic-data tests for Task 9 similar assets and embeddings."""

from __future__ import annotations

from copy import deepcopy

from sqlgraph.analyze import (
    AnalysisConfig,
    MetricStatus,
    ResourceBudget,
    TableGraph,
    analyze_similarity,
    build_graph_embeddings,
    build_table_graph,
    jaccard_similarity,
    load_analysis_view,
)
from sqlgraph.model import ColumnNode, Edge, EdgeType, PropertyGraph, TableNode


def _graph(
    edges: list[tuple[str, str]],
    columns: dict[str, list[tuple[str, str]]] | None = None,
    names: dict[str, str] | None = None,
) -> PropertyGraph:
    graph = PropertyGraph()
    names = names or {}
    columns = columns or {}
    table_ids = sorted(set(columns) | {table_id for edge in edges for table_id in edge})
    for table_id in table_ids:
        graph.add_node(
            TableNode(
                id=table_id,
                name=names.get(table_id, table_id),
                schema_name="synthetic_dw",
            )
        )
        for column_name, data_type in columns.get(table_id, []):
            graph.add_node(
                ColumnNode(
                    id=f"{table_id}_{column_name}",
                    name=column_name,
                    table_id=table_id,
                    data_type=data_type,
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


def _similarity_graph() -> PropertyGraph:
    columns = {
        "t_src_orders": [("order_id", "bigint"), ("amount", "double")],
        "t_src_events": [("event_id", "bigint"), ("amount", "double")],
        "t_dwd_orders_daily": [
            ("order_id", "bigint"),
            ("amount", "double"),
            ("event_date", "date"),
        ],
        "t_dwd_orders_hourly": [
            ("order_id", "bigint"),
            ("amount", "double"),
            ("event_date", "date"),
        ],
        "t_ads_orders_daily": [("order_id", "bigint"), ("amount", "double")],
        "t_ads_orders_hourly": [("order_id", "bigint"), ("amount", "double")],
        "t_dim_region": [("region_id", "bigint"), ("region_name", "string")],
    }
    return _graph(
        [
            ("t_src_orders", "t_dwd_orders_daily"),
            ("t_src_events", "t_dwd_orders_daily"),
            ("t_src_orders", "t_dwd_orders_hourly"),
            ("t_src_events", "t_dwd_orders_hourly"),
            ("t_dwd_orders_daily", "t_ads_orders_daily"),
            ("t_dwd_orders_hourly", "t_ads_orders_hourly"),
            ("t_dim_region", "t_ads_orders_daily"),
            ("t_dim_region", "t_ads_orders_hourly"),
        ],
        columns=columns,
        names={
            "t_src_orders": "ods_orders",
            "t_src_events": "ods_events",
            "t_dwd_orders_daily": "dwd_orders_daily",
            "t_dwd_orders_hourly": "dwd_orders_hourly",
            "t_ads_orders_daily": "ads_orders_daily",
            "t_ads_orders_hourly": "ads_orders_hourly",
            "t_dim_region": "dim_region",
        },
    )


def _table_graph_and_view(graph: PropertyGraph):
    view = load_analysis_view(graph)
    return build_table_graph(view), view


def test_jaccard_similarity_handles_empty_and_overlapping_sets():
    assert jaccard_similarity(("a", "b"), ("b", "c")) == round(1 / 3, 8)
    assert jaccard_similarity((), ()) == 1.0
    assert jaccard_similarity(("a",), ()) == 0.0


def test_similarity_ranks_structural_and_schema_neighbors_with_evidence():
    graph = _similarity_graph()
    table_graph, view = _table_graph_and_view(graph)

    result = analyze_similarity(table_graph, view=view, embedding_enabled=True)
    top = result.similarity_candidates[0]

    assert result.embedding.status == MetricStatus.SUCCESS
    assert result.candidate_recall.status == MetricStatus.SUCCESS
    assert {top["left_table_id"], top["right_table_id"]} == {
        "t_dwd_orders_daily",
        "t_dwd_orders_hourly",
    }
    assert top["similarity_score"] > 0.7
    assert set(top["common_upstream"]) == {"t_src_events", "t_src_orders"}
    assert set(top["schema_overlap"]) == {
        "name:amount",
        "name:event_date",
        "name:order_id",
        "type:bigint",
        "type:date",
        "type:double",
    }
    assert set(top["recall_sources"]) >= {"community", "layer", "schema"}
    assert top["embedding_evidence"]["available"] is True
    assert top["embedding_evidence"]["left_vector_index"] is not None
    assert result.summary["top_similarity_candidates"].value[0]["similarity_score"] == (
        top["similarity_score"]
    )


def test_node2vec_missing_degrades_but_structural_similarity_still_runs(monkeypatch):
    import sqlgraph.analyze.embeddings as embeddings_module

    monkeypatch.setattr(embeddings_module, "_load_node2vec_backend", lambda: None)
    table_graph, view = _table_graph_and_view(_similarity_graph())

    result = analyze_similarity(
        table_graph,
        view=view,
        embedding_backend="node2vec",
    )

    assert result.embedding.status == MetricStatus.DEGRADED
    assert "node2vec backend is not available" in result.embedding.reason
    assert result.candidate_recall.status == MetricStatus.SUCCESS
    assert result.similarity_candidates
    assert result.similarity_candidates[0]["similarity_score"] is not None


def test_embedding_can_be_disabled_without_breaking_structural_similarity():
    table_graph, view = _table_graph_and_view(_similarity_graph())

    result = analyze_similarity(table_graph, view=view, embedding_enabled=False)

    assert result.embedding.status == MetricStatus.SKIPPED
    assert result.embedding.value["vectors_available"] is False
    assert result.similarity_candidates
    assert result.similarity_candidates[0]["embedding_evidence"]["available"] is False
    assert result.similarity_candidates[0]["similarity_score"] is not None


def test_large_candidate_recall_uses_indexed_buckets_not_full_pair_scan():
    table_count = 100_000
    nodes = tuple(f"t_{index:06d}" for index in range(table_count))
    table_graph = TableGraph(
        nodes=nodes,
        edges=(),
        node_index={node_id: index for index, node_id in enumerate(nodes)},
        adjacency={node_id: () for node_id in nodes},
        in_degree={node_id: 0 for node_id in nodes},
        out_degree={node_id: 0 for node_id in nodes},
        nodes_by_id={
            node_id: {
                "id": node_id,
                "node_type": "table",
                "schema_name": "synthetic_dw",
                "name": f"dwd_bucket_{index % 1000:04d}_{index:06d}",
            }
            for index, node_id in enumerate(nodes)
        },
    )
    config = AnalysisConfig(
        resource_budget=ResourceBudget(
            exact_algorithm_max_nodes=10,
            similarity_candidates_per_node=3,
        )
    )

    result = analyze_similarity(table_graph, config=config)

    assert result.embedding.status == MetricStatus.SKIPPED
    assert result.candidate_recall.value["full_pair_count"] == 4_999_950_000
    assert result.candidate_recall.value["candidate_pair_count"] < 200_000
    assert result.candidate_recall.value["full_pair_scan_avoided"] is True
    assert result.candidate_recall.value["per_node_candidate_limit"] == 3


def test_embeddings_are_deterministic_and_use_stable_node_mapping():
    table_graph, _ = _table_graph_and_view(_similarity_graph())
    config = AnalysisConfig(random_seed=17)

    first = build_graph_embeddings(table_graph, config=config)
    second = build_graph_embeddings(table_graph, config=config)

    assert first.to_dict() == second.to_dict()
    assert first.node_mapping == {
        node_id: index for index, node_id in enumerate(table_graph.nodes)
    }
    assert set(first.vectors) == set(table_graph.nodes)


def test_similarity_analysis_does_not_mutate_input_graph_view_or_table_graph():
    graph = _similarity_graph()
    before_graph = deepcopy(graph.to_dict())
    view = load_analysis_view(graph)
    before_view = deepcopy(view.to_dict())
    table_graph = build_table_graph(view)
    before_table_graph = deepcopy(table_graph.to_dict())

    first = analyze_similarity(table_graph, view=view).to_dict()
    second = analyze_similarity(table_graph, view=view).to_dict()

    assert first == second
    assert graph.to_dict() == before_graph
    assert view.to_dict() == before_view
    assert table_graph.to_dict() == before_table_graph
