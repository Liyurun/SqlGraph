# sqlgraph/__init__.py
"""
SQLGraph - SQL 血缘图构建框架

一个轻量级的 SQL 血缘和数据资产图谱构建框架，支持多种 SQL 方言，
提供从 SQL 解析到图谱构建、序列化输出、交互式可视化的完整工具链。

主要功能：
  - 解析多种 SQL 方言（Spark/Hive/Presto/BigQuery 等）
  - 构建表级和字段级血缘关系图
  - 支持 CSV/GraphRAG/JSON/NetworkX 等多种序列化格式
  - 生成 Cytoscape.js 交互式 HTML 可视化
  - 提供简洁的 Python API 和命令行工具

快速开始:
    >>> from sqlgraph import build_graph, to_html
    >>> graph = build_graph("SELECT * FROM source_table", dialect="spark")
    >>> to_html(graph, output_path="lineage.html", auto_open=True)
"""
from __future__ import annotations

# 高层 API 入口
from sqlgraph.api import build_graph

# 核心数据模型
from sqlgraph.model import PropertyGraph

# 序列化和可视化模块（作为子模块导出）
from sqlgraph import serialize
from sqlgraph import visualize

# 常用便捷函数
from sqlgraph.visualize import to_html

# 公开 API 列表
__all__ = [
    "build_graph",
    "PropertyGraph",
    "serialize",
    "visualize",
    "to_html",
]

# 版本号
__version__ = "0.1.0"
