# sqlgraph/visualize/html.py
"""
Cytoscape.js 知识图谱风格交互式 HTML 可视化生成模块。

生成类似 Gephi/AntV G6 知识图谱风格的精美可视化：
- 圆形节点，按度数缩放大小，核心节点突出
- 半透明弧线边，多层连线不杂乱
- 浅色米白背景，柔和马卡龙配色
- 力导向布局自动发散，可选 Dagre 分层
- 悬停高亮邻接节点，点击显示详情
- 玻璃拟态控制面板
"""
from __future__ import annotations
import os
import json
import math
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlgraph.model import PropertyGraph, NodeType, EdgeType, SqlNode, TableNode, ColumnNode, TransformNode
from sqlgraph.visualize.colors import NODE_COLORS, EDGE_COLORS, DARK_THEME, LIGHT_THEME
from sqlgraph.utils.logging import log_info
from sqlgraph.utils.notebook import is_notebook_env, display_html_in_notebook


def _compute_degrees(elements: list) -> dict:
    """计算每个节点的度数（入度+出度）"""
    degrees = {}
    for el in elements:
        if "source" in el.get("data", {}):
            s = el["data"]["source"]
            t = el["data"]["target"]
            degrees[s] = degrees.get(s, 0) + 1
            degrees[t] = degrees.get(t, 0) + 1
        else:
            nid = el["data"]["id"]
            degrees.setdefault(nid, 0)
    return degrees


def _node_size(degree: int, ntype: str, is_target: bool) -> int:
    """根据节点度数和类型计算节点大小（像素）"""
    base = {"sql": 28, "table": 30, "column": 10, "transform": 16}
    size = base.get(ntype, 20)
    size += min(degree * 3, 30)
    if is_target:
        size += 15
    if ntype == "table" and is_target:
        size = max(size, 52)
    if ntype == "table" and degree > 3:
        size = max(size, 40)
    return size


def _font_size(node_size: int) -> int:
    """根据节点大小计算标签字号"""
    if node_size >= 48:
        return 11
    if node_size >= 36:
        return 10
    if node_size >= 24:
        return 9
    if node_size >= 16:
        return 8
    return 0


def _short_label(name: str, ntype: str, size: int) -> str:
    """根据节点大小智能截断标签（标签在节点外部，可以显示更多）"""
    if size <= 14:
        return ""
    max_chars = {16: 5, 22: 7, 28: 10, 36: 14, 44: 18, 52: 24, 60: 30}
    limit = 10
    for s, c in sorted(max_chars.items()):
        if size <= s:
            limit = c
            break
    if len(name) > limit and limit > 0:
        return name[:limit - 1] + "…"
    return name if limit > 0 else ""


