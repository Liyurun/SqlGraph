# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""In-memory model over the JSONL index for search and subgraph queries."""
from __future__ import annotations

import re
import os
from typing import Any

from sqlgraph.serve.stats import AnalysisSnapshot, table_stats

_RAW_MAX_DEPTH = 3
_MAX_TABLE_DEPTH = 25
_INTERNAL_TABLE_RESOLVE_DEPTH = 3
_INTERNAL_TABLE_RESOLVE_LIMIT = 5000
_DEFAULT_MAX_GRAPH_NODES = 800
_DEFAULT_MAX_GRAPH_EDGES = 3000
_CTE_NAME_RE = re.compile(r"\b[`\"]?([A-Za-z_][\w$]*)[`\"]?\s+as\s*\(", re.IGNORECASE)


def _node_full_name(node: dict[str, Any]) -> str:
    """Compute a table's full name; mirror TableNode.full_name for cached dicts."""
    parts = [p for p in (node.get("catalog"), node.get("schema_name")) if p]
    parts.append(node.get("name") or node["id"])
    return ".".join(parts)


def _clamp_depth(depth: int, max_depth: int) -> int:
    return max(1, min(int(depth), max_depth))


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def _is_internal_table_node(node: dict[str, Any]) -> bool:
    """True for CTE/subquery tables that should not appear in table mode."""
    if node.get("node_type") != "table":
        return False
    return (
        node.get("is_cte") is True
        or node.get("_inferred_cte") is True
        or str(node.get("name") or "").startswith("subq_")
    )


def _is_physical_table_node(node: dict[str, Any]) -> bool:
    """True for real tables that table-mode lineage should expose."""
    return node.get("node_type") == "table" and not _is_internal_table_node(node)


def _extract_cte_names(sql_content: str) -> set[str]:
    """Extract CTE aliases from common WITH/`,` CTE syntax."""
    if not sql_content or "as" not in sql_content.lower():
        return set()
    return {match.group(1).strip("`\"").lower() for match in _CTE_NAME_RE.finditer(sql_content)}


