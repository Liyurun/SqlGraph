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
