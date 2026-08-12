# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import copy
import json

import pytest

from sqlgraph.analyze import load_analysis_view
from sqlgraph.model import Edge, EdgeType, PropertyGraph, SqlNode, TableNode


def _graph():
    graph = PropertyGraph()
    graph.add_node(
        SqlNode(
            id="sql_1",
            name="synthetic_query",
            sql_content="SELECT id FROM synthetic.source",
        )
    )
    graph.add_node(
        TableNode(
            id="table_1",
            name="source",
            schema_name="synthetic",
            aliases=["src"],
        )
    )
    graph.add_edge(
        Edge(
            id="edge_1",
            source_id="sql_1",
            target_id="table_1",
            edge_type=EdgeType.READS_FROM,
            properties={"evidence": {"columns": ["id"]}},
        )
    )
    return graph


def test_property_graph_load_is_deeply_immutable_and_does_not_mutate_graph():
    graph = _graph()
    before = copy.deepcopy(graph.to_dict())

    view = load_analysis_view(graph)

    assert graph.to_dict() == before
    assert view.get_node("table_1")["aliases"] == ("src",)
    assert list(view.iter_nodes("table"))[0]["id"] == "table_1"
    assert list(view.iter_edges("reads_from"))[0]["id"] == "edge_1"

    with pytest.raises(TypeError):
        view.nodes_by_id["table_2"] = {}
    with pytest.raises(TypeError):
        view.get_node("table_1")["name"] = "changed"
    with pytest.raises(TypeError):
        view.edges[0]["evidence"]["columns"][0] = "changed"

    assert graph.to_dict() == before


def test_analysis_view_is_isolated_from_later_graph_mutation():
    graph = _graph()
    view = load_analysis_view(graph)

    graph.get_node("table_1").aliases.append("later")
    graph.edges[0].properties["evidence"]["columns"].append("later_column")

    assert view.get_node("table_1")["aliases"] == ("src",)
    assert view.edges[0]["evidence"]["columns"] == ("id",)


def test_loads_graph_json_without_rebuilding_graph(tmp_path):
    payload = _graph().to_dict()
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(payload), encoding="utf-8")

    view = load_analysis_view(graph_path)

    assert len(view.nodes) == 2
    assert len(view.edges) == 1
    assert view.get_node("sql_1")["sql_content"].startswith("SELECT")


def test_mapping_input_is_copied_before_freezing():
    payload = _graph().to_dict()
    view = load_analysis_view(payload)

    payload["nodes"][0]["name"] = "changed"
    payload["edges"][0]["evidence"]["columns"].append("changed")

    assert view.get_node("sql_1")["name"] == "synthetic_query"
    assert view.edges[0]["evidence"]["columns"] == ("id",)


def test_duplicate_edge_ids_are_normalized_without_mutating_input():
    payload = {
        "nodes": [
            {"id": "table_1", "node_type": "table", "name": "source"},
            {"id": "table_2", "node_type": "table", "name": "target"},
        ],
        "edges": [
            {
                "id": "edge_same",
                "source": "table_1",
                "target": "table_2",
                "type": "table_lineage",
            },
            {
                "id": "edge_same",
                "source": "table_1",
                "target": "table_2",
                "type": "table_lineage",
            },
        ],
    }

    view = load_analysis_view(payload)
    edge_ids = sorted(edge["id"] for edge in view.edges)

    assert edge_ids == ["edge_same", "edge_same__dup_1"]
    duplicate = next(edge for edge in view.edges if edge["id"] == "edge_same__dup_1")
    assert duplicate["original_id"] == "edge_same"
    assert payload["edges"][1]["id"] == "edge_same"
    assert "original_id" not in payload["edges"][1]


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"nodes": [], "edges": {}}, "list fields"),
        (
            {
                "nodes": [
                    {"id": "duplicate", "node_type": "table"},
                    {"id": "duplicate", "node_type": "table"},
                ],
                "edges": [],
            },
            "Duplicate node id",
        ),
        (
            {
                "nodes": [{"id": "table_1", "node_type": "table"}],
                "edges": [
                    {
                        "id": "edge_1",
                        "source": "missing",
                        "target": "table_1",
                        "type": "table_lineage",
                    }
                ],
            },
            "references missing node",
        ),
    ],
)
def test_rejects_invalid_graph_contract(payload, message):
    with pytest.raises(ValueError, match=message):
        load_analysis_view(payload)


def test_rejects_invalid_json(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid graph JSON"):
        load_analysis_view(path)
