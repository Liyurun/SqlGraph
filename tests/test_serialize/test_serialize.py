"""
sqlgraph.serialize 模块单元测试

测试覆盖：
  - to_csv: CSV 文件输出（nodes.csv + edges.csv）
  - to_graphrag: GraphRAG schema v2 JSON payload 输出
  - to_json / to_dict: 基础 JSON/字典序列化
"""

import sys
import os
import tempfile
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlgraph.builder import GraphBuilder
from sqlgraph.serialize import to_csv, to_graphrag, to_json, to_dict
import csv as csv_mod


def _build_test_graph():
    """构建一个测试用的 PropertyGraph（简单 INSERT OVERWRITE 语句）"""
    builder = GraphBuilder(dialect="spark")
    sql = "INSERT OVERWRITE TABLE target SELECT id, name FROM source"
    return builder.build_from_sql(sql, name="test")


def test_to_csv():
    """测试 CSV 序列化：验证 nodes.csv 和 edges.csv 正常生成且包含关键字段"""
    graph = _build_test_graph()
    with tempfile.TemporaryDirectory() as tmpdir:
        to_csv(graph, tmpdir)
        nodes_path = os.path.join(tmpdir, "nodes.csv")
        edges_path = os.path.join(tmpdir, "edges.csv")

        # 验证文件存在
        assert os.path.isfile(nodes_path), "nodes.csv should be created"
        assert os.path.isfile(edges_path), "edges.csv should be created"

        # 验证 nodes.csv 内容
        with open(nodes_path, encoding="utf-8") as f:
            reader = csv_mod.DictReader(f)
            rows = list(reader)
            assert len(rows) > 0, "nodes.csv should have at least one row"
            assert "id" in reader.fieldnames, "nodes.csv should have 'id' column"
            assert "node_type" in reader.fieldnames, "nodes.csv should have 'node_type' column"

        # 验证 edges.csv 内容
        with open(edges_path, encoding="utf-8") as f:
            reader = csv_mod.DictReader(f)
            rows = list(reader)
            assert len(rows) > 0, "edges.csv should have at least one row"
            assert "source" in reader.fieldnames, "edges.csv should have 'source' column"
            assert "target" in reader.fieldnames, "edges.csv should have 'target' column"
            assert "type" in reader.fieldnames, "edges.csv should have 'type' column"


def test_to_graphrag():
    """测试 GraphRAG payload 序列化：验证结构正确且文件写入正常"""
    graph = _build_test_graph()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        path = f.name
    try:
        payload = to_graphrag(graph, path)

        # 验证返回值结构
        assert "entities" in payload, "payload should have 'entities'"
        assert "relations" in payload, "payload should have 'relations'"
        assert "schema" in payload, "payload should have 'schema'"
        assert payload["schema"]["version"] == "2.0", "schema version should be 2.0"
        assert len(payload["entities"]) > 0, "should have at least one entity"
        assert len(payload["relations"]) > 0, "should have at least one relation"

        # 验证实体结构
        entity = payload["entities"][0]
        assert "id" in entity
        assert "name" in entity
        assert "type" in entity
        assert "properties" in entity

        # 验证关系结构
        relation = payload["relations"][0]
        assert "id" in relation
        assert "source" in relation
        assert "target" in relation
        assert "type" in relation
        assert "properties" in relation

        # 验证文件可被正确读取
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert len(loaded["entities"]) == len(payload["entities"])
        assert len(loaded["relations"]) == len(payload["relations"])
    finally:
        os.unlink(path)


def test_to_json():
    """测试 JSON 序列化：验证内存返回和文件写入均正常"""
    graph = _build_test_graph()

    # 测试不写文件，仅返回字典
    data = to_json(graph)
    assert "nodes" in data, "data should have 'nodes'"
    assert "edges" in data, "data should have 'edges'"
    assert len(data["nodes"]) > 0, "should have nodes"
    assert len(data["edges"]) > 0, "should have edges"

    # 测试 to_dict 便捷函数
    d = to_dict(graph)
    assert d["nodes"] == data["nodes"]
    assert d["edges"] == data["edges"]

    # 测试写入文件
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        path = f.name
    try:
        to_json(graph, path)
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert len(loaded["nodes"]) == len(data["nodes"])
        assert len(loaded["edges"]) == len(data["edges"])
    finally:
        os.unlink(path)
