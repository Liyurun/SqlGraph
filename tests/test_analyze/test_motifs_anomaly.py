# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Synthetic-data tests for Task 10 motifs, path diversity, and anomalies."""

from __future__ import annotations

from copy import deepcopy

from sqlgraph.analyze import (
    AnalysisConfig,
    MetricStatus,
    ResourceBudget,
    analyze_anomalies,
    analyze_basic_metrics,
    analyze_communities,
    analyze_impact,
    analyze_motifs,
    analyze_topology,
    build_table_graph,
    load_analysis_view,
    path_diversity,
)
import sqlgraph.analyze.anomaly as anomaly_module
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


def _table_graph(graph: PropertyGraph):
    return build_table_graph(load_analysis_view(graph))


def _add_sql_dependency(
    graph: PropertyGraph,
    source: str,
    target: str,
    suffix: str,
) -> None:
    sql_id = f"sql_{suffix}_{source}_{target}"
    graph.add_node(SqlNode(id=sql_id, name=sql_id))
    graph.add_edge(
        Edge(
            id=f"read_{suffix}_{source}_{target}",
            source_id=sql_id,
            target_id=source,
            edge_type=EdgeType.READS_FROM,
        )
    )
    graph.add_edge(
        Edge(
            id=f"write_{suffix}_{source}_{target}",
            source_id=sql_id,
            target_id=target,
            edge_type=EdgeType.WRITES_TO,
        )
    )


def _motif_graph() -> PropertyGraph:
    graph = _graph(
        [
            ("t_src", "t_b1"),
            ("t_src", "t_b2"),
            ("t_src", "t_sink"),
            ("t_b1", "t_sink"),
            ("t_b2", "t_sink"),
            ("t_x", "t_y"),
            ("t_y", "t_x"),
        ],
        names={
            "t_src": "ods_events",
            "t_b1": "dwd_branch_1",
            "t_b2": "dwd_branch_2",
            "t_sink": "ads_sink",
        },
    )
    _add_sql_dependency(graph, "t_src", "t_sink", "a")
    _add_sql_dependency(graph, "t_src", "t_sink", "b")
    return graph


def test_motifs_identify_fans_diamonds_parallel_links_cycles_and_paths():
    table_graph = _table_graph(_motif_graph())
    result = analyze_motifs(
        table_graph,
        communities_by_table={
            "t_src": "c_source",
            "t_b1": "c_mid",
            "t_b2": "c_mid",
            "t_sink": "c_sink",
            "t_x": "c_cycle",
            "t_y": "c_cycle",
        },
        max_path_depth=2,
    )
    motif_counts = result.motifs.value["motif_type_counts"]
    path_records = {
        item["table_id"]: item
        for item in result.path_diversity.value["records"]
    }

    assert result.motifs.status == MetricStatus.SUCCESS
    assert motif_counts["fan_in"] >= 1
    assert motif_counts["fan_out"] >= 1
    assert motif_counts["diamond"] == 1
    assert motif_counts["parallel_link"] == 1
    assert motif_counts["small_cycle"] == 1
    assert path_records["t_src"]["bounded_path_count"] == 5
    assert path_records["t_src"]["community_distribution"] == {
        "c_mid": 2,
        "c_sink": 3,
    }
    assert result.summary["top_motif_tables"].value[0]["motif_count"] > 0


def test_path_diversity_caps_paths_without_enumerating_all_simple_paths():
    graph = _graph(
        [
            ("t0", "t1"),
            ("t0", "t2"),
            ("t1", "t3"),
            ("t1", "t4"),
            ("t2", "t5"),
            ("t2", "t6"),
        ]
    )
    metric = path_diversity(
        _table_graph(graph),
        start_tables=("t0",),
        max_depth=3,
        max_paths_per_start=2,
    )
    record = metric.value["records"][0]

    assert metric.status == MetricStatus.SUCCESS
    assert record["bounded_path_count"] == 2
    assert record["truncated"] is True


def test_motif_resource_budget_degrades_expensive_pattern_enumeration():
    graph = _graph(
        [
            ("t0", "t1"),
            ("t0", "t2"),
            ("t1", "t3"),
            ("t2", "t3"),
        ]
    )
    config = AnalysisConfig(
        random_seed=7,
        resource_budget=ResourceBudget(
            exact_algorithm_max_nodes=3,
            betweenness_samples=2,
        ),
    )
    result = analyze_motifs(_table_graph(graph), config=config)

    assert result.motifs.status == MetricStatus.DEGRADED
    assert result.motifs.value["skipped_motif_types"] == (
        "diamond",
        "small_cycle",
    )
    assert result.path_diversity.status == MetricStatus.DEGRADED
    assert result.path_diversity.value["sampled_starts"] is True


