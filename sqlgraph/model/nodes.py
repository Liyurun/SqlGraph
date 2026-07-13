# sqlgraph/model/nodes.py
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    """节点类型枚举"""
    SQL = "sql"
    TABLE = "table"
    COLUMN = "column"
    TRANSFORM = "transform"


class ExpressionType(str, Enum):
    """Transform 表达式类型枚举"""
    CASE_WHEN = "case_when"
    AGG = "agg"
    CAST = "cast"
    ARITHMETIC = "arithmetic"
    COALESCE = "coalesce"
    WINDOW = "window"
    UNION = "union"
    LITERAL = "literal"
    COLUMN_REF = "column_ref"
    FUNCTION = "function"


@dataclass
class BaseNode:
    """节点基类"""
    id: str
    name: str
    node_type: NodeType = field(init=False)

    def to_dict(self) -> dict:
        """序列化为字典"""
        d = asdict(self)
        d["node_type"] = self.node_type.value
        return d


@dataclass
class SqlNode(BaseNode):
    """SQL 任务/文件节点"""
    file_path: str | None = None
    sql_content: str | None = None
    dialect: str | None = None
    created_at: str | None = None
    source_uri: str | None = None
    content_hash: str | None = None
    source_type: str | None = None

    def __post_init__(self):
        self.node_type = NodeType.SQL


@dataclass
class TableNode(BaseNode):
    """物理表或 CTE 节点"""
    catalog: str | None = None
    schema_name: str | None = None
    is_cte: bool = False
    columns: list = field(default_factory=list)

    def __post_init__(self):
        self.node_type = NodeType.TABLE

    @property
    def full_name(self) -> str:
        """获取完整表名（catalog.schema.name）"""
        parts = []
        if self.catalog:
            parts.append(self.catalog)
        if self.schema_name:
            parts.append(self.schema_name)
        parts.append(self.name)
        return ".".join(parts)


@dataclass
class ColumnNode(BaseNode):
    """字段节点"""
    table_id: str | None = None
    data_type: str | None = None
    is_primary_key: bool = False

    def __post_init__(self):
        self.node_type = NodeType.COLUMN


@dataclass
class TransformNode(BaseNode):
    """字段计算表达式节点（表达式 Merkle DAG 中的一个逻辑节点）

    在表达式 DAG 模型中，一个节点代表一段计算逻辑（如 SUM(x)、a/b、ROUND(...)）。
    fingerprint 表示纯逻辑内容指纹；构图时节点身份还会纳入输出字段名，
    保证相同逻辑只有在产出字段相同时才收敛。
    op 为算子/函数标签（如 sum/div/round/case/window），叶子列/字面量为空。
    """
    name: str = ""
    expression: str = ""
    expression_type: ExpressionType = ExpressionType.FUNCTION
    fingerprint: str = ""
    op: str = ""
    output_name: str | None = None

    def __post_init__(self):
        self.node_type = NodeType.TRANSFORM
        if not self.name and self.expression:
            self.name = self.expression

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["expression_type"] = self.expression_type.value
        return d


# 语义别名：在表达式 DAG 语境下，Transform 节点即"表达式节点"
ExpressionNode = TransformNode
