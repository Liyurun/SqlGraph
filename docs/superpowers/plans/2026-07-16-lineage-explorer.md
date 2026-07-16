# Lineage Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight local `sqlgraph serve` mode that builds a JSONL index from SQL/df.csv, loads it fully into memory, and serves search / viewer / playground pages so large lineage graphs no longer bloat a single HTML file.

**Architecture:** After the existing `build_graph → PropertyGraph` pipeline, serialize the graph to JSONL (`nodes/edges/sql` + `manifest`), then load it into an in-memory `GraphIndex` (nodes dict, edges list, adjacency, sql_by_id, per-table read/write SQL groups, table/column name index). A `ThreadingHTTPServer` serves Jinja-rendered HTML pages plus `/api/*` JSON endpoints that read only from the in-memory index.

**Tech Stack:** Python stdlib `http.server.ThreadingHTTPServer`, Jinja2, native HTML/CSS/JS, Cytoscape.js. No Node build. Reuses `sqlgraph.api.build_graph`, `sqlgraph.input.sql_source.SqlSource`, `sqlgraph.playground.graph_to_playground_payload`, `sqlgraph.playground.find_free_port`.

**Reference spec:** `docs/superpowers/specs/2026-07-16-lineage-explorer-design.md`

---

## File Structure

New package `sqlgraph/serve/`:

- `sqlgraph/serve/__init__.py` — exports `serve_explorer`, `GraphIndex`, `build_index`, `load_index`.
- `sqlgraph/serve/index_io.py` — `build_index(graph, index_dir, source_meta, log)`, `load_index(index_dir)`, `is_cache_valid(index_dir, source_meta)`, `source_fingerprint(path)`. JSONL + manifest read/write.
- `sqlgraph/serve/graph_index.py` — `GraphIndex` in-memory model: adjacency, subgraph BFS, node detail with read/write SQL groups, table/column search.
- `sqlgraph/serve/server.py` — `serve_explorer(...)`, `ExplorerHandler` (routes + `/api/*`), `_render_page`.
- `sqlgraph/serve/web/shell.html.j2`, `search.html.j2`, `viewer.html.j2`, `playground.html.j2`
- `sqlgraph/serve/web/static/app.css`, `graph.js`, `detail.js`

Modified:

- `sqlgraph/cli.py` — add `serve` command (lazy import of `serve_explorer`).

Tests:

- `tests/test_serve/__init__.py`
- `tests/test_serve/test_index_io.py`
- `tests/test_serve/test_graph_index.py`
- `tests/test_serve/test_server_api.py`

---

## Task 1: Index serialization (PropertyGraph → JSONL)

**Files:**
- Create: `sqlgraph/serve/__init__.py`
- Create: `sqlgraph/serve/index_io.py`
- Test: `tests/test_serve/__init__.py`, `tests/test_serve/test_index_io.py`

- [ ] **Step 1: Create empty package files**

Create `sqlgraph/serve/__init__.py`:

```python
"""SqlGraph Lineage Explorer: JSONL index + local serve mode."""
```

Create `tests/test_serve/__init__.py`:

```python
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_serve/test_index_io.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_serve/test_index_io.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sqlgraph.serve.index_io'`

- [ ] **Step 4: Implement `build_index` and fingerprint helpers**

Create `sqlgraph/serve/index_io.py`:

```python
"""JSONL index serialization and cache metadata for the Lineage Explorer."""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Callable, Optional

INDEX_VERSION = 1


def source_fingerprint(path: str) -> dict[str, Any]:
    """Build a cheap fingerprint of an input file for cache reuse decisions."""
    if not path or not os.path.isfile(path):
        return {"path": path or "inline", "size": 0, "mtime": 0, "sha1_16": ""}
    stat = os.stat(path)
    h = hashlib.sha1()
    with open(path, "rb") as f:
        h.update(f.read(1024 * 1024))  # first 1 MB is enough to detect edits cheaply
    return {
        "path": os.path.abspath(path),
        "size": stat.st_size,
        "mtime": int(stat.st_mtime),
        "sha1_16": h.hexdigest()[:16],
    }


def index_dir_for(base_dir: str, source_meta: dict[str, Any]) -> str:
    """Deterministic per-input subdirectory under the index base dir."""
    key = f"{source_meta.get('path')}|{source_meta.get('size')}|{source_meta.get('sha1_16')}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return os.path.join(base_dir, digest)


def build_index(
    graph,
    index_dir: str,
    source_meta: dict[str, Any],
    log: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Serialize a PropertyGraph into nodes/edges/sql JSONL + manifest.json."""
    log = log or (lambda _msg: None)
    os.makedirs(index_dir, exist_ok=True)

    node_count = 0
    sql_count = 0
    with open(os.path.join(index_dir, "nodes.jsonl"), "w", encoding="utf-8") as nf, \
         open(os.path.join(index_dir, "sql.jsonl"), "w", encoding="utf-8") as sf:
        for node in graph.nodes:
            nd = node.to_dict()
            nf.write(json.dumps(nd, ensure_ascii=False) + "\n")
            node_count += 1
            if nd.get("node_type") == "sql":
                sf.write(json.dumps({
                    "id": nd["id"],
                    "name": nd.get("name"),
                    "source_uri": nd.get("source_uri"),
                    "file_path": nd.get("file_path"),
                    "content_hash": nd.get("content_hash"),
                    "sql_content": nd.get("sql_content") or "",
                }, ensure_ascii=False) + "\n")
                sql_count += 1
    log(f"[index] writing nodes.jsonl ... {node_count} nodes")

    edge_count = 0
    with open(os.path.join(index_dir, "edges.jsonl"), "w", encoding="utf-8") as ef:
        for edge in graph.edges:
            ef.write(json.dumps(edge.to_dict(), ensure_ascii=False) + "\n")
            edge_count += 1
    log(f"[index] writing edges.jsonl ... {edge_count} edges")
    log(f"[index] writing sql.jsonl ... {sql_count} sql")

    manifest = {
        "version": INDEX_VERSION,
        "source": source_meta,
        "stats": {"nodes": node_count, "edges": edge_count, "sql": sql_count},
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(os.path.join(index_dir, "manifest.json"), "w", encoding="utf-8") as mf:
        json.dump(manifest, mf, ensure_ascii=False, indent=2)
    return manifest
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_serve/test_index_io.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sqlgraph/serve/__init__.py sqlgraph/serve/index_io.py tests/test_serve/__init__.py tests/test_serve/test_index_io.py
git commit -m "feat: serialize property graph to jsonl index"
```

