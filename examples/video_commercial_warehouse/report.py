"""视频商业化数仓治理工作台报告生成器。"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from sqlgraph.serve.theme import load_explorer_css


TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "workbench.html"


def _safe_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )


def render_report(payload: dict[str, Any], output_path: Path) -> Path:
    """将治理结果渲染为无外部依赖的单文件工作台。"""
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    document = template.replace(
        "__TITLE__", html.escape(payload["scenario"]["title"])
    ).replace(
        "__EXPLORER_CSS__", load_explorer_css()
    ).replace("__PAYLOAD__", _safe_json(payload))
    output_path.write_text(document, encoding="utf-8")
    return output_path
