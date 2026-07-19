# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

# sqlgraph/visualize/__init__.py
"""
可视化层包初始化模块。

对外导出 to_html（生成 HTML 文件）和 to_notebook（Notebook 内嵌展示）
两个核心函数，是 sqlgraph 可视化功能的统一入口。
"""
from sqlgraph.visualize.html import to_html, to_notebook

__all__ = ["to_html", "to_notebook"]
