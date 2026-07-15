# sqlgraph/parser/base.py
from __future__ import annotations
import uuid
import hashlib
import re
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
        self._parsed_derived_queries = set()
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
        elif isinstance(stmt, exp.Command) and self._parse_create_view_command(stmt, result):
            return
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
            self._parse_query_expression(stmt.expression, result)

    def _parse_create(self, stmt: exp.Create, result: SqlParseResult) -> None:
        """解析 CREATE TABLE/VIEW 语句
        
        提取目标表，并解析其内部的 SELECT 查询（CTAS 或 CREATE VIEW）
        
        Args:
            stmt: sqlglot Create 节点
            result: 解析结果对象
        """
        target = stmt.this
        if target:
            tgt_name = _create_target_to_name(target)
            if tgt_name:
                result.target_tables.append({"name": tgt_name, "is_cte": False})
        if stmt.expression:
            self._parse_query_expression(stmt.expression, result)

    def _parse_create_view_command(self, stmt: exp.Command, result: SqlParseResult) -> bool:
        """兼容 sqlglot 降级为 Command 的 Hive/Spark CREATE VIEW DDL"""
        parsed = _extract_create_view_command_parts(stmt)
        if not parsed:
            return False
        target_name, query_sql = parsed
        result.target_tables.append({"name": target_name, "is_cte": False})
        try:
            query = sqlglot.parse_one(query_sql, read=self.dialect)
        except Exception as e:
            message = f"Failed to parse CREATE VIEW query body for {target_name}: {e}"
            result.errors.append(message)
            log_warn(message)
            return True
        self._parse_query_expression(query, result)
        return True

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
            if cte.this:
                self._register_derived_query(cte_name, cte.this, result)
            else:
                self._cte_aliases[cte_name] = cte_name
                if result:
                    result.cte_tables.append({"name": cte_name, "alias": cte_name, "is_cte": True})

    def _register_derived_query(self, alias: str, query, result: SqlParseResult | None) -> str:
        """注册 CTE/子查询逻辑身份，相同逻辑与输出字段的 derived query 共用名称"""
        logical_name, fingerprint = _derived_query_identity(query, self.dialect)
        self._cte_aliases[alias] = logical_name
        if result:
            result.cte_tables.append({
                "name": logical_name,
                "alias": alias,
                "is_cte": True,
                "logic_fingerprint": fingerprint,
            })
        if logical_name not in self._parsed_derived_queries:
            self._parsed_derived_queries.add(logical_name)
            self._parse_query_expression(query, result, cte_name=logical_name)
        return logical_name

    def _parse_query_expression(
        self,
        query,
        result: SqlParseResult | None = None,
        cte_name: str | None = None,
        output_names: list[str] | None = None,
    ) -> None:
        """解析 SELECT/UNION/子查询表达式"""
        if result is None:
            result = getattr(self, "_current_result", None)
        if result is None or query is None:
            return
        if isinstance(query, exp.Select):
            self._parse_select(query, result, cte_name=cte_name, output_names=output_names)
            return
        if isinstance(query, exp.Union):
            names = output_names or _query_output_names(query.this)
            self._parse_query_expression(query.this, result, cte_name=cte_name, output_names=names)
            self._parse_query_expression(query.expression, result, cte_name=cte_name, output_names=names)
            return
        if isinstance(query, exp.Subquery):
            self._parse_query_expression(query.this, result, cte_name=cte_name, output_names=output_names)
            return
        for select in query.find_all(exp.Select):
            self._parse_select(select, result, cte_name=cte_name, output_names=output_names)

    def _parse_select(
        self,
        stmt: exp.Select,
        result: SqlParseResult | None = None,
        cte_name: str | None = None,
        output_names: list[str] | None = None,
    ) -> None:
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
        for source in _iter_select_sources(stmt):
            if isinstance(source, exp.Subquery):
                alias = source.alias_or_name
                tname = self._register_derived_query(alias, source.this, result)
                is_cte = True
            else:
                raw_name = _table_to_name(source)
                alias = source.alias_or_name
                tname = self._cte_aliases.get(raw_name, raw_name)
                if alias and alias != raw_name:
                    self._cte_aliases[alias] = tname
                is_cte = raw_name in self._cte_aliases or tname in self._cte_aliases.values()
            already_added = any(t["name"] == tname and t.get("alias") == alias for t in result.source_tables)
            already_in_target = any(t["name"] == tname for t in result.target_tables)
            if not already_added and not already_in_target:
                result.source_tables.append({"name": tname, "alias": alias, "is_cte": is_cte})
                if not is_cte:
                    self._current_source_tables.append(tname)
            # 解析用的候选源表包含 CTE，保证从 CTE 读取的裸列能绑定到 CTE
            if tname not in self._current_all_sources:
                self._current_all_sources.append(tname)
        lateral_outputs = _collect_lateral_outputs(stmt)
        self._parse_columns(stmt, result, cte_name, output_names=output_names, lateral_outputs=lateral_outputs)
        self._current_source_tables = prev_sources
        self._current_all_sources = prev_all

    def _parse_columns(
        self,
        stmt: exp.Select,
        result: SqlParseResult,
        cte_name: str | None = None,
        output_names: list[str] | None = None,
        lateral_outputs: dict[str, dict] | None = None,
    ) -> None:
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
        lateral_outputs = lateral_outputs or {}
        for idx, sel_expr in enumerate(selects):
            if isinstance(sel_expr, exp.Star):
                continue
            col_name = (
                output_names[idx]
                if output_names and idx < len(output_names) and output_names[idx]
                else sel_expr.alias_or_name
            )
            if not col_name:
                continue
            inner = sel_expr.unalias() if hasattr(sel_expr, "unalias") else sel_expr
            lateral_match = _lookup_lateral_output_with_suffix(inner, lateral_outputs)
            lateral_source = lateral_match[0] if lateral_match and not lateral_match[1] else None
            expanded_inner = _expand_lateral_references(inner, lateral_outputs)
            lineage_expr = lateral_source["expression"] if lateral_source else expanded_inner
            dag_expr = lateral_source["expression"] if lateral_source else expanded_inner
            transform = self._analyze_expression(lineage_expr)
            source_cols = self._extract_source_columns(lineage_expr, resolver=resolver)
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

            if lateral_source:
                root_fp, nodes = expr_dag.decompose(dag_expr, resolver.resolve, dialect=self.dialect or None)
                col_entry["expr_root"] = root_fp
                col_entry["expr_nodes"] = nodes
            elif not lateral_match and expr_dag.is_passthrough(inner):
                # 纯透传列：不建表达式节点，直接记录物理列
                col_entry["passthrough"] = True
                col_entry["physical_column"] = resolver.resolve(inner)
            else:
                root_fp, nodes = expr_dag.decompose(dag_expr, resolver.resolve, dialect=self.dialect or None)
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

    def _extract_source_columns(self, expr, resolver: ColumnResolver | None = None) -> list[str]:
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
            if resolver:
                columns.add(resolver.resolve(col))
                continue
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


