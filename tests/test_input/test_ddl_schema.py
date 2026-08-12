# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from sqlgraph.input.ddl_schema import (
    parse_ddl_columns,
    ddl_csv_to_schema_rows,
)


# ---- CREATE TABLE：抽列名 + Hive 类型归一化 ----

def test_parse_create_table_columns_and_types():
    ddl = (
        "CREATE TABLE `db`.`t`(\n"
        "  `id` BIGINT COMMENT 'pk',\n"
        "  `name` STRING COMMENT 'the name',\n"
        "  `price` DECIMAL(10,2),\n"
        "  `tags` ARRAY<STRING>)\n"
        "COMMENT 'demo'\n"
        "PARTITIONED BY (`p_date` STRING)"
    )
    table, cols = parse_ddl_columns(ddl)
    # 库名前缀被剥离，仅保留表名后缀
    assert table == "t"
    names = [c for c, _ in cols]
    # 普通列 + 分区列都要在
    assert names == ["id", "name", "price", "tags", "p_date"]
    types = dict(cols)
    # STRING 归一化为小写 string（sqlglot 默认会给 TEXT）
    assert types["name"] == "string"
    assert types["id"] == "bigint"
    assert types["price"].startswith("decimal")
    assert types["tags"].startswith("array")


# ---- 库名剥离：catalog.db.table 只留最后一段 ----

def test_parse_strips_db_prefix():
    ddl = "CREATE TABLE `demo_mart`.`dim_foo`(`a` STRING, `b` INT)"
    table, cols = parse_ddl_columns(ddl)
    assert table == "dim_foo"
    assert [c for c, _ in cols] == ["a", "b"]


# ---- 无类型 VIEW：sqlglot 会降级，走正则兜底 ----

def test_parse_untyped_view_fallback():
    ddl = (
        "CREATE VIEW `demo_mart`.`v_events`(\n"
        "  `app` COMMENT 'App',\n"
        "  `event` COMMENT 'evt',\n"
        "  `p_date`,\n"
        "  `metric_id` COMMENT 'id')\n"
        "COMMENT 'x' AS SELECT app, event FROM foo"
    )
    table, cols = parse_ddl_columns(ddl)
    assert table == "v_events"
    names = [c for c, _ in cols]
    assert names == ["app", "event", "p_date", "metric_id"]
    # 兜底路径拿不到类型，统一给 string
    assert all(t == "string" for _, t in cols)


# ---- 复杂类型：STRUCT 子字段不能被当成表列泄漏出来 ----

def test_parse_struct_nested_fields_not_leaked():
    ddl = (
        "CREATE TABLE `db`.`t`(\n"
        "  `item_id` BIGINT,\n"
        "  `price_info` STRUCT<currency:STRING,amount:DECIMAL(18,2)> COMMENT 'p')\n"
        "PARTITIONED BY (`p_date` STRING)"
    )
    table, cols = parse_ddl_columns(ddl)
    names = [c for c, _ in cols]
    # 只应有顶层列 + 分区列，STRUCT 内部的 currency/amount 不得出现
    assert names == ["item_id", "price_info", "p_date"]
    assert "currency" not in names
    assert "amount" not in names


# ---- 完全无法解析的返回 None，不抛异常 ----

def test_parse_unparseable_returns_none():
    table, cols = parse_ddl_columns("this is not a ddl at all")
    assert table is None
    assert cols == []


# ---- 批量 CSV -> schema 行生成器 ----

def test_ddl_csv_to_schema_rows():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("table_name,ddl\n")
        f.write('"db.t1","CREATE TABLE `db`.`t1`(`a` STRING, `b` BIGINT)"\n')
        f.write('"db.t2","CREATE TABLE `db`.`t2`(`x` INT, `y` STRING)"\n')
        f.flush()
        path = f.name
    try:
        rows = list(ddl_csv_to_schema_rows(path))
        # (table, column, data_type) 三元组
        assert ("t1", "a", "string") in rows
        assert ("t1", "b", "bigint") in rows
        assert ("t2", "x", "int") in rows
        assert ("t2", "y", "string") in rows
    finally:
        os.unlink(path)


# ---- 产物可直接被 SchemaRegistry.from_csv 消费（端到端）----

def test_generated_schema_feeds_registry():
    from sqlgraph.input.csv_schema import SchemaRegistry
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("table_name,ddl\n")
        f.write('"db.orders","CREATE TABLE `db`.`orders`(`id` BIGINT, `amount` DOUBLE)"\n')
        f.flush()
        ddl_path = f.name
    schema_path = ddl_path + ".schema.csv"
    try:
        import csv as _csv
        with open(schema_path, "w", newline="") as out:
            w = _csv.writer(out)
            w.writerow(["table_name", "column_name", "data_type"])
            for t, c, dt in ddl_csv_to_schema_rows(ddl_path):
                w.writerow([t, c, dt])
        reg = SchemaRegistry.from_csv(schema_path)
        assert reg.has_table("orders")
        assert set(reg.get_table_columns("orders")) == {"id", "amount"}
    finally:
        os.unlink(ddl_path)
        if os.path.exists(schema_path):
            os.unlink(schema_path)
