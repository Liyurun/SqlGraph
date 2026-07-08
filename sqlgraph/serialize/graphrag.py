# sqlgraph/serialize/graphrag.py
"""
GraphRAG payload 序列化模块

将 PropertyGraph 输出为符合 GraphRAG schema v2 规范的 JSON payload，
包含 entities（实体）、relations（关系）和 schema（元数据）三部分。

参考格式：
  {
    "entities": [{"id", "name", "type", "properties": {...}}, ...],
    "relations": [{"id", "source", "target", "type", "properties": {...}}, ...],
    "schema": {"version": "2.0", "entity_types": [...], "relation_types": [...]}
  }
"""

from __future__ import annotations

import os
import json
from typing import Dict, Any, List

from sqlgraph.model import PropertyGraph, NodeType
from sqlgraph.utils.logging import log_info


def to_graphrag(graph: PropertyGraph, output_path: str) -> Dict[str, Any]:
    """将图输出为 GraphRAG entity/relation payload 格式（schema v2）

    Args:
        graph: 要序列化的 PropertyGraph 对象
        output_path: 输出 JSON 文件路径，父目录不存在时自动创建

    Returns:
        构造好的 payload 字典（同时写入文件）
    """
    entities: List[Dict[str, Any]] = []
    relations: List[Dict[str, Any]] = []

    # 转换节点为 entities
    # 将 id/name/node_type 提取为顶层字段，其余放入 properties
    for node in graph.nodes:
        nd = node.to_dict()
        entity_type = nd.get("node_type", "entity")
        entity = {
            "id": nd["id"],
            "name": nd.get("name", nd["id"]),
            "type": entity_type,
            "properties": {
                k: v
                for k, v in nd.items()
                if k not in ("id", "name", "node_type") and v is not None
            },
        }
        entities.append(entity)

    # 转换边为 relations
    # 将 id/source/target/type 提取为顶层字段，其余放入 properties
    for edge in graph.edges:
        ed = edge.to_dict()
        relation = {
            "id": ed["id"],
            "source": ed["source"],
            "target": ed["target"],
            "type": ed["type"],
            "properties": {
                k: v
                for k, v in ed.items()
                if k not in ("id", "source", "target", "type") and v is not None
            },
        }
        relations.append(relation)

    # 构建 schema v2 元数据
    # entity_types 从 NodeType 枚举获取所有已定义类型
    # relation_types 从图中实际出现的边类型去重获取
    schema_v2 = {
        "version": "2.0",
        "entity_types": [t.value for t in NodeType],
        "relation_types": list({e.edge_type.value for e in graph.edges}),
    }

    # 组装最终 payload
    payload: Dict[str, Any] = {
        "entities": entities,
        "relations": relations,
        "schema": schema_v2,
    }

    # 确保输出目录存在并写入 JSON 文件
    parent_dir = os.path.dirname(output_path)
    os.makedirs(parent_dir if parent_dir else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log_info(
        f"GraphR payload written to {output_path}: "
        f"{len(entities)} entities, {len(relations)} relations"
    )
    return payload