---

## Task 2: Cache validity + load index into memory

**Files:**
- Modify: `sqlgraph/serve/index_io.py`
- Test: `tests/test_serve/test_index_io.py`

- [ ] **Step 1: Write the failing test (append)**

Append to `tests/test_serve/test_index_io.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_serve/test_index_io.py -v`
Expected: FAIL with `ImportError: cannot import name 'is_cache_valid'`

- [ ] **Step 3: Implement cache check + raw loader (append to `sqlgraph/serve/index_io.py`)**

```python
def _read_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def is_cache_valid(index_dir: str, source_meta: dict[str, Any]) -> bool:
    """True when a prior index exists and its source fingerprint still matches."""
    manifest_path = os.path.join(index_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        return False
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if manifest.get("version") != INDEX_VERSION:
        return False
    prev = manifest.get("source", {})
    return (
        prev.get("size") == source_meta.get("size")
        and prev.get("sha1_16") == source_meta.get("sha1_16")
    )


def load_raw_index(index_dir: str) -> dict[str, Any]:
    """Load manifest + nodes/edges/sql JSONL rows from disk."""
    with open(os.path.join(index_dir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    return {
        "manifest": manifest,
        "nodes": _read_jsonl(os.path.join(index_dir, "nodes.jsonl")),
        "edges": _read_jsonl(os.path.join(index_dir, "edges.jsonl")),
        "sql": _read_jsonl(os.path.join(index_dir, "sql.jsonl")),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_serve/test_index_io.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add sqlgraph/serve/index_io.py tests/test_serve/test_index_io.py
git commit -m "feat: add jsonl index cache check and raw loader"
```

---

## Task 3: GraphIndex in-memory model (adjacency, node lookup, sql groups)

**Files:**
- Create: `sqlgraph/serve/graph_index.py`
- Modify: `sqlgraph/serve/__init__.py`
- Test: `tests/test_serve/test_graph_index.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_serve/test_graph_index.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_serve/test_graph_index.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sqlgraph.serve.graph_index'`

- [ ] **Step 3: Implement `GraphIndex.from_raw`, `meta`, adjacency, full_name backfill**

Create `sqlgraph/serve/graph_index.py`:

```python
"""In-memory model over the JSONL index for search and subgraph queries."""
from __future__ import annotations

from typing import Any


def _node_full_name(node: dict[str, Any]) -> str:
    """Compute a table's full name; mirror TableNode.full_name for cached dicts."""
    parts = [p for p in (node.get("catalog"), node.get("schema_name")) if p]
    parts.append(node.get("name") or node["id"])
    return ".".join(parts)


class GraphIndex:
    """All index data resident in memory: nodes, edges, adjacency, sql, name index."""

    def __init__(self) -> None:
        self.manifest: dict[str, Any] = {}
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self.adjacency: dict[str, dict[str, list[str]]] = {}
        self.sql_by_id: dict[str, dict[str, Any]] = {}
        self.table_write_sqls: dict[str, list[str]] = {}
        self.table_read_sqls: dict[str, list[str]] = {}
        self.name_index: dict[str, list[str]] = {}

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "GraphIndex":
        index = cls()
        index.manifest = raw.get("manifest", {})
        for node in raw.get("nodes", []):
            if node.get("node_type") == "table":
                node["full_name"] = _node_full_name(node)
            index.nodes[node["id"]] = node
            index.adjacency[node["id"]] = {"in": [], "out": []}
        index.edges = raw.get("edges", [])
        for edge in index.edges:
            src, tgt = edge.get("source"), edge.get("target")
            if src in index.adjacency and tgt in index.adjacency:
                index.adjacency[src]["out"].append(tgt)
                index.adjacency[tgt]["in"].append(src)
        for sql in raw.get("sql", []):
            index.sql_by_id[sql["id"]] = sql
        index._build_sql_groups()
        index._build_name_index()
        return index

    def meta(self) -> dict[str, Any]:
        return {
            "stats": self.manifest.get("stats", {}),
            "built_at": self.manifest.get("built_at"),
            "source": self.manifest.get("source", {}),
        }

    def _build_sql_groups(self) -> None:
        for edge in self.edges:
            etype = edge.get("type")
            src, tgt = edge.get("source"), edge.get("target")
            if etype == "writes_to" and self.nodes.get(src, {}).get("node_type") == "sql":
                self.table_write_sqls.setdefault(tgt, []).append(src)
            elif etype == "reads_from" and self.nodes.get(src, {}).get("node_type") == "sql":
                self.table_read_sqls.setdefault(tgt, []).append(src)

    def _build_name_index(self) -> None:
        for nid, node in self.nodes.items():
            if node.get("node_type") not in ("table", "column"):
                continue
            keys = {node.get("name"), node.get("full_name")}
            for key in keys:
                if key:
                    self.name_index.setdefault(key.strip().lower(), []).append(nid)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_serve/test_graph_index.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add sqlgraph/serve/graph_index.py tests/test_serve/test_graph_index.py
git commit -m "feat: add in-memory GraphIndex with adjacency and sql groups"
```

