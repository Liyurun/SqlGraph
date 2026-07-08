# sqlgraph/visualize/html.py
"""
Cytoscape.js 交互式 HTML 可视化生成模块。

将 PropertyGraph 转换为 Cytoscape.js elements 格式，使用 Jinja2 模板
渲染自包含的 HTML 文件，支持深色/浅色主题、多种布局算法、节点类型
过滤、悬停高亮、点击详情面板、PNG 导出等功能。
"""
from __future__ import annotations
import os
import json
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlgraph.model import PropertyGraph, NodeType, EdgeType, SqlNode, TableNode, ColumnNode, TransformNode
from sqlgraph.visualize.colors import NODE_COLORS, EDGE_COLORS, DARK_THEME, LIGHT_THEME
from sqlgraph.visualize.layouts import LAYOUTS
from sqlgraph.utils.logging import log_info
from sqlgraph.utils.notebook import is_notebook_env, display_html_in_notebook


def _prepare_elements(graph: PropertyGraph, view: str = "table") -> list:
    """
    将 PropertyGraph 转换为 Cytoscape.js elements 格式。

    根据视图模式过滤节点类型：
      - table 视图：仅显示 SQL 和表节点，隐藏字段和 Transform
      - column 视图：显示所有节点
      - sql 视图：仅显示 SQL 节点

    同时为目标表（writes_to 的终点）标记 isTarget 属性，
    使其在图中以金色边框高亮显示。

    Args:
        graph: 属性图实例
        view: 视图模式，可选 "table" / "column" / "sql"

    Returns:
        Cytoscape elements 列表，每个元素为 {"data": {...}} 格式
    """
    elements = []
    target_tables = set()
    for e in graph.edges:
        if e.edge_type == EdgeType.WRITES_TO:
            target_tables.add(e.target_id)
    for node in graph.nodes:
        nd = node.to_dict()
        ntype = nd.get("node_type", "unknown")
        colors = NODE_COLORS.get(ntype, NODE_COLORS["table"])
        skip = False
        if view == "table" and ntype in ("column", "transform"):
            skip = True
        elif view == "sql" and ntype != "sql":
            skip = True
        if skip:
            continue
        label = nd.get("name", nd["id"])
        elements.append({
            "data": {
                "id": nd["id"],
                "label": _short_label(label, ntype),
                "nodeType": ntype,
                "bg": colors["bg"],
                "border": colors["border"],
                "font": colors["font"],
                "isTarget": nd["id"] in target_tables,
                "isCte": nd.get("is_cte", False),
                "dialect": nd.get("dialect"),
                "expressionType": nd.get("expression_type"),
                "expression": nd.get("expression"),
                "fullName": label,
            }
        })
    valid_ids = {el["data"]["id"] for el in elements}
    for edge in graph.edges:
        if edge.source_id not in valid_ids or edge.target_id not in valid_ids:
            continue
        ed = edge.to_dict()
        etype = ed.get("type", "unknown")
        color = EDGE_COLORS.get(etype, "#999")
        elements.append({
            "data": {
                "id": ed["id"],
                "source": ed["source"],
                "target": ed["target"],
                "color": color,
                "edgeType": etype,
            }
        })
    return elements


def _short_label(name: str, ntype: str) -> str:
    """
    截断过长的节点标签，确保在图中显示美观。

    Args:
        name: 原始名称
        ntype: 节点类型（当前未使用，保留用于后续差异化截断策略）

    Returns:
        截断后的标签字符串（超过18字符时截断为前16字符加".."）
    """
    if len(name) > 18:
        return name[:16] + ".."
    return name


def to_html(
    graph: PropertyGraph,
    output_path: str = "lineage.html",
    view: str = "table",
    theme: str = "dark",
    title: str = "SQL Lineage",
    auto_open: bool = False,
) -> str:
    """
    生成自包含交互式 HTML 文件并写入磁盘。

    使用 Jinja2 模板引擎渲染 graph.html.j2，注入图数据、配色方案和
    主题配置，生成可直接在浏览器中打开的单文件 HTML。

    Args:
        graph: 属性图实例
        output_path: 输出 HTML 文件路径，默认 "lineage.html"
        view: 初始视图模式，"table"（表级）/ "column"（字段级）/ "sql"（SQL依赖）
        theme: 主题，"dark"（深色）/ "light"（浅色）
        title: 页面标题
        auto_open: 是否在生成后自动用浏览器打开

    Returns:
        渲染后的 HTML 字符串内容
    """
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("graph.html.j2")
    elements = _prepare_elements(graph, view=view)
    theme_cfg = DARK_THEME if theme == "dark" else LIGHT_THEME
    html_content = template.render(
        title=title,
        graph_data=json.dumps(elements, ensure_ascii=False),
        node_colors=json.dumps(NODE_COLORS, ensure_ascii=False),
        edge_colors=json.dumps(EDGE_COLORS, ensure_ascii=False),
        theme=theme_cfg,
        initial_view=view,
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
    theme: str = "dark",
    title: str = "SQL Lineage",
) -> None:
    """
    在 Jupyter Notebook 中内嵌展示交互式血缘图。

    不写入磁盘文件，直接渲染 HTML 并通过 IPython.display 展示，
    适用于 Notebook 环境中的交互式探索。

    Args:
        graph: 属性图实例
        view: 初始视图模式
        theme: 主题
        title: 页面标题
    """
    from sqlgraph.utils.notebook import display_html_in_notebook
    elements = _prepare_elements(graph, view=view)
    theme_cfg = DARK_THEME if theme == "dark" else LIGHT_THEME
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
    )
    display_html_in_notebook(html)


def _open_browser(path: str) -> None:
    """
    用系统默认浏览器打开指定 HTML 文件。

    Args:
        path: HTML 文件的本地路径
    """
    import webbrowser
    webbrowser.open("file://" + os.path.abspath(path))
