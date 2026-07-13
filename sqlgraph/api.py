# sqlgraph/api.py
"""
SQLGraph 高层 Python API 模块。

提供统一的高层入口函数 `build_graph`，封装了从输入源解析、Schema 加载、
图构建到统计输出的完整流程，是用户使用 SqlGraph 的首选接口。

支持的输入源类型：
  - SQL 文件路径（单个 .sql 文件）
  - 目录路径（自动扫描目录下所有 .sql 文件）
  - df.csv 文件（table_name,code 两列，每行一段 SQL 代码）
  - SQL 字符串（直接传入 SQL 文本）
  - 路径列表（多个文件/目录/SQL 字符串的混合列表）
  - SqlSource 对象（已构建好的 SqlSource 实例）
"""
from __future__ import annotations

import os
from typing import Union, Optional, List

from sqlgraph.builder import GraphBuilder
from sqlgraph.input import SqlSource
from sqlgraph.input.csv_schema import SchemaRegistry
from sqlgraph.model import PropertyGraph
from sqlgraph.serialize import to_csv, to_graphrag, to_json
from sqlgraph.visualize import to_html
from sqlgraph.utils.logging import log_info, log_stats
from sqlgraph.utils.notebook import setup_notebook
from sqlgraph.utils.batch import process_batch, BatchResult


def build_graph(
    source: Union[str, List[str], SqlSource],
    dialect: Optional[str] = None,
    schema_path: Optional[str] = None,
) -> PropertyGraph:
    """从输入源构建血缘图（统一高层入口）

    这是 sqlgraph 最核心的 API 函数，封装了完整的图构建流程：
    1. 初始化 Notebook 环境兼容性
    2. 加载可选的表 Schema CSV 文件（用于字段消歧）
    3. 智能识别输入源类型并构建 SqlSource
    4. 使用 GraphBuilder 解析 SQL 并构建 PropertyGraph
    5. 输出构建统计信息

    Args:
        source: SQL 输入源，支持以下类型：
            - str: SQL 文件路径、目录路径、或 SQL 字符串（自动识别）
                   也支持 table_name,code 格式的 df.csv 文件
            - List[str]: 路径或字符串列表，支持混合输入
            - SqlSource: 已构建好的 SqlSource 实例
        dialect: SQL 方言，可选值：spark/hive/presto/bigquery/...
                 None 表示自动检测（默认）
        schema_path: 可选的表 Schema CSV 文件路径。
                     CSV 格式要求: table_name,column_name,data_type[,description]
                     提供后可辅助解析器进行字段消歧，提高血缘准确性。

    Returns:
        PropertyGraph: 构建完成的属性图对象，包含所有节点和边信息。
                       可通过 graph.stats() 获取统计信息，或传入 serialize/visualize
                       模块进行输出。

    Example:
        >>> from sqlgraph import build_graph
        >>> # 从 SQL 字符串构建
        >>> graph = build_graph("SELECT * FROM source_table", dialect="spark")
        >>> # 从目录构建并加载 schema
        >>> graph = build_graph("./sql_files", schema_path="./schema.csv")
        >>> print(graph.stats())
    """
    # 初始化 Notebook 环境（处理 Python 版本兼容性等）
    setup_notebook()

    # 初始化 Schema 注册表
    schema_registry = None
    if schema_path:
        log_info(f"Loading schema from: {schema_path}")
        schema_registry = SchemaRegistry.from_csv(schema_path)

    # 构建 SqlSource 输入源
    if isinstance(source, SqlSource):
        # 如果已经是 SqlSource 对象，直接使用
        sql_source = source
        log_info(f"Using provided SqlSource with {len(sql_source)} item(s)")
    else:
        # 智能识别输入类型（文件/目录/SQL字符串/列表）
        log_info(f"Detecting input source type for: {type(source).__name__}")
        sql_source = SqlSource.from_any(source, dialect=dialect)

    # 创建图构建器并执行构建
    builder = GraphBuilder(dialect=dialect, schema_registry=schema_registry)
    log_info("Starting graph construction...")
    graph = builder.build_from_source(sql_source)

    # 输出构建统计信息
    stats = graph.stats()
    log_stats(stats)

    return graph
