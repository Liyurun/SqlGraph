# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Synthetic-data tests for Task 11 pipeline, cache, and output artifacts."""

from __future__ import annotations

from copy import deepcopy
import json

from sqlgraph.analyze import (
    AnalysisConfig,
    MetricStatus,
    run_governance_analysis,
    stable_json_dumps,
)
import sqlgraph.analyze.pipeline as pipeline_module
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


def _pipeline_graph() -> PropertyGraph:
    graph = PropertyGraph()
    for table_id, name in (
        ("t_ods", "ods_events"),
        ("t_dwd", "dwd_events"),
        ("t_ads", "ads_report"),
    ):
        graph.add_node(
            TableNode(id=table_id, name=name, schema_name="synthetic_dw")
        )

    for table_id, columns in {
        "t_ods": (("event_id", "bigint"), ("amount", "double")),
        "t_dwd": (("event_id", "bigint"), ("amount", "double")),
        "t_ads": (("amount", "double"),),
    }.items():
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

    graph.add_node(
        SqlNode(
            id="sql_dwd",
            name="build_dwd",
            sql_content=(
                "select event_id, amount from synthetic_dw.ods_events"
            ),
            dialect="spark",
        )
    )
    graph.add_node(
        SqlNode(
            id="sql_ads",
            name="build_ads",
            sql_content=(
                "select sum(amount) as amount from synthetic_dw.dwd_events"
            ),
            dialect="spark",
        )
    )
    graph.add_node(
        TransformNode(
            id="tr_sum_amount",
            name="sum_amount",
            expression="sum(amount)",
            expression_type=ExpressionType.AGG,
            fingerprint="fp_sum_amount",
            op="sum",
            output_name="amount",
        )
    )

    for edge_id, sql_id, source_id in (
        ("read_dwd_ods", "sql_dwd", "t_ods"),
        ("read_ads_dwd", "sql_ads", "t_dwd"),
    ):
        graph.add_edge(
            Edge(edge_id, sql_id, source_id, EdgeType.READS_FROM)
        )
    for edge_id, sql_id, target_id in (
        ("write_dwd", "sql_dwd", "t_dwd"),
        ("write_ads", "sql_ads", "t_ads"),
    ):
        graph.add_edge(
            Edge(edge_id, sql_id, target_id, EdgeType.WRITES_TO)
        )
    graph.add_edge(Edge("lineage_ods_dwd", "t_ods", "t_dwd", EdgeType.TABLE_LINEAGE))
    graph.add_edge(Edge("lineage_dwd_ads", "t_dwd", "t_ads", EdgeType.TABLE_LINEAGE))
    graph.add_edge(
        Edge(
            "dep_ods_event_dwd_event",
            "t_ods_event_id",
            "t_dwd_event_id",
            EdgeType.COMPUTE_DEPENDENCY,
        )
    )
    graph.add_edge(
        Edge(
            "dep_ods_amount_dwd_amount",
            "t_ods_amount",
            "t_dwd_amount",
            EdgeType.COMPUTE_DEPENDENCY,
        )
    )
    graph.add_edge(
        Edge(
            "dep_dwd_amount_transform",
            "t_dwd_amount",
            "tr_sum_amount",
            EdgeType.COMPUTE_DEPENDENCY,
        )
    )
    graph.add_edge(
        Edge(
            "produces_ads_amount",
            "tr_sum_amount",
            "t_ads_amount",
            EdgeType.PRODUCES,
        )
    )
    graph.add_edge(
        Edge("contains_sum", "sql_ads", "tr_sum_amount", EdgeType.CONTAINS)
    )
    return graph


