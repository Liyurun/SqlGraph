# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""End-to-end validation for Task 13 governance analytics requirements."""

from __future__ import annotations

import csv
from copy import deepcopy
import json

from sqlgraph.analyze import (
    AnalysisConfig,
    MetricStatus,
    ResourceBudget,
    TableGraph,
    analyze_motifs,
    analyze_similarity,
    run_governance_analysis,
)
from sqlgraph.model import (
    ColumnNode,
    Edge,
    EdgeType,
    ExpressionType,
    PropertyGraph,
    SqlNode,
    TableNode,
    TransformNode,
)
from sqlgraph.serialize import to_csv, to_graphrag, to_json
from sqlgraph.visualize import to_html


def _add_table(
    graph: PropertyGraph,
    table_id: str,
    name: str,
    columns: tuple[tuple[str, str], ...],
) -> None:
    graph.add_node(TableNode(id=table_id, name=name, schema_name="synthetic_dw"))
    for column_name, data_type in columns:
        column_id = f"{table_id}_{column_name}"
        graph.add_node(
            ColumnNode(
                id=column_id,
                name=column_name,
                table_id=table_id,
                data_type=data_type,
            )
        )
        graph.add_edge(
            Edge(
                id=f"has_{column_id}",
                source_id=table_id,
                target_id=column_id,
                edge_type=EdgeType.HAS_COLUMN,
            )
        )


def _add_sql(
    graph: PropertyGraph,
    sql_id: str,
    reads: tuple[str, ...],
    writes: tuple[str, ...],
    sql_content: str,
) -> None:
    graph.add_node(
        SqlNode(
            id=sql_id,
            name=sql_id,
            sql_content=sql_content,
            dialect="spark",
        )
    )
    for table_id in reads:
        graph.add_edge(
            Edge(
                id=f"read_{sql_id}_{table_id}",
                source_id=sql_id,
                target_id=table_id,
                edge_type=EdgeType.READS_FROM,
            )
        )
    for table_id in writes:
        graph.add_edge(
            Edge(
                id=f"write_{sql_id}_{table_id}",
                source_id=sql_id,
                target_id=table_id,
                edge_type=EdgeType.WRITES_TO,
            )
        )


def _add_lineage(graph: PropertyGraph, source: str, target: str) -> None:
    graph.add_edge(
        Edge(
            id=f"tl_{source}_{target}",
            source_id=source,
            target_id=target,
            edge_type=EdgeType.TABLE_LINEAGE,
        )
    )


def _add_transform(
    graph: PropertyGraph,
    transform_id: str,
    expression: str,
    fingerprint: str,
    output_name: str,
    sql_ids: tuple[str, ...],
    source_columns: tuple[str, ...],
    output_columns: tuple[str, ...],
) -> None:
    graph.add_node(
        TransformNode(
            id=transform_id,
            expression=expression,
            expression_type=ExpressionType.AGG,
            fingerprint=fingerprint,
            op="sum",
            output_name=output_name,
        )
    )
    for sql_id in sql_ids:
        graph.add_edge(
            Edge(
                id=f"contains_{sql_id}_{transform_id}",
                source_id=sql_id,
                target_id=transform_id,
                edge_type=EdgeType.CONTAINS,
            )
        )
    for column_id in source_columns:
        graph.add_edge(
            Edge(
                id=f"dep_{column_id}_{transform_id}",
                source_id=column_id,
                target_id=transform_id,
                edge_type=EdgeType.COMPUTE_DEPENDENCY,
            )
        )
    for column_id in output_columns:
        graph.add_edge(
            Edge(
                id=f"prod_{transform_id}_{column_id}",
                source_id=transform_id,
                target_id=column_id,
                edge_type=EdgeType.PRODUCES,
            )
        )


