# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

# sqlgraph/builder/table_registry.py
from __future__ import annotations
from sqlgraph.utils.logging import log_warn


class TableRegistry:
    """全局表注册表，记录每个表由哪个 SQL 产出，用于跨 SQL 血缘融合"""

    def __init__(self):
        self._table_producer: dict = {}
        self._table_id: dict = {}

    def register_producer(self, table_name: str, sql_id: str, table_node_id: str) -> None:
        """注册表的产出 SQL"""
        if table_name in self._table_producer:
            log_warn(f"Table '{table_name}' is produced by multiple SQLs")
        self._table_producer[table_name] = sql_id
        self._table_id[table_name] = table_node_id

    def get_producer(self, table_name: str) -> str | None:
        """获取产出指定表的 SQL ID"""
        return self._table_producer.get(table_name)

    def get_table_id(self, table_name: str) -> str | None:
        """获取指定表的节点 ID"""
        return self._table_id.get(table_name)

    def has_table(self, table_name: str) -> bool:
        return table_name in self._table_producer
