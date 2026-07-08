import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from sqlgraph.model.graph import PropertyGraph
from sqlgraph.model.nodes import SqlNode, TableNode, ColumnNode, TransformNode, ExpressionType
from sqlgraph.model.edges import Edge, EdgeType

def _make_sample_graph():
    g = PropertyGraph()
    g.add_node(SqlNode(id="s1", name="sql1"))
    g.add_node(TableNode(id="t1", name="src_table"))
    g.add_node(TableNode(id="t2", name="dst_table"))
    g.add_node(ColumnNode(id="c1", name="id", table_id="t1"))
    g.add_node(ColumnNode(id="c2", name="id", table_id="t2"))
    g.add_node(TransformNode(id="tr1", expression="id", expression_type=ExpressionType.COLUMN_REF))
    g.add_edge(Edge("e1", "s1", "t1", EdgeType.READS_FROM))
    g.add_edge(Edge("e2", "s1", "t2", EdgeType.WRITES_TO))
    g.add_edge(Edge("e3", "t1", "c1", EdgeType.HAS_COLUMN))
    g.add_edge(Edge("e4", "t2", "c2", EdgeType.HAS_COLUMN))
    g.add_edge(Edge("e5", "s1", "tr1", EdgeType.CONTAINS))
    g.add_edge(Edge("e6", "c1", "tr1", EdgeType.COMPUTE_DEPENDENCY))
    g.add_edge(Edge("e7", "tr1", "c2", EdgeType.PRODUCES))
    g.add_edge(Edge("e8", "t1", "t2", EdgeType.TABLE_LINEAGE))
    return g

def test_add_node_and_edge():
    g = PropertyGraph()
    g.add_node(SqlNode(id="s1", name="test_sql"))
    g.add_node(TableNode(id="t1", name="test_table"))
    g.add_edge(Edge("e1", "s1", "t1", EdgeType.WRITES_TO))
    assert len(g.nodes) == 2
    assert len(g.edges) == 1

def test_stats():
    g = _make_sample_graph()
    stats = g.stats()
    assert stats["sql_count"] == 1
    assert stats["table_count"] == 2
    assert stats["column_count"] == 2
    assert stats["transform_count"] == 1

def test_get_upstream_tables():
    g = _make_sample_graph()
    upstream = g.get_upstream("dst_table")
    assert "src_table" in upstream

def test_duplicate_node_raises():
    g = PropertyGraph()
    g.add_node(SqlNode(id="s1", name="s1"))
    import pytest
    with pytest.raises(ValueError):
        g.add_node(SqlNode(id="s1", name="s1_dup"))

def test_to_dict():
    g = _make_sample_graph()
    d = g.to_dict()
    assert "nodes" in d
    assert "edges" in d
    assert len(d["nodes"]) == 6
    assert len(d["edges"]) == 8
