# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

# sqlgraph/serialize/json_output.py
"""
JSON / Dict 序列化模块

提供最基础的序列化功能：将 PropertyGraph 转换为 Python 字典或 JSON 文件。
字典格式与 PropertyGraph.to_dict() 保持一致：
  {"nodes": [...], "edges": [...]}
"""

from __future__ import annotations

import os
import json
from typing import Dict, Any, Optional

from sqlgraph.model import PropertyGraph


def to_json(graph: PropertyGraph, output_path: Optional[str] = None) -> Dict[str, Any]:
    """将图序列化为 JSON 文件

    Args:
        graph: 要序列化的 PropertyGraph 对象
        output_path: 输出 JSON 文件路径，为 None 时不写文件，仅返回字典

    Returns:
        图的字典表示 {"nodes": [...], "edges": [...]}
    """
    data = graph.to_dict()
    if output_path:
        parent_dir = os.path.dirname(output_path)
        os.makedirs(parent_dir if parent_dir else ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def to_dict(graph: PropertyGraph) -> Dict[str, Any]:
    """将图转为字典

    是 PropertyGraph.to_dict() 的便捷包装，保持 API 一致性。

    Args:
        graph: 要转换的 PropertyGraph 对象

    Returns:
        图的字典表示 {"nodes": [...], "edges": [...]}
    """
    return graph.to_dict()