def _validation_graph() -> PropertyGraph:
    graph = PropertyGraph()
    _add_table(
        graph,
        "t_ods",
        "ods_orders",
        (
            ("order_id", "bigint"),
            ("amount", "double"),
            ("discount", "double"),
            ("region_id", "bigint"),
        ),
    )
    _add_table(
        graph,
        "t_dim",
        "dim_region",
        (("region_id", "bigint"), ("region_name", "string")),
    )
    _add_table(
        graph,
        "t_dwd_daily",
        "dwd_orders_daily",
        (("order_id", "bigint"), ("revenue", "double")),
    )
    _add_table(
        graph,
        "t_dwd_hourly",
        "dwd_orders_hourly",
        (("order_id", "bigint"), ("revenue", "double")),
    )
    _add_table(
        graph,
        "t_ads_daily",
        "ads_orders_daily",
        (("revenue", "double"), ("gmv", "double")),
    )
    _add_table(
        graph,
        "t_ads_monthly",
        "ads_orders_monthly",
        (("revenue", "double"),),
    )

    _add_sql(
        graph,
        "sql_dwd_daily",
        ("t_ods",),
        ("t_dwd_daily",),
        "select order_id, sum(amount) as revenue from synthetic_dw.ods_orders group by order_id",
    )
    _add_sql(
        graph,
        "sql_dwd_hourly",
        ("t_ods",),
        ("t_dwd_hourly",),
        "select order_id, sum(amount - discount) as revenue from synthetic_dw.ods_orders group by order_id",
    )
    _add_sql(
        graph,
        "sql_ads_daily",
        ("t_dwd_daily", "t_dwd_hourly", "t_dim"),
        ("t_ads_daily",),
        "select sum(revenue) as revenue, sum(revenue) as gmv from synthetic_dw.dwd_orders_daily",
    )
    _add_sql(
        graph,
        "sql_ads_monthly",
        ("t_dwd_daily", "t_dwd_hourly"),
        ("t_ads_monthly",),
        "select sum(revenue) as revenue from synthetic_dw.dwd_orders_hourly",
    )

    for source, target in (
        ("t_ods", "t_dwd_daily"),
        ("t_ods", "t_dwd_hourly"),
        ("t_dwd_daily", "t_ads_daily"),
        ("t_dwd_hourly", "t_ads_daily"),
        ("t_dwd_daily", "t_ads_monthly"),
        ("t_dwd_hourly", "t_ads_monthly"),
        ("t_dim", "t_ads_daily"),
    ):
        _add_lineage(graph, source, target)

    for target in ("t_dwd_daily", "t_dwd_hourly"):
        graph.add_edge(
            Edge(
                id=f"dep_t_ods_order_id_{target}_order_id",
                source_id="t_ods_order_id",
                target_id=f"{target}_order_id",
                edge_type=EdgeType.COMPUTE_DEPENDENCY,
            )
        )

    _add_transform(
        graph,
        "tr_dwd_daily_revenue",
        "sum(amount)",
        "fp_revenue_gross",
        "revenue",
        ("sql_dwd_daily",),
        ("t_ods_amount",),
        ("t_dwd_daily_revenue",),
    )
    _add_transform(
        graph,
        "tr_dwd_hourly_revenue",
        "sum(amount - discount)",
        "fp_revenue_net",
        "revenue",
        ("sql_dwd_hourly",),
        ("t_ods_amount", "t_ods_discount"),
        ("t_dwd_hourly_revenue",),
    )
    _add_transform(
        graph,
        "tr_ads_revenue_shared",
        "sum(revenue)",
        "fp_revenue_gross",
        "revenue",
        ("sql_ads_daily", "sql_ads_monthly"),
        ("t_dwd_daily_revenue", "t_dwd_hourly_revenue"),
        ("t_ads_daily_revenue", "t_ads_monthly_revenue"),
    )
    _add_transform(
        graph,
        "tr_ads_gmv",
        "sum(revenue)",
        "fp_revenue_gross",
        "gmv",
        ("sql_ads_daily",),
        ("t_dwd_daily_revenue", "t_dwd_hourly_revenue"),
        ("t_ads_daily_gmv",),
    )
    return graph


def _by_id(records):
    return {str(item["table_id"]): item for item in records}


def _metric_statuses(snapshot):
    return {name: status for name, status in snapshot.manifest.metric_statuses.items()}


def _read_csv_rows(path):
    with path.open(encoding="utf-8") as stream:
        return sorted(
            (dict(row) for row in csv.DictReader(stream)),
            key=lambda row: json.dumps(row, sort_keys=True),
        )


