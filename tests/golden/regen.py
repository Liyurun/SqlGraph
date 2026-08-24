# tests/golden/regen.py
"""重新固化 golden 基线（rebless）。

仅当图确有**预期**变化时运行，并在 PR 中标注涉及的 REQ 编号：

    python -m tests.golden.regen

它会为 ``fixtures/`` 下每个 SQL 重新生成规范化结构签名并写入 ``snapshots/``。
日常 CI 绝不自动运行本脚本——那会让 golden 回归失去意义。
"""
from __future__ import annotations

from tests.golden import _harness as h


def main() -> int:
    fixtures = h.list_fixtures()
    if not fixtures:
        print("未发现任何 golden fixture。")
        return 1
    for fx in fixtures:
        graph = h.build_fixture_graph(fx)
        sig = h.canonical_signature(graph)
        h.write_snapshot(fx, sig)
        print(f"已固化基线: {fx.name} -> {h.snapshot_path(fx).name} "
              f"(nodes={sig['counts']['nodes']}, edges={sig['counts']['edges']})")
    print(f"共固化 {len(fixtures)} 个基线。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
