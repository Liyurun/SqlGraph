from __future__ import annotations

from sqlgraph.api import build_graph
from sqlgraph.model import EdgeType


def _all_ids(graph):
    return sorted([node.id for node in graph.nodes] + [edge.id for edge in graph.edges])


def _table_pairs(graph):
    names = {node.id: node.name for node in graph.nodes}
    return {
        (names[edge.source_id], names[edge.target_id])
        for edge in graph.edges
        if edge.edge_type == EdgeType.TABLE_LINEAGE
    }


def test_two_builds_have_identical_full_ids():
    sql = "INSERT INTO d SELECT a + b AS c FROM s"

    assert _all_ids(build_graph(sql, dialect="spark")) == _all_ids(
        build_graph(sql, dialect="spark")
    )


def test_independent_statements_do_not_cross_link():
    graph = build_graph(
        "INSERT INTO d1 SELECT * FROM s1; INSERT INTO d2 SELECT * FROM s2;",
        dialect="spark",
    )

    assert _table_pairs(graph) == {("s1", "d1"), ("s2", "d2")}


def test_previous_target_can_be_next_statement_source():
    graph = build_graph(
        "INSERT INTO mid SELECT id FROM src; "
        "INSERT INTO dst SELECT id FROM mid;",
        dialect="spark",
    )

    assert _table_pairs(graph) == {("src", "mid"), ("mid", "dst")}


def test_self_read_keeps_read_and_write_ownership():
    graph = build_graph(
        "INSERT INTO snapshot SELECT id FROM snapshot",
        dialect="spark",
    )
    table_id = graph.get_node_by_name("snapshot").id
    edge_types = {
        edge.edge_type
        for edge in graph.edges
        if edge.target_id == table_id
    }

    assert EdgeType.READS_FROM in edge_types
    assert EdgeType.WRITES_TO in edge_types


def test_table_lineage_keeps_statement_provenance():
    graph = build_graph(
        "INSERT INTO d1 SELECT * FROM s1; INSERT INTO d2 SELECT * FROM s2;",
        dialect="spark",
    )

    edges = graph.get_edges_by_type(EdgeType.TABLE_LINEAGE)
    assert edges
    for edge in edges:
        assert edge.properties["provenance"]
        assert {"sql_id", "stmt_index"} <= edge.properties["provenance"][0].keys()


def test_graph_contains_reproducible_environment_and_coverage():
    graph = build_graph("INSERT INTO d SELECT a FROM s", dialect="spark")

    assert graph.metadata["environment"]["identity_rule_version"]
    assert graph.metadata["environment"]["dialect"] == "spark"
    assert graph.metadata["coverage"]["ok"] == 1