---

## Task 4: GraphIndex search, subgraph BFS, node detail

**Files:**
- Modify: `sqlgraph/serve/graph_index.py`
- Test: `tests/test_serve/test_graph_index.py`

- [ ] **Step 1: Write the failing test (append)**

Append to `tests/test_serve/test_graph_index.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_serve/test_graph_index.py -v`
Expected: FAIL with `AttributeError: 'GraphIndex' object has no attribute 'search'`

- [ ] **Step 3: Implement `search`, `subgraph`, `node_detail`, `sql_detail` (append to `sqlgraph/serve/graph_index.py`)**

```python
    _PREVIEW_LEN = 160

    def search(self, q: str, entity_type: str = "all", limit: int = 50) -> list[dict[str, Any]]:
        """Case-insensitive substring search over table and column names only."""
        term = (q or "").strip().lower()
        if not term:
            return []
        seen: set[str] = set()
        hits: list[dict[str, Any]] = []
        for key, node_ids in self.name_index.items():
            if term not in key:
                continue
            for nid in node_ids:
                if nid in seen:
                    continue
                node = self.nodes[nid]
                ntype = node.get("node_type")
                if entity_type != "all" and ntype != entity_type:
                    continue
                seen.add(nid)
                hits.append({
                    "id": nid,
                    "type": ntype,
                    "name": node.get("name"),
                    "fullName": node.get("full_name") or node.get("name"),
                    "tableId": node.get("table_id"),
                    "sqlCount": len(self.table_write_sqls.get(nid, []))
                    + len(self.table_read_sqls.get(nid, [])),
                })
                if len(hits) >= limit:
                    return hits
        return hits

    def subgraph(self, node_id: str, depth: int = 1, direction: str = "both") -> dict[str, Any]:
        """BFS neighborhood around node_id up to `depth` hops in `direction`."""
        if node_id not in self.nodes:
            return {"nodes": [], "edges": []}
        depth = max(1, min(int(depth), 3))
        visited = {node_id}
        frontier = [node_id]
        for _ in range(depth):
            nxt: list[str] = []
            for nid in frontier:
                adj = self.adjacency.get(nid, {"in": [], "out": []})
                neighbors: list[str] = []
                if direction in ("down", "both"):
                    neighbors += adj["out"]
                if direction in ("up", "both"):
                    neighbors += adj["in"]
                for nb in neighbors:
                    if nb not in visited:
                        visited.add(nb)
                        nxt.append(nb)
            frontier = nxt
            if not frontier:
                break
        nodes = [self._node_view(nid) for nid in visited]
        edges = [
            e for e in self.edges
            if e.get("source") in visited and e.get("target") in visited
        ]
        return {"nodes": nodes, "edges": edges}

    def _node_view(self, nid: str) -> dict[str, Any]:
        node = dict(self.nodes[nid])
        if node.get("node_type") == "table":
            node["writeSqlCount"] = len(self.table_write_sqls.get(nid, []))
            node["readSqlCount"] = len(self.table_read_sqls.get(nid, []))
        return node

    def _sql_summaries(self, sql_ids: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for sid in sql_ids:
            sql = self.sql_by_id.get(sid, {})
            content = sql.get("sql_content") or ""
            preview = " ".join(content.split())[: self._PREVIEW_LEN]
            out.append({
                "sqlId": sid,
                "name": sql.get("name"),
                "sourceUri": sql.get("source_uri") or sql.get("file_path"),
                "preview": preview,
            })
        return out

    def node_detail(self, node_id: str) -> dict[str, Any] | None:
        node = self.nodes.get(node_id)
        if node is None:
            return None
        columns = []
        if node.get("node_type") == "table":
            columns = [
                {"id": nid, "name": self.nodes[nid].get("name")}
                for nid in self.adjacency.get(node_id, {}).get("out", [])
                if self.nodes.get(nid, {}).get("node_type") == "column"
                and self.nodes[nid].get("table_id") == node_id
            ]
        return {
            "node": self._node_view(node_id),
            "writeSqls": self._sql_summaries(self.table_write_sqls.get(node_id, [])),
            "readSqls": self._sql_summaries(self.table_read_sqls.get(node_id, [])),
            "columns": columns,
        }

    def sql_detail(self, sql_id: str) -> dict[str, Any] | None:
        return self.sql_by_id.get(sql_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_serve/test_graph_index.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add sqlgraph/serve/graph_index.py tests/test_serve/test_graph_index.py
git commit -m "feat: add search, subgraph and node detail to GraphIndex"
```

---

## Task 5: Index orchestration (build-or-reuse with progress logging)

**Files:**
- Modify: `sqlgraph/serve/index_io.py`
- Modify: `sqlgraph/serve/__init__.py`
- Test: `tests/test_serve/test_index_io.py`

