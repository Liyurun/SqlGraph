# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from sqlgraph.model.nodes import (
    SqlNode, TableNode, ColumnNode, TransformNode, NodeType, ExpressionType
)

def test_sql_node_creation():
    node = SqlNode(id="sql_001", name="01_stg_impressions", file_path="01_stg_impressions.sql",
                   sql_content="INSERT OVERWRITE TABLE stg_imp SELECT ...", dialect="spark")
    assert node.id == "sql_001"
    assert node.node_type == NodeType.SQL

def test_table_node_creation():
    node = TableNode(id="tbl_001", name="stg_impressions", is_cte=False)
    assert node.node_type == NodeType.TABLE
    assert node.is_cte is False

def test_column_node_creation():
    node = ColumnNode(id="col_001", name="imp_count", table_id="tbl_002", data_type="bigint")
    assert node.node_type == NodeType.COLUMN

def test_transform_node_creation():
    node = TransformNode(id="tr_001", expression="SUM(imp_flag)", expression_type=ExpressionType.AGG)
    assert node.node_type == NodeType.TRANSFORM
    assert node.expression_type == ExpressionType.AGG

def test_node_to_dict():
    node = SqlNode(id="s1", name="test", dialect="spark")
    d = node.to_dict()
    assert d["id"] == "s1"
    assert d["node_type"] == "sql"