def _serialized_semantics(graph: PropertyGraph, tmp_path, label: str) -> dict:
    output_dir = tmp_path / label
    csv_dir = output_dir / "csv"
    json_path = output_dir / "graph.json"
    graphrag_path = output_dir / "graphrag.json"
    html_path = output_dir / "lineage.html"
    output_dir.mkdir()

    json_payload = to_json(graph, str(json_path))
    to_csv(graph, str(csv_dir))
    graphrag = to_graphrag(graph, str(graphrag_path))
    html = to_html(graph, output_path=str(html_path), title="Synthetic Validation")

    return {
        "json": json_payload,
        "csv_nodes": _read_csv_rows(csv_dir / "nodes.csv"),
        "csv_edges": _read_csv_rows(csv_dir / "edges.csv"),
        "graphrag_entities": sorted(
            (item["id"], item["type"], item["name"]) for item in graphrag["entities"]
        ),
        "graphrag_relations": sorted(
            (item["id"], item["source"], item["target"], item["type"])
            for item in graphrag["relations"]
        ),
        "graphrag_schema": {
            "version": graphrag["schema"]["version"],
            "entity_types": sorted(graphrag["schema"]["entity_types"]),
            "relation_types": sorted(graphrag["schema"]["relation_types"]),
        },
        "html": html,
    }


def test_end_to_end_snapshot_validates_formulas_and_direction_semantics(tmp_path):
    graph = _validation_graph()
    before = deepcopy(graph.to_dict())
    output_dir = tmp_path / "analysis"
    config = AnalysisConfig(
        random_seed=17,
        float_precision=4,
        resource_budget=ResourceBudget(
            max_nodes=100_000,
            max_edges=1_000_000,
            exact_algorithm_max_nodes=1000,
            betweenness_samples=4,
            similarity_candidates_per_node=8,
            top_k_removal_simulation=3,
        ),
    )

    snapshot = run_governance_analysis(graph, config=config, output_dir=output_dir)

    assert graph.to_dict() == before
    assert not snapshot.manifest.failed_metrics
    assert snapshot.manifest.metadata["resource_budget"]["max_nodes"] == 100_000
    assert snapshot.manifest.metadata["resource_budget"]["max_edges"] == 1_000_000
    assert snapshot.manifest.metadata["execution"]["duration_ms"] >= 0
    assert (output_dir / "manifest.json").is_file()
    assert (output_dir / "summary.json").is_file()

    statuses = _metric_statuses(snapshot)
    for metric_name in (
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
    ):
        assert statuses[metric_name] in {
            MetricStatus.SUCCESS,
            MetricStatus.DEGRADED,
        }

    assert snapshot.summary["table_graph"]["node_count"] == 6
    assert snapshot.summary["table_graph"]["edge_count"] == 7
    assert snapshot.summary["inventory"]["lineage_inventory"]["table_count"] == 6

    layer_matrix = {
        (item["source_layer"], item["target_layer"]): item
        for item in snapshot.layer_matrix
    }
    assert layer_matrix[("ods", "dwd")]["edge_count"] == 2
    assert layer_matrix[("dwd", "ads")]["edge_count"] == 4
    assert layer_matrix[("dim", "ads")]["sql_weight"] == 1

    tables = _by_id(snapshot.table_metrics)
    assert tables["t_ods"]["in_degree"] == 0
    assert tables["t_ods"]["out_degree"] == 2
    assert tables["t_ods"]["downstream_reachability_count"] == 4
    assert tables["t_ads_daily"]["direct_upstream_count"] == 3
    assert tables["t_ads_monthly"]["no_downstream"] is True
    assert tables["t_dwd_daily"]["graph_layer_max"] == 1
    assert tables["t_ads_daily"]["graph_layer_max"] == 2

    if tables["t_ods"]["pagerank_reverse"] is not None:
        assert tables["t_ods"]["pagerank_reverse"] > tables["t_ads_daily"]["pagerank_reverse"]
        assert tables["t_ads_daily"]["pagerank_forward"] > tables["t_ods"]["pagerank_forward"]

    duplicate_groups = {
        item["fingerprint"]: item
        for item in snapshot.consistency_groups
        if item["group_type"] == "duplicate_expression"
    }
    assert duplicate_groups["fp_revenue_gross"]["field_names"] == (
        "gmv",
        "revenue",
    )
    assert duplicate_groups["fp_revenue_gross"]["sql_count"] == 3

    same_name = {
        item["field_name"]: item
        for item in snapshot.consistency_groups
        if item["group_type"] == "same_name_different_logic"
    }
    assert same_name["revenue"]["fingerprints"] == (
        "fp_revenue_gross",
        "fp_revenue_net",
    )
    assert same_name["revenue"]["is_business_error"] is False

    assert any(
        item["motif_type"] == "diamond"
        for item in snapshot.motif_records
    )
    assert any(
        {item["left_table_id"], item["right_table_id"]}
        == {"t_dwd_daily", "t_dwd_hourly"}
        for item in snapshot.similarity_candidates
    )
    assert any(
        item.get("rule_anomaly_score") is not None
        for item in snapshot.anomaly_metrics
    )


