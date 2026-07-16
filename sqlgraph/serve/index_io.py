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
