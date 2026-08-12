# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

# sqlgraph/input/ddl_schema.py
"""从原始建表语句（DDL）解析表结构，生成字段消歧所需的列清单。

线上数仓的 schema 供给通常是整段原始 Hive `CREATE TABLE / CREATE VIEW`
语句，而非逐列展开的 `table_name,column_name,data_type`。本模块负责把前者
转换为后者，作为 :class:`~sqlgraph.input.csv_schema.SchemaRegistry` 的数据来源。

解析策略（两级）：
  1. 主路径：用 sqlglot 以 hive 方言解析，抽取 ColumnDef（含分区列），
     类型经 hive 方言归一化为小写（STRING -> string、BIGINT -> bigint）。
  2. 兜底路径：部分 `CREATE VIEW` 只有列名和 COMMENT、没有类型，sqlglot 会
     降级为 Command 无法取列；此时用正则从首个括号组抽取反引号列名，
     类型统一记为 string。

设计原则与全局一致：解析失败不抛异常、不猜测，返回空列表由上层决定兜底。
"""
from __future__ import annotations

import re
import csv
import sys
from typing import Iterator, Optional

import sqlglot
from sqlglot import exp

from sqlgraph.utils.logging import log_info, log_warn

# 提升 csv 字段上限：单条 DDL 文本可能很长
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

# 兜底：匹配反引号列名，且其后紧跟 COMMENT / 逗号 / 右括号，
# 借此排除表名本身与括号外的 COMMENT/PARTITIONED BY 等噪声。
_FALLBACK_COL_RE = re.compile(r"`([a-zA-Z0-9_]+)`(?=\s*(?:COMMENT|,|\)))", re.IGNORECASE)


def _table_suffix(name: str) -> str:
    """剥离 catalog.db 前缀，只保留表名后缀。

    与 SchemaRegistry 的后缀匹配语义对齐（get_table_columns 会按最后一段匹配）。
    """
    return name.split(".")[-1] if name else name


def _normalize_type(col_def: exp.ColumnDef) -> str:
    """把 sqlglot 的类型节点归一化为小写 hive 类型字符串。"""
    if not col_def.kind:
        return "string"
    try:
        return col_def.kind.sql(dialect="hive").lower()
    except Exception:
        return col_def.kind.sql().lower()


def _fallback_columns(ddl: str) -> list[tuple[str, str]]:
    """无类型 DDL（如纯列名 VIEW）的正则兜底，类型统一记 string。

    只扫描 ` AS ` 之前的头部，避免把 SELECT 主体里的字段也抓进来。
    """
    head = re.split(r"\bAS\b", ddl, maxsplit=1, flags=re.IGNORECASE)[0]
    seen = set()
    cols = []
    for name in _FALLBACK_COL_RE.findall(head):
        if name not in seen:
            seen.add(name)
            cols.append((name, "string"))
    return cols


def parse_ddl_columns(ddl: str) -> tuple[Optional[str], list[tuple[str, str]]]:
    """解析单条 DDL，返回 (表名后缀, [(列名, 类型), ...])。

    Args:
        ddl: 原始建表 / 建视图语句文本。

    Returns:
        (table_name, columns)。table_name 已剥离库前缀；columns 为按出现顺序
        排列的 (列名, 小写类型) 列表（含分区列）。完全无法解析时返回 (None, [])。
    """
    if not ddl or not ddl.strip():
        return None, []

    stmt = None
    try:
        stmt = sqlglot.parse_one(ddl, read="hive")
    except Exception:
        stmt = None

    # sqlglot 无法解析时会把 this 降级成字符串（Command），此时走兜底
    if stmt is None or isinstance(getattr(stmt, "this", None), str):
        table = _extract_table_name_regex(ddl)
        return table, _fallback_columns(ddl)

    # 表名：CREATE ... 的目标是 Schema/Table 节点
    table = None
    tbl_node = stmt.find(exp.Table)
    if tbl_node is not None:
        table = _table_suffix(tbl_node.sql(dialect="hive").replace("`", ""))

    cols = _extract_columns_from_stmt(stmt)

    # sqlglot 解析成功但没抽到任何列（少见的无类型定义）时兜底
    if not cols:
        cols = _fallback_columns(ddl)

    return table, cols


def _extract_columns_from_stmt(stmt: exp.Expression) -> list[tuple[str, str]]:
    """从已解析的语句中按出现顺序抽取列。

    覆盖三种情况：
      - 带类型 / 带 COMMENT 的列被解析为 ColumnDef；
      - 纯列名（无类型无 COMMENT）的列被解析为裸 Identifier（常见于 VIEW），
        这类列同样要收进来，类型记为 string；
      - 分区列位于独立的 PartitionedByProperty 里，一并抽取。
    """
    cols: list[tuple[str, str]] = []
    seen = set()

    def _add(name: str, dtype: str) -> None:
        if name and name not in seen:
            seen.add(name)
            cols.append((name, dtype))

    # 主体列定义：Schema 节点的 expressions（ColumnDef 或裸 Identifier）
    # 只遍历直接子节点，避免把 STRUCT<...> 等复杂类型里的嵌套字段当成表列。
    schema = stmt.this if isinstance(stmt.this, exp.Schema) else None
    if schema is not None:
        for e in schema.expressions:
            if isinstance(e, exp.ColumnDef):
                _add(e.name, _normalize_type(e))
            elif isinstance(e, exp.Identifier):
                _add(e.name, "string")
    else:
        # 没有 Schema 包裹时退回全局 ColumnDef 扫描
        for cd in stmt.find_all(exp.ColumnDef):
            _add(cd.name, _normalize_type(cd))

    # 分区列（PARTITIONED BY）：仅从 PartitionedByProperty 的 Schema 直接子节点抽取，
    # 同样不递归进复杂类型内部。
    for prop in stmt.find_all(exp.PartitionedByProperty):
        part_schema = prop.this
        part_exprs = getattr(part_schema, "expressions", None) or []
        for e in part_exprs:
            if isinstance(e, exp.ColumnDef):
                _add(e.name, _normalize_type(e))
            elif isinstance(e, exp.Identifier):
                _add(e.name, "string")

    return cols


def _extract_table_name_regex(ddl: str) -> Optional[str]:
    """兜底路径下用正则提取表名后缀。"""
    m = re.search(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:\w+\s+)*?(?:TABLE|VIEW)\s+"
        r"(?:IF\s+NOT\s+EXISTS\s+)?([`\w.]+)",
        ddl,
        re.IGNORECASE,
    )
    if not m:
        return None
    return _table_suffix(m.group(1).replace("`", ""))


def ddl_csv_to_schema_rows(csv_path: str) -> Iterator[tuple[str, str, str]]:
    """读取 `table_name,ddl` 两列 CSV，逐行产出 (表名, 列名, 类型) 三元组。

    产出的三元组可直接写成 `table_name,column_name,data_type` 的轻量 schema CSV，
    再交给 :meth:`SchemaRegistry.from_csv` 加载。

    Args:
        csv_path: 原始 DDL 供给文件路径，需含表头 `table_name,ddl`。

    Yields:
        (table_name, column_name, data_type) 三元组。
    """
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ddl = (row.get("ddl") or "").strip()
            if not ddl:
                continue
            table, cols = parse_ddl_columns(ddl)
            if not table or not cols:
                # 优先用 CSV 里显式给出的表名后缀兜底
                fallback_name = _table_suffix((row.get("table_name") or "").strip())
                table = table or fallback_name
            if not table:
                continue
            for cname, ctype in cols:
                yield table, cname, ctype