- [ ] **Step 1: Write the failing test (append to `tests/test_serve/test_index_io.py`)**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_serve/test_index_io.py::test_prepare_index_builds_then_reuses -v`
Expected: FAIL with `ImportError: cannot import name 'prepare_index'`

- [ ] **Step 3: Implement `prepare_index` (append to `sqlgraph/serve/index_io.py`)**

```python
def prepare_index(
    input_path: str,
    base_dir: str,
    dialect: str | None = None,
    rebuild: bool = False,
    log: Optional[Callable[[str], None]] = None,
) -> str:
    """Build the JSONL index or reuse a valid cache. Returns the concrete index dir."""
    from sqlgraph.api import build_graph

    log = log or (lambda _msg: None)
    meta = source_fingerprint(input_path)
    target_dir = index_dir_for(base_dir, meta)

    if not rebuild and is_cache_valid(target_dir, meta):
        log(f"[serve] index cache hit → {target_dir}")
        return target_dir

    reason = "forced rebuild" if rebuild else "cache miss"
    log(f"[serve] {reason} → building index")
    graph = build_graph(input_path, dialect=dialect)
    build_index(graph, target_dir, source_meta=meta, log=log)
    log(f"[load]  index ready → {target_dir}")
    return target_dir
```

- [ ] **Step 4: Export from package (edit `sqlgraph/serve/__init__.py`)**

```python
"""SqlGraph Lineage Explorer: JSONL index + local serve mode."""
from sqlgraph.serve.index_io import build_index, load_raw_index, prepare_index
from sqlgraph.serve.graph_index import GraphIndex

