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
