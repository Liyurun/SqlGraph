import json
import os

from sqlgraph.api import build_graph
from sqlgraph.serve.index_io import build_index


def _graph():
    sql = "INSERT OVERWRITE TABLE dst SELECT id, name FROM src"
    return build_graph(sql, dialect="spark")


def test_build_index_writes_jsonl_and_manifest(tmp_path):
    graph = _graph()
    index_dir = os.path.join(tmp_path, "idx")
    build_index(graph, index_dir, source_meta={"path": "inline", "size": 0, "mtime": 0, "sha1_16": "x"})

    for fname in ("manifest.json", "nodes.jsonl", "edges.jsonl", "sql.jsonl"):
        assert os.path.isfile(os.path.join(index_dir, fname))

    with open(os.path.join(index_dir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["version"] == 1
    assert manifest["stats"]["nodes"] > 0
    assert manifest["source"]["sha1_16"] == "x"

    with open(os.path.join(index_dir, "nodes.jsonl"), encoding="utf-8") as f:
        first = json.loads(f.readline())
    assert "id" in first and "node_type" in first


from sqlgraph.serve.index_io import is_cache_valid, load_raw_index


def test_cache_valid_only_when_source_meta_matches(tmp_path):
    graph = _graph()
    index_dir = os.path.join(tmp_path, "idx2")
    meta = {"path": "df.csv", "size": 100, "mtime": 5, "sha1_16": "aaaa"}
    build_index(graph, index_dir, source_meta=meta)

    assert is_cache_valid(index_dir, meta) is True
    changed = dict(meta, size=200)
    assert is_cache_valid(index_dir, changed) is False
    assert is_cache_valid(os.path.join(tmp_path, "missing"), meta) is False


def test_load_raw_index_returns_nodes_edges_sql(tmp_path):
    graph = _graph()
    index_dir = os.path.join(tmp_path, "idx3")
    build_index(graph, index_dir, source_meta={"path": "inline", "size": 0, "mtime": 0, "sha1_16": ""})

    raw = load_raw_index(index_dir)
    assert len(raw["nodes"]) > 0
    assert len(raw["edges"]) > 0
    assert isinstance(raw["sql"], list)
    assert raw["manifest"]["version"] == 1


from sqlgraph.serve.index_io import prepare_index


def test_prepare_index_builds_then_reuses(tmp_path):
    sql_file = os.path.join(tmp_path, "q.sql")
    with open(sql_file, "w", encoding="utf-8") as f:
        f.write("INSERT OVERWRITE TABLE dst SELECT id FROM src")
    base = os.path.join(tmp_path, "index_base")

    logs1: list[str] = []
    dir1 = prepare_index(sql_file, base, dialect="spark", rebuild=False, log=logs1.append)
    assert os.path.isfile(os.path.join(dir1, "manifest.json"))
    assert any("rebuilding" in m or "building" in m for m in logs1)

    logs2: list[str] = []
    dir2 = prepare_index(sql_file, base, dialect="spark", rebuild=False, log=logs2.append)
    assert dir2 == dir1
    assert any("cache hit" in m for m in logs2)

    logs3: list[str] = []
    prepare_index(sql_file, base, dialect="spark", rebuild=True, log=logs3.append)
    assert any("rebuild" in m for m in logs3)
