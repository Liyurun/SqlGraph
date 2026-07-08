import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from sqlgraph.model.edges import Edge, EdgeType

def test_edge_creation():
    edge = Edge(id="e1", source_id="sql_001", target_id="tbl_001", edge_type=EdgeType.WRITES_TO)
    assert edge.source_id == "sql_001"
    assert edge.target_id == "tbl_001"

def test_edge_to_dict():
    edge = Edge(id="e2", source_id="tbl_001", target_id="sql_001", edge_type=EdgeType.READS_FROM)
    d = edge.to_dict()
    assert d["source"] == "tbl_001"
    assert d["type"] == "reads_from"

def test_edge_with_properties():
    edge = Edge(id="e3", source_id="col_001", target_id="tr_001",
                edge_type=EdgeType.COMPUTE_DEPENDENCY, properties={"position": 0})
    assert edge.properties["position"] == 0
