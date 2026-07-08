# sqlgraph/visualize/colors.py
"""
可视化层配色方案模块。

定义节点颜色、边颜色、高亮色以及深色/浅色主题的完整配色体系，
供 Cytoscape.js HTML 模板和 Python 端生成逻辑共同使用。
"""
from __future__ import annotations


NODE_COLORS = {
    "sql": {"bg": "#9c27b0", "border": "#7b1fa2", "font": "#ffffff"},
    "table": {"bg": "#2196f3", "border": "#1976d2", "font": "#ffffff"},
    "column": {"bg": "#4caf50", "border": "#388e3c", "font": "#ffffff"},
    "transform": {"bg": "#ff9800", "border": "#f57c00", "font": "#ffffff"},
}

EDGE_COLORS = {
    "writes_to": "#d32f2f",
    "reads_from": "#1976d2",
    "table_lineage": "#388e3c",
    "produces": "#7b1fa2",
    "compute_dependency": "#f57c00",
    "has_column": "#90a4ae",
    "contains": "#0097a7",
}

HIGHLIGHT_COLOR = "#ffd700"

DARK_THEME = {
    "bg": "#1a1a2e",
    "panel_bg": "#16213e",
    "sidebar_bg": "#0f3460",
    "text": "#e0e0e0",
    "text_secondary": "#a0a0a0",
    "border": "#334",
    "accent": "#e94560",
}

LIGHT_THEME = {
    "bg": "#f5f7fa",
    "panel_bg": "#ffffff",
    "sidebar_bg": "#e8edf3",
    "text": "#222",
    "text_secondary": "#666",
    "border": "#ddd",
    "accent": "#e94560",
}
