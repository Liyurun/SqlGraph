# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

# tests/test_integration/test_e2e.py
from __future__ import annotations
import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from sqlgraph import build_graph
from sqlgraph.serialize import to_csv, to_graphrag, to_json
from sqlgraph.visualize import to_html


DEMO_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'examples', 'ads_pipeline')


def test_demo_end_to_end():
    """端到端测试：解析示例目录所有 SQL，验证节点/边数量"""
    schema_path = os.path.join(DEMO_DIR, 'schema.csv')
    if not os.path.isdir(DEMO_DIR):
        import pytest
        pytest.skip("Demo directory not found")
    graph = build_graph(DEMO_DIR, dialect='spark', schema_path=schema_path)
    stats = graph.stats()
    assert stats['sql_count'] == 11
    assert stats['table_count'] >= 20
    assert stats['column_count'] >= 100
    assert stats['transform_count'] >= 30
    assert stats['edge_count'] >= 300
    assert stats['node_count'] >= 150
    assert len(graph.get_upstream('dws_ad_daily') or graph.get_upstream('stg_impressions') or []) >= 0


def test_all_output_formats():
    """验证所有输出格式都能生成"""
    schema_path = os.path.join(DEMO_DIR, 'schema.csv')
    if not os.path.isdir(DEMO_DIR):
        import pytest
        pytest.skip("Demo directory not found")
    graph = build_graph(DEMO_DIR, dialect='spark', schema_path=schema_path)
    with tempfile.TemporaryDirectory() as tmpdir:
        to_csv(graph, os.path.join(tmpdir, 'csv'))
        assert os.path.isfile(os.path.join(tmpdir, 'csv', 'nodes.csv'))
        assert os.path.isfile(os.path.join(tmpdir, 'csv', 'edges.csv'))
        payload = to_graphrag(graph, os.path.join(tmpdir, 'graphrag.json'))
        assert 'entities' in payload
        assert 'relations' in payload
        assert 'schema' in payload
        data = to_json(graph, os.path.join(tmpdir, 'graph.json'))
        assert 'nodes' in data
        html = to_html(graph, output_path=os.path.join(tmpdir, 'lineage.html'), auto_open=False)
        assert os.path.isfile(os.path.join(tmpdir, 'lineage.html'))
        assert 'cytoscape' in html.lower()
