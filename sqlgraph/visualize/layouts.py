# sqlgraph/visualize/layouts.py
"""
可视化层布局配置模块。

定义 Cytoscape.js 支持的多种布局算法参数，包括 Dagre 分层布局、
CoSE 力导向布局、环形布局和广度优先布局，供 HTML 模板和
Python 端生成逻辑引用。
"""
from __future__ import annotations


DAGRE_LAYOUT = {
    "name": "dagre",
    "rankDir": "LR",
    "nodeSep": 40,
    "rankSep": 80,
    "edgeSep": 20,
    "animate": True,
    "animationDuration": 500,
}

COSE_LAYOUT = {
    "name": "cose",
    "animate": True,
    "animationDuration": 500,
    "nodeRepulsion": 8000,
    "idealEdgeLength": 100,
    "nodeOverlap": 20,
}

CIRCLE_LAYOUT = {
    "name": "circle",
    "animate": True,
    "animationDuration": 300,
}

BREADTHFIRST_LAYOUT = {
    "name": "breadthfirst",
    "directed": True,
    "padding": 30,
    "circle": False,
    "grid": True,
    "spacingFactor": 1.5,
}

LAYOUTS = {
    "dagre": DAGRE_LAYOUT,
    "cose": COSE_LAYOUT,
    "circle": CIRCLE_LAYOUT,
    "breadthfirst": BREADTHFIRST_LAYOUT,
}
