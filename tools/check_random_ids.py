# tools/check_random_ids.py
"""随机 ID 禁令扫描（REQ-ID-01 强制项 / REQ-CLI-02 TC1）。

书稿定稿态的两大修正点之一是「确定性 ID」：全仓库节点与边的 ID 必须由内容键 /
语义键派生，禁止随机 UUID/随机数。否则跨构建差分会把随机噪声误判为结构变化。

本脚本用 AST 静态扫描 ``sqlgraph/`` 下是否引入了随机性来源：
  - ``import uuid`` / ``from uuid import ...`` / ``uuid.uuid1/uuid4`` 等；
  - ``import random`` / ``random.*``；
  - ``import secrets`` / ``secrets.*``；
  - ``os.urandom``。

命中即视为违反禁令，退出码 1，阻断 CI（REQ-CLI-02 TC1：提交违反随机 ID 禁令
的代码，CI 失败）。允许通过行内注释 ``# allow-random`` 显式豁免（例如与身份
无关的抽样场景），豁免会被记录在报告中，做到「不静默放行」。

用法：
    python -m tools.check_random_ids
    python -m tools.check_random_ids --json
"""
from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path

# 被禁止的随机性来源模块名。
_FORBIDDEN_MODULES = {"uuid", "random", "secrets"}
# 被禁止的属性调用（模块.属性）。
_FORBIDDEN_ATTRS = {
    ("os", "urandom"),
}
_ALLOW_MARKER = "allow-random"


@dataclass(frozen=True)
class Finding:
    """一处随机性来源命中。"""

    location: str  # "文件:行号"
    symbol: str    # 命中的符号，如 "uuid" / "random.random" / "os.urandom"
    allowed: bool  # 是否被行内 # allow-random 豁免

    def __str__(self) -> str:  # pragma: no cover - 仅 CLI 展示
        tag = "（已豁免 allow-random）" if self.allowed else ""
        return f"{self.location}: 检出随机性来源 '{self.symbol}'{tag}"


def _line_allows(source_lines: list[str], lineno: int) -> bool:
    """该行是否带有 ``# allow-random`` 豁免标记。"""
    if 1 <= lineno <= len(source_lines):
        return _ALLOW_MARKER in source_lines[lineno - 1]
    return False


def scan_file(py_file: Path) -> list[Finding]:
    """扫描单个文件的随机性来源命中。"""
    findings: list[Finding] = []
    text = py_file.read_text(encoding="utf-8")
    lines = text.splitlines()
    try:
        tree = ast.parse(text, filename=str(py_file))
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        symbol: str | None = None
        lineno = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".", 1)[0]
                if base in _FORBIDDEN_MODULES:
                    findings.append(
                        Finding(f"{py_file}:{node.lineno}", alias.name,
                                _line_allows(lines, node.lineno))
                    )
            continue
        if isinstance(node, ast.ImportFrom):
            base = (node.module or "").split(".", 1)[0]
            if base in _FORBIDDEN_MODULES:
                symbol = f"from {node.module}"
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            mod = node.value.id
            if (mod, node.attr) in _FORBIDDEN_ATTRS:
                symbol = f"{mod}.{node.attr}"
        if symbol is not None:
            findings.append(Finding(f"{py_file}:{lineno}", symbol,
                                    _line_allows(lines, lineno)))
    return findings


def scan_tree(root: Path) -> list[Finding]:
    """扫描整个包目录，返回全部命中（含已豁免项）。"""
    findings: list[Finding] = []
    for py_file in sorted(root.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        findings.extend(scan_file(py_file))
    return findings


def violations(findings: list[Finding]) -> list[Finding]:
    """未被豁免的命中即违规。"""
    return [f for f in findings if not f.allowed]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="随机 ID 禁令扫描（REQ-ID-01）")
    parser.add_argument("--root", default=None, help="被扫描的包目录，默认 sqlgraph/")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent / "sqlgraph"
    findings = scan_tree(root)
    bad = violations(findings)

    if args.json:
        print(json.dumps([f.__dict__ for f in findings], ensure_ascii=False, indent=2))
    elif bad:
        print(f"检出 {len(bad)} 处未豁免的随机性来源，违反 REQ-ID-01（确定性 ID 禁令）：")
        for f in bad:
            print(f"  - {f}")
    else:
        allowed = [f for f in findings if f.allowed]
        note = f"（{len(allowed)} 处经 allow-random 显式豁免）" if allowed else ""
        print(f"随机 ID 扫描通过：地基未引入随机性来源{note}。")

    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