def _prepare_elements(graph: PropertyGraph, view: str = "table") -> list:
    """
    将 PropertyGraph 转换为 Cytoscape.js elements 格式。

    节点大小根据连接度数动态计算，边使用半透明弧线样式，
    目标表节点额外增大突出显示。
    """
    target_tables = set()
    source_tables = set()
    for e in graph.edges:
        if e.edge_type == EdgeType.WRITES_TO:
            target_tables.add(e.target_id)
        if e.edge_type == EdgeType.READS_FROM:
            source_tables.add(e.target_id)

    raw_nodes = []
    raw_edges = []
    for node in graph.nodes:
        nd = node.to_dict()
        ntype = nd.get("node_type", "unknown")
        skip = False
        if view == "table" and ntype in ("column", "transform"):
            skip = True
        elif view == "sql" and ntype != "sql":
            skip = True
        elif view == "lineage" and ntype in ("column", "transform"):
            skip = True
        if skip:
            continue
        colors = NODE_COLORS.get(ntype, NODE_COLORS["table"])
        label = nd.get("name", nd["id"])
        is_target = nd["id"] in target_tables
        is_source = nd["id"] in source_tables and not is_target
        raw_nodes.append({
            "data": {
                "id": nd["id"],
                "label": label,
                "nodeType": ntype,
                "bg": colors["bg"],
                "border": colors["border"],
                "shadow": colors.get("shadow", "rgba(0,0,0,0.2)"),
                "isTarget": is_target,
                "isSource": is_source,
                "isCte": nd.get("is_cte", False),
                "dialect": nd.get("dialect"),
                "expressionType": nd.get("expression_type"),
                "expression": nd.get("expression"),
                "fullName": label,
                "degree": 0,
            }
        })
    valid_ids = {el["data"]["id"] for el in raw_nodes}
    for edge in graph.edges:
        if edge.source_id not in valid_ids or edge.target_id not in valid_ids:
            continue
        ed = edge.to_dict()
        etype = ed.get("type", "unknown")
        color = EDGE_COLORS.get(etype, "#bdbdbd")
        if view == "table" and etype in ("has_column", "contains", "produces", "compute_dependency"):
            continue
        opacity = 0.35 if etype in ("has_column", "contains") else 0.45
        width = 1.5 if etype in ("table_lineage", "writes_to") else 1.0
        raw_edges.append({
            "data": {
                "id": ed["id"],
                "source": ed["source"],
                "target": ed["target"],
                "color": color,
                "edgeType": etype,
                "opacity": opacity,
                "width": width,
            }
        })
    all_elements = raw_nodes + raw_edges
    degrees = _compute_degrees(all_elements)
    for el in raw_nodes:
        d = degrees.get(el["data"]["id"], 0)
        el["data"]["degree"] = d
        size = _node_size(d, el["data"]["nodeType"], el["data"]["isTarget"])
        el["data"]["size"] = size
        el["data"]["fontSize"] = _font_size(size)
        el["data"]["label"] = _short_label(el["data"]["label"], el["data"]["nodeType"], size)
        if el["data"]["nodeType"] == "table":
            el["data"]["label"] = el["data"]["fullName"] if size >= 24 else _short_label(el["data"]["fullName"], "table", size)
    return raw_nodes + raw_edges


def to_html(
    graph: PropertyGraph,
    output_path: str = "lineage.html",
    view: str = "table",
    theme: str = "light",
    title: str = "SQL Lineage",
    auto_open: bool = False,
) -> str:
    """生成知识图谱风格的自包含交互式 HTML 文件"""
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("graph.html.j2")
    elements = _prepare_elements(graph, view=view)
    theme_cfg = LIGHT_THEME if theme == "light" else DARK_THEME
    html_content = template.render(
        title=title,
        graph_data=json.dumps(elements, ensure_ascii=False),
        node_colors=json.dumps(NODE_COLORS, ensure_ascii=False),
        edge_colors=json.dumps(EDGE_COLORS, ensure_ascii=False),
        theme=theme_cfg,
        initial_view=view,
        initial_theme=theme,
    )
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    log_info(f"HTML visualization written to {output_path}")
    if is_notebook_env():
        display_html_in_notebook(html_content)
    if auto_open:
        _open_browser(output_path)
    return html_content


def to_notebook(
    graph: PropertyGraph,
    view: str = "table",
    theme: str = "light",
    title: str = "SQL Lineage",
) -> None:
    """在 Jupyter Notebook 中内嵌展示交互式血缘图"""
    from sqlgraph.utils.notebook import display_html_in_notebook
    elements = _prepare_elements(graph, view=view)
    theme_cfg = LIGHT_THEME if theme == "light" else DARK_THEME
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("graph.html.j2")
    html = template.render(
        title=title,
        graph_data=json.dumps(elements, ensure_ascii=False),
        node_colors=json.dumps(NODE_COLORS, ensure_ascii=False),
        edge_colors=json.dumps(EDGE_COLORS, ensure_ascii=False),
        theme=theme_cfg,
        initial_view=view,
        initial_theme=theme,
    )
    display_html_in_notebook(html)


def _open_browser(path: str) -> None:
    import webbrowser
    webbrowser.open("file://" + os.path.abspath(path))
