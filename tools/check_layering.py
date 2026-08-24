# tools/check_layering.py
"""分层依赖单向性检查（REQ-ARCH-01）。

《AI 原生数仓治理》第 2-3 章把「解析 / 图 / 证据」定义为确定性地基，第 4-7 章
把「推理循环（决策 / 执行）」定义为上层操作化展开。地基不得依赖推理结果，
否则确定性会被上层污染。本脚本把该约束固化为可执行、可纳入 CI 的守卫：

    上层可以 import 下层；下层禁止 import 上层。

用法：
    python -m tools.check_layering            # 检查真实仓库，反向依赖时退出码 1
    python -m tools.check_layering --json     # 结构化输出

也可作为库被验收测试调用：``scan_imports`` / ``classify``。

层级映射（真实子包 -> 规格书建议的层名 -> 层级序号）：规格书建议的模块名
（adapters/graph/...）与本仓库既有命名（input+parser/model+builder/...）不完全
一致，这里按语义对齐，并在报告中给出层名，避免读者困惑。
"""
from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path

# 真实子包 -> (层级序号, 规格书层名)。序号越小越靠近确定性地基。
# 规则：一个子包只能 import 层级序号 <= 自身的子包（含同层）。
LAYERS: dict[str, tuple[int, str]] = {
    # L0 共享基础设施：无业务语义，任何层都可依赖。
    "utils": (0, "shared"),
    # L1 确定性地基：数据模型 + 身份服务。
    "model": (1, "graph"),
    "identity": (1, "identity"),
    # L2-L3 适配器：输入装载 + SQL 解析（graph 的上游、身份的下游）。
    "input": (2, "adapters"),
    "parser": (3, "adapters"),
    # L4 图构建：把解析结果编译为确定性图。
    "builder": (4, "graph"),
    # L5 图派生只读服务：序列化 / 可视化 / 血缘下钻 / 结构指标 / 契约。
    "serialize": (5, "graph-derived"),
    "visualize": (5, "graph-derived"),
    "lineage": (5, "lineage"),
    "metrics": (5, "metrics"),
    "contract": (5, "adapters-contract"),
    # L6 证据子图。
    "evidence": (6, "evidence"),
    # L7 验证与决策（推理循环的判定层）。
    "verify": (7, "verify"),
    "autonomy": (7, "autonomy"),
    # L8 智能体：编排七步闭环。
    "agent": (8, "agent"),
    # L9-L10 入口层：高层 API / playground / CLI。
    "api": (9, "entry"),
    "playground": (9, "entry"),
    "cli": (10, "cli"),
}


@dataclass(frozen=True)
class Violation:
    """一条反向依赖：``importer`` 属于下层，却 import 了上层 ``imported``。"""

    importer_pkg: str
    imported_pkg: str
    importer_level: int
    imported_level: int
    location: str  # "文件:行号"

    def __str__(self) -> str:  # pragma: no cover - 仅用于 CLI 展示
        return (
            f"{self.location}: 下层 '{self.importer_pkg}'(L{self.importer_level}) "
            f"禁止 import 上层 '{self.imported_pkg}'(L{self.imported_level})"
        )


def classify(importer_pkg: str, imported_pkg: str) -> bool:
    """判断一条包间依赖是否构成反向依赖（违规）。

    Returns:
        True 表示违规（下层 import 了严格上层）；False 表示合法（含同层、
        依赖下层，或任一包不在受管层级表中而无法判定）。
    """
    if importer_pkg == imported_pkg:
        return False
    a = LAYERS.get(importer_pkg)
    b = LAYERS.get(imported_pkg)
    if a is None or b is None:
        return False
    return b[0] > a[0]


def _imported_pkg(module: str, package_name: str) -> str | None:
    """从被 import 的模块全名中取出其受管子包名。

    ``sqlgraph.autonomy.decision`` -> ``autonomy``；``sqlgraph`` 门面 -> None。
    """
    if module == package_name:
        return None
    prefix = package_name + "."
    if not module.startswith(prefix):
        return None
    return module[len(prefix):].split(".", 1)[0]


def _importer_pkg(py_file: Path, root: Path) -> str | None:
    """从文件路径推断其所属受管子包名（root 直属文件如 api.py -> 'api'）。"""
    rel = py_file.relative_to(root)
    parts = rel.parts
    if len(parts) == 1:  # 例如 api.py / cli.py / playground.py
        return parts[0][:-3] if parts[0].endswith(".py") else parts[0]
    return parts[0]  # 例如 autonomy/decision.py -> 'autonomy'


def scan_imports(root: Path, package_name: str = "sqlgraph") -> list[Violation]:
    """遍历包目录，用 AST 收集内部 import 并返回全部反向依赖。"""
    violations: list[Violation] = []
    for py_file in sorted(root.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        importer = _importer_pkg(py_file, root)
        if importer is None:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    pkg = _imported_pkg(node.module, package_name)
                    if pkg and classify(importer, pkg):
                        violations.append(_mk(importer, pkg, py_file, node.lineno))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    pkg = _imported_pkg(alias.name, package_name)
                    if pkg and classify(importer, pkg):
                        violations.append(_mk(importer, pkg, py_file, node.lineno))
    return violations


def _mk(importer: str, imported: str, py_file: Path, lineno: int) -> Violation:
    return Violation(
        importer_pkg=importer,
        imported_pkg=imported,
        importer_level=LAYERS[importer][0],
        imported_level=LAYERS[imported][0],
        location=f"{py_file}:{lineno}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="分层依赖单向性检查（REQ-ARCH-01）")
    parser.add_argument("--root", default=None, help="被检查的包目录，默认自动定位 sqlgraph/")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent / "sqlgraph"
    violations = scan_imports(root)

    if args.json:
        print(json.dumps([v.__dict__ for v in violations], ensure_ascii=False, indent=2))
    elif violations:
        print(f"发现 {len(violations)} 条反向依赖（下层 import 上层），违反 REQ-ARCH-01：")
        for v in violations:
            print(f"  - {v}")
    else:
        print("分层依赖检查通过：无反向依赖（REQ-ARCH-01 AC / 退出码 0）。")

    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
