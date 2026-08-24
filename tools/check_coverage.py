# tools/check_coverage.py
"""地基层覆盖率闸门（REQ-CLI-02 AC2）。

规格书要求：测试覆盖率对**地基层**（graph / identity / lineage）达到约定阈值
（建议 ≥ 85%）。本脚本读取 `coverage` 生成的 JSON 报告，只统计地基层文件的
合计覆盖率，低于阈值即退出码 1，用于在 CI 中阻断合并。

用法（先跑测试并生成 coverage.json，再校验）：
    COVERAGE_CORE=sysmon coverage run -m pytest -q
    coverage json -o coverage.json
    python -m tools.check_coverage --report coverage.json --min 85

地基层文件由路径前缀识别：sqlgraph/model/、sqlgraph/identity/、sqlgraph/lineage/。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 地基层：确定性图模型 + 身份服务 + 血缘下钻（书稿第 2-3 章的确定性地基）。
FOUNDATION_PREFIXES = (
    "sqlgraph/model/",
    "sqlgraph/identity/",
    "sqlgraph/lineage/",
)


def _is_foundation(path: str) -> bool:
    norm = path.replace("\\", "/")
    return any(seg in norm for seg in FOUNDATION_PREFIXES)


def foundation_coverage(report: dict) -> tuple[int, int, float]:
    """从 coverage JSON 汇总地基层的 (已覆盖语句, 总语句, 覆盖率%)。"""
    covered = 0
    total = 0
    for path, data in report.get("files", {}).items():
        if not _is_foundation(path):
            continue
        summary = data.get("summary", {})
        total += summary.get("num_statements", 0)
        covered += summary.get("covered_lines", 0)
    pct = (covered / total * 100.0) if total else 0.0
    return covered, total, pct


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="地基层覆盖率闸门（REQ-CLI-02 AC2）")
    parser.add_argument("--report", default="coverage.json", help="coverage json 报告路径")
    parser.add_argument("--min", type=float, default=85.0, help="地基层最低覆盖率阈值（百分比）")
    args = parser.parse_args(argv)

    report_path = Path(args.report)
    if not report_path.exists():
        print(f"未找到覆盖率报告 {report_path}；请先运行 `coverage json -o {report_path}`。")
        return 2

    report = json.loads(report_path.read_text(encoding="utf-8"))
    covered, total, pct = foundation_coverage(report)
    if total == 0:
        print("未在覆盖率报告中找到地基层文件（model/identity/lineage）。")
        return 2

    status = "达标" if pct >= args.min else "未达标"
    print(f"地基层覆盖率（model/identity/lineage）：{covered}/{total} = {pct:.2f}% "
          f"（阈值 {args.min:.0f}%）→ {status}")
    if pct < args.min:
        print("覆盖率低于阈值，阻断合并（REQ-CLI-02 AC2）。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
