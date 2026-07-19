# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

# sqlgraph/model/graph.py
from typing import Any
from sqlgraph.model.nodes import BaseNode, SqlNode, TableNode, ColumnNode, TransformNode, NodeType
from sqlgraph.model.edges import Edge, EdgeType


class PropertyGraph:
    """属性图 - SqlGraph 的核心数据模型"""

    def __init__(self):
        self._nodes: dict = {}
        self._edges: list = []
        self._node_by_name: dict = {}

    @property
    def nodes(self) -> list:
        """所有节点列表"""
        return list(self._nodes.values())

    @property
    def edges(self) -> list:
        """所有边列表"""
        return list(self._edges)

    def add_node(self, node: BaseNode) -> None:
        """添加节点，重复 id 抛出异常"""
        if node.id in self._nodes:
            raise ValueError(f"Node with id '{node.id}' already exists")
        self._nodes[node.id] = node
        # 短名可能重复（如 db1.orders 与 db2.orders），不覆盖已有索引；
        # 对 TableNode 额外注册 full_name，保证全限定表名查询可靠。
        self._node_by_name.setdefault(node.name, node.id)
        if isinstance(node, TableNode):
            self._node_by_name.setdefault(node.full_name, node.id)

    def add_edge(self, edge: Edge) -> None:
        """添加边"""
        self._edges.append(edge)

    def get_node(self, node_id: str):
        """按 ID 获取节点"""
        return self._nodes.get(node_id)

    def get_node_by_name(self, name: str):
        """按名称获取节点"""
        nid = self._node_by_name.get(name)
        if nid:
            return self._nodes.get(nid)
        for node in self._nodes.values():
            if node.name == name:
                return node
        return None

    def stats(self) -> dict:
        """统计节点/边数量"""
        counts = {
            "sql_count": 0,
            "table_count": 0,
            "column_count": 0,
            "transform_count": 0,
            "edge_count": len(self._edges),
        }
        for node in self._nodes.values():
            if isinstance(node, SqlNode):
                counts["sql_count"] += 1
            elif isinstance(node, TableNode):
                counts["table_count"] += 1
            elif isinstance(node, ColumnNode):
                counts["column_count"] += 1
            elif isinstance(node, TransformNode):
                counts["transform_count"] += 1
        counts["node_count"] = len(self._nodes)
        return counts

    def get_upstream(self, table_name: str) -> list:
        """获取指定表的上游表名列表"""
        tgt_id = self._node_by_name.get(table_name)
        if not tgt_id:
            return []
        upstream = []
        for edge in self._edges:
            if edge.edge_type == EdgeType.TABLE_LINEAGE and edge.target_id == tgt_id:
                src = self._nodes.get(edge.source_id)
                if src and isinstance(src, TableNode):
                    upstream.append(src.full_name)
        return upstream

    def get_downstream(self, table_name: str) -> list:
        """获取指定表的下游表名列表"""
        src_id = self._node_by_name.get(table_name)
        if not src_id:
            return []
        downstream = []
        for edge in self._edges:
            if edge.edge_type == EdgeType.TABLE_LINEAGE and edge.source_id == src_id:
                tgt = self._nodes.get(edge.target_id)
                if tgt and isinstance(tgt, TableNode):
                    downstream.append(tgt.full_name)
        return downstream

    def get_nodes_by_type(self, node_type: NodeType) -> list:
        """按类型获取节点列表"""
        return [n for n in self._nodes.values() if n.node_type == node_type]

    def get_edges_by_type(self, edge_type: EdgeType) -> list:
        """按类型获取边列表"""
        return [e for e in self._edges if e.edge_type == edge_type]

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges],
        }
