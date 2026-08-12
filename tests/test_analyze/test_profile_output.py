# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Profile dashboard artifact coverage."""

from __future__ import annotations

import json

from sqlgraph.analyze import AnalysisConfig, ResourceBudget, run_governance_analysis
from sqlgraph.analyze.profile import (
    DASHBOARD_VERSION,
    build_dashboard,
    write_profile_output,
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


def _profile_graph() -> PropertyGraph:
    graph = PropertyGraph()
    for table_id, schema, name in (
        ("t_ods", "synthetic_dw", "ods_events"),
        ("t_dwd", "synthetic_dw", "dwd_events"),
        ("t_ads", "synthetic_dw", "ads_report"),
    ):
        graph.add_node(TableNode(id=table_id, schema_name=schema, name=name))

    for table_id, columns in {
        "t_ods": ("event_id", "amount"),
        "t_dwd": ("event_id", "amount"),
        "t_ads": ("amount",),
    }.items():
        for column_name in columns:
            column_id = f"{table_id}_{column_name}"
            graph.add_node(ColumnNode(id=column_id, name=column_name, table_id=table_id))
            graph.add_edge(Edge(f"has_{column_id}", table_id, column_id, EdgeType.HAS_COLUMN))

    graph.add_node(
        SqlNode(
            id="sql_dwd",
            name="build_dwd",
            sql_content=(
                "insert overwrite table synthetic_dw.dwd_events "
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
                "insert overwrite table synthetic_dw.ads_report "
                "select sum(amount) as amount from synthetic_dw.dwd_events"
            ),
            dialect="spark",
        )
    )
    graph.add_node(
        TransformNode(
            id="tr_sum",
            name="sum_amount",
            expression="sum(amount)",
            expression_type=ExpressionType.AGG,
            fingerprint="fp_sum_amount",
            op="sum",
            output_name="amount",
        )
    )
    graph.add_edge(Edge("read_dwd_ods", "sql_dwd", "t_ods", EdgeType.READS_FROM))
    graph.add_edge(Edge("write_dwd", "sql_dwd", "t_dwd", EdgeType.WRITES_TO))
    graph.add_edge(Edge("read_ads_dwd", "sql_ads", "t_dwd", EdgeType.READS_FROM))
    graph.add_edge(Edge("write_ads", "sql_ads", "t_ads", EdgeType.WRITES_TO))
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
            "tr_sum",
            EdgeType.COMPUTE_DEPENDENCY,
        )
    )
    graph.add_edge(Edge("produces_ads_amount", "tr_sum", "t_ads_amount", EdgeType.PRODUCES))
    graph.add_edge(Edge("contains_sum", "sql_ads", "tr_sum", EdgeType.CONTAINS))
    return graph


def test_build_dashboard_contains_six_governance_sections():
    snapshot = run_governance_analysis(
        _profile_graph(),
        config=AnalysisConfig(
            metrics=(
                "basic",
                "sql_complexity",
                "topology",
                "impact",
                "communities",
                "consistency",
                "similarity",
                "motifs",
                "anomaly",
            ),
            resource_budget=ResourceBudget(max_nodes=1000, max_edges=1000),
        ),
    )

    dashboard = build_dashboard(snapshot, top_n=5)

    assert dashboard["version"] == DASHBOARD_VERSION
    assert {
        "overview",
        "layerHealth",
        "coreAssets",
        "domains",
        "riskAssets",
        "consistency",
    } <= set(dashboard)
    assert dashboard["overview"]["cards"]["sql_count"] == 2
    assert dashboard["overview"]["cards"]["table_count"] == 3
    assert dashboard["layerHealth"]["layerMatrix"]
    assert "topBlastScoreTables" in dashboard["coreAssets"]
    assert "communitySummary" in dashboard["domains"]
    assert "topSqlComplexity" in dashboard["riskAssets"]
    assert "similarityCandidates" in dashboard["consistency"]


def test_write_profile_output_writes_dashboard_json(tmp_path):
    snapshot = run_governance_analysis(
        _profile_graph(),
        config=AnalysisConfig(
            metrics=("basic", "topology", "impact"),
            resource_budget=ResourceBudget(max_nodes=1000, max_edges=1000),
        ),
        output_dir=tmp_path,
    )

    written = write_profile_output(snapshot, tmp_path, top_n=3)
    payload = json.loads((tmp_path / "dashboard.json").read_text(encoding="utf-8"))

    assert written["dashboard"].endswith("dashboard.json")
    assert payload["overview"]["cards"]["table_count"] == 3
    assert len(payload["coreAssets"]["topBlastScoreTables"]) <= 3
