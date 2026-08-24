# tests/golden/test_golden.py
"""Golden 回归测试（REQ-ARCH-02 / REQ-CLI-02 TC2）。

对 §14.2 的 golden fixture 集：
- 断言每个 fixture 的规范化结构签名与基线快照逐字节一致；漂移即失败并输出
  可读 diff（REQ-CLI-02 TC2：golden 图漂移时回归测试失败并输出 diff）。
- 断言同一输入连续构建两次签名相等（REQ-ARCH-02 AC1：确定性可复算）。
- 断言 8 类边在 golden 图全集上均有非零实例（呼应 REQ-GRAPH-02 AC2）。
"""
from __future__ import annotations

import difflib

import pytest

from tests.golden import _harness as h

_FIXTURES = h.list_fixtures()
_FIXTURE_IDS = [f.stem for f in _FIXTURES]

# 8 类边的权威集合（REQ-GRAPH-02）。
_ALL_EDGE_TYPES = {
    "reads_from", "writes_to", "has_column", "contains",
    "compute_dependency", "produces", "expr_operand", "table_lineage",
}


def test_golden_fixtures_present():
    """至少覆盖 DS-01~DS-04、DS-06 五个数据集。"""
    assert len(_FIXTURES) >= 5, "golden fixture 数量不足，检查 tests/golden/fixtures/"


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
def test_golden_signature_matches_baseline(fixture):
    """规范化结构签名与基线快照逐字节一致；漂移输出 diff。"""
    snap = h.snapshot_path(fixture)
    assert snap.exists(), (
        f"缺少基线快照 {snap.name}；如为新增 fixture，请运行 "
        f"`python -m tests.golden.regen` 固化基线。"
    )
    actual = h.dumps(h.canonical_signature(h.build_fixture_graph(fixture)))
    expected = snap.read_text(encoding="utf-8")
    if actual != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile=f"baseline/{snap.name}",
                tofile=f"current/{fixture.stem}",
            )
        )
        pytest.fail(
            f"golden 图漂移：{fixture.name} 的结构签名与基线不一致。\n"
            f"若为预期变更，请运行 `python -m tests.golden.regen` 并在 PR 标注 REQ 编号。\n"
            f"--- diff ---\n{diff}"
        )


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
def test_golden_build_is_reproducible(fixture):
    """REQ-ARCH-02 AC1：同一输入连续构建两次，规范化签名相等。"""
    s1 = h.dumps(h.canonical_signature(h.build_fixture_graph(fixture)))
    s2 = h.dumps(h.canonical_signature(h.build_fixture_graph(fixture)))
    assert s1 == s2


def test_all_eight_edge_types_present_across_golden():
    """REQ-GRAPH-02 AC2：8 类边在 golden 图全集上均有非零实例。"""
    seen: set[str] = set()
    for fixture in _FIXTURES:
        sig = h.canonical_signature(h.build_fixture_graph(fixture))
        seen |= set(sig["counts"]["by_edge_type"].keys())
    missing = _ALL_EDGE_TYPES - seen
    assert not missing, f"以下边类型在 golden 集上没有实例，覆盖不足: {sorted(missing)}"
