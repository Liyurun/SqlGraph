# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

# sqlgraph/input/dataframe.py
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


def dataframe_to_sql_source(df: "pd.DataFrame", table_name: str) -> str:
    """将 DataFrame 转换为虚拟 CREATE TABLE 语句，用于 schema 推导

    根据 Pandas DataFrame 的数据类型映射到对应的 SQL 类型，
    生成包含 schema 信息的 DDL 语句，供后续 SQL 解析使用。

    类型映射规则：
    - int64 -> bigint
    - int32 -> int
    - float64 -> double
    - float32 -> float
    - bool -> boolean
    - datetime64[ns] -> timestamp
    - object -> string

    Args:
        df: Pandas DataFrame 实例
        table_name: 目标表名

    Returns:
        包含 schema 信息的 SQL DDL 字符串
    """
    type_map = {
        "int64": "bigint",
        "int32": "int",
        "float64": "double",
        "float32": "float",
        "bool": "boolean",
        "datetime64[ns]": "timestamp",
        "object": "string",
    }
    cols = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        sql_type = type_map.get(dtype, "string")
        cols.append(f"  {col} {sql_type}")
    cols_str = ",\n".join(cols)
    return (
        f"CREATE OR REPLACE TEMP VIEW {table_name} AS (\n"
        f"  SELECT * FROM VALUES (0)\n"
        f");\n"
        f"-- Schema inferred from DataFrame:\n"
        f"-- {table_name} (\n"
        f"{chr(10).join(['--   ' + c for c in cols])}\n"
        f"-- )"
    )
