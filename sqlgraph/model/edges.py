# sqlgraph/model/edges.py
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class EdgeType(str, Enum):
    """边类型枚举"""
    WRITES_TO = "writes_to"
    READS_FROM = "reads_from"
    TABLE_LINEAGE = "table_lineage"
    PRODUCES = "produces"
    COMPUTE_DEPENDENCY = "compute_dependency"
    HAS_COLUMN = "has_column"
    CONTAINS = "contains"


@dataclass
class Edge:
    """图的边"""
    id: str
    source_id: str
    target_id: str
    edge_type: EdgeType
    properties: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为字典（使用 source/target/type 键名）"""
        return {
            "id": self.id,
            "source": self.source_id,
            "target": self.target_id,
            "type": self.edge_type.value,
            **self.properties,
        }
