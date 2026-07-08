# tests/test_integration/test_api.py
"""
SQLGraph 高层 API 集成测试模块。

测试 build_graph 高层 API 的各种使用场景：
  - 从 SQL 字符串构建图
  - 从多条 SQL（SqlSource 对象）构建图
  - 验证统计信息正确性
"""
from __future__ import annotations

import sys
import os
import tempfile

# 将项目根目录添加到 sys.path，确保可以导入 sqlgraph 包
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlgraph import build_graph
from sqlgraph.input import SqlSource
from sqlgraph.input.sql_source import SqlSourceItem


def test_build_graph_from_string():
    """测试从单个 SQL 字符串构建血缘图

    验证点：
      - SQL 数量统计正确（1条）
      - 表节点数量至少为 2（源表和目标表）
    """
    sql = """
    INSERT OVERWRITE TABLE target
    SELECT id, name, age FROM source
    """
    graph = build_graph(sql, dialect="spark")
    stats = graph.stats()
    # 验证解析了 1 条 SQL
    assert stats["sql_count"] == 1
    # 验证至少有 2 个表节点（source 和 target）
    assert stats["table_count"] >= 2


def test_build_graph_multi_sql():
    """测试从多条 SQL（SqlSource 对象）构建血缘图

    构建一个 3 层血缘链路：src -> a -> b -> c
    验证点：
      - SQL 数量统计正确（3条）
      - 表节点数量正确（至少包含 src、a、b、c 共4个表）
    """
    sqls = [
        "INSERT OVERWRITE TABLE a SELECT id FROM src",
        "INSERT OVERWRITE TABLE b SELECT id FROM a",
        "INSERT OVERWRITE TABLE c SELECT id FROM b",
    ]
    # 手动构建 SqlSource 对象
    src = SqlSource()
    for i, s in enumerate(sqls):
        src.add_item(SqlSourceItem(
            name=f"q{i}",
            content=s,
            source_type="string"
        ))
    graph = build_graph(src, dialect="spark")
    stats = graph.stats()
    # 验证解析了 3 条 SQL
    assert stats["sql_count"] == 3
    # 验证至少有 4 个表节点（src, a, b, c）
    assert stats["table_count"] >= 4


def test_build_graph_from_list():
    """测试从 SQL 字符串列表构建图"""
    sqls = [
        "CREATE TABLE tmp AS SELECT user_id FROM users",
        "INSERT OVERWRITE TABLE final SELECT * FROM tmp",
    ]
    graph = build_graph(sqls, dialect="spark")
    stats = graph.stats()
    assert stats["sql_count"] == 2


def test_build_graph_stats_keys():
    """测试 stats() 返回的字典包含预期的键"""
    sql = "SELECT * FROM t1 JOIN t2 ON t1.id = t2.id"
    graph = build_graph(sql, dialect="spark")
    stats = graph.stats()
    # 验证必须包含的统计键
    assert "sql_count" in stats
    assert "table_count" in stats
    assert "edge_count" in stats