__all__ = ["build_index", "load_raw_index", "prepare_index", "GraphIndex"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_serve/test_index_io.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add sqlgraph/serve/index_io.py sqlgraph/serve/__init__.py tests/test_serve/test_index_io.py
git commit -m "feat: add build-or-reuse index orchestration with logging"
```

---

## Task 6: Frontend assets (shell, pages, shared JS/CSS)

**Files:**
- Create: `sqlgraph/serve/web/shell.html.j2`, `search.html.j2`, `viewer.html.j2`, `playground.html.j2`
- Create: `sqlgraph/serve/web/static/app.css`, `graph.js`, `detail.js`
- Test: none (static assets; covered indirectly by Task 7 page-render test)

- [ ] **Step 1: Create `sqlgraph/serve/web/shell.html.j2`**

```html
<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SqlGraph Explorer · {{ page_title }}</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<header class="app-tabs">
  <span class="brand">SqlGraph Explorer</span>
  <nav>
    <a href="/search" class="{{ 'active' if active == 'search' else '' }}">检索</a>
    <a href="/viewer" class="{{ 'active' if active == 'viewer' else '' }}">图谱查看</a>
    <a href="/playground" class="{{ 'active' if active == 'playground' else '' }}">在线解析</a>
  </nav>
</header>
<main class="app-body">
{{ body | safe }}
</main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.min.js"></script>
<script src="/static/graph.js"></script>
<script src="/static/detail.js"></script>
{% block page_script %}{% endblock %}
</body>
</html>
```

- [ ] **Step 2: Create `sqlgraph/serve/web/search.html.j2`**

```html
<section class="search-page">
  <div class="search-bar">
    <input id="q" type="text" placeholder="搜索表名或字段名...">
    <select id="type">
      <option value="all">全部</option>
      <option value="table">表</option>
      <option value="column">字段</option>
    </select>
  </div>
  <div id="results" class="results"></div>
</section>
<script>
const results = document.getElementById('results');
async function runSearch(){
  const q = document.getElementById('q').value.trim();
  const type = document.getElementById('type').value;
  if(!q){ results.innerHTML=''; return; }
  const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&type=${type}&limit=50`);
  const data = await res.json();
  results.innerHTML = (data.hits||[]).map(h =>
    `<a class="hit" href="/viewer?node_id=${encodeURIComponent(h.id)}">
       <span class="hit-type ${h.type}">${h.type}</span>
       <span class="hit-name">${h.fullName||h.name}</span>
       <span class="hit-sql">SQL ${h.sqlCount||0}</span>
     </a>`).join('') || '<div class="empty">无匹配结果</div>';
}
document.getElementById('q').addEventListener('input', runSearch);
document.getElementById('type').addEventListener('change', runSearch);
</script>
```

- [ ] **Step 3: Create `sqlgraph/serve/web/viewer.html.j2`**

```html
<section class="viewer-page">
  <div class="viewer-toolbar">
    <label>深度
      <select id="depth"><option>1</option><option>2</option><option>3</option></select>
    </label>
    <label>方向
      <select id="direction">
        <option value="both">双向</option>
        <option value="up">上游</option>
        <option value="down">下游</option>
      </select>
    </label>
    <button id="reload">刷新</button>
  </div>
  <div id="cy"></div>
  <aside id="detail" class="detail"></aside>
</section>
<script>
const params = new URLSearchParams(location.search);
let rootId = params.get('node_id');
async function loadSubgraph(){
  if(!rootId){ document.getElementById('detail').innerHTML = '从检索页选择一个节点开始。'; return; }
  const depth = document.getElementById('depth').value;
  const direction = document.getElementById('direction').value;
  const res = await fetch(`/api/subgraph?node_id=${encodeURIComponent(rootId)}&depth=${depth}&direction=${direction}`);
  const data = await res.json();
  window.renderGraph(data);
  const detail = await (await fetch(`/api/node/${encodeURIComponent(rootId)}`)).json();
  window.renderDetail(detail);
}
document.getElementById('reload').addEventListener('click', loadSubgraph);
window.onGraphNodeTap = async (nodeId) => {
  const detail = await (await fetch(`/api/node/${encodeURIComponent(nodeId)}`)).json();
  window.renderDetail(detail);
};
loadSubgraph();
</script>
```

- [ ] **Step 4: Create `sqlgraph/serve/web/playground.html.j2`**

```html
<section class="playground-page">
  <div class="pg-input">
    <textarea id="sql" placeholder="输入 SQL..."></textarea>
    <button id="parse">解析</button>
    <div id="msg"></div>
  </div>
  <div id="cy"></div>
  <aside id="detail" class="detail"></aside>
</section>
<script>
document.getElementById('parse').addEventListener('click', async () => {
  const sql = document.getElementById('sql').value.trim();
  const msg = document.getElementById('msg');
  if(!sql){ msg.textContent='请输入 SQL'; return; }
  msg.textContent='解析中...';
  const res = await fetch('/api/parse', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({sql, dialect:'spark'})
  });
  const data = await res.json();
  if(!data.ok){ msg.textContent = data.error || '解析失败'; return; }
  msg.textContent = `节点 ${data.elementCount.nodes} · 边 ${data.elementCount.edges}`;
  window.renderGraph({elements: data.elements});
});
window.onGraphNodeTap = (nodeId) => {};
</script>
```

- [ ] **Step 5: Create `sqlgraph/serve/web/static/graph.js`**

```javascript
// Shared Cytoscape renderer for viewer and playground pages.
(function(){
  if (window.cytoscape && window.cytoscapeDagre) { cytoscape.use(cytoscapeDagre); }
  let cy = null;

  function toElements(data){
    if (data.elements) return data.elements;
    const nodes = (data.nodes||[]).map(n => ({ data: {
      id: n.id, label: n.full_name || n.name || n.id, nodeType: n.node_type,
      writeSqlCount: n.writeSqlCount||0, readSqlCount: n.readSqlCount||0
    }}));
    const edges = (data.edges||[]).map(e => ({ data: {
      id: e.id, source: e.source, target: e.target, edgeType: e.type
    }}));
    return nodes.concat(edges);
  }

  window.renderGraph = function(data){
    const container = document.getElementById('cy');
    if (!container) return;
    cy = cytoscape({
      container,
      elements: toElements(data),
      style: [
        {selector:'node',style:{'label':'data(label)','font-size':10,'background-color':'#64b5f6','color':'#e5e7eb','text-valign':'bottom'}},
        {selector:'node[nodeType="column"]',style:{'background-color':'#66bb6a','width':12,'height':12}},
        {selector:'node[nodeType="sql"]',style:{'shape':'round-rectangle','background-color':'#7c3aed','color':'#fff'}},
        {selector:'node[nodeType="transform"]',style:{'shape':'diamond','background-color':'#ffa726'}},
        {selector:'edge',style:{'curve-style':'bezier','target-arrow-shape':'triangle','line-color':'#94a3b8','target-arrow-color':'#94a3b8','width':1.2,'arrow-scale':.7}}
      ],
      layout:{name:'dagre', rankDir:'LR', nodeSep:36, rankSep:110}
    });
    cy.on('tap','node', evt => {
      if (window.onGraphNodeTap) window.onGraphNodeTap(evt.target.id());
    });
  };
})();
```

- [ ] **Step 6: Create `sqlgraph/serve/web/static/detail.js`**

```javascript
// Shared detail panel with per-table read/write SQL groups (lazy full text).
(function(){
  function esc(s){ const d=document.createElement('div'); d.textContent=s==null?'':String(s); return d.innerHTML; }

  function sqlGroup(title, items){
    if(!items || !items.length) return '';
    const rows = items.map(it => `
      <div class="sql-item">
        <div class="sql-head" data-sql-id="${esc(it.sqlId)}">
          <strong>${esc(it.name||it.sqlId)}</strong>
          <span class="sql-src">${esc(it.sourceUri||'')}</span>
        </div>
        <div class="sql-preview">${esc(it.preview||'')}</div>
        <pre class="sql-full" id="full-${esc(it.sqlId)}" hidden></pre>
      </div>`).join('');
    return `<div class="sql-group"><h4>${esc(title)}</h4>${rows}</div>`;
  }

  window.renderDetail = function(detail){
    const box = document.getElementById('detail');
    if(!box) return;
    if(!detail || !detail.node){ box.innerHTML = '<div class="empty">无详情</div>'; return; }
    const n = detail.node;
    box.innerHTML = `
      <h3>${esc(n.full_name || n.name || n.id)}</h3>
      <div class="badge">${esc(n.node_type)}</div>
      ${sqlGroup('写入 SQL', detail.writeSqls)}
      ${sqlGroup('读取 SQL', detail.readSqls)}`;
    box.querySelectorAll('.sql-head').forEach(head => {
      head.addEventListener('click', async () => {
        const id = head.getAttribute('data-sql-id');
        const pre = document.getElementById(`full-${id}`);
        if(!pre) return;
        if(pre.hidden && !pre.textContent){
          const sql = await (await fetch(`/api/sql/${encodeURIComponent(id)}`)).json();
          pre.textContent = (sql && sql.sql_content) || '(无原文)';
        }
        pre.hidden = !pre.hidden;
      });
    });
  };
})();
```

- [ ] **Step 7: Create `sqlgraph/serve/web/static/app.css`**

```css
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: Inter, "PingFang SC", sans-serif; background:#0b1020; color:#e5e7eb; }
.app-tabs { display:flex; align-items:center; gap:18px; padding:10px 18px; background:#0f172a; border-bottom:1px solid rgba(148,163,184,.2); }
.app-tabs .brand { font-weight:800; }
.app-tabs nav a { color:#94a3b8; text-decoration:none; margin-right:12px; }
.app-tabs nav a.active { color:#c4b5fd; font-weight:700; }
.app-body { height: calc(100vh - 44px); }
.search-page { padding:18px; }
.search-bar { display:flex; gap:8px; margin-bottom:14px; }
.search-bar input { flex:1; height:36px; padding:0 12px; border-radius:8px; border:1px solid rgba(148,163,184,.3); background:#111827; color:#e5e7eb; }
.results .hit { display:flex; gap:10px; padding:8px 10px; border-bottom:1px solid rgba(148,163,184,.12); text-decoration:none; color:#e5e7eb; }
.hit-type { font-size:10px; padding:2px 6px; border-radius:4px; background:#1e293b; }
.hit-type.table { color:#93c5fd; } .hit-type.column { color:#86efac; }
.hit-sql { margin-left:auto; color:#94a3b8; font-size:11px; }
.viewer-page, .playground-page { display:grid; grid-template-columns: 1fr 340px; grid-template-rows:auto 1fr; height:100%; }
.viewer-toolbar, .pg-input { grid-column:1 / 2; padding:10px 14px; display:flex; gap:12px; align-items:center; }
.pg-input { flex-direction:column; align-items:stretch; }
.pg-input textarea { min-height:120px; background:#0f172a; color:#e5e7eb; border:1px solid rgba(148,163,184,.3); border-radius:8px; padding:10px; }
#cy { grid-column:1 / 2; grid-row:2; background:#111827; }
.detail { grid-column:2 / 3; grid-row:1 / 3; padding:14px; background:#0f172a; border-left:1px solid rgba(148,163,184,.2); overflow:auto; }
.detail h3 { font-size:14px; word-break:break-all; margin-bottom:6px; }
.badge { display:inline-block; font-size:10px; padding:2px 7px; background:#312e81; border-radius:6px; margin-bottom:10px; }
.sql-group h4 { font-size:12px; margin:10px 0 6px; color:#c4b5fd; }
.sql-item { border:1px solid rgba(148,163,184,.15); border-radius:8px; padding:8px; margin-bottom:6px; }
.sql-head { cursor:pointer; display:flex; justify-content:space-between; gap:8px; }
.sql-src { color:#94a3b8; font-size:10px; }
.sql-preview { color:#94a3b8; font-size:11px; margin-top:4px; }
.sql-full { margin-top:6px; background:#1e1e2e; color:#cdd6f4; padding:8px; border-radius:6px; white-space:pre-wrap; font-size:11px; }
.empty { color:#94a3b8; padding:12px; }
```

- [ ] **Step 8: Commit**

```bash
git add sqlgraph/serve/web
git commit -m "feat: add explorer frontend shell, pages and shared assets"
```

---

## Task 7: HTTP server (routes + /api endpoints)

**Files:**
- Create: `sqlgraph/serve/server.py`
- Modify: `sqlgraph/serve/__init__.py`
- Test: `tests/test_serve/test_server_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_serve/test_server_api.py`:

```python
import json
import os
import threading
import urllib.request

import pytest

from sqlgraph.serve.index_io import prepare_index
from sqlgraph.serve.graph_index import GraphIndex
from sqlgraph.serve.index_io import load_raw_index
from sqlgraph.serve.server import build_app_server


@pytest.fixture()
def server(tmp_path):
    sql_file = os.path.join(tmp_path, "q.sql")
    with open(sql_file, "w", encoding="utf-8") as f:
        f.write("INSERT OVERWRITE TABLE dst SELECT id FROM src")
    index_dir = prepare_index(sql_file, os.path.join(tmp_path, "idx"), dialect="spark")
    index = GraphIndex.from_raw(load_raw_index(index_dir))
    httpd = build_app_server(index, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base, index
    httpd.shutdown()
    httpd.server_close()


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, resp.read().decode("utf-8")


def _table_id(index, full_name):
    for nid, node in index.nodes.items():
        if node.get("node_type") == "table" and node.get("full_name") == full_name:
            return nid
    raise AssertionError("not found")


def test_meta_and_pages(server):
    base, _ = server
    status, body = _get(f"{base}/api/meta")
    assert status == 200 and json.loads(body)["stats"]["nodes"] > 0
    status, html = _get(f"{base}/search")
    assert status == 200 and "SqlGraph Explorer" in html


def test_search_and_subgraph_and_node(server):
    base, index = server
    status, body = _get(f"{base}/api/search?q=dst&type=table")
    assert status == 200 and any(h["name"] == "dst" for h in json.loads(body)["hits"])
    dst = _table_id(index, "dst")
    status, body = _get(f"{base}/api/subgraph?node_id={dst}&depth=1&direction=both")
    assert status == 200 and len(json.loads(body)["nodes"]) >= 1
    status, body = _get(f"{base}/api/node/{dst}")
    assert status == 200 and json.loads(body)["node"]["id"] == dst


def test_missing_node_returns_404(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{base}/api/node/nope")
    assert exc.value.code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_serve/test_server_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sqlgraph.serve.server'`

- [ ] **Step 3: Implement `sqlgraph/serve/server.py`**

```python
"""Local HTTP server for the Lineage Explorer (search / viewer / playground)."""
from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from jinja2 import Environment, FileSystemLoader, select_autoescape

from sqlgraph.serve.graph_index import GraphIndex
from sqlgraph.serve.index_io import prepare_index, load_raw_index
from sqlgraph.playground import graph_to_playground_payload, find_free_port

_WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
_STATIC_DIR = os.path.join(_WEB_DIR, "static")
_ENV = Environment(loader=FileSystemLoader(_WEB_DIR), autoescape=select_autoescape(["html", "j2"]))

_PAGES = {
    "/search": ("search", "检索"),
    "/viewer": ("viewer", "图谱查看"),
    "/playground": ("playground", "在线解析"),
}
_CONTENT_TYPES = {".css": "text/css", ".js": "application/javascript"}


def _render_page(active: str, title: str) -> str:
    body = _ENV.get_template(f"{active}.html.j2").render()
    return _ENV.get_template("shell.html.j2").render(
        active=active, page_title=title, body=body
    )


def make_handler(index: GraphIndex):
    class ExplorerHandler(BaseHTTPRequestHandler):
        server_version = "SqlGraphExplorer/1.0"

        def log_message(self, *args):
            return

        def _send(self, data: bytes, status: int, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, payload, status: int = 200):
            self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       status, "application/json; charset=utf-8")

        def _html(self, html: str, status: int = 200):
            self._send(html.encode("utf-8"), status, "text/html; charset=utf-8")

        def do_GET(self):
            parsed = urlparse(self.path)
            path, qs = parsed.path, parse_qs(parsed.query)
            if path == "/":
                self.send_response(302); self.send_header("Location", "/search"); self.end_headers(); return
            if path in _PAGES:
                active, title = _PAGES[path]
                self._html(_render_page(active, title)); return
            if path.startswith("/static/"):
                self._serve_static(path); return
            if path == "/api/meta":
                self._json(index.meta()); return
            if path == "/api/search":
                q = (qs.get("q") or [""])[0]
                etype = (qs.get("type") or ["all"])[0]
                limit = int((qs.get("limit") or ["50"])[0])
                self._json({"ok": True, "hits": index.search(q, etype, limit)}); return
            if path == "/api/subgraph":
                node_id = (qs.get("node_id") or [""])[0]
                if node_id not in index.nodes:
                    self._json({"ok": False, "error": "node not found"}, 404); return
                depth = int((qs.get("depth") or ["1"])[0])
                direction = (qs.get("direction") or ["both"])[0]
                self._json(index.subgraph(node_id, depth, direction)); return
            if path.startswith("/api/node/"):
                node_id = path[len("/api/node/"):]
                detail = index.node_detail(node_id)
                if detail is None:
                    self._json({"ok": False, "error": "node not found"}, 404); return
                self._json(detail); return
            if path.startswith("/api/sql/"):
                sql_id = path[len("/api/sql/"):]
                sql = index.sql_detail(sql_id)
                if sql is None:
                    self._json({"ok": False, "error": "sql not found"}, 404); return
                self._json(sql); return
            self._json({"ok": False, "error": "not found"}, 404)

        def do_POST(self):
            if urlparse(self.path).path != "/api/parse":
                self._json({"ok": False, "error": "not found"}, 404); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                sql = (payload.get("sql") or "").strip()
                if not sql:
                    raise ValueError("SQL 不能为空")
                self._json(graph_to_playground_payload(
                    sql=sql, dialect=payload.get("dialect") or None))
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)}, 400)

        def _serve_static(self, path: str):
            rel = path[len("/static/"):]
            full = os.path.normpath(os.path.join(_STATIC_DIR, rel))
            if not full.startswith(_STATIC_DIR) or not os.path.isfile(full):
                self._json({"ok": False, "error": "not found"}, 404); return
            ext = os.path.splitext(full)[1]
            with open(full, "rb") as f:
                self._send(f.read(), 200, _CONTENT_TYPES.get(ext, "application/octet-stream"))

    return ExplorerHandler


def build_app_server(index: GraphIndex, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """Create (but do not start) the HTTP server bound to an in-memory index."""
    if port <= 0:
        port = find_free_port(host)
    return ThreadingHTTPServer((host, port), make_handler(index))


def serve_explorer(
    input_path: str,
    host: str = "127.0.0.1",
    port: int = 8770,
    dialect: str | None = None,
    rebuild: bool = False,
    index_dir: str = ".sqlgraph_index",
    open_browser: bool = True,
) -> str:
    """Build-or-reuse the index, load it into memory, then serve the explorer."""
    def log(msg: str) -> None:
        print(msg, flush=True)

    size = os.path.getsize(input_path) / 1e6 if os.path.isfile(input_path) else 0
    log(f"[serve] input: {input_path} ({size:.1f} MB)")
    concrete_dir = prepare_index(input_path, index_dir, dialect=dialect, rebuild=rebuild, log=log)
    log("[load]  loading index into memory ...")
    index = GraphIndex.from_raw(load_raw_index(concrete_dir))
    log(f"[load]  ready | nodes={len(index.nodes)} edges={len(index.edges)} sql={len(index.sql_by_id)}")

    httpd = build_app_server(index, host=host, port=port)
    actual_port = httpd.server_address[1]
    url = f"http://{host}:{actual_port}/"
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    log(f"[serve] {url} (search / viewer / playground)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return url
```

- [ ] **Step 4: Export `serve_explorer` and `build_app_server` (edit `sqlgraph/serve/__init__.py`)**

```python
"""SqlGraph Lineage Explorer: JSONL index + local serve mode."""
from sqlgraph.serve.index_io import build_index, load_raw_index, prepare_index
from sqlgraph.serve.graph_index import GraphIndex
from sqlgraph.serve.server import serve_explorer, build_app_server

__all__ = [
    "build_index", "load_raw_index", "prepare_index",
    "GraphIndex", "serve_explorer", "build_app_server",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_serve/test_server_api.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add sqlgraph/serve/server.py sqlgraph/serve/__init__.py tests/test_serve/test_server_api.py
git commit -m "feat: add explorer http server with search/viewer/api routes"
```

---

## Task 8: CLI `serve` command

**Files:**
- Modify: `sqlgraph/cli.py`
- Test: `tests/test_serve/test_server_api.py` (add CLI smoke via import)

- [ ] **Step 1: Write the failing test (append to `tests/test_serve/test_server_api.py`)**

```python
def test_cli_registers_serve_command():
    from typer.testing import CliRunner
    from sqlgraph.cli import app

    result = CliRunner().invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "serve" in result.output.lower()
    assert "--rebuild" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_serve/test_server_api.py::test_cli_registers_serve_command -v`
Expected: FAIL with `No such command 'serve'` (exit_code != 0)

- [ ] **Step 3: Add `serve` command to `sqlgraph/cli.py`**

Add this command function after the existing `playground` command (near `sqlgraph/cli.py:260`). Use a lazy import so normal CLI commands do not eagerly import the serve package:

```python
@app.command()
def serve(
    input_path: str = typer.Argument(
        ...,
        help="SQL 文件、目录或 df.csv 路径。启动时会解析并构建 JSONL 索引。",
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="服务监听地址。"),
    port: int = typer.Option(8770, "--port", help="服务端口。传 0 时自动寻找可用端口。"),
    dialect: Optional[str] = typer.Option(None, "--dialect", help="SQL 方言，不指定则自动检测。"),
    rebuild: bool = typer.Option(False, "--rebuild", help="强制重建索引，忽略缓存。"),
    index_dir: str = typer.Option(".sqlgraph_index", "--index-dir", help="索引缓存目录。"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="启动后是否自动打开浏览器。"),
):
    """启动本地血缘检索浏览器（检索 / 图谱查看 / 在线解析）"""
    from sqlgraph.serve import serve_explorer

    serve_explorer(
        input_path=input_path,
        host=host,
        port=port,
        dialect=dialect,
        rebuild=rebuild,
        index_dir=index_dir,
        open_browser=open_browser,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_serve/test_server_api.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest`
Expected: PASS (all prior tests + new `tests/test_serve/*`)

- [ ] **Step 6: Commit**

```bash
git add sqlgraph/cli.py tests/test_serve/test_server_api.py
git commit -m "feat: add sqlgraph serve cli command"
```

---

## Task 9: gitignore + docs

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`, `README.zh-CN.md`

- [ ] **Step 1: Ignore the local index cache**

Add to `.gitignore` under the "Large or private local datasets" section:

```gitignore
.sqlgraph_index/
```

- [ ] **Step 2: Document the serve command in `README.md`**

Add after the Playground section (near `README.md:126`):

```markdown
### Lineage Explorer (search + local subgraphs)

For large inputs, avoid one giant HTML file. Serve a searchable explorer instead:

```bash
sqlgraph serve df.csv --dialect spark
# builds a JSONL index (reused on next start), then opens:
#   /search      search tables & columns
#   /viewer      load a node's 1-hop subgraph (switch to 2/3 hops)
#   /playground  paste SQL and parse on the fly
```
```

- [ ] **Step 3: Document in `README.zh-CN.md`**

Add after the Playground section (near `README.zh-CN.md:91`):

```markdown
### 血缘检索浏览器（检索 + 局部子图）

大规模输入不再依赖单个巨大 HTML，改用可检索的本地浏览器：

```bash
sqlgraph serve df.csv --dialect spark
# 首次启动构建 JSONL 索引（后续复用），随后打开：
#   /search      检索表与字段
#   /viewer      加载节点的 1 跳子图（可切换 2/3 跳）
#   /playground  粘贴 SQL 即时解析
```
```

- [ ] **Step 4: Verify gitignore works**

Run: `git check-ignore -v .sqlgraph_index/x`
Expected: prints a `.gitignore` match line

- [ ] **Step 5: Commit**

```bash
git add .gitignore README.md README.zh-CN.md
git commit -m "docs: document sqlgraph serve explorer and ignore index cache"
```

---

## Self-Review

**1. Spec coverage:**
- 本地轻量服务 → Task 7/8 ✓
- 启动自动构建 + 进度日志 → Task 5 (`prepare_index` log) + Task 7 (`serve_explorer` log) ✓
- 自动复用 / `--rebuild` → Task 5 `is_cache_valid`/`prepare_index` + Task 8 CLI ✓
- 检索仅表/字段 → Task 4 `search` + `_build_name_index` ✓
- 局部图默认 1 层可切 2/3 → Task 4 `subgraph` + Task 6 viewer toolbar ✓
- 统一应用壳 + 页签 → Task 6 `shell.html.j2` ✓
- 保留静态导出 → 未改动 `visualize/`、`cli build`（仅新增 `serve`）✓
- 表读写 SQL 分组 + 按需取全文 → Task 4 `node_detail`/`sql_detail` + Task 6 `detail.js` ✓
- 原生 HTML/JS + Jinja → Task 6/7 ✓
- 全量内存加载 → Task 3/4 `GraphIndex`（无懒加载）✓
- JSONL 结构 (manifest/nodes/edges/sql) → Task 1/2 ✓

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step is complete.

**3. Type consistency:** `GraphIndex.from_raw`/`meta`/`search`/`subgraph`/`node_detail`/`sql_detail` names used identically in server and tests. Edge dict keys `type/source/target` match `Edge.to_dict()`. Node dict keys `node_type/full_name/table_id/name/sql_content/source_uri` match `nodes.py`. `find_free_port`/`graph_to_playground_payload` signatures match `playground.py`. `build_app_server(index, host, port)` used consistently in Task 7 test and impl.
