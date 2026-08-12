# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from sqlgraph.analyze import (
    AnalysisConfig,
    AnalysisManifest,
    GovernanceSnapshot,
    MetricResult,
    MetricStatus,
    ResourceBudget,
    load_analysis_view,
)
from sqlgraph.model import Edge, EdgeType, PropertyGraph, SqlNode, TableNode


def _synthetic_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node(
        SqlNode(
            id="sql_build_report",
            name="build_report",
            sql_content="SELECT * FROM demo.source_table",
            dialect="spark",
        )
    )
    graph.add_node(
        TableNode(
            id="tbl_source",
            name="source_table",
            schema_name="demo",
            aliases=["src"],
        )
    )
    graph.add_node(
        TableNode(
            id="tbl_report",
            name="report_table",
            schema_name="demo",
        )
    )
    graph.add_edge(
        Edge(
            id="edge_read",
            source_id="sql_build_report",
            target_id="tbl_source",
            edge_type=EdgeType.READS_FROM,
            properties={"evidence": {"columns": ["record_id"]}},
        )
    )
    graph.add_edge(
        Edge(
            id="edge_write",
            source_id="sql_build_report",
            target_id="tbl_report",
            edge_type=EdgeType.WRITES_TO,
        )
    )
    return graph


def test_config_is_deterministic_and_validates_resource_budget():
    first = AnalysisConfig()
    second = AnalysisConfig()
    changed = AnalysisConfig(random_seed=7)

    assert first.fingerprint() == second.fingerprint()
    assert first.fingerprint() != changed.fingerprint()
    assert first.to_dict()["resource_budget"]["max_nodes"] == 100_000

    with pytest.raises(ValueError, match="max_nodes"):
        ResourceBudget(max_nodes=0)
    with pytest.raises(ValueError, match="float_precision"):
        AnalysisConfig(float_precision=17)


def test_property_graph_load_is_deeply_read_only_and_does_not_mutate_input():
    graph = _synthetic_graph()
    before = deepcopy(graph.to_dict())

    view = load_analysis_view(graph)

    assert graph.to_dict() == before
    assert view.input_kind == "property_graph"
    assert view.node_by_id["tbl_source"]["name"] == "source_table"
    assert view.to_dict()["nodes"] == sorted(before["nodes"], key=lambda n: n["id"])

    with pytest.raises(TypeError):
        view.node_by_id["tbl_source"]["name"] = "changed"
    with pytest.raises(TypeError):
        view.node_by_id["tbl_source"]["aliases"][0] = "changed"
    read_edge = next(edge for edge in view.edges if edge["id"] == "edge_read")
    with pytest.raises(TypeError):
        read_edge["evidence"]["columns"][0] = "changed"

    mutable_copy = view.to_dict()
    mutable_copy["nodes"][0]["name"] = "changed"
    assert graph.to_dict() == before
    assert view.node_by_id["sql_build_report"]["name"] == "build_report"


def test_graph_json_and_property_graph_have_same_fingerprint(tmp_path):
    graph = _synthetic_graph()
    json_path = tmp_path / "graph.json"
    json_path.write_text(
        json.dumps(graph.to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )

    memory_view = load_analysis_view(graph)
    json_view = load_analysis_view(json_path)

    assert json_view.input_kind == "graph_json"
    assert json_view.source_path == str(json_path.resolve())
    assert json_view.graph_fingerprint == memory_view.graph_fingerprint
    assert json_view.to_dict() == memory_view.to_dict()


def test_loader_rejects_invalid_graph_contract(tmp_path):
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(
        json.dumps(
            {
                "nodes": [{"id": "tbl_a", "node_type": "table"}],
                "edges": [
                    {
                        "id": "edge_missing",
                        "source": "tbl_a",
                        "target": "tbl_missing",
                        "type": "table_lineage",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing from the input"):
        load_analysis_view(invalid_path)


def test_manifest_snapshot_and_metric_status_are_serializable():
    config = AnalysisConfig(random_seed=9, float_precision=6)
    view = load_analysis_view(_synthetic_graph())
    metric = MetricResult(
        name="parse_failure_count",
        status=MetricStatus.UNAVAILABLE,
        reason="parse diagnostics were not provided",
    )
    manifest = AnalysisManifest(
        graph_fingerprint=view.graph_fingerprint,
        config_fingerprint=config.fingerprint(),
        random_seed=config.random_seed,
        float_precision=config.float_precision,
        skipped_metrics=("parse_failure_count",),
        metadata={"resource_budget": config.resource_budget.__dict__},
    )
    snapshot = GovernanceSnapshot(
        manifest=manifest,
        summary={"lineage_table_count": 2},
        metrics=(metric,),
    )

    payload = snapshot.to_dict()
    assert payload["manifest"]["schema_version"] == "1.0"
    assert payload["manifest"]["random_seed"] == 9
    assert payload["metrics"][0]["status"] == "unavailable"
    assert payload["metrics"][0]["value"] is None