def _anomaly_graph() -> PropertyGraph:
    graph = _graph(
        [
            ("unknown_src", "t_ads"),
            ("t_ods", "t_dwd"),
            ("t_dwd", "t_ads"),
            ("t_ads", "t_dwd"),
            ("t_ads", "t_ods"),
        ],
        names={
            "unknown_src": "unknown_source",
            "t_ods": "ods_events",
            "t_dwd": "dwd_orders",
            "t_ads": "ads_report",
        },
    )
    for table_id in ("unknown_src", "t_ads"):
        graph.add_node(
            ColumnNode(
                id=f"{table_id}_metric",
                name="metric",
                table_id=table_id,
            )
        )
    graph.add_edge(
        Edge(
            id="unknown_metric_to_ads",
            source_id="unknown_src_metric",
            target_id="t_ads_metric",
            edge_type=EdgeType.COMPUTE_DEPENDENCY,
        )
    )
    _add_sql_dependency(graph, "unknown_src", "t_ads", "one")
    sql_id = "sql_second_producer"
    graph.add_node(SqlNode(id=sql_id, name=sql_id))
    graph.add_edge(
        Edge(
            id="write_second_producer",
            source_id=sql_id,
            target_id="t_ads",
            edge_type=EdgeType.WRITES_TO,
        )
    )
    return graph


def test_rule_anomaly_score_outputs_feature_contributions_and_skips_model():
    graph = _anomaly_graph()
    view = load_analysis_view(graph)
    table_graph = build_table_graph(view)
    config = AnalysisConfig(
        layer_patterns=(("ods", "ods"), ("dwd", "dwd"), ("ads", "ads")),
        layer_violation_rules=(
            ("ads", "ods", "ads_to_ods", "high"),
            ("ads", "dwd", "ads_to_dwd", "medium"),
        ),
    )
    basic = analyze_basic_metrics(view, table_graph=table_graph, config=config)
    topology = analyze_topology(table_graph, config=config)
    impact = analyze_impact(table_graph, topology=topology, config=config)
    communities = analyze_communities(
        table_graph,
        topology=topology,
        impact=impact,
        config=config,
    )

    result = analyze_anomalies(
        table_graph,
        config=config,
        topology=topology,
        impact=impact,
        communities=communities,
        basic_metrics=basic,
        enable_model=False,
    )
    ads_record = next(
        item for item in result.table_metrics if item["table_id"] == "t_ads"
    )

    assert result.rule_based.status == MetricStatus.SUCCESS
    assert result.unsupervised_model.status == MetricStatus.SKIPPED
    assert ads_record["rule_anomaly_status"] == "success"
    assert ads_record["model_anomaly_score"] is None
    assert ads_record["raw_features"]["unknown_source_column_count"] == 1
    assert ads_record["raw_features"]["multi_producer"] is True
    assert ads_record["raw_features"]["is_cycle_member"] is True
    assert ads_record["raw_features"]["cross_layer_violation_count"] == 2
    assert set(ads_record["feature_contributions"]) == {
        "cross_layer_violation",
        "cycle_member",
        "high_in_degree",
        "high_out_degree",
        "impact_entropy",
        "layer_drift",
        "multi_producer",
        "unknown_lineage",
    }


def test_unsupervised_model_records_metadata_without_overwriting_rule_score(monkeypatch):
    class FakeIsolationForest:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def fit(self, matrix):
            self.matrix = matrix
            return self

        def score_samples(self, matrix):
            return [-sum(row) for row in matrix]

        def predict(self, matrix):
            return [-1] + [1 for _ in matrix[1:]]

    monkeypatch.setattr(
        anomaly_module,
        "_load_isolation_forest",
        lambda: FakeIsolationForest,
    )
    graph = _graph(
        [
            ("t0", "t1"),
            ("t0", "t2"),
            ("t2", "t3"),
        ]
    )
    result = analyze_anomalies(_table_graph(graph), enable_model=True)

    assert result.rule_based.status == MetricStatus.DEGRADED
    assert result.unsupervised_model.status == MetricStatus.SUCCESS
    assert result.unsupervised_model.value["feature_version"] == "1.0"
    assert result.unsupervised_model.value["parameters"]["random_seed"] == 42
    assert result.unsupervised_model.value["training_summary"]["sample_count"] == 4
    assert result.table_metrics[0]["rule_anomaly_score"] is not None
    assert result.table_metrics[0]["model_anomaly_score"] is not None


def test_motif_and_anomaly_analysis_are_deterministic_and_do_not_mutate_inputs():
    graph = _motif_graph()
    before_graph = deepcopy(graph.to_dict())
    view = load_analysis_view(graph)
    before_view = deepcopy(view.to_dict())
    table_graph = build_table_graph(view)
    before_table_graph = deepcopy(table_graph.to_dict())

    first_motifs = analyze_motifs(table_graph).to_dict()
    second_motifs = analyze_motifs(table_graph).to_dict()
    first_anomaly = analyze_anomalies(table_graph, enable_model=False).to_dict()
    second_anomaly = analyze_anomalies(table_graph, enable_model=False).to_dict()

    assert first_motifs == second_motifs
    assert first_anomaly == second_anomaly
    assert graph.to_dict() == before_graph
    assert view.to_dict() == before_view
    assert table_graph.to_dict() == before_table_graph
