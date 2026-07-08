# sqlgraph/input/sql_source.py
from __future__ import annotations
import os
import glob
from dataclasses import dataclass, field
from typing import Iterator
from sqlgraph.utils.errors import InputError


@dataclass
class SqlSourceItem:
    """单个 SQL 输入项

    Attributes:
        name: 输入项名称（通常是文件名或自定义名称）
        content: SQL 内容文本
        source_path: 源文件路径（如果来自文件）
        source_type: 来源类型：file/dir/string/dataframe
    """
    name: str
    content: str
    source_path: str | None = None
    source_type: str = "string"


class SqlSource:
    """统一 SQL 输入源，支持多源混合输入

    支持从文件、目录、SQL 字符串、DataFrame 等多种来源加载 SQL，
    并提供统一的迭代访问接口。支持混合多种来源输入。
    """

    def __init__(self):
        self._items: list[SqlSourceItem] = []

    @classmethod
    def from_file(cls, file_path: str, encoding: str = "utf-8") -> "SqlSource":
        """从单个 SQL 文件创建输入源

        Args:
            file_path: SQL 文件路径
            encoding: 文件编码，默认 utf-8

        Returns:
            SqlSource 实例

        Raises:
            InputError: 文件不存在时抛出
        """
        source = cls()
        if not os.path.isfile(file_path):
            raise InputError(f"SQL file not found: {file_path}")
        with open(file_path, "r", encoding=encoding) as f:
            content = f.read()
        name = os.path.splitext(os.path.basename(file_path))[0]
        source._items.append(SqlSourceItem(
            name=name, content=content, source_path=file_path, source_type="file"
        ))
        return source

    @classmethod
    def from_dir(
        cls, dir_path: str, pattern: str = "*.sql",
        encoding: str = "utf-8", recursive: bool = False
    ) -> "SqlSource":
        """从目录下的 SQL 文件创建输入源

        Args:
            dir_path: 目录路径
            pattern: 文件匹配模式，默认 *.sql
            encoding: 文件编码，默认 utf-8
            recursive: 是否递归搜索子目录，默认 False

        Returns:
            SqlSource 实例

        Raises:
            InputError: 目录不存在时抛出
        """
        source = cls()
        if not os.path.isdir(dir_path):
            raise InputError(f"Directory not found: {dir_path}")
        search_pattern = (
            os.path.join(dir_path, "**", pattern) if recursive
            else os.path.join(dir_path, pattern)
        )
        files = sorted(glob.glob(search_pattern, recursive=recursive))
        for fp in files:
            with open(fp, "r", encoding=encoding) as f:
                content = f.read()
            name = os.path.splitext(os.path.basename(fp))[0]
            source._items.append(SqlSourceItem(
                name=name, content=content, source_path=fp, source_type="file"
            ))
        return source

    @classmethod
    def from_string(cls, sql: str, name: str = "inline_sql") -> "SqlSource":
        """从 SQL 字符串创建输入源

        Args:
            sql: SQL 文本内容
            name: 输入项名称，默认 inline_sql

        Returns:
            SqlSource 实例
        """
        source = cls()
        source._items.append(SqlSourceItem(
            name=name, content=sql, source_type="string"
        ))
        return source

    @classmethod
    def from_dataframe(cls, df, table_name: str) -> "SqlSource":
        """从 Pandas DataFrame 创建输入源（作为输入表，生成 CREATE TABLE 语义）

        Args:
            df: Pandas DataFrame 实例
            table_name: 表名

        Returns:
            SqlSource 实例
        """
        source = cls()
        cols = ", ".join([f"{c} STRING" for c in df.columns])
        ddl = f"-- DataFrame input: {table_name}\n-- columns: {list(df.columns)}\n"
        source._items.append(SqlSourceItem(
            name=f"df_{table_name}", content=ddl, source_type="dataframe"
        ))
        return source

    @classmethod
    def from_any(cls, path_or_source: str | list, dialect: str | None = None) -> "SqlSource":
        """智能输入：字符串路径可能是文件或目录，自动检测

        支持传入：
        - 单个字符串：自动判断是文件路径、目录路径还是 SQL 字符串
        - 列表：列表元素可以是 SqlSource 实例或字符串，递归合并

        Args:
            path_or_source: 字符串或列表输入
            dialect: SQL 方言（预留参数，暂未使用）

        Returns:
            SqlSource 实例
        """
        source = cls()
        if isinstance(path_or_source, list):
            for item in path_or_source:
                if isinstance(item, SqlSource):
                    source._items.extend(item._items)
                elif isinstance(item, str):
                    sub = cls.from_any(item)
                    source._items.extend(sub._items)
            return source
        if isinstance(path_or_source, str):
            if os.path.isdir(path_or_source):
                return cls.from_dir(path_or_source)
            elif os.path.isfile(path_or_source):
                return cls.from_file(path_or_source)
            else:
                return cls.from_string(path_or_source)
        return source

    def add_item(self, item: SqlSourceItem) -> None:
        """添加单个 SQL 项

        Args:
            item: SqlSourceItem 实例
        """
        self._items.append(item)

    def __iter__(self) -> Iterator[SqlSourceItem]:
        """迭代器支持"""
        return iter(self._items)

    def __len__(self) -> int:
        """获取输入项数量"""
        return len(self._items)

    def __getitem__(self, idx):
        """通过索引访问输入项"""
        return self._items[idx]
