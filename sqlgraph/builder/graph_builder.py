# sqlgraph/builder/graph_builder.py
from __future__ import annotations
import uuid
import hashlib
import re
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


def _det_id(prefix: str, key: str) -> str:
    """确定性 id：由内容 key 生成，保证相同实体在多次运行/多条 SQL 间稳定

    取 24 个十六进制字符（96 bit）。在 160 万级表/字段规模下，40 bit 空间存在
    实际可感知的碰撞风险，96 bit 可将碰撞概率降到可忽略。
    """
    return f"{prefix}_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:24]}"


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


def _normalize_output_name(name: str | None) -> str:
    """输出字段名用于表达式合并 key，按常见 SQL 语义做大小写归一"""
    return (name or "").strip().strip("`\"").lower()


def _result_table_name(sql_name: str | None) -> str:
    """为无显式目标表的 SELECT 构造稳定的结果集表名"""
    safe_name = re.sub(r"\W+", "_", sql_name or "select").strip("_").lower()
    return f"{safe_name or 'select'}_result"


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
        self._expr_nodes: dict = {}
        self._edge_seen: set = set()
        self._current_ctes: list = []

    def _add_edge_dedup(self, source_id: str, target_id: str, edge_type: EdgeType, **props) -> None:
        """按 (source,target,type) 去重后添加边，避免共享节点导致重复边"""
        key = (source_id, target_id, edge_type)
        if key in self._edge_seen:
            return
        self._edge_seen.add(key)
        self.graph.add_edge(Edge(
            id=_gen_id("e"),
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            properties=props or {},
        ))

    def build_from_source(self, source: SqlSource) -> PropertyGraph:
        """从 SqlSource 构建完整图"""
        log_info(f"Building graph from {len(source)} SQL source(s)")
        results = []
        df_failed = 0
        df_failed_samples = []
        for item in source:
            try:
                parse_result = self.parser.parse(
                    item.content, name=item.name, file_path=item.source_path
                )
            except Exception as e:
                if item.source_type == "df_csv":
                    df_failed += 1
                    if len(df_failed_samples) < 5:
                        df_failed_samples.append(f"{item.name}: {e}")
                    continue
                raise
            self._apply_source_metadata(parse_result, item)
            results.append(parse_result)
            self._add_parse_result(parse_result, item)
        self._link_cross_sql_lineage()
        if df_failed:
            log_warn(
                f"Skipped {df_failed} df_csv SQL item(s) due to parse errors. "
                f"Samples: {' | '.join(df_failed_samples)}"
            )
        log_info(f"Graph built: {self.graph.stats()}")
        return self.graph

    def build_from_sql(self, sql: str, name: str = "query") -> PropertyGraph:
        """从单条 SQL 字符串构建图"""
        result = self.parser.parse(sql, name=name)
        self._add_parse_result(result)
        self._link_cross_sql_lineage()
        return self.graph

    def _apply_source_metadata(self, result: SqlParseResult, item) -> None:
        """把输入源元数据应用到解析结果，支持 df.csv 稳定复现"""
        meta = getattr(item, "metadata", {}) or {}
        content_hash = meta.get("content_hash")
        if content_hash:
            result.sql_id = f"sql_{content_hash[:12]}"
        raw_content = meta.get("raw_content")
        if raw_content:
            result.sql_content = raw_content

    def _add_parse_result(self, result: SqlParseResult, item=None) -> None:
        """将单个 SQL 的解析结果添加到图中"""
        self._current_ctes = result.cte_tables
        meta = getattr(item, "metadata", {}) if item else {}

        sql_node = SqlNode(
            id=result.sql_id,
            name=result.sql_name,
            file_path=result.file_path,
            sql_content=result.sql_content,
            dialect=result.dialect,
            source_uri=meta.get("source_uri"),
            content_hash=meta.get("content_hash"),
            source_type=getattr(item, "source_type", None) if item else None,
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

        if not result.target_tables and any(col.get("table") is None for col in result.columns):
            tname = _result_table_name(result.sql_name)
            tid = self._ensure_table_node(tname, is_cte=False)
            self.graph.add_edge(Edge(
                id=_gen_id("e"),
                source_id=result.sql_id,
                target_id=tid,
                edge_type=EdgeType.WRITES_TO,
            ))
            self.table_registry.register_producer(tname, result.sql_id, tid)

        for cte in result.cte_tables:
            self._ensure_table_node(
                cte["name"],
                is_cte=True,
                aliases=[cte.get("alias")] if cte.get("alias") else None,
                logic_fingerprint=cte.get("logic_fingerprint"),
            )

        for col in result.columns:
            self._add_column_dependency(sql_node.id, col)

        self._current_ctes = []

    def _ensure_table_node(
        self,
        table_name: str,
        is_cte: bool = False,
        aliases: list[str] | None = None,
        logic_fingerprint: str | None = None,
    ) -> str:
        """确保表节点存在，返回节点 ID（id 由表名确定性生成）"""
        if table_name in self._table_nodes:
            node = self.graph.get_node(self._table_nodes[table_name])
            if node and is_cte:
                for alias in aliases or []:
                    if alias and alias not in node.aliases:
                        node.aliases.append(alias)
                if logic_fingerprint and not node.logic_fingerprint:
                    node.logic_fingerprint = logic_fingerprint
            return self._table_nodes[table_name]
        parts = table_name.split(".")
        catalog = parts[0] if len(parts) > 2 else None
        schema_name = parts[-2] if len(parts) > 1 else None
        short_name = parts[-1]
        node = TableNode(
            id=_det_id("tbl", table_name),
            name=short_name if not is_cte else table_name,
            catalog=catalog,
            schema_name=schema_name,
            is_cte=is_cte,
            aliases=[a for a in (aliases or []) if a],
            logic_fingerprint=logic_fingerprint,
        )
        if is_cte:
            node.name = table_name
        self.graph.add_node(node)
        self._table_nodes[table_name] = node.id
        return node.id

    def _ensure_column_node(self, table_id: str, col_name: str, table_name_hint: str | None = None) -> str:
        """确保字段节点存在（id 由 表id.列名 确定性生成）"""
        key = (table_id, col_name)
        if key in self._column_nodes:
            return self._column_nodes[key]
        node = ColumnNode(
            id=_det_id("col", f"{table_id}.{col_name}"),
            name=col_name,
            table_id=table_id,
        )
        self.graph.add_node(node)
        self._column_nodes[key] = node.id
        self._add_edge_dedup(table_id, node.id, EdgeType.HAS_COLUMN)
        return node.id

    def _ensure_physical_column(self, physical_column: str) -> str | None:
        """由 "table.col" 物理列串确保表/列节点存在，返回列节点 id"""
        if not physical_column:
            return None
        parts = physical_column.split(".")
        if len(parts) < 2:
            return None
        col_name = parts[-1]
        table_name = ".".join(parts[:-1])
        cte_names = [c["name"] for c in self._current_ctes]
        if table_name in self._table_nodes:
            table_id = self._table_nodes[table_name]
        else:
            table_id = self._ensure_table_node(table_name, is_cte=table_name in cte_names)
        return self._ensure_column_node(table_id, col_name)

    def _ensure_expr_node(self, info: dict, output_name: str) -> str:
        """确保表达式节点存在，按 逻辑指纹+输出字段名 去重复用，返回节点 id"""
        fp = info["fingerprint"]
        normalized_output = _normalize_output_name(output_name)
        merge_key = f"{fp}::{normalized_output}"
        if merge_key in self._expr_nodes:
            return self._expr_nodes[merge_key]
        node_id = _det_id("expr", merge_key)
        node = TransformNode(
            id=node_id,
            name=info.get("expression", "") or fp,
            expression=info.get("expression", ""),
            expression_type=_expr_type_from_str(info.get("expr_type", "function")),
            fingerprint=fp,
            op=info.get("op", ""),
            output_name=output_name,
        )
        self.graph.add_node(node)
        self._expr_nodes[merge_key] = node.id
        return node_id

    def _add_column_dependency(self, sql_id: str, col_info: dict) -> None:
        """把一个输出字段的加工逻辑接入图。

        - 透传列：物理列 -> 输出列 直接血缘，不建表达式节点；
        - 其它：整条表达式作为一个节点，该表达式引用的每个物理列 ->
          表达式 COMPUTE_DEPENDENCY 边，SQL -> 表达式 CONTAINS 边，
          表达式 -> 输出列 PRODUCES 边。相同指纹的表达式节点全局复用。
        """
        col_name = col_info["name"]

        cte_names = {c["name"] for c in self._current_ctes}
        out_col_ids = []
        target_table = col_info.get("table")
        if target_table:
            table_id = self._ensure_table_node(target_table, is_cte=target_table in cte_names)
            out_col_ids.append(self._ensure_column_node(table_id, col_name))
        else:
            target_tables = [e.target_id for e in self.graph.edges
                             if e.source_id == sql_id and e.edge_type == EdgeType.WRITES_TO]
            for ttid in target_tables:
                tbl_node = self.graph.get_node(ttid)
                if tbl_node and tbl_node.is_cte:
                    continue
                out_col_ids.append(self._ensure_column_node(ttid, col_name))

        # 透传列：物理列直接连输出列
        if col_info.get("passthrough"):
            src_col_id = self._ensure_physical_column(col_info.get("physical_column"))
            if src_col_id:
                for out_col_id in out_col_ids:
                    self._add_edge_dedup(src_col_id, out_col_id, EdgeType.COMPUTE_DEPENDENCY)
            return

        expr_nodes = col_info.get("expr_nodes") or {}
        root_fp = col_info.get("expr_root")
        if not expr_nodes or not root_fp:
            return

        # 整条表达式 + 输出字段名 对应唯一一个节点。
        # 同逻辑同字段收敛；同逻辑不同字段保留独立节点，避免误合并别名语义。
        info = expr_nodes[root_fp]
        expr_node_id = self._ensure_expr_node(info, col_name)

        # SQL -> 表达式 包含边
        self._add_edge_dedup(sql_id, expr_node_id, EdgeType.CONTAINS)
        # 表达式引用的每个物理列 -> 表达式 计算依赖边
        for phys_col in info.get("source_columns", []):
            src_col_id = self._ensure_physical_column(phys_col)
            if src_col_id:
                self._add_edge_dedup(src_col_id, expr_node_id, EdgeType.COMPUTE_DEPENDENCY)

        # 表达式 -> 输出列
        for out_col_id in out_col_ids:
            self._add_edge_dedup(expr_node_id, out_col_id, EdgeType.PRODUCES)

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
