# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Synthetic-data tests for Task 3 basic governance metrics."""

from __future__ import annotations

from copy import deepcopy

from sqlgraph.analyze import (
    MetricStatus,
    analyze_basic_metrics,
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


def _task3_graph() -> PropertyGraph:
    graph = PropertyGraph()
    for node in (
        TableNode(id="t_ods", name="ods_events", schema_name="dw"),
        TableNode(id="t_dwd", name="dwd_orders", schema_name="dw"),
        TableNode(id="t_ads", name="ads_report", schema_name="dw"),
        TableNode(id="t_orphan", name="fact_misc", schema_name="dw"),
        TableNode(id="t_unknown", name="UNKNOWN_SOURCE", schema_name="dw"),
        TableNode(
            id="t_cte",
            name="cte_tmp",
            schema_name="dw",
            is_cte=True,
            logic_fingerprint="cte-fp",
        ),
    ):
        graph.add_node(node)

    for column_id, name, table_id in (
        ("c_ods_id", "user_id", "t_ods"),
        ("c_ods_amount", "amount", "t_ods"),
        ("c_dwd_id", "user_id", "t_dwd"),
        ("c_dwd_metric", "amount_sum", "t_dwd"),
        ("c_dwd_const", "is_active", "t_dwd"),
        ("c_dwd_unparsed", "missing_lineage", "t_dwd"),
        ("c_ads_report", "report_amount", "t_ads"),
        ("c_ads_window", "rolling_amount", "t_ads"),
        ("c_ads_bad", "bad_source", "t_ads"),
        ("c_orphan_unused", "unused_col", "t_orphan"),
        ("c_unknown_bad", "bad_source", "t_unknown"),
        ("c_cte_tmp", "tmp_col", "t_cte"),
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

    for sql_id in ("sql_load_dwd", "sql_repair_dwd", "sql_load_ads"):
        graph.add_node(SqlNode(id=sql_id, name=sql_id))

    graph.add_edge(Edge("read_1", "sql_load_dwd", "t_ods", EdgeType.READS_FROM))
    graph.add_edge(Edge("write_1", "sql_load_dwd", "t_dwd", EdgeType.WRITES_TO))
    graph.add_edge(Edge("read_2", "sql_repair_dwd", "t_ods", EdgeType.READS_FROM))
    graph.add_edge(Edge("write_2", "sql_repair_dwd", "t_dwd", EdgeType.WRITES_TO))
    graph.add_edge(Edge("read_3a", "sql_load_ads", "t_dwd", EdgeType.READS_FROM))
    graph.add_edge(Edge("read_3b", "sql_load_ads", "t_unknown", EdgeType.READS_FROM))
    graph.add_edge(Edge("write_3", "sql_load_ads", "t_ads", EdgeType.WRITES_TO))

    graph.add_edge(Edge("tl_ods_dwd", "t_ods", "t_dwd", EdgeType.TABLE_LINEAGE))
    graph.add_edge(Edge("tl_dwd_ads", "t_dwd", "t_ads", EdgeType.TABLE_LINEAGE))
    graph.add_edge(Edge("tl_unknown_ads", "t_unknown", "t_ads", EdgeType.TABLE_LINEAGE))

    graph.add_node(
        TransformNode(
            id="tr_agg",
            expression="sum(amount)",
            expression_type=ExpressionType.AGG,
            fingerprint="fp_agg",
        )
    )
    graph.add_node(
        TransformNode(
            id="tr_literal",
            expression="1",
            expression_type=ExpressionType.LITERAL,
            fingerprint="fp_literal",
        )
    )
    graph.add_node(
        TransformNode(
            id="tr_window",
            expression="sum(amount) over(partition by user_id)",
            expression_type=ExpressionType.WINDOW,
            fingerprint="fp_window",
        )
    )
    graph.add_node(
        TransformNode(
            id="tr_func",
            expression="round(amount_sum, 2)",
            expression_type=ExpressionType.FUNCTION,
            fingerprint="fp_func",
        )
    )

    graph.add_edge(
        Edge("dep_pass", "c_ods_id", "c_dwd_id", EdgeType.COMPUTE_DEPENDENCY)
    )
    graph.add_edge(
        Edge("dep_agg", "c_ods_amount", "tr_agg", EdgeType.COMPUTE_DEPENDENCY)
    )
    graph.add_edge(Edge("prod_agg", "tr_agg", "c_dwd_metric", EdgeType.PRODUCES))
    graph.add_edge(
        Edge("prod_literal", "tr_literal", "c_dwd_const", EdgeType.PRODUCES)
    )
    graph.add_edge(
        Edge("dep_window", "c_dwd_id", "tr_window", EdgeType.COMPUTE_DEPENDENCY)
    )
    graph.add_edge(
        Edge("prod_window", "tr_window", "c_ads_window", EdgeType.PRODUCES)
    )
    graph.add_edge(
        Edge("dep_func", "c_dwd_metric", "tr_func", EdgeType.COMPUTE_DEPENDENCY)
    )
    graph.add_edge(Edge("prod_func", "tr_func", "c_ads_report", EdgeType.PRODUCES))
    graph.add_edge(
        Edge("dep_unknown", "c_unknown_bad", "c_ads_bad", EdgeType.COMPUTE_DEPENDENCY)
    )

    return graph


def _values(metrics):
    return {name: result.value for name, result in metrics.items()}


def test_overview_layer_distribution_and_production_metrics():
    view = load_analysis_view(_task3_graph())
    result = analyze_basic_metrics(view, top_n=3)
    overview = _values(result.overview)

    assert overview["sql_count"] == 3
    assert overview["table_count"] == 6
    assert overview["physical_table_count"] == 5
    assert overview["logical_table_count"] == 1
    assert overview["cte_table_count"] == 1
    assert overview["column_count"] == 12
    assert overview["physical_column_count"] == 11
    assert overview["transform_count"] == 4
    assert overview["table_lineage_edge_count"] == 3
    assert overview["field_dependency_edge_count"] == 5
    assert overview["average_fields_per_physical_table"] == 2.2
    assert overview["average_upstream_count"] == 0.6
    assert overview["average_downstream_count"] == 0.6

    layers = {
        item["layer"]: item for item in result.layer_distribution
    }
    assert layers["ods"]["table_count"] == 1
    assert layers["ods"]["field_count"] == 2
    assert layers["ods"]["edge_count"] == 1
    assert layers["dwd"]["table_count"] == 1
    assert layers["dwd"]["field_count"] == 4
    assert layers["dwd"]["sql_count"] == 2
    assert layers["dwd"]["multi_producer_table_count"] == 1
    assert layers["ads"]["sql_count"] == 1
    assert layers["ads"]["no_downstream_table_count"] == 1
    assert layers["unknown"]["table_count"] == 2
    assert layers["unknown"]["field_count"] == 2
    assert layers["unknown"]["edge_count"] == 1

    matrix = {
        (item["source_layer"], item["target_layer"]): item
        for item in result.layer_matrix
    }
    assert matrix[("ods", "dwd")]["edge_count"] == 1
    assert matrix[("ods", "dwd")]["field_weight"] == 2
    assert matrix[("ods", "dwd")]["sql_weight"] == 2
    assert matrix[("dwd", "ads")]["field_weight"] == 2
    assert matrix[("unknown", "ads")]["field_weight"] == 1

    production = result.production_consumption
    assert production["no_upstream_table_count"] == 3
    assert production["no_downstream_table_count"] == 2
    assert production["multi_producer_table_count"] == 1
    assert production["read_top_n"][0]["table_id"] == "t_ods"
    assert production["read_top_n"][0]["read_count"] == 2
    assert production["write_top_n"][0]["table_id"] == "t_dwd"
    assert production["write_top_n"][0]["write_count"] == 2
    assert production["high_in_degree_tables"][0]["table_id"] == "t_ads"
    assert production["high_in_degree_tables"][0]["in_degree"] == 2


def test_field_lineage_quality_metrics_are_separate_from_physical_coverage():
    result = analyze_basic_metrics(load_analysis_view(_task3_graph()))
    summary = _values(result.field_lineage.summary)

    assert summary["output_column_count"] == 7
    assert summary["parsed_output_column_count"] == 6
    assert summary["physical_source_column_count"] == 4
    assert summary["parsed_output_coverage_ratio"] == 0.85714286
    assert summary["physical_source_coverage_ratio"] == 0.57142857
    assert summary["passthrough_column_count"] == 2
    assert summary["aggregate_column_count"] == 1
    assert summary["window_column_count"] == 1
    assert summary["literal_column_count"] == 1
    assert summary["derived_column_count"] == 1
    assert summary["unknown_source_column_count"] == 1
    assert summary["lineage_breakpoint_column_count"] == 2

    columns = {
        item["column_id"]: item for item in result.field_lineage.column_metrics
    }
    assert columns["c_dwd_const"]["classification"] == "literal"
    assert columns["c_dwd_const"]["is_parsed"] is True
    assert columns["c_dwd_const"]["has_physical_source"] is False
    assert columns["c_dwd_const"]["lineage_breakpoint"] is False

    assert columns["c_ads_bad"]["classification"] == "passthrough"
    assert columns["c_ads_bad"]["has_unknown_source"] is True
    assert columns["c_ads_bad"]["lineage_breakpoint"] is True

    assert columns["c_dwd_unparsed"]["classification"] == "unparsed"
    assert columns["c_dwd_unparsed"]["is_parsed"] is False
    assert columns["c_dwd_unparsed"]["lineage_breakpoint"] is True


def test_parse_diagnostics_are_unavailable_when_missing_and_counted_when_given():
    missing = analyze_basic_metrics(load_analysis_view(_task3_graph()))
    assert missing.parse_diagnostics["parse_failure_count"].status == (
        MetricStatus.UNAVAILABLE
    )
    assert missing.parse_diagnostics["parse_failure_count"].value is None

    diagnostics = {
        "total": 3,
        "success": 1,
        "partial": 1,
        "failed": 1,
        "warnings": ["synthetic warning", "synthetic warning 2"],
        "unsupported_syntax": {"lateral_view": 2},
    }
    result = analyze_basic_metrics(
        load_analysis_view(_task3_graph()),
        parse_diagnostics=diagnostics,
    )
    values = _values(result.parse_diagnostics)

    assert values["parse_total_count"] == 3
    assert values["parse_success_count"] == 1
    assert values["parse_partial_count"] == 1
    assert values["parse_failure_count"] == 1
    assert values["parse_success_rate"] == 0.33333333
    assert values["parse_warning_count"] == 2
    assert values["unsupported_syntax_distribution"]["lateral_view"] == 2


def test_basic_metrics_are_deterministic_and_do_not_mutate_input_graph():
    graph = _task3_graph()
    before = deepcopy(graph.to_dict())
    view = load_analysis_view(graph)
    view_before = view.to_dict()

    first = analyze_basic_metrics(view).to_dict()
    second = analyze_basic_metrics(view).to_dict()

    assert first == second
    assert graph.to_dict() == before
    assert view.to_dict() == view_before
