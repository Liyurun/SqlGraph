# sqlgraph/visualize/colors.py
"""
可视化层配色方案模块。

知识图谱风格配色：采用柔和、低饱和度的马卡龙色系，
节点使用圆形填充，边使用半透明弧线，整体视觉效果
优雅、现代、不刺眼。
"""
from __future__ import annotations


NODE_COLORS = {
    "sql": {
        "bg": "#b388ff",
        "border": "#9575cd",
        "font": "#fff",
        "shadow": "rgba(179,136,255,0.4)",
    },
    "table": {
        "bg": "#64b5f6",
        "border": "#42a5f5",
        "font": "#fff",
        "shadow": "rgba(100,181,246,0.4)",
    },
    "column": {
        "bg": "#81c784",
        "border": "#66bb6a",
        "font": "#fff",
        "shadow": "rgba(129,199,132,0.3)",
    },
    "transform": {
        "bg": "#ffb74d",
        "border": "#ffa726",
        "font": "#5d4037",
        "shadow": "rgba(255,183,77,0.4)",
    },
}

EDGE_COLORS = {
    "writes_to": "#ef5350",
    "reads_from": "#42a5f5",
    "table_lineage": "#66bb6a",
    "produces": "#ab47bc",
    "compute_dependency": "#ffa726",
    "has_column": "#b0bec5",
    "contains": "#26c6da",
}

HIGHLIGHT_COLOR = "#ffc107"

LIGHT_THEME = {
    "bg": "#faf8f5",
    "panel_bg": "rgba(255,255,255,0.88)",
    "sidebar_bg": "rgba(250,248,245,0.95)",
    "text": "#2c3e50",
    "text_secondary": "#7f8c8d",
    "border": "rgba(0,0,0,0.08)",
    "accent": "#e91e63",
    "node_label_color": "#2c3e50",
}

DARK_THEME = {
    "bg": "#0d1117",
    "panel_bg": "rgba(22,27,34,0.92)",
    "sidebar_bg": "rgba(13,17,23,0.96)",
    "text": "#e6edf3",
    "text_secondary": "#8b949e",
    "border": "rgba(255,255,255,0.1)",
    "accent": "#f778ba",
    "node_label_color": "#f0f6fc",
}
