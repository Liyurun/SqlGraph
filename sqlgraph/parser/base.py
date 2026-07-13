# sqlgraph/parser/base.py
from __future__ import annotations
import uuid
from typing import Optional
import sqlglot
from sqlglot import exp
from sqlgraph.utils.logging import log_info, log_warn
from sqlgraph.input.csv_schema import SchemaRegistry
from sqlgraph.utils.errors import SqlParseError
from sqlgraph.parser import expr_dag


# 无法确定归属物理表时的占位表名
UNKNOWN_TABLE = "UNKNOWN"


class ColumnResolver:
    """列 → 物理表解析器

    捕获当前 SELECT 作用域的上下文快照（源表、别名映射、schema），
    把 sqlglot 的 exp.Column 解析成物理列串 "table.column"。

    解析顺序：
    1. 有限定名：经别名映射到物理表；
    2. 无限定名、仅单一源表：绑定到该表；
    3. 无限定名、多表：用 schema 消歧（唯一匹配才采纳）；
    4. 都无法确定：绑定到 UNKNOWN 占位表，绝不瞎猜。
    """

    def __init__(self, source_tables: list[str], alias_map: dict, schema_registry: SchemaRegistry | None,
                 all_sources: list[str] | None = None):
        self.source_tables = list(source_tables)
        # 包含 CTE 在内的全部候选源表，用于单源绑定与消歧
        self.all_sources = list(all_sources) if all_sources is not None else list(source_tables)
        self.alias_map = dict(alias_map)
        self.schema_registry = schema_registry

    def resolve(self, col) -> str:
        """把 exp.Column 解析为 "table.column" 物理列串"""
        col_name = col.name
        table_part = col.table
        if table_part:
            resolved_table = self.alias_map.get(table_part, table_part)
            return f"{resolved_table}.{col_name}"
        # 无限定名、唯一候选源表（含 CTE）：直接绑定
        if len(self.all_sources) == 1:
            return f"{self.all_sources[0]}.{col_name}"
        # 无限定名、多源：优先用 schema 在物理源表中消歧
        if self.schema_registry and len(self.source_tables) > 1:
            hit = self.schema_registry.resolve_column(col_name, self.source_tables)
            if hit:
                return hit
        return f"{UNKNOWN_TABLE}.{col_name}"


def _gen_id(prefix: str = "n") -> str:
    """生成唯一节点 ID
    
    Args:
        prefix: ID 前缀，默认为 "n"
    
    Returns:
        唯一 ID 字符串，格式为 "{prefix}_{8位十六进制随机数}"
    """
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class SqlParseResult:
    """单条 SQL 解析结果
    
    存储一条 SQL 语句解析后的表级和字段级血缘信息
    
    Attributes:
        sql_id: SQL 唯一标识
        sql_name: SQL 名称
        sql_content: 原始 SQL 内容
        file_path: SQL 来源路径
        dialect: SQL 方言
        source_tables: 源表列表，每个元素为 {name, alias, is_cte}
        target_tables: 目标表列表，每个元素为 {name, is_cte}
        cte_tables: CTE 表列表，每个元素为 {name, is_cte}
        columns: 字段列表，每个元素含 name/table 及表达式 DAG 字段
                 (passthrough, physical_column, expr_root, expr_nodes)，
                 并保留兼容字段 (transform_expr, transform_type, source_columns)
        errors: 解析过程中的错误信息列表
    """
    def __init__(self):
        self.sql_id: str = ""
        self.sql_name: str = ""
        self.sql_content: str = ""
        self.file_path: str | None = None
        self.dialect: str = ""
        self.source_tables: list[dict] = []
        self.target_tables: list[dict] = []
        self.cte_tables: list[dict] = []
        self.columns: list[dict] = []
        self.errors: list[str] = []


