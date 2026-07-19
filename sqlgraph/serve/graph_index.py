# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

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
