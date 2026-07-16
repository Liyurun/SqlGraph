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


def test_search_matches_table_and_column(tmp_path):
    index = _index(tmp_path, "INSERT OVERWRITE TABLE dst SELECT id FROM src")
    tables = index.search("dst", entity_type="table", limit=10)
    assert any(hit["type"] == "table" and hit["name"] == "dst" for hit in tables)
    cols = index.search("id", entity_type="column", limit=10)
    assert any(hit["type"] == "column" and hit["name"] == "id" for hit in cols)
    # SQL raw text is NOT searchable in v1
    assert index.search("select", entity_type="all", limit=10) == [] or all(
        hit["type"] in ("table", "column") for hit in index.search("select", entity_type="all", limit=10)
    )


def test_subgraph_depth_and_direction(tmp_path):
    index = _index(
        tmp_path,
        "INSERT OVERWRITE TABLE mid SELECT id FROM src;\n"
        "INSERT OVERWRITE TABLE dst SELECT id FROM mid",
    )
    mid_id = _table_id(index, "mid")
    both = index.subgraph(mid_id, depth=1, direction="both")
    node_ids = {n["id"] for n in both["nodes"]}
    assert mid_id in node_ids
    assert len(both["edges"]) >= 1
    # depth 1 from mid should not reach 2-hop-only nodes on a single side
    up_only = index.subgraph(mid_id, depth=1, direction="up")
    down_only = index.subgraph(mid_id, depth=1, direction="down")
    assert {n["id"] for n in up_only["nodes"]} != {n["id"] for n in down_only["nodes"]}


def test_node_detail_has_read_write_sql_groups(tmp_path):
    index = _index(tmp_path, "INSERT OVERWRITE TABLE dst SELECT id FROM src")
    dst_id = _table_id(index, "dst")
    detail = index.node_detail(dst_id)
    assert detail["node"]["id"] == dst_id
    assert any(item["sqlId"] for item in detail["writeSqls"])
    assert isinstance(detail["readSqls"], list)


def test_node_detail_missing_returns_none(tmp_path):
    index = _index(tmp_path, "INSERT OVERWRITE TABLE dst SELECT id FROM src")
    assert index.node_detail("no_such_id") is None
