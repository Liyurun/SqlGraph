# sqlgraph/input/sql_source.py
from __future__ import annotations
import csv
import hashlib
import os
import glob
import sys
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
    metadata: dict = field(default_factory=dict)


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
    def from_df_csv(
        cls,
        file_path: str,
        table_column: str = "table_name",
        sql_column: str = "code",
        encoding: str = "utf-8",
        deduplicate: bool = True,
        clean_runtime_statements: bool = True,
    ) -> "SqlSource":
        """从 table_name/code 格式的 df.csv 创建 SQL 输入源

        df.csv 是生产任务常见导出格式：每行代表一个任务，table_name 是任务/目标表名，
        code 是完整 SQL 脚本。这里会跳过空代码、null 代码，并按原始代码内容 hash
        去重，避免重复任务在图中生成重复 SQL 节点。
        """
        if not os.path.isfile(file_path):
            raise InputError(f"DataFrame CSV file not found: {file_path}")

        source = cls()
        seen_hashes: set[str] = set()
        csv.field_size_limit(sys.maxsize)

        with open(file_path, "r", encoding=encoding, newline="") as f:
            reader = csv.DictReader(f)
            fields = set(reader.fieldnames or [])
            if table_column not in fields or sql_column not in fields:
                raise InputError(
                    f"df CSV must contain '{table_column}' and '{sql_column}' columns"
                )

            for row_number, row in enumerate(reader, start=2):
                raw_sql = row.get(sql_column, "") or ""
                if not raw_sql.strip() or raw_sql.strip().lower() == "null":
                    continue

                content_hash = hashlib.sha256(raw_sql.encode("utf-8")).hexdigest()
                if deduplicate and content_hash in seen_hashes:
                    continue
                seen_hashes.add(content_hash)

                sql = (
                    clean_df_sql(raw_sql)
                    if clean_runtime_statements
                    else raw_sql
                )
                if not sql.strip():
                    continue

                table_name = (row.get(table_column, "") or "").strip()
                name = table_name or f"df_row_{row_number}"
                source._items.append(SqlSourceItem(
                    name=name,
                    content=sql,
                    source_path=f"{file_path}#{row_number}",
                    source_type="df_csv",
                    metadata={
                        "source_uri": f"{name}.sql",
                        "content_hash": content_hash,
                        "raw_content": raw_sql,
                        "row_number": row_number,
                        "table_name": table_name,
                    },
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
                if is_df_csv(path_or_source):
                    return cls.from_df_csv(path_or_source)
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


def is_df_csv(file_path: str) -> bool:
    """判断文件是否为 table_name/code 格式的 df.csv"""
    if not file_path.lower().endswith(".csv"):
        return False
    try:
        with open(file_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
    except Exception:
        return False
    normalized = {h.strip().strip("\ufeff") for h in header}
    return {"table_name", "code"}.issubset(normalized)


def clean_df_sql(sql: str) -> str:
    """清洗 df.csv 中的运行配置语句，保留可解析的业务 SQL"""
    statements = _split_sql_statements(sql)
    kept: list[str] = []
    for stmt in statements:
        stripped = _strip_leading_sql_comments(stmt).strip()
        low = stripped.lower()
        if not stripped or low == "null":
            continue
        if low.startswith((
            "set ", "add ", "use ", "msck ", "repair ", "cache ", "uncache ",
            "analyze ", "drop partition", "alter table",
        )):
            continue
        if low.startswith("insert overwrite directory"):
            continue
        if low.startswith(("import ", "from ", "#!", "# ", "echo ", "python ")):
            continue
        kept.append(stmt.strip())
    return ";\n".join(kept)


def _split_sql_statements(sql: str) -> list[str]:
    """按分号切分 SQL，避免切到单双引号内部的分号"""
    statements: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    prev = ""
    for ch in sql:
        if ch == "'" and prev != "\\" and not in_double:
            in_single = not in_single
        elif ch == '"' and prev != "\\" and not in_single:
            in_double = not in_double
        if ch == ";" and not in_single and not in_double:
            statements.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        prev = ch
    tail = "".join(buf)
    if tail.strip():
        statements.append(tail)
    return statements


def _strip_leading_sql_comments(stmt: str) -> str:
    """去掉语句开头的 SQL 注释，方便判断真实语句类型"""
    text = stmt.lstrip()
    changed = True
    while changed:
        changed = False
        if text.startswith("--"):
            parts = text.split("\n", 1)
            text = parts[1].lstrip() if len(parts) == 2 else ""
            changed = True
        elif text.startswith("/*"):
            end = text.find("*/")
            if end >= 0:
                text = text[end + 2:].lstrip()
                changed = True
    return text