def _create_target_to_name(target) -> str | None:
    """从 CREATE 目标中提取表/视图名，兼容带字段列表的 Schema 节点"""
    if isinstance(target, exp.Schema):
        target = target.this
    if isinstance(target, exp.Table):
        return _table_to_name(target)
    name = getattr(target, "name", None)
    return name or None


def _extract_create_view_command_parts(stmt: exp.Command) -> tuple[str, str] | None:
    """从 sqlglot Command fallback 中提取 (view_name, query_sql)"""
    if str(stmt.this).upper() != "CREATE":
        return None
    text = f"{stmt.this}{stmt.expression or ''}"
    target_name = _extract_create_view_name(text)
    if not target_name:
        return None
    as_pos = _find_top_level_as(text)
    if as_pos < 0:
        return None
    query_sql = _strip_wrapping_parentheses(text[as_pos + 2:].strip().rstrip(";"))
    if not query_sql:
        return None
    return target_name, query_sql


_CREATE_VIEW_NAME_RE = re.compile(
    r"""
    ^\s*CREATE\s+
    (?:OR\s+REPLACE\s+)?
    (?:(?:GLOBAL|LOCAL)\s+)?
    (?:(?:TEMPORARY|TEMP)\s+)?
    VIEW\s+
    (?:IF\s+NOT\s+EXISTS\s+)?
    (?P<name>
        (?:`[^`]+`|"[^"]+"|[A-Za-z_][\w$-]*)
        (?:\s*\.\s*(?:`[^`]+`|"[^"]+"|[A-Za-z_][\w$-]*))*
    )
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)


def _extract_create_view_name(sql: str) -> str | None:
    match = _CREATE_VIEW_NAME_RE.search(sql)
    if not match:
        return None
    raw_name = match.group("name")
    parts = []
    for part in re.finditer(r"`([^`]+)`|\"([^\"]+)\"|([A-Za-z_][\w$-]*)", raw_name):
        parts.append(next(group for group in part.groups() if group))
    return ".".join(parts) if parts else None


def _find_top_level_as(sql: str) -> int:
    """寻找最外层 AS 关键字，跳过字段列表、属性、字符串和注释"""
    depth = 0
    in_single = False
    in_double = False
    in_backtick = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue
        if not in_single and not in_double and not in_backtick:
            if ch == "-" and nxt == "-":
                in_line_comment = True
                i += 2
                continue
            if ch == "/" and nxt == "*":
                in_block_comment = True
                i += 2
                continue

        if ch == "`" and not in_single and not in_double:
            in_backtick = not in_backtick
        elif ch == "'" and not in_double and not in_backtick:
            in_single = not in_single
        elif ch == '"' and not in_single and not in_backtick:
            in_double = not in_double
        elif not in_single and not in_double and not in_backtick:
            if ch == "(":
                depth += 1
            elif ch == ")" and depth > 0:
                depth -= 1
            elif depth == 0 and sql[i:i + 2].lower() == "as":
                before = sql[i - 1] if i > 0 else " "
                after = sql[i + 2] if i + 2 < len(sql) else " "
                if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                    return i
        i += 1
    return -1


def _strip_wrapping_parentheses(sql: str) -> str:
    text = sql.strip()
    if not text.startswith("("):
        return text
    depth = 0
    in_single = False
    in_double = False
    in_backtick = False
    for idx, ch in enumerate(text):
        if ch == "`" and not in_single and not in_double:
            in_backtick = not in_backtick
        elif ch == "'" and not in_double and not in_backtick:
            in_single = not in_single
        elif ch == '"' and not in_single and not in_backtick:
            in_double = not in_double
        elif not in_single and not in_double and not in_backtick:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return text[1:idx].strip() if not text[idx + 1:].strip() else text
    return text


def _query_output_names(query) -> list[str]:
    """获取查询输出字段名；UNION 使用左侧查询的字段名作为最终输出名"""
    if isinstance(query, exp.Select):
        return [expr.alias_or_name for expr in query.expressions if not isinstance(expr, exp.Star)]
    if isinstance(query, exp.Union):
        return _query_output_names(query.this)
    if isinstance(query, exp.Subquery):
        return _query_output_names(query.this)
    first_select = next(query.find_all(exp.Select), None) if query is not None else None
    return _query_output_names(first_select) if first_select is not None else []


def _derived_query_identity(query, dialect: str | None) -> tuple[str, str]:
    """用规范化查询逻辑与输出字段生成 derived query 身份"""
    canonical = query.sql(dialect=dialect, normalize=True, comments=False)
    outputs = [_normalize_identifier(name) for name in _query_output_names(query)]
    key = f"{canonical}||outputs:{','.join(outputs)}"
    fingerprint = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"subq_{fingerprint}", fingerprint


def _normalize_identifier(name: str | None) -> str:
    return (name or "").strip().strip("`\"").lower()


def _iter_select_sources(stmt: exp.Select):
    """仅遍历当前 SELECT 作用域的直接 FROM/JOIN 来源，避免扫入 CTE 定义内部表"""
    from_expr = stmt.args.get("from_")
    if from_expr is not None:
        source = from_expr.args.get("this")
        if isinstance(source, (exp.Table, exp.Subquery)):
            yield source
    for join in stmt.args.get("joins") or []:
        source = join.args.get("this")
        if isinstance(source, (exp.Table, exp.Subquery)):
            yield source


def _collect_lateral_outputs(stmt: exp.Select) -> dict[str, dict]:
    """收集 LATERAL VIEW explode(...) 产生的列别名"""
    outputs: dict[str, dict] = {}
    for lateral in stmt.args.get("laterals") or []:
        generator = _expand_lateral_references(lateral.this, outputs) if lateral.this is not None else None
        alias = lateral.args.get("alias")
        if generator is None or alias is None:
            continue
        table_alias = alias.this.name if alias.this is not None else ""
        columns = [c.name for c in alias.args.get("columns") or [] if getattr(c, "name", "")]
        if not columns and table_alias:
            columns = [table_alias]
        for column in columns:
            payload = {"expression": generator, "table_alias": table_alias, "column": column}
            outputs[column] = payload
            if table_alias:
                outputs[f"{table_alias}.{column}"] = payload
    return outputs


def _lookup_lateral_output(expr, lateral_outputs: dict[str, dict]) -> dict | None:
    """判断 SELECT 表达式是否引用 lateral view 产出的列"""
    match = _lookup_lateral_output_with_suffix(expr, lateral_outputs)
    return match[0] if match else None


def _lookup_lateral_output_with_suffix(expr, lateral_outputs: dict[str, dict]) -> tuple[dict, list[str]] | None:
    """返回 lateral 产出列及剩余的 struct 访问路径"""
    if not isinstance(expr, exp.Column):
        return None
    parts = _column_part_names(expr)
    if not parts:
        return None
    if len(parts) >= 2:
        qualified = f"{parts[0]}.{parts[1]}"
        if qualified in lateral_outputs:
            return lateral_outputs[qualified], parts[2:]
    if parts[0] in lateral_outputs:
        return lateral_outputs[parts[0]], parts[1:]
    return None


def _column_part_names(column: exp.Column) -> list[str]:
    """获取 Column 的完整分段名，兼容 a.b.c 这类 struct 字段访问"""
    parts = []
    for part in column.parts:
        name = getattr(part, "name", None) or getattr(part, "this", None)
        if name:
            parts.append(str(name))
    return parts


def _build_lateral_expression(payload: dict, suffix: list[str]):
    """将 lateral generator 与剩余 struct 路径组合成可分解表达式"""
    expr = payload["expression"].copy()
    for part in suffix:
        expr = exp.Dot(this=expr, expression=exp.to_identifier(part))
    return expr


def _expand_lateral_references(expr, lateral_outputs: dict[str, dict]):
    """把表达式中引用的 lateral 产出列替换为其 generator 表达式"""
    if not lateral_outputs:
        return expr
    direct = _lookup_lateral_output_with_suffix(expr, lateral_outputs)
    if direct:
        return _build_lateral_expression(*direct)

    def _replace(node):
        lateral_source = _lookup_lateral_output_with_suffix(node, lateral_outputs)
        if lateral_source:
            return _build_lateral_expression(*lateral_source)
        return node

    return expr.copy().transform(_replace)