def _write_schema(path):
    path.write_text(
        "\n".join(
            [
                "table_name,column_name,data_type",
                "synthetic_dw.ods_events,event_id,bigint",
                "synthetic_dw.ods_events,amount,double",
                "synthetic_dw.dwd_events,event_id,bigint",
                "synthetic_dw.dwd_events,amount,double",
                "synthetic_dw.ads_report,amount,double",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_pipeline_runs_metrics_writes_outputs_and_preserves_graph(tmp_path):
    graph = _pipeline_graph()
    before = deepcopy(graph.to_dict())
    output_dir = tmp_path / "governance_output"
    schema_path = _write_schema(tmp_path / "schema.csv")
    parse_diagnostics = [
        {"sql_id": "sql_dwd", "status": "success"},
        {"sql_id": "sql_ads", "status": "success", "warnings": ["synthetic"]},
    ]
    config = AnalysisConfig(float_precision=4)

    snapshot = run_governance_analysis(
        graph,
        config=config,
        external_schema=schema_path,
        parse_diagnostics=parse_diagnostics,
        output_dir=output_dir,
    )

    assert graph.to_dict() == before
    assert snapshot.manifest.metric_statuses["basic"] in {
        MetricStatus.SUCCESS,
        MetricStatus.DEGRADED,
    }
    assert snapshot.manifest.metric_statuses["sql_complexity"] == MetricStatus.SUCCESS
    assert snapshot.summary["inventory"]["asset_coverage"]["external_table_count"] == 3
    assert [item["table_id"] for item in snapshot.table_metrics] == [
        "t_ads",
        "t_dwd",
        "t_ods",
    ]
    assert snapshot.sql_metrics[0]["sql_id"] == "sql_ads"

    expected_files = {
        "manifest.json",
        "summary.json",
        "table_metrics.jsonl",
        "column_metrics.jsonl",
        "sql_metrics.jsonl",
        "transform_metrics.jsonl",
        "layer_matrix.json",
        "community_matrix.json",
        "violations.jsonl",
        "consistency_groups.jsonl",
        "similarity_candidates.jsonl",
        "motifs.jsonl",
        "anomaly_metrics.jsonl",
        "table_metrics.csv",
        "column_metrics.csv",
        "sql_metrics.csv",
        "transform_metrics.csv",
    }
    assert expected_files <= {path.name for path in output_dir.iterdir()}
    assert "select event_id" not in (output_dir / "manifest.json").read_text(
        encoding="utf-8"
    )
    assert "sql_content" not in (output_dir / "sql_metrics.jsonl").read_text(
        encoding="utf-8"
    )
    assert stable_json_dumps({"ratio": 1 / 3}, precision=4) == (
        '{"ratio":0.3333}'
    )


def test_cache_hits_and_invalidates_on_config_change(tmp_path):
    graph = _pipeline_graph()
    cache_dir = tmp_path / "cache"
    config = AnalysisConfig(metrics=("basic", "topology"))

    first = run_governance_analysis(graph, config=config, cache_dir=cache_dir)
    second = run_governance_analysis(graph, config=config, cache_dir=cache_dir)
    changed = run_governance_analysis(
        graph,
        config=AnalysisConfig(metrics=("basic", "topology"), random_seed=99),
        cache_dir=cache_dir,
    )

    assert first.manifest.metadata["cache"]["metrics"]["governance_snapshot"] == "miss"
    assert first.manifest.metadata["cache"]["projections"]["table_graph"] == "miss"
    assert second.manifest.metadata["cache"]["metrics"]["governance_snapshot"] == "hit"
    assert changed.manifest.metadata["cache"]["metrics"]["governance_snapshot"] == "miss"
    assert (
        changed.manifest.metadata["cache"]["context_key"]
        != first.manifest.metadata["cache"]["context_key"]
    )


def test_noncritical_metric_failure_is_recorded_and_pipeline_continues(
    monkeypatch,
    tmp_path,
):
    graph = _pipeline_graph()

    def fail_similarity(*args, **kwargs):
        assert args or kwargs
        raise RuntimeError("synthetic backend failure with no SQL text")

    monkeypatch.setattr(pipeline_module, "analyze_similarity", fail_similarity)
    snapshot = run_governance_analysis(
        graph,
        config=AnalysisConfig(metrics=("basic", "topology", "similarity", "motifs")),
        output_dir=tmp_path / "out",
    )

    assert "similarity" in snapshot.manifest.failed_metrics
    assert snapshot.manifest.metric_statuses["similarity"] == MetricStatus.FAILED
    assert snapshot.manifest.metric_statuses["motifs"] in {
        MetricStatus.SUCCESS,
        MetricStatus.DEGRADED,
    }
    manifest_payload = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert manifest_payload["metric_statuses"]["similarity"] == "failed"
    assert "synthetic_dw.dwd_events" not in json.dumps(manifest_payload)
