# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import copy

from sqlgraph.analyze import (
    AnalysisConfig,
    MetricStatus,
    analyze_sql_complexity,
    load_analysis_view,
)


def _graph_payload(sql_content, dialect="spark"):
    nodes = [
        {
            "id": "sql_b",
            "name": "synthetic_complex_query",
            "node_type": "sql",
            "sql_content": sql_content,
            "dialect": dialect,
        },
        {"id": "sql_a", "name": "missing_query", "node_type": "sql"},
        {"id": "table_raw", "name": "raw", "node_type": "table"},
        {"id": "table_dim", "name": "dim", "node_type": "table"},
        {"id": "table_out", "name": "out", "node_type": "table"},
        {
            "id": "column_out_1",
            "name": "id",
            "node_type": "column",
            "table_id": "table_out",
        },
        {
            "id": "column_out_2",
            "name": "metric",
            "node_type": "column",
            "table_id": "table_out",
        },
        {
            "id": "column_out_3",
            "name": "code",
            "node_type": "column",
            "table_id": "table_out",
        },
        {
            "id": "transform_1",
            "name": "metric expression",
            "node_type": "transform",
        },
        {
            "id": "transform_2",
            "name": "code expression",
            "node_type": "transform",
        },
    ]
    edge_specs = [
        ("sql_b", "table_raw", "reads_from"),
        ("sql_b", "table_dim", "reads_from"),
        ("sql_b", "table_out", "writes_to"),
        ("table_out", "column_out_1", "has_column"),
        ("table_out", "column_out_2", "has_column"),
        ("table_out", "column_out_3", "has_column"),
        ("sql_b", "transform_1", "contains"),
        ("sql_b", "transform_2", "contains"),
    ]
    edges = [
        {
            "id": f"edge_{index}",
            "source": source,
            "target": target,
            "type": edge_type,
        }
        for index, (source, target, edge_type) in enumerate(edge_specs)
    ]
    return {"nodes": nodes, "edges": edges}


def _values(result):
    return {
        name: metric.value
        for name, metric in result.features.items()
        if metric.status == MetricStatus.SUCCESS
    }


def test_counts_ast_and_graph_features_and_calculates_versioned_score():
    sql = """
    WITH base AS (
        SELECT id, payload, amount FROM synthetic.raw_events
    )
    SELECT
        b.id,
        SUM(b.amount) OVER (PARTITION BY b.id) AS rolling_amount,
        get_json_object(b.payload, '$.code') AS code
    FROM base b
    JOIN synthetic.dim_users d ON b.id = d.id
    UNION ALL
    SELECT id, amount, from_json(payload, 'string')
    FROM synthetic.backup_events
    """
    view = load_analysis_view(_graph_payload(sql))

    result = analyze_sql_complexity(view)[1]
    values = _values(result)

    assert result.sql_id == "sql_b"
    assert result.status == MetricStatus.SUCCESS
    assert values == {
        "read_table_count": 2,
        "output_column_count": 3,
        "transform_count": 2,
        "join_count": 1,
        "cte_count": 1,
        "union_count": 1,
        "window_count": 1,
        "aggregate_count": 1,
        "json_extract_count": 2,
        "select_star_count": 0,
    }
    assert result.complexity_score.status == MetricStatus.SUCCESS
    assert result.complexity_score.value == 13.6
    assert result.complexity_score.version == "1.0"
    assert result.complexity_score.parameters["weights"]["select_star_count"] == 5.0


def test_select_star_does_not_count_count_star():
    payload = _graph_payload(
        "SELECT *, synthetic.source.*, COUNT(*) AS row_count "
        "FROM synthetic.source"
    )
    result = analyze_sql_complexity(load_analysis_view(payload))[1]

    assert result.features["select_star_count"].value == 2
    assert result.features["aggregate_count"].value == 1


def test_missing_sql_content_is_degraded_without_false_zero_ast_values():
    result = analyze_sql_complexity(
        load_analysis_view(_graph_payload("SELECT id FROM synthetic.source"))
    )[0]

    assert result.sql_id == "sql_a"
    assert result.status == MetricStatus.DEGRADED
    assert result.features["read_table_count"].status == MetricStatus.SUCCESS
    assert result.features["read_table_count"].value == 0
    assert result.features["join_count"].status == MetricStatus.UNAVAILABLE
    assert result.features["join_count"].value is None
    assert result.complexity_score.status == MetricStatus.UNAVAILABLE
    assert result.complexity_score.value is None


def test_parse_failure_is_degraded_and_does_not_expose_sql_text():
    result = analyze_sql_complexity(
        load_analysis_view(_graph_payload("SELECT 'unterminated", dialect="spark"))
    )[1]
    payload = result.to_dict()

    assert result.status == MetricStatus.DEGRADED
    assert result.features["union_count"].status == MetricStatus.UNAVAILABLE
    assert result.complexity_score.status == MetricStatus.UNAVAILABLE
    assert "unterminated" not in result.reason
    assert "sql_content" not in payload


def test_results_are_stably_sorted_and_input_view_is_unchanged():
    source = _graph_payload("SELECT id FROM synthetic.source")
    before = copy.deepcopy(source)
    view = load_analysis_view(source)
    view_before = view.to_dict()

    results = analyze_sql_complexity(
        view,
        AnalysisConfig(
            algorithm_versions=(
                ("analysis", "1.0"),
                ("complexity_score", "2.3"),
            )
        ),
    )

    assert [result.sql_id for result in results] == ["sql_a", "sql_b"]
    assert results[1].complexity_score.version == "2.3"
    assert source == before
    assert view.to_dict() == view_before
