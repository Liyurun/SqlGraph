# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from sqlgraph.input.csv_schema import SchemaRegistry


def test_register_and_get_columns():
    reg = SchemaRegistry()
    reg.register_table("users", ["id", "name", "email"])
    cols = reg.get_table_columns("users")
    assert cols == ["id", "name", "email"]


def test_resolve_column_disambiguates():
    reg = SchemaRegistry()
    reg.register_table("a", ["id", "name"])
    reg.register_table("b", ["id", "title"])
    result = reg.resolve_column("name", ["a", "b"])
    assert result == "a.name"


def test_from_csv():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("table_name,column_name,data_type\n")
        f.write("users,id,bigint\n")
        f.write("users,name,string\n")
        f.write("orders,id,bigint\n")
        f.write("orders,user_id,bigint\n")
        f.flush()
        path = f.name
    try:
        reg = SchemaRegistry.from_csv(path)
        assert reg.has_table("users")
        assert reg.has_table("orders")
        assert "name" in reg.get_table_columns("users")
    finally:
        os.unlink(path)