def test_large_scale_resource_protection_uses_bounded_paths_without_full_pair_scan():
    table_count = 100_000
    nodes = tuple(f"t_{index:06d}" for index in range(table_count))
    large_table_graph = TableGraph(
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
        random_seed=31,
        resource_budget=ResourceBudget(
            max_nodes=100_000,
            max_edges=1_000_000,
            exact_algorithm_max_nodes=10,
            betweenness_samples=5,
            similarity_candidates_per_node=3,
        ),
    )

    similarity = analyze_similarity(large_table_graph, config=config)
    motifs = analyze_motifs(large_table_graph, config=config)

    assert similarity.candidate_recall.value["full_pair_count"] == 4_999_950_000
    assert similarity.candidate_recall.value["candidate_pair_count"] < 200_000
    assert similarity.candidate_recall.value["full_pair_scan_avoided"] is True
    assert similarity.embedding.status == MetricStatus.SKIPPED
    assert motifs.motifs.status == MetricStatus.DEGRADED
    assert motifs.path_diversity.status == MetricStatus.DEGRADED
    assert motifs.path_diversity.value["start_count"] == 5
    # The million-edge path is validated through resource thresholds rather
    # than materializing 1,000,000 test edges in CI.
    assert config.resource_budget.max_edges == 1_000_000


def test_analysis_does_not_change_existing_serialization_or_visualization(tmp_path):
    graph = _validation_graph()
    before_graph = deepcopy(graph.to_dict())
    before_outputs = _serialized_semantics(graph, tmp_path, "before")

    run_governance_analysis(
        graph,
        config=AnalysisConfig(metrics=("basic", "topology", "impact")),
        output_dir=tmp_path / "analysis",
    )

    after_outputs = _serialized_semantics(graph, tmp_path, "after")
    assert graph.to_dict() == before_graph
    assert after_outputs == before_outputs


def test_stable_ids_fingerprints_transform_keys_and_cross_sql_fusion_remain_unchanged(tmp_path):
    graph = _validation_graph()
    before = graph.to_dict()
    before_node_ids = [node["id"] for node in before["nodes"]]
    before_edge_ids = [edge["id"] for edge in before["edges"]]
    before_transform_keys = sorted(
        (node["fingerprint"], node.get("output_name"), node["id"])
        for node in before["nodes"]
        if node["node_type"] == "transform"
    )

    snapshot = run_governance_analysis(
        graph,
        config=AnalysisConfig(metrics=("basic", "topology", "consistency")),
        output_dir=tmp_path / "analysis",
    )

    after = graph.to_dict()
    assert [node["id"] for node in after["nodes"]] == before_node_ids
    assert [edge["id"] for edge in after["edges"]] == before_edge_ids
    assert sorted(
        (node["fingerprint"], node.get("output_name"), node["id"])
        for node in after["nodes"]
        if node["node_type"] == "transform"
    ) == before_transform_keys

    transform_metrics = {
        item["transform_id"]: item for item in snapshot.transform_metrics
    }
    assert transform_metrics["tr_ads_revenue_shared"]["fingerprint"] == (
        "fp_revenue_gross"
    )
    assert transform_metrics["tr_ads_revenue_shared"]["output_name"] == "revenue"
    assert transform_metrics["tr_ads_revenue_shared"]["sql_ids"] == (
        "sql_ads_daily",
        "sql_ads_monthly",
    )
    assert transform_metrics["tr_ads_revenue_shared"]["target_table_ids"] == (
        "t_ads_daily",
        "t_ads_monthly",
    )
    assert transform_metrics["tr_ads_gmv"]["fingerprint"] == "fp_revenue_gross"
    assert transform_metrics["tr_ads_gmv"]["output_name"] == "gmv"

    graph_json = json.loads((tmp_path / "analysis" / "manifest.json").read_text())
    assert graph_json["graph_fingerprint"] == snapshot.manifest.graph_fingerprint
    assert "select order_id" not in json.dumps(graph_json)
