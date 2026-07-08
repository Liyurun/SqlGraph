# sqlgraph/serialize/csv.py
"""
CSV 序列化模块

将 PropertyGraph 输出为两个 CSV 文件：
  - nodes.csv：存储所有节点（表、列、SQL 等）
  - edges.csv：存储所有边（血缘关系、依赖关系等）

这是一种通用的 property graph CSV 格式，便于在 Excel、Pandas、
Neo4j import tool、Gephi 等工具中直接加载使用。
"""

from __future__ import annotations

import os
import csv
from typing import List, Dict, Any

from sqlgraph.model import PropertyGraph
from sqlgraph.utils.logging import log_info


def to_csv(graph: PropertyGraph, output_dir: str) -> None:
    """将图输出为 nodes.csv 和 edges.csv（通用 property graph CSV 格式）

    Args:
        graph: 要序列化的 PropertyGraph 对象
        output_dir: 输出目录路径，不存在时自动创建

    输出文件：
        nodes.csv - 包含所有节点，列为节点属性，id/name/node_type 优先排列
        edges.csv - 包含所有边，列为边属性，id/source/target/type 优先排列
    """
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    nodes_path = os.path.join(output_dir, "nodes.csv")
    edges_path = os.path.join(output_dir, "edges.csv")

    # 将所有节点和边转换为字典
    node_dicts: List[Dict[str, Any]] = [n.to_dict() for n in graph.nodes]
    edge_dicts: List[Dict[str, Any]] = [e.to_dict() for e in graph.edges]

    # 收集所有字段（按优先级排列关键字段）
    node_fields = _collect_fields(node_dicts)
    edge_fields = _collect_fields(edge_dicts)

    # 写入 nodes.csv
    # extrasaction="ignore" 表示忽略 DictWriter 中未声明的额外字段
    with open(nodes_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=node_fields, extrasaction="ignore")
        writer.writeheader()
        for nd in node_dicts:
            writer.writerow(nd)

    # 写入 edges.csv
    with open(edges_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=edge_fields, extrasaction="ignore")
        writer.writeheader()
        for ed in edge_dicts:
            writer.writerow(ed)

    log_info(
        f"CSV written to {output_dir}: {len(node_dicts)} nodes, {len(edge_dicts)} edges"
    )


def _collect_fields(dicts: List[Dict[str, Any]]) -> List[str]:
    """从字典列表中收集所有字段名，按优先级排列关键字段

    优先字段顺序：id > name > node_type > type > source > target
    其余字段按首次出现顺序排列在后面。

    Args:
        dicts: 字典列表，每个字典代表一条记录（节点或边）

    Returns:
        有序的字段名列表
    """
    fields: List[str] = []
    seen: set = set()

    # 定义关键字段的优先级顺序
    priority = ["id", "name", "node_type", "type", "source", "target"]

    # 先添加优先级字段（按优先级顺序）
    for p in priority:
        for d in dicts:
            if p in d and p not in seen:
                fields.append(p)
                seen.add(p)

    # 再添加其余字段（按首次出现顺序）
    for d in dicts:
        for k in d.keys():
            if k not in seen:
                fields.append(k)
                seen.add(k)

    return fields
