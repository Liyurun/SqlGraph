from __future__ import annotations

from sqlgraph.api import build_graph
from sqlgraph.model import EdgeType, NodeType


def test_expression_operands_are_explicit_graph_edges():
    graph = build_graph(
        "INSERT INTO d SELECT a + b * c AS result FROM s",
        dialect="spark",
    )

    transforms = {
        node.id: node
        for node in graph.get_nodes_by_type(NodeType.TRANSFORM)
    }
    operand_edges = graph.get_edges_by_type(EdgeType.EXPR_OPERAND)

    assert operand_edges
    assert any(
        transforms[edge.source_id].op == "mul"
        and transforms[edge.target_id].op == "add"
        for edge in operand_edges
    )