class GraphIndex:
    """All index data resident in memory: nodes, edges, adjacency, sql, name index."""

    def __init__(self) -> None:
        self.manifest: dict[str, Any] = {}
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self.adjacency: dict[str, dict[str, list[str]]] = {}
        self.in_edges: dict[str, list[dict[str, Any]]] = {}
        self.out_edges: dict[str, list[dict[str, Any]]] = {}
        self.table_adjacency: dict[str, dict[str, list[str]]] = {}
        self.table_lineage_edges: list[dict[str, Any]] = []
        self.sql_by_id: dict[str, dict[str, Any]] = {}
        self.table_write_sqls: dict[str, list[str]] = {}
        self.table_read_sqls: dict[str, list[str]] = {}
        self.name_index: dict[str, list[str]] = {}
        self.max_graph_nodes = _positive_int_env(
            "SQLGRAPH_MAX_GRAPH_NODES",
            _DEFAULT_MAX_GRAPH_NODES,
        )
        self.max_graph_edges = _positive_int_env(
            "SQLGRAPH_MAX_GRAPH_EDGES",
            _DEFAULT_MAX_GRAPH_EDGES,
        )

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "GraphIndex":
        index = cls()
        index.manifest = raw.get("manifest", {})
        for node in raw.get("nodes", []):
            if node.get("node_type") == "table":
                node["full_name"] = _node_full_name(node)
            index.nodes[node["id"]] = node
            index.adjacency[node["id"]] = {"in": [], "out": []}
            index.in_edges[node["id"]] = []
            index.out_edges[node["id"]] = []
        index.edges = raw.get("edges", [])
        for edge in index.edges:
            src, tgt = edge.get("source"), edge.get("target")
            if src in index.adjacency and tgt in index.adjacency:
                index.adjacency[src]["out"].append(tgt)
                index.adjacency[tgt]["in"].append(src)
                index.out_edges[src].append(edge)
                index.in_edges[tgt].append(edge)
        for sql in raw.get("sql", []):
            index.sql_by_id[sql["id"]] = sql
        index._mark_inferred_cte_tables()
        index._build_sql_groups()
        index._build_table_lineage()
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
            if (
                etype == "writes_to"
                and self.nodes.get(src, {}).get("node_type") == "sql"
                and self._is_physical_table_id(tgt)
            ):
                self.table_write_sqls.setdefault(tgt, []).append(src)
            elif (
                etype == "reads_from"
                and self.nodes.get(src, {}).get("node_type") == "sql"
                and self._is_physical_table_id(tgt)
            ):
                self.table_read_sqls.setdefault(tgt, []).append(src)

    def _mark_inferred_cte_tables(self) -> None:
        """Mark unqualified table nodes that match CTE aliases in SQL text."""
        cte_names: set[str] = set()
        for sql in self.sql_by_id.values():
            cte_names.update(_extract_cte_names(sql.get("sql_content") or ""))
        if not cte_names:
            return
        for node in self.nodes.values():
            if node.get("node_type") != "table":
                continue
            if node.get("catalog") or node.get("schema_name"):
                continue
            name = str(node.get("name") or "").lower()
            if name in cte_names:
                node["_inferred_cte"] = True

    def _build_table_lineage(self) -> None:
        """Build table-only adjacency from table_lineage edges."""
        for nid, node in self.nodes.items():
            if _is_physical_table_node(node):
                self.table_adjacency[nid] = {"in": [], "out": []}
        for edge in self.edges:
            if edge.get("type") != "table_lineage":
                continue
            src, tgt = edge.get("source"), edge.get("target")
            if src in self.table_adjacency and tgt in self.table_adjacency:
                self.table_lineage_edges.append(edge)
                self.table_adjacency[src]["out"].append(tgt)
                self.table_adjacency[tgt]["in"].append(src)

    def _is_physical_table_id(self, node_id: str | None) -> bool:
        return bool(node_id and _is_physical_table_node(self.nodes.get(node_id, {})))

    def _is_internal_start_node(self, node_id: str) -> bool:
        node = self.nodes.get(node_id, {})
        if _is_internal_table_node(node):
            return True
        if node.get("node_type") == "column":
            return _is_internal_table_node(self.nodes.get(node.get("table_id"), {}))
        return False

    def _tables_for_start_node(self, node_id: str) -> set[str]:
        """Resolve any supported start node to table ids for table expansion."""
        node = self.nodes.get(node_id)
        if node is None:
            return set()
        ntype = node.get("node_type")
        if ntype == "table":
            if self._is_physical_table_id(node_id):
                return {node_id}
            return self._physical_tables_near_internal_node(node_id)
        if ntype == "column":
            table_id = node.get("table_id")
            if self._is_physical_table_id(table_id):
                return {table_id}
            return self._physical_tables_near_internal_node(node_id)
        if ntype == "sql":
            return self._tables_for_sql_node(node_id)
        if ntype == "transform":
            return (
                self._tables_for_transform_node(node_id)
                or self._physical_tables_near_internal_node(node_id)
            )
        return set()

    def _tables_for_sql_node(self, sql_id: str) -> set[str]:
        tables: set[str] = set()
        for nb in self.adjacency.get(sql_id, {}).get("out", []):
            if self._is_physical_table_id(nb):
                tables.add(nb)
        for nb in self.adjacency.get(sql_id, {}).get("in", []):
            if self._is_physical_table_id(nb):
                tables.add(nb)
        return tables

    def _tables_for_transform_node(self, transform_id: str) -> set[str]:
        tables: set[str] = set()
        for direction in ("in", "out"):
            for nb in self.adjacency.get(transform_id, {}).get(direction, []):
                node = self.nodes.get(nb, {})
                if node.get("node_type") == "column":
                    table_id = node.get("table_id")
                    if self._is_physical_table_id(table_id):
                        tables.add(table_id)
        return tables

    def _raw_neighborhood(self, start_id: str, depth: int) -> set[str]:
        """Small bounded raw BFS used to resolve internal CTE nodes."""
        visited = {start_id}
        frontier = [start_id]
        for _ in range(depth):
            nxt: list[str] = []
            for nid in frontier:
                adj = self.adjacency.get(nid, {"in": [], "out": []})
                for nb in adj["in"] + adj["out"]:
                    if nb in visited:
                        continue
                    visited.add(nb)
                    nxt.append(nb)
                    if len(visited) >= _INTERNAL_TABLE_RESOLVE_LIMIT:
                        return visited
            frontier = nxt
            if not frontier:
                break
        return visited

    def _physical_tables_near_internal_node(self, node_id: str) -> set[str]:
        """Resolve a CTE/subquery table or field to physical tables in its SQL."""
        visited = self._raw_neighborhood(node_id, _INTERNAL_TABLE_RESOLVE_DEPTH)
        fallback_tables: set[str] = set()
        sql_ids: set[str] = set()
        for nid in visited:
            node = self.nodes.get(nid, {})
            if self._is_physical_table_id(nid):
                fallback_tables.add(nid)
            elif node.get("node_type") == "column":
                table_id = node.get("table_id")
                if self._is_physical_table_id(table_id):
                    fallback_tables.add(table_id)
            elif node.get("node_type") == "sql":
                sql_ids.add(nid)
        tables: set[str] = set()
        for sql_id in sql_ids:
            tables.update(self._tables_for_sql_node(sql_id))
        return tables or fallback_tables

    def _table_bfs(self, start_tables: set[str], depth: int, direction: str) -> set[str]:
        return set(self._table_bfs_ordered(start_tables, depth, direction))

    def _table_bfs_ordered(self, start_tables: set[str], depth: int, direction: str) -> list[str]:
        """BFS table neighborhood in deterministic visit order."""
        ordered: list[str] = []
        visited: set[str] = set()
        frontier: list[str] = []
        for table_id in sorted(start_tables):
            if table_id in visited:
                continue
            visited.add(table_id)
            ordered.append(table_id)
            frontier.append(table_id)
        for _ in range(_clamp_depth(depth, _MAX_TABLE_DEPTH)):
            nxt: list[str] = []
            for table_id in frontier:
                adj = self.table_adjacency.get(table_id, {"in": [], "out": []})
                neighbors: list[str] = []
                if direction in ("down", "both"):
                    neighbors += adj["out"]
                if direction in ("up", "both"):
                    neighbors += adj["in"]
                for nb in sorted(neighbors):
                    if nb not in visited:
                        visited.add(nb)
                        ordered.append(nb)
                        nxt.append(nb)
            frontier = nxt
            if not frontier:
                break
        return ordered

    def _limited_payload(
        self,
        ordered_node_ids: list[str],
        edges: list[dict[str, Any]],
        mode: str,
    ) -> dict[str, Any]:
        total_nodes = len(ordered_node_ids)
        total_edges = len(edges)
        node_limited = total_nodes > self.max_graph_nodes
        displayed_node_ids = ordered_node_ids[: self.max_graph_nodes]
        displayed_set = set(displayed_node_ids)
        visible_edges = [
            edge for edge in edges
            if edge.get("source") in displayed_set and edge.get("target") in displayed_set
        ]
        edge_limited = len(visible_edges) > self.max_graph_edges
        visible_edges = visible_edges[: self.max_graph_edges]
        truncated = node_limited or edge_limited
        payload: dict[str, Any] = {
            "nodes": [self._node_view(nid) for nid in displayed_node_ids],
            "edges": visible_edges,
            "mode": mode,
            "truncated": truncated,
            "totalNodes": total_nodes,
            "totalEdges": total_edges,
            "displayedNodes": len(displayed_node_ids),
            "displayedEdges": len(visible_edges),
            "limits": {
                "maxNodes": self.max_graph_nodes,
                "maxEdges": self.max_graph_edges,
            },
        }
        if truncated:
            payload["message"] = (
                "图谱过大，已只展示一部分结果。"
                f"当前展示 {len(displayed_node_ids)}/{total_nodes} 个节点、"
                f"{len(visible_edges)}/{total_edges} 条边；"
                "请降低深度或选择上游/下游单向查看。"
            )
        return payload

    def _table_payload(self, table_ids: set[str] | list[str]) -> dict[str, Any]:
        ordered_ids = [
            nid for nid in table_ids
            if self._is_physical_table_id(nid)
        ]
        seen: set[str] = set()
        physical_ids: list[str] = []
        for nid in ordered_ids:
            if nid in seen:
                continue
            seen.add(nid)
            physical_ids.append(nid)
        physical_set = set(physical_ids)
        edges = [
            edge for edge in self.table_lineage_edges
            if edge.get("source") in physical_set and edge.get("target") in physical_set
        ]
        return self._limited_payload(physical_ids, edges, "table")

    def _build_name_index(self) -> None:
        for nid, node in self.nodes.items():
            if node.get("node_type") not in ("table", "column"):
                continue
            if _is_internal_table_node(node):
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
                if _is_internal_table_node(node):
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

    def table_subgraph(self, node_id: str, depth: int = 2, direction: str = "both") -> dict[str, Any]:
        """Table-only lineage neighborhood around a normalized start node."""
        if node_id not in self.nodes:
            return {"nodes": [], "edges": []}
        start_tables = self._tables_for_start_node(node_id)
        if not start_tables:
            return {
                "nodes": [],
                "edges": [],
                "error": "start node cannot be resolved to a table",
                "mode": "table",
            }
        if self._is_internal_start_node(node_id):
            return self._table_payload(sorted(start_tables))
        return self._table_payload(self._table_bfs_ordered(start_tables, depth, direction))

    def table_expansion(self, table_id: str, direction: str = "both", depth: int = 1) -> dict[str, Any]:
        """Incremental table-only expansion around an already visible table."""
        if table_id not in self.table_adjacency:
            return {
                "nodes": [],
                "edges": [],
                "error": "node is not a table",
                "mode": "table",
            }
        return self._table_payload(self._table_bfs_ordered({table_id}, depth, direction))

    def subgraph(self, node_id: str, depth: int = 1, direction: str = "both") -> dict[str, Any]:
        """BFS neighborhood around node_id up to `depth` hops in `direction`."""
        if node_id not in self.nodes:
            return {"nodes": [], "edges": []}
        depth = _clamp_depth(depth, _RAW_MAX_DEPTH)
        ordered: list[str] = [node_id]
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
                        ordered.append(nb)
                        nxt.append(nb)
            frontier = nxt
            if not frontier:
                break
        edges = [
            e for e in self.edges
            if e.get("source") in visited and e.get("target") in visited
        ]
        payload = self._limited_payload(ordered, edges, "raw")
        payload.pop("mode", None)
        return payload

    def _node_view(self, nid: str) -> dict[str, Any]:
        node = dict(self.nodes[nid])
        if node.get("node_type") == "table":
            node["writeSqlCount"] = len(self.table_write_sqls.get(nid, []))
            node["readSqlCount"] = len(self.table_read_sqls.get(nid, []))
        return node

    def _table_ref(self, table_id: str | None) -> dict[str, Any] | None:
        if not table_id or table_id not in self.nodes:
            return None
        node = self.nodes[table_id]
        return {
            "id": table_id,
            "name": node.get("name"),
            "fullName": node.get("full_name") or node.get("name"),
            "nodeType": node.get("node_type"),
            "isCte": bool(_is_internal_table_node(node)),
        }

    def _column_ref(self, column_id: str) -> dict[str, Any]:
        node = self.nodes[column_id]
        table = self._table_ref(node.get("table_id"))
        return {
            "id": column_id,
            "name": node.get("name"),
            "nodeType": node.get("node_type"),
            "tableId": node.get("table_id"),
            "tableName": (table or {}).get("fullName"),
        }

    def _transform_ref(self, transform_id: str) -> dict[str, Any]:
        node = self.nodes[transform_id]
        return {
            "id": transform_id,
            "name": node.get("name"),
            "nodeType": node.get("node_type"),
            "expression": node.get("expression") or node.get("name"),
            "outputName": node.get("output_name"),
        }

    def _column_detail(self, column_id: str) -> dict[str, Any]:
        node = self.nodes[column_id]
        upstream_ids: set[str] = set()
        downstream_ids: set[str] = set()
        transform_ids: set[str] = set()

        for edge in self.in_edges.get(column_id, []):
            src = edge.get("source")
            src_node = self.nodes.get(src, {})
            if edge.get("type") == "compute_dependency" and src_node.get("node_type") == "column":
                upstream_ids.add(src)
            elif edge.get("type") == "produces" and src_node.get("node_type") == "transform":
                transform_ids.add(src)

        for edge in self.out_edges.get(column_id, []):
            tgt = edge.get("target")
            tgt_node = self.nodes.get(tgt, {})
            if edge.get("type") == "compute_dependency" and tgt_node.get("node_type") == "column":
                downstream_ids.add(tgt)
            elif edge.get("type") == "expr_operand" and tgt_node.get("node_type") == "transform":
                transform_ids.add(tgt)

        sql_ids = [
            nid for nid in self._raw_neighborhood(column_id, 2)
            if self.nodes.get(nid, {}).get("node_type") == "sql"
        ]
        table_id = node.get("table_id")
        if self._is_physical_table_id(table_id):
            sql_ids.extend(self.table_read_sqls.get(table_id, []))
            sql_ids.extend(self.table_write_sqls.get(table_id, []))

        return {
            "node": self._node_view(column_id),
            "ownerTable": self._table_ref(table_id),
            "upstream": [self._column_ref(nid) for nid in sorted(upstream_ids)],
            "downstream": [self._column_ref(nid) for nid in sorted(downstream_ids)],
            "transforms": [self._transform_ref(nid) for nid in sorted(transform_ids)],
            "sqls": self._sql_summaries(sorted(set(sql_ids))),
        }

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

    def node_detail(
        self,
        node_id: str,
        analysis: AnalysisSnapshot | None = None,
    ) -> dict[str, Any] | None:
        node = self.nodes.get(node_id)
        if node is None:
            return None
        if node.get("node_type") == "column":
            return self._column_detail(node_id)
        columns = []
        if node.get("node_type") == "table":
            columns = [
                self._column_ref(nid)
                for nid in self.adjacency.get(node_id, {}).get("out", [])
                if self.nodes.get(nid, {}).get("node_type") == "column"
                and self.nodes[nid].get("table_id") == node_id
            ]
        payload = {
            "node": self._node_view(node_id),
            "writeSqls": self._sql_summaries(self.table_write_sqls.get(node_id, [])),
            "readSqls": self._sql_summaries(self.table_read_sqls.get(node_id, [])),
            "columns": columns,
        }
        if node.get("node_type") == "table" and node_id in self.table_adjacency:
            payload["stats"] = table_stats(
                self,
                analysis or AnalysisSnapshot.unavailable(),
                node_id,
            )
        return payload

    def sql_detail(self, sql_id: str) -> dict[str, Any] | None:
        return self.sql_by_id.get(sql_id)
