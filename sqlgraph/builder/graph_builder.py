# sqlgraph/builder/graph_builder.py
from __future__ import annotations
import uuid
from typing import Optional
from sqlgraph.model import (
    PropertyGraph, SqlNode, TableNode, ColumnNode, TransformNode,
    Edge, EdgeType, ExpressionType,
)
from sqlgraph.parser.base import SqlParser, SqlParseResult
from sqlgraph.input.sql_source import SqlSource
from sqlgraph.input.csv_schema import SchemaRegistry
from sqlgraph.builder.table_registry import TableRegistry
from sqlgraph.utils.logging import log_info, log_warn


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _expr_type_from_str(t: str) -> ExpressionType:
    mapping = {
        "case_when": ExpressionType.CASE_WHEN,
        "agg": ExpressionType.AGG,
        "cast": ExpressionType.CAST,
        "arithmetic": ExpressionType.ARITHMETIC,
        "coalesce": ExpressionType.COALESCE,
        "window": ExpressionType.WINDOW,
        "union": ExpressionType.UNION,
        "literal": ExpressionType.LITERAL,
        "column_ref": ExpressionType.COLUMN_REF,
        "function": ExpressionType.FUNCTION,
    }
    return mapping.get(t, ExpressionType.FUNCTION)


class GraphBuilder:
    """图构建器：从 SQL 解析结果构建 PropertyGraph"""

    def __init__(self, dialect: str | None = None, schema_registry: SchemaRegistry | None = None):
        self.dialect = dialect
        self.schema_registry = schema_registry
        self.parser = SqlParser(dialect=dialect, schema_registry=schema_registry)
        self.table_registry = TableRegistry()
        self.graph = PropertyGraph()
        self._table_nodes: dict = {}
        self._column_nodes: dict = {}
        self._current_ctes: list = []

    def build_from_source(self, source: SqlSource) -> PropertyGraph:
        """从 SqlSource 构建完整图"""
        log_info(f"Building graph from {len(source)} SQL source(s)")
        results = []
        for item in source:
            parse_result = self.parser.parse(
                item.content, name=item.name, file_path=item.source_path
            )
            results.append(parse_result)
            self._add_parse_result(parse_result)
        self._link_cross_sql_lineage()
        log_info(f"Graph built: {self.graph.stats()}")
        return self.graph

    def build_from_sql(self, sql: str, name: str = "query") -> PropertyGraph:
        """从单条 SQL 字符串构建图"""
        result = self.parser.parse(sql, name=name)
        self._add_parse_result(result)
        self._link_cross_sql_lineage()
        return self.graph

    def _add_parse_result(self, result: SqlParseResult) -> None:
        """将单个 SQL 的解析结果添加到图中"""
        self._current_ctes = result.cte_tables

        sql_node = SqlNode(
            id=result.sql_id,
            name=result.sql_name,
            file_path=None,
            sql_content=result.sql_content,
            dialect=result.dialect,
        )
        self.graph.add_node(sql_node)

        for src in result.source_tables:
            tname = src["name"]
            if src.get("is_cte"):
                continue
            tid = self._ensure_table_node(tname, is_cte=False)
            self.graph.add_edge(Edge(
                id=_gen_id("e"),
                source_id=result.sql_id,
                target_id=tid,
                edge_type=EdgeType.READS_FROM,
            ))

        for tgt in result.target_tables:
            tname = tgt["name"]
            tid = self._ensure_table_node(tname, is_cte=False)
            self.graph.add_edge(Edge(
                id=_gen_id("e"),
                source_id=result.sql_id,
                target_id=tid,
                edge_type=EdgeType.WRITES_TO,
            ))
            self.table_registry.register_producer(tname, result.sql_id, tid)

        for cte in result.cte_tables:
            tid = self._ensure_table_node(cte["name"], is_cte=True)

        for col in result.columns:
            self._add_column_dependency(sql_node.id, col)

        self._current_ctes = []

    def _ensure_table_node(self, table_name: str, is_cte: bool = False) -> str:
        """确保表节点存在，返回节点 ID"""
        if table_name in self._table_nodes:
            return self._table_nodes[table_name]
        parts = table_name.split(".")
        catalog = parts[0] if len(parts) > 2 else None
        schema_name = parts[-2] if len(parts) > 1 else None
        short_name = parts[-1]
        node = TableNode(
            id=_gen_id("tbl"),
            name=short_name if not is_cte else table_name,
            catalog=catalog,
            schema_name=schema_name,
            is_cte=is_cte,
        )
        if is_cte:
            node.name = table_name
        self.graph.add_node(node)
        self._table_nodes[table_name] = node.id
        return node.id

    def _ensure_column_node(self, table_id: str, col_name: str, table_name_hint: str | None = None) -> str:
        """确保字段节点存在"""
        key = (table_id, col_name)
        if key in self._column_nodes:
            return self._column_nodes[key]
        node = ColumnNode(
            id=_gen_id("col"),
            name=col_name,
            table_id=table_id,
        )
        self.graph.add_node(node)
        self._column_nodes[key] = node.id
        self.graph.add_edge(Edge(
            id=_gen_id("e"),
            source_id=table_id,
            target_id=node.id,
            edge_type=EdgeType.HAS_COLUMN,
        ))
        return node.id

    def _add_column_dependency(self, sql_id: str, col_info: dict) -> None:
        """添加字段级 Transform 依赖"""
        col_name = col_info["name"]
        target_table_hint = col_info.get("table")
        expr = col_info.get("transform_expr", "")
        expr_type = _expr_type_from_str(col_info.get("transform_type", "function"))
        source_cols = col_info.get("source_columns", [])

        tr_node = TransformNode(
            id=_gen_id("tr"),
            name=f"tr_{col_name}",
            expression=expr,
            expression_type=expr_type,
        )
        self.graph.add_node(tr_node)

        self.graph.add_edge(Edge(
            id=_gen_id("e"),
            source_id=sql_id,
            target_id=tr_node.id,
            edge_type=EdgeType.CONTAINS,
        ))

        cte_names = [c["name"] for c in self._current_ctes]
        for src_col in source_cols:
            parts = src_col.split(".")
            src_col_name = parts[-1]
            src_table_name = ".".join(parts[:-1]) if len(parts) > 1 else None
            src_table_id = None
            if src_table_name and src_table_name in self._table_nodes:
                src_table_id = self._table_nodes[src_table_name]
            elif src_table_name:
                is_src_cte = src_table_name in cte_names
                src_table_id = self._ensure_table_node(src_table_name, is_cte=is_src_cte)
            if src_table_id:
                src_col_id = self._ensure_column_node(src_table_id, src_col_name)
                self.graph.add_edge(Edge(
                    id=_gen_id("e"),
                    source_id=src_col_id,
                    target_id=tr_node.id,
                    edge_type=EdgeType.COMPUTE_DEPENDENCY,
                ))

        target_tables = [e.target_id for e in self.graph.edges
                         if e.source_id == sql_id and e.edge_type == EdgeType.WRITES_TO]
        for ttid in target_tables:
            tbl_node = self.graph.get_node(ttid)
            if tbl_node and tbl_node.is_cte:
                continue
            out_col_id = self._ensure_column_node(ttid, col_name)
            self.graph.add_edge(Edge(
                id=_gen_id("e"),
                source_id=tr_node.id,
                target_id=out_col_id,
                edge_type=EdgeType.PRODUCES,
            ))

    def _link_cross_sql_lineage(self) -> None:
        """建立跨 SQL 的表级血缘边 (src_table -> dst_table)"""
        existing = set()
        for edge in self.graph.edges:
            if edge.edge_type == EdgeType.TABLE_LINEAGE:
                existing.add((edge.source_id, edge.target_id))
        sql_writes: dict = {}
        sql_reads: dict = {}
        for e in self.graph.edges:
            if e.edge_type == EdgeType.WRITES_TO:
                sql_writes.setdefault(e.source_id, []).append(e.target_id)
            elif e.edge_type == EdgeType.READS_FROM:
                sql_reads.setdefault(e.source_id, []).append(e.target_id)
        cte_table_ids = set()
        for node in self.graph.nodes:
            if isinstance(node, TableNode) and node.is_cte:
                cte_table_ids.add(node.id)
        for sql_id, src_tables in sql_reads.items():
            dst_tables = sql_writes.get(sql_id, [])
            for src_tid in src_tables:
                if src_tid in cte_table_ids:
                    continue
                for dst_tid in dst_tables:
                    if dst_tid in cte_table_ids:
                        continue
                    if src_tid != dst_tid and (src_tid, dst_tid) not in existing:
                        self.graph.add_edge(Edge(
                            id=_gen_id("e"),
                            source_id=src_tid,
                            target_id=dst_tid,
                            edge_type=EdgeType.TABLE_LINEAGE,
                        ))
                        existing.add((src_tid, dst_tid))
