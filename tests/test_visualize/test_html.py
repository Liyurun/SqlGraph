"""测试 HTML 可视化生成功能"""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlgraph.builder import GraphBuilder
from sqlgraph.visualize import to_html


def _build_graph():
    """构建一个简单的两级 SQL 血缘图用于测试：raw -> mid -> final"""
    builder = GraphBuilder(dialect="spark")
    sql1 = "INSERT OVERWRITE TABLE mid SELECT id, name FROM raw"
    sql2 = "INSERT OVERWRITE TABLE final SELECT id, name FROM mid"
    from sqlgraph.input import SqlSource

    src = SqlSource.from_string(sql1, name="etl1")
    src.add_item(src._items[0].__class__(name="etl2", content=sql2, source_type="string"))
    return builder.build_from_source(src)


def test_to_html_generates_file():
    """测试 to_html 能正确生成包含 Cytoscape.js 的 HTML 文件"""
    graph = _build_graph()
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "lineage.html")
        html = to_html(graph, output_path=out_path, title="Test")
        assert os.path.isfile(out_path)
        with open(out_path) as f:
            content = f.read()
        assert "cytoscape" in content.lower()
        assert "Test" in content