class SqlParser:
    """SQL 解析器，基于 SQLGlot
    
    解析 SQL 语句，提取表级和字段级血缘关系。支持 SELECT、INSERT、CREATE TABLE/VIEW、CTE 等语句类型。
    
    Attributes:
        dialect: SQL 方言（如 "spark", "hive", "mysql" 等）
        schema_registry: Schema 注册表，用于字段消歧
        _cte_aliases: CTE 别名映射，存储 CTE 名称到其定义的映射
        _current_source_tables: 当前 SELECT 语句的源表列表（用于递归处理）
    """

    def __init__(self, dialect: str | None = None, schema_registry: SchemaRegistry | None = None):
        self.dialect = dialect
        self.schema_registry = schema_registry
        self._cte_aliases: dict = {}
        self._current_source_tables: list[str] = []

    def parse(self, sql: str, name: str = "sql", file_path: str | None = None) -> SqlParseResult:
        """解析单条 SQL，返回 ParseResult
        
        Args:
            sql: SQL 语句字符串
            name: SQL 名称，默认为 "sql"
            file_path: SQL 文件路径（用于错误提示）
        
        Returns:
            SqlParseResult 解析结果对象
        
        Raises:
            SqlParseError: SQL 解析失败时抛出
        """
        result = SqlParseResult()
        result.sql_id = _gen_id("sql")
        result.sql_name = name
        result.sql_content = sql
        result.file_path = file_path
        result.dialect = self.dialect or ""
        self._cte_aliases = {}
        self._current_source_tables = []
        self._current_all_sources = []
        self._current_result = result
        try:
            statements = sqlglot.parse(sql, read=self.dialect)
        except Exception as e:
            raise SqlParseError(f"Failed to parse SQL: {e}", sql=sql, file_path=file_path)
        for stmt in statements:
            if stmt is None:
                continue
            self._parse_statement(stmt, result)
        return result

    def _parse_statement(self, stmt, result: SqlParseResult) -> None:
        """解析单个语句
        
        根据语句类型分发到对应的解析方法
        
        Args:
            stmt: sqlglot 表达式节点
            result: 解析结果对象
        """
        if isinstance(stmt, exp.Insert):
            self._parse_insert(stmt, result)
        elif isinstance(stmt, exp.Select):
            self._parse_select(stmt, result)
        elif isinstance(stmt, exp.Create):
            self._parse_create(stmt, result)
        else:
            log_warn(f"Unsupported statement type: {type(stmt).__name__}")

    def _parse_insert(self, stmt: exp.Insert, result: SqlParseResult) -> None:
        """解析 INSERT OVERWRITE/INTO 语句
        
        提取目标表，并解析其内部的 SELECT 查询
        
        Args:
            stmt: sqlglot Insert 节点
            result: 解析结果对象
        """
        self._extract_ctes(stmt)
        target = stmt.this
        if target:
            tgt_name = _table_to_name(target)
            result.target_tables.append({"name": tgt_name, "is_cte": False})
        if stmt.expression:
            if isinstance(stmt.expression, exp.Select):
                self._parse_select(stmt.expression, result)

    def _parse_create(self, stmt: exp.Create, result: SqlParseResult) -> None:
        """解析 CREATE TABLE/VIEW 语句
        
        提取目标表，并解析其内部的 SELECT 查询（CTAS 或 CREATE VIEW）
        
        Args:
            stmt: sqlglot Create 节点
            result: 解析结果对象
        """
        target = stmt.this
        if target:
            tgt_name = _table_to_name(target)
            result.target_tables.append({"name": tgt_name, "is_cte": False})
        if stmt.expression and isinstance(stmt.expression, exp.Select):
            self._parse_select(stmt.expression, result)

    def _extract_ctes(self, stmt) -> None:
        """从语句中提取并注册 CTE
        
        处理 Select/Insert 等语句的 CTE，提取所有 CTE 定义并注册
        
        Args:
            stmt: sqlglot 语句节点（可能是 Select 或 Insert）
        """
        ctes = getattr(stmt, "ctes", None)
        if not ctes:
            return
        result = getattr(self, "_current_result", None)
        for cte in ctes:
            cte_name = cte.alias_or_name
            self._cte_aliases[cte_name] = cte_name
            if result:
                result.cte_tables.append({"name": cte_name, "is_cte": True})
            if cte.this and isinstance(cte.this, exp.Select):
                self._parse_select(cte.this, result, cte_name=cte_name)

    def _parse_select(self, stmt: exp.Select, result: SqlParseResult | None = None, cte_name: str | None = None) -> None:
        """解析 SELECT 语句，提取源表和字段
        
        递归处理子查询时，通过保存和恢复 _current_source_tables 来避免上下文污染
        
        Args:
            stmt: sqlglot Select 节点
            result: 解析结果对象，None 时使用 self._current_result
            cte_name: 当前是否在解析 CTE 内部，为 CTE 名称时表示在解析该 CTE
        """
        if result is None:
            result = getattr(self, "_current_result", None)
        if result is None:
            return
        self._extract_ctes(stmt)
        prev_sources = getattr(self, "_current_source_tables", []).copy()
        prev_all = getattr(self, "_current_all_sources", []).copy()
        self._current_source_tables = []
        self._current_all_sources = []
        for table in stmt.find_all(exp.Table):
            tname = _table_to_name(table)
            alias = table.alias_or_name
            if alias and alias != tname:
                self._cte_aliases[alias] = tname
            is_cte = tname in self._cte_aliases
            already_added = any(t["name"] == tname for t in result.source_tables)
            already_in_target = any(t["name"] == tname for t in result.target_tables)
            if not already_added and not already_in_target:
                result.source_tables.append({"name": tname, "alias": alias, "is_cte": is_cte})
                if not is_cte:
                    self._current_source_tables.append(tname)
            # 解析用的候选源表包含 CTE，保证从 CTE 读取的裸列能绑定到 CTE
            if tname not in self._current_all_sources:
                self._current_all_sources.append(tname)
        for union in stmt.find_all(exp.Union):
            pass
        self._parse_columns(stmt, result, cte_name)
        self._current_source_tables = prev_sources
        self._current_all_sources = prev_all

    def _parse_columns(self, stmt: exp.Select, result: SqlParseResult, cte_name: str | None = None) -> None:
        """解析输出字段及其来源
        
        Args:
            stmt: sqlglot Select 节点
            result: 解析结果对象
            cte_name: 当前是否在解析 CTE 内部
        """
        selects = stmt.expressions
        resolver = ColumnResolver(
            source_tables=self._current_source_tables,
            alias_map=self._cte_aliases,
            schema_registry=self.schema_registry,
            all_sources=getattr(self, "_current_all_sources", None),
        )
        for sel_expr in selects:
            if isinstance(sel_expr, exp.Star):
                continue
            col_name = sel_expr.alias_or_name
            if not col_name:
                continue
            inner = sel_expr.unalias() if hasattr(sel_expr, "unalias") else sel_expr
            transform = self._analyze_expression(sel_expr)
            source_cols = self._extract_source_columns(sel_expr)
            target_table = cte_name
            if target_table is None and result.target_tables:
                target_table = result.target_tables[-1]["name"]

            col_entry = {
                "name": col_name,
                "table": target_table,
                # 兼容旧字段：parser 单测仍读取 transform_type/transform_expr/source_columns
                "transform_expr": transform["expression"],
                "transform_type": transform["type"],
                "source_columns": source_cols,
                # 表达式 DAG 字段
                "passthrough": False,
                "physical_column": None,
                "expr_root": None,
                "expr_nodes": {},
            }

            if expr_dag.is_passthrough(inner):
                # 纯透传列：不建表达式节点，直接记录物理列
                col_entry["passthrough"] = True
                col_entry["physical_column"] = resolver.resolve(inner)
            else:
                root_fp, nodes = expr_dag.decompose(inner, resolver.resolve, dialect=self.dialect or None)
                col_entry["expr_root"] = root_fp
                col_entry["expr_nodes"] = nodes

            result.columns.append(col_entry)

    def _analyze_expression(self, expr) -> dict:
        """分析表达式类型
        
        判断字段的转换类型：case_when、agg、cast、window、coalesce、arithmetic、column_ref、literal、function 等
        
        Args:
            expr: sqlglot 表达式节点
        
        Returns:
            包含 expression（表达式字符串）和 type（类型）的字典
        """
        inner = expr.unalias() if hasattr(expr, "unalias") else expr
        expr_str = expr.sql()
        if isinstance(inner, exp.Case):
            return {"expression": expr_str, "type": "case_when"}
        if isinstance(inner, exp.AggFunc):
            return {"expression": expr_str, "type": "agg"}
        if isinstance(inner, exp.Cast):
            return {"expression": expr_str, "type": "cast"}
        if isinstance(inner, exp.Window):
            return {"expression": expr_str, "type": "window"}
        if isinstance(inner, exp.Coalesce):
            return {"expression": expr_str, "type": "coalesce"}
        if isinstance(inner, exp.Round) or isinstance(inner, exp.Div) or isinstance(inner, exp.Mul):
            return {"expression": expr_str, "type": "arithmetic"}
        if isinstance(inner, exp.Column):
            return {"expression": inner.sql(), "type": "column_ref"}
        if isinstance(inner, exp.Literal):
            return {"expression": inner.sql(), "type": "literal"}
        if isinstance(inner, exp.Nullif):
            return {"expression": expr_str, "type": "arithmetic"}
        if isinstance(inner, exp.Anonymous):
            return {"expression": expr_str, "type": "function"}
        for child in inner.find_all(exp.Column):
            if child == inner:
                return {"expression": inner.sql(), "type": "column_ref"}
        if inner.find(exp.AggFunc):
            return {"expression": expr_str, "type": "agg"}
        return {"expression": expr_str, "type": "function"}

    def _extract_source_columns(self, expr) -> list[str]:
        """提取表达式中引用的源字段
        
        递归查找表达式中的所有 Column 节点，解析为 table.column 格式
        
        Args:
            expr: sqlglot 表达式节点
        
        Returns:
            源字段列表，格式为 ["table1.col1", "table2.col2", ...]
        """
        columns = set()
        inner = expr.unalias() if hasattr(expr, "unalias") else expr
        for col in inner.find_all(exp.Column):
            parts = []
            table_part = col.table
            col_part = col.name
            if table_part:
                resolved_table = self._cte_aliases.get(table_part, table_part)
                parts.append(resolved_table)
            elif self.schema_registry and len(self._get_all_source_tables()) == 1:
                srcs = self._get_all_source_tables()
                if srcs:
                    parts.append(srcs[0])
            parts.append(col_part)
            columns.add(".".join(parts))
        return list(columns)

    def _get_all_source_tables(self) -> list[str]:
        """获取当前 SELECT 上下文中的所有源表名
        
        Returns:
            源表名列表
        """
        return self._current_source_tables


def _table_to_name(table) -> str:
    """将 sqlglot Table 节点转为字符串表名
    
    处理 catalog.db.table 或 db.table 或 table 等格式
    
    Args:
        table: sqlglot Table 节点
    
    Returns:
        表名字符串
    """
    parts = []
    if table.catalog:
        parts.append(table.catalog)
    if table.db:
        parts.append(table.db)
    parts.append(table.name)
    return ".".join(parts)
