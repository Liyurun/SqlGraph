# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

# sqlgraph/serialize/networkx.py
"""
NetworkX 转换模块（可选依赖）

将 PropertyGraph 转换为 networkx.DiGraph（有向图）对象，
便于使用 NetworkX 进行图分析、路径查找、中心性计算等操作。

使用前需要安装 networkx：
    pip install networkx
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import networkx as nx
    from networkx import DiGraph

from sqlgraph.model import PropertyGraph


def to_networkx(graph: PropertyGraph) -> "DiGraph":
    """将图转换为 networkx.DiGraph（需要安装 networkx）

    转换规则：
      - 每个节点的 id 作为 DiGraph 的节点 ID
      - 节点的其余属性（name, node_type, 等）作为节点属性
      - 每条边的 source -> target 作为有向边
      - 边的其余属性（type, 等）作为边属性

    Args:
        graph: 要转换的 PropertyGraph 对象

    Returns:
        networkx.DiGraph 有向图对象

    Raises:
        ImportError: 未安装 networkx 时抛出
    """
    try:
        import networkx as nx
    except ImportError:
        raise ImportError(
            "networkx is required for to_networkx(). Install with: pip install networkx"
        )

    G = nx.DiGraph()

    # 添加节点：id 作为节点标识，其余字典项作为属性
    for node in graph.nodes:
        nd = node.to_dict()
        node_id = nd.pop("id")
        G.add_node(node_id, **nd)

    # 添加边：source -> target 作为有向边，其余字典项作为属性
    for edge in graph.edges:
        ed = edge.to_dict()
        src = ed.pop("source")
        tgt = ed.pop("target")
        G.add_edge(src, tgt, **ed)

    return G
