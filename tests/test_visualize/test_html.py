"""测试 HTML 可视化生成功能"""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlgraph.builder import GraphBuilder
from sqlgraph.visualize import to_html


def _build_graph():
    """构建一个含加工逻辑的两级 SQL 血缘图：raw -> mid -> final

    mid 层带聚合表达式，保证图中存在 transform（表达式）节点，
    用于验证 HTML 中保留字段/转换节点。
    """
    builder = GraphBuilder(dialect="spark")
    sql1 = "INSERT OVERWRITE TABLE mid SELECT id, COUNT(*) AS cnt FROM raw GROUP BY id"
    sql2 = "INSERT OVERWRITE TABLE final SELECT id, cnt FROM mid"
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
        # 默认表级视图只是在前端过滤显示，HTML 内仍保留字段/转换节点，
        # 这样用户无需重新生成文件即可切换到“字段级详情”查看加工逻辑。
        assert '"nodeType": "transform"' in content
