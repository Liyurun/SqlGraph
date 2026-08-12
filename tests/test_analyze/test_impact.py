# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Synthetic-data tests for Task 6 impact radius and core-asset metrics."""

from __future__ import annotations

from copy import deepcopy

from sqlgraph.analyze import (
    AnalysisConfig,
    MetricStatus,
    ResourceBudget,
    analyze_impact,
    build_table_graph,
    load_analysis_view,
    n_hop_impact,
)
from sqlgraph.model import (
    ColumnNode,
    Edge,
    EdgeType,
    PropertyGraph,
    SqlNode,
    TableNode,
)


def _graph(
    edges: list[tuple[str, str]],
    names: dict[str, str] | None = None,
    *,
    add_sql_weights: bool = False,
    add_field_weights: bool = False,
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
        if add_field_weights:
            graph.add_node(
                ColumnNode(
                    id=f"{table_id}_c",
                    name="metric_value",
                    table_id=table_id,
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
        if add_sql_weights:
            sql_id = f"sql_{index}_{source}_{target}"
            graph.add_node(SqlNode(id=sql_id, name=sql_id))
            graph.add_edge(
                Edge(
                    id=f"read_{index}_{source}_{target}",
                    source_id=sql_id,
                    target_id=source,
                    edge_type=EdgeType.READS_FROM,
                )
            )
            graph.add_edge(
                Edge(
                    id=f"write_{index}_{source}_{target}",
                    source_id=sql_id,
                    target_id=target,
                    edge_type=EdgeType.WRITES_TO,
                )
            )
        if add_field_weights:
            graph.add_edge(
                Edge(
                    id=f"dep_{index}_{source}_{target}",
                    source_id=f"{source}_c",
                    target_id=f"{target}_c",
                    edge_type=EdgeType.COMPUTE_DEPENDENCY,
                )
            )
    return graph


def _table_graph(graph: PropertyGraph):
    return build_table_graph(load_analysis_view(graph))


def _table_metrics(result):
    return {str(item["table_id"]): item for item in result.table_metrics}


def test_n_hop_bfs_handles_cycles_without_repeating_nodes():
    graph = _graph(
        [
            ("t_a", "t_b"),
            ("t_b", "t_c"),
            ("t_c", "t_b"),
            ("t_c", "t_d"),
        ]
    )
    table_graph = _table_graph(graph)

    downstream = n_hop_impact(table_graph, "t_a", 3, direction="downstream")
    upstream = n_hop_impact(table_graph, "t_d", 2, direction="upstream")

    assert downstream.status == MetricStatus.SUCCESS
    assert downstream.value["nodes"] == ("t_b", "t_c", "t_d")
    assert tuple(dict(item) for item in downstream.value["hop_counts"]) == (
        {"hop": 1, "count": 1},
        {"hop": 2, "count": 1},
        {"hop": 3, "count": 1},
    )
    assert upstream.value["nodes"] == ("t_b", "t_c")


def test_exact_scc_reachability_entropy_and_blast_score_are_explainable():
    graph = _graph(
        [
            ("t_a", "t_b"),
            ("t_b", "t_c"),
            ("t_c", "t_b"),
            ("t_c", "t_d"),
            ("t_a", "t_e"),
        ],
        names={
            "t_a": "ods_events",
            "t_b": "dwd_orders_a",
            "t_c": "dwd_orders_b",
            "t_d": "ads_order_report",
            "t_e": "ads_side_report",
        },
        add_sql_weights=True,
        add_field_weights=True,
    )
    table_graph = _table_graph(graph)
    communities = {
        "t_a": "c_source",
        "t_b": "c_mid",
        "t_c": "c_mid",
        "t_d": "c_report",
        "t_e": "c_side",
    }

    result = analyze_impact(
        table_graph,
        communities_by_table=communities,
        config=AnalysisConfig(
            layer_patterns=(("ods", "ods"), ("dwd", "dwd"), ("ads", "ads"))
        ),
    )
    metrics = _table_metrics(result)

    assert result.reachability.status == MetricStatus.SUCCESS
    assert result.reachability.value["mode"] == "exact_bitset"
    assert result.betweenness.parameters["mode"] == "exact"
    assert metrics["t_b"]["downstream_reachability_count"] == 2
    assert metrics["t_b"]["upstream_reachability_count"] == 2
    assert metrics["t_a"]["downstream_reachability_count"] == 4
    assert metrics["t_a"]["downstream_layer_distribution"] == {"ads": 2, "dwd": 2}
    assert metrics["t_a"]["downstream_community_distribution"] == {
        "c_mid": 2,
        "c_report": 1,
        "c_side": 1,
    }
    assert metrics["t_a"]["impact_entropy"] == 1.5
    assert metrics["t_a"]["blast_score_status"] == "success"
    assert set(metrics["t_a"]["blast_score_submetrics"]) == {
        "betweenness",
        "direct_downstream",
        "field_dependency",
        "impact_entropy",
        "indirect_downstream",
        "sql_dependency",
    }
    assert result.summary["top_blast_score_tables"].value[0]["table_id"] == "t_a"


def test_blast_score_prioritizes_large_fan_out_asset():
    graph = _graph(
        [
            ("t_src", "t_sink_1"),
            ("t_src", "t_sink_2"),
            ("t_src", "t_sink_3"),
            ("t_src", "t_sink_4"),
            ("t_src", "t_sink_5"),
        ],
        add_sql_weights=True,
        add_field_weights=True,
    )
    result = analyze_impact(_table_graph(graph))
    metrics = _table_metrics(result)

    assert metrics["t_src"]["direct_downstream_count"] == 5
    assert metrics["t_src"]["downstream_reachability_count"] == 5
    assert metrics["t_src"]["out_sql_weight"] == 5
    assert metrics["t_src"]["out_field_weight"] == 5
    assert result.summary["top_blast_score_tables"].value[0]["table_id"] == "t_src"


def test_resource_budget_degrades_reachability_and_samples_betweenness():
    graph = _graph(
        [
            ("t0", "t1"),
            ("t1", "t2"),
            ("t2", "t3"),
            ("t3", "t4"),
            ("t4", "t5"),
        ]
    )
    config = AnalysisConfig(
        random_seed=7,
        resource_budget=ResourceBudget(
            exact_algorithm_max_nodes=3,
            betweenness_samples=2,
        ),
    )

    result = analyze_impact(_table_graph(graph), config=config)
    metrics = _table_metrics(result)

    assert result.reachability.status == MetricStatus.DEGRADED
    assert result.reachability.value["mode"] == "approx_topological_upper_bound"
    assert result.reachability.value["exact_masks_available"] is False
    assert metrics["t0"]["downstream_reachability_count"] == 5
    assert result.betweenness.status == MetricStatus.SUCCESS
    assert result.betweenness.parameters["mode"] == "approximate_sampled"
    assert result.betweenness.parameters["sample_size"] == 2


def test_impact_analysis_is_deterministic_and_does_not_mutate_input_graph():
    graph = _graph(
        [
            ("t_a", "t_b"),
            ("t_b", "t_c"),
            ("t_a", "t_c"),
        ],
        add_sql_weights=True,
        add_field_weights=True,
    )
    before_graph = deepcopy(graph.to_dict())
    view = load_analysis_view(graph)
    before_view = deepcopy(view.to_dict())
    table_graph = build_table_graph(view)

    first = analyze_impact(table_graph).to_dict()
    second = analyze_impact(table_graph).to_dict()

    assert first == second
    assert graph.to_dict() == before_graph
    assert view.to_dict() == before_view
