import os

from sqlgraph.api import build_graph
from sqlgraph.serve.index_io import build_index, load_raw_index
from sqlgraph.serve.graph_index import GraphIndex


def _index(tmp_path, sql):
    graph = build_graph(sql, dialect="spark")
    index_dir = os.path.join(tmp_path, "idx")
    build_index(graph, index_dir, source_meta={"path": "inline", "size": 0, "mtime": 0, "sha1_16": ""})
    return GraphIndex.from_raw(load_raw_index(index_dir))


def _table_id(index, full_name):
    for nid, node in index.nodes.items():
        if node.get("node_type") == "table" and node.get("full_name") == full_name:
            return nid
    raise AssertionError(f"table {full_name} not found")


def test_meta_reports_counts(tmp_path):
    index = _index(tmp_path, "INSERT OVERWRITE TABLE dst SELECT id FROM src")
    meta = index.meta()
    assert meta["stats"]["nodes"] > 0
    assert meta["stats"]["edges"] > 0


def test_adjacency_and_full_name(tmp_path):
    index = _index(tmp_path, "INSERT OVERWRITE TABLE dst SELECT id FROM src")
    src_id = _table_id(index, "src")
    adj = index.adjacency[src_id]
    assert set(adj.keys()) == {"in", "out"}
    assert all(isinstance(x, str) for x in adj["out"])
    # full_name is derived once and stored on the cached node dict
    assert index.nodes[src_id]["full_name"] == "src"
