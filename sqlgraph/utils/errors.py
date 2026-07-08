from __future__ import annotations


class SqlGraphError(Exception):
    """sqlGraph 基础异常类"""
    pass


class SqlParseError(SqlGraphError):
    """SQL 解析失败异常"""

    def __init__(self, message: str, sql: str | None = None, file_path: str | None = None):
        super().__init__(message)
        self.sql = sql
        self.file_path = file_path


class SchemaNotFoundError(SqlGraphError):
    """表 Schema 未找到异常"""

    def __init__(self, table_name: str):
        super().__init__(f"Schema not found for table: {table_name}")
        self.table_name = table_name


class AmbiguousColumnError(SqlGraphError):
    """字段引用歧义异常"""

    def __init__(self, column_name: str, candidates: list):
        super().__init__(
            f"Ambiguous column '{column_name}', candidates: {candidates}"
        )
        self.column_name = column_name
        self.candidates = candidates


class CircularDependencyError(SqlGraphError):
    """循环依赖异常"""

    def __init__(self, chain: list):
        super().__init__(f"Circular dependency detected: {' -> '.join(chain)}")
        self.chain = chain


class InputError(SqlGraphError):
    """输入错误（配置问题，立即失败）"""
    pass
