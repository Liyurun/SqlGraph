# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

# sqlgraph/serialize/__init__.py
"""
序列化层模块

提供将 PropertyGraph 输出为多种格式的功能：
  - to_csv: 输出 nodes.csv + edges.csv（通用 CSV 格式）
  - to_graphrag: 输出 GraphRAG schema v2 JSON payload
  - to_json / to_dict: 基础 JSON / 字典序列化
  - to_networkx: 转换为 NetworkX DiGraph（可选依赖）
"""

from sqlgraph.serialize.csv import to_csv
from sqlgraph.serialize.graphrag import to_graphrag
from sqlgraph.serialize.json_output import to_json, to_dict
from sqlgraph.serialize.networkx import to_networkx

__all__ = ["to_csv", "to_graphrag", "to_json", "to_dict", "to_networkx"]
