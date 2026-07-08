# sqlgraph/input/csv_schema.py
from __future__ import annotations
import os
import csv
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
from sqlgraph.utils.logging import log_info, log_warn


@dataclass
class ColumnSchema:
    """字段 Schema 定义

    Attributes:
        name: 字段名
        data_type: 数据类型，默认 string
        description: 字段描述，默认为空
    """
    name: str
    data_type: str = "string"
    description: str = ""


@dataclass
class TableSchema:
    """表 Schema 定义

    Attributes:
        table_name: 表名
        columns: 字段列表，ColumnSchema 实例数组
    """
    table_name: str
    columns: list = field(default_factory=list)


class SchemaRegistry:
    """表 Schema 注册表，用于字段消歧

    维护表名到字段列表的映射，支持：
    - 注册表及其字段
    - 查询表字段
    - 字段消歧（在多个候选表中确定字段所属表）
    - 从 CSV 文件加载 schema
    - 从字典创建 schema
    """

    def __init__(self):
        self._tables: dict = {}

    def register_table(self, table_name: str, columns: list) -> None:
        """注册表及其字段列表

        Args:
            table_name: 表名（支持带 schema 前缀，如 db.table）
            columns: 字段列表，可以是字符串列表或字典列表
        """
        self._tables[table_name] = TableSchema(
            table_name=table_name,
            columns=[
                ColumnSchema(name=c) if isinstance(c, str)
                else ColumnSchema(**c) for c in columns
            ]
        )

    def get_table_columns(self, table_name: str) -> list[str] | None:
        """获取表的字段名列表

        先尝试完全匹配表名，如果找不到则尝试匹配表名后缀（不考虑 schema 前缀）

        Args:
            table_name: 表名

        Returns:
            字段名列表，如果表不存在返回 None
        """
        schema = self._tables.get(table_name)
        if not schema:
            for tname in self._tables:
                if tname.split(".")[-1] == table_name:
                    return [c.name for c in self._tables[tname].columns]
            return None
        return [c.name for c in schema.columns]

    def resolve_column(self, column_name: str, table_candidates: list[str]) -> str | None:
        """在候选表中消歧字段，返回 table.column 或 None

        当字段名在多个候选表中唯一存在时，返回完整的 table.column 引用；
        如果字段不存在或存在多个匹配，返回 None

        Args:
            column_name: 字段名
            table_candidates: 候选表名列表

        Returns:
            "table.column" 格式的字符串，无法消歧时返回 None
        """
        matches = []
        for t in table_candidates:
            cols = self.get_table_columns(t)
            if cols and column_name in cols:
                matches.append(t)
        if len(matches) == 1:
            return f"{matches[0]}.{column_name}"
        return None

    def has_table(self, table_name: str) -> bool:
        """检查表是否已注册

        支持完全匹配和后缀匹配

        Args:
            table_name: 表名

        Returns:
            表存在返回 True，否则返回 False
        """
        if table_name in self._tables:
            return True
        for tname in self._tables:
            if tname.split(".")[-1] == table_name:
                return True
        return False

    @classmethod
    def from_csv(cls, csv_path: str) -> "SchemaRegistry":
        """从 CSV 文件加载 Schema

        CSV 格式要求: table_name,column_name,data_type[,description]

        Args:
            csv_path: CSV 文件路径

        Returns:
            SchemaRegistry 实例
        """
        registry = cls()
        if not os.path.isfile(csv_path):
            log_warn(f"Schema file not found: {csv_path}")
            return registry
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                df = pd.DataFrame(list(reader))
        table_columns = {}
        for _, row in df.iterrows():
            tname = str(row.get("table_name", "")).strip()
            cname = str(row.get("column_name", "")).strip()
            dtype = str(row.get("data_type", "string")).strip()
            if not tname or not cname:
                continue
            if tname not in table_columns:
                table_columns[tname] = []
            table_columns[tname].append(ColumnSchema(name=cname, data_type=dtype))
        for tname, cols in table_columns.items():
            registry._tables[tname] = TableSchema(table_name=tname, columns=cols)
        log_info(f"Loaded schema for {len(table_columns)} tables from {csv_path}")
        return registry

    @classmethod
    def from_dict(cls, schema_dict: dict) -> "SchemaRegistry":
        """从字典创建 Schema，格式: {table_name: [col1, col2, ...]}

        Args:
            schema_dict: 表到字段列表的映射字典

        Returns:
            SchemaRegistry 实例
        """
        registry = cls()
        for tname, cols in schema_dict.items():
            registry.register_table(tname, cols)
        return registry
