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
