# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Synthetic-data tests for Task 8 consistency and product scoring."""

from __future__ import annotations

from copy import deepcopy

from sqlgraph.analyze import (
    MetricStatus,
    analyze_basic_metrics,
    analyze_consistency,
    analyze_product_scores,
    build_table_graph,
    load_analysis_view,
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


def _consistency_graph() -> PropertyGraph:
    graph = PropertyGraph()
    for table_id, table_name in (
        ("t_src", "ods_orders"),
        ("t_a", "ads_revenue_a"),
        ("t_b", "ads_revenue_b"),
        ("t_c", "ads_revenue_c"),
    ):
        graph.add_node(TableNode(id=table_id, name=table_name, schema_name="dw"))

    for column_id, name, table_id in (
        ("c_src_amount", "amount", "t_src"),
        ("c_src_discount", "discount", "t_src"),
        ("c_a_revenue", "revenue", "t_a"),
        ("c_b_revenue", "revenue", "t_b"),
        ("c_b_gmv", "gmv", "t_b"),
        ("c_c_revenue", "revenue", "t_c"),
    ):
        graph.add_node(ColumnNode(id=column_id, name=name, table_id=table_id))
        graph.add_edge(
            Edge(
                id=f"has_{column_id}",
                source_id=table_id,
                target_id=column_id,
                edge_type=EdgeType.HAS_COLUMN,
            )
        )

    for sql_id, target_table in (
        ("sql_a", "t_a"),
        ("sql_b", "t_b"),
        ("sql_c", "t_c"),
    ):
        graph.add_node(SqlNode(id=sql_id, name=sql_id))
        graph.add_edge(Edge(f"read_{sql_id}", sql_id, "t_src", EdgeType.READS_FROM))
        graph.add_edge(
            Edge(f"write_{sql_id}", sql_id, target_table, EdgeType.WRITES_TO)
        )
        graph.add_edge(
            Edge(f"tl_{sql_id}", "t_src", target_table, EdgeType.TABLE_LINEAGE)
        )

    graph.add_node(
        TransformNode(
            id="tr_revenue_gross",
            expression="sum(amount)",
            expression_type=ExpressionType.AGG,
            fingerprint="fp_revenue_gross",
            op="sum",
            output_name="revenue",
        )
    )
    graph.add_node(
        TransformNode(
            id="tr_revenue_net",
            expression="sum(amount - discount)",
            expression_type=ExpressionType.AGG,
            fingerprint="fp_revenue_net",
            op="sum",
            output_name="revenue",
        )
    )
    graph.add_node(
        TransformNode(
            id="tr_gmv",
            expression="sum(amount)",
            expression_type=ExpressionType.AGG,
            fingerprint="fp_revenue_gross",
            op="sum",
            output_name="gmv",
        )
    )

    for sql_id, transform_id in (
        ("sql_a", "tr_revenue_gross"),
        ("sql_c", "tr_revenue_gross"),
        ("sql_b", "tr_revenue_net"),
        ("sql_b", "tr_gmv"),
    ):
        graph.add_edge(
            Edge(
                id=f"contains_{sql_id}_{transform_id}",
                source_id=sql_id,
                target_id=transform_id,
                edge_type=EdgeType.CONTAINS,
            )
        )

    for source_col, transform_id in (
        ("c_src_amount", "tr_revenue_gross"),
        ("c_src_amount", "tr_revenue_net"),
        ("c_src_discount", "tr_revenue_net"),
        ("c_src_amount", "tr_gmv"),
    ):
        graph.add_edge(
            Edge(
                id=f"dep_{source_col}_{transform_id}",
                source_id=source_col,
                target_id=transform_id,
                edge_type=EdgeType.COMPUTE_DEPENDENCY,
            )
        )

    for transform_id, column_id in (
        ("tr_revenue_gross", "c_a_revenue"),
        ("tr_revenue_gross", "c_c_revenue"),
        ("tr_revenue_net", "c_b_revenue"),
        ("tr_gmv", "c_b_gmv"),
    ):
        graph.add_edge(
            Edge(
                id=f"prod_{transform_id}_{column_id}",
                source_id=transform_id,
                target_id=column_id,
                edge_type=EdgeType.PRODUCES,
            )
        )
    return graph


def test_duplicate_expressions_group_by_logical_fingerprint_across_sqls():
    result = analyze_consistency(load_analysis_view(_consistency_graph()))
    duplicates = {
        item["fingerprint"]: item for item in result.duplicate_expressions
    }

    assert duplicates["fp_revenue_gross"]["transform_count"] == 2
    assert duplicates["fp_revenue_gross"]["occurrence_count"] == 3
    assert duplicates["fp_revenue_gross"]["sql_count"] == 3
    assert duplicates["fp_revenue_gross"]["table_count"] == 3
    assert duplicates["fp_revenue_gross"]["field_names"] == ("gmv", "revenue")
    assert duplicates["fp_revenue_gross"]["sql_ids"] == ("sql_a", "sql_b", "sql_c")


def test_same_name_and_same_logic_candidates_are_reported_as_governance_hints():
    result = analyze_consistency(load_analysis_view(_consistency_graph()))

    same_name = {
        item["field_name"]: item for item in result.same_name_different_logic
    }
    assert same_name["revenue"]["fingerprint_count"] == 2
    assert same_name["revenue"]["fingerprints"] == (
        "fp_revenue_gross",
        "fp_revenue_net",
    )
    assert same_name["revenue"]["candidate_type"] == "same_name_different_logic"
    assert same_name["revenue"]["is_business_error"] is False

    same_logic = {
        item["fingerprint"]: item for item in result.same_logic_different_names
    }
    assert same_logic["fp_revenue_gross"]["field_names"] == ("gmv", "revenue")
    assert same_logic["fp_revenue_gross"]["candidate_type"] == (
        "same_logic_different_names"
    )
    assert same_logic["fp_revenue_gross"]["is_business_error"] is False


def test_metric_candidates_include_drift_evidence_without_declaring_errors():
    result = analyze_consistency(load_analysis_view(_consistency_graph()))
    candidates = {
        item["metric_name"]: item for item in result.metric_candidates
    }

    assert "revenue" in candidates
    revenue = candidates["revenue"]
    assert revenue["distinct_fingerprint_count"] == 2
    assert revenue["has_drift_evidence"] is True
    assert revenue["aggregation_functions"] == ("sum",)
    assert revenue["candidate_only"] is True
    assert revenue["is_business_error"] is False
    assert revenue["evidence"]["filter_variants"] == ("none",)
    assert revenue["evidence"]["time_window_variants"] == ("none",)


def test_product_score_degrades_when_required_submetrics_are_missing():
    view = load_analysis_view(_consistency_graph())
    table_graph = build_table_graph(view)
    basic_metrics = analyze_basic_metrics(view, table_graph=table_graph)

    result = analyze_product_scores(
        table_graph,
        basic_metrics=basic_metrics,
    )

    assert result.summary.status == MetricStatus.DEGRADED
    assert "pagerank_reverse" in result.missing_submetrics
    assert result.table_scores
    assert all(item["score_status"] == "degraded" for item in result.table_scores)
    assert all("pagerank_reverse" in item["missing_submetrics"] for item in result.table_scores)


def test_consistency_analysis_is_deterministic_and_does_not_mutate_graph():
    graph = _consistency_graph()
    before = deepcopy(graph.to_dict())
    view = load_analysis_view(graph)
    before_view = deepcopy(view.to_dict())

    first = analyze_consistency(view).to_dict()
    second = analyze_consistency(view).to_dict()

    assert first == second
    assert graph.to_dict() == before
    assert view.to_dict() == before_view
