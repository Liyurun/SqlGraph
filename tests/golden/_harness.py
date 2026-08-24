# tests/golden/_harness.py
"""Golden 回归公共工具（REQ-ARCH-02 / REQ-CLI-02 TC2）。

把 ``tests/golden/fixtures/*.sql`` 构建成图，导出一份**规范化结构签名**并与
``tests/golden/snapshots/*.json`` 基线比对。产物漂移即测试失败并输出可读 diff。

规范化签名的设计取舍：
- 纳入：节点/边总数、按类型计数、全量节点 ID（含类型与名字）、全量边
  （source->target:type）、table_lineage 的表名对、覆盖报告。
  这些字段完整刻画「图的确定性结构」，任何真实结构漂移都会改变签名。
- 剔除：环境指纹里的 ``parser_version``（内嵌 sqlglot 版本号），它随运行环境
  合法变化，且已由 REQ-ARCH-02 AC2 单独覆盖；纳入签名会让 golden 在纯粹的
  依赖升级下误报。身份规则版本 ``identity_rule_version`` 仍纳入，因为它一旦
  变化就意味着 ID 派生规则改变，正是应当触发 rebless 的信号。

维护方式：图确有预期变化时，运行 ``python -m tests.golden.regen`` 重新固化
基线（rebless），并在 PR 中说明变更的 REQ 编号。
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlgraph.api import build_graph

_HERE = Path(__file__).resolve().parent
FIXTURES_DIR = _HERE / "fixtures"
SNAPSHOTS_DIR = _HERE / "snapshots"
DIALECT = "spark"


def list_fixtures() -> list[Path]:
    """返回全部 golden fixture（按文件名排序，保证确定顺序）。"""
    return sorted(FIXTURES_DIR.glob("*.sql"))


def build_fixture_graph(path: Path):
    """构建单个 fixture 的图。"""
    sql = path.read_text(encoding="utf-8")
    return build_graph(sql, dialect=DIALECT)


def _name_map(graph) -> dict:
    return {n.id: n.name for n in graph.nodes}


def canonical_signature(graph) -> dict:
    """把图规范化为可 JSON 序列化、可稳定 diff 的结构签名。"""
    nm = _name_map(graph)

    nodes = sorted(
        (
            {
                "id": n.id,
                "type": getattr(n.node_type, "value", str(n.node_type)),
                "name": n.name,
            }
            for n in graph.nodes
        ),
        key=lambda d: d["id"],
    )
    edges = sorted(
        (
            {
                "id": e.id,
                "source": e.source_id,
                "target": e.target_id,
                "type": getattr(e.edge_type, "value", str(e.edge_type)),
            }
            for e in graph.edges
        ),
        key=lambda d: (d["id"], d["source"], d["target"], d["type"]),
    )

    by_node_type: dict[str, int] = {}
    for n in nodes:
        by_node_type[n["type"]] = by_node_type.get(n["type"], 0) + 1
    by_edge_type: dict[str, int] = {}
    for e in edges:
        by_edge_type[e["type"]] = by_edge_type.get(e["type"], 0) + 1

    table_lineage = sorted(
        [nm.get(e["source"]), nm.get(e["target"])]
        for e in edges
        if e["type"] == "table_lineage"
    )

    coverage = graph.metadata.get("coverage", {})
    identity_rule_version = graph.metadata.get("environment", {}).get(
        "identity_rule_version"
    )

    return {
        "counts": {
            "nodes": len(nodes),
            "edges": len(edges),
            "by_node_type": dict(sorted(by_node_type.items())),
            "by_edge_type": dict(sorted(by_edge_type.items())),
        },
        "identity_rule_version": identity_rule_version,
        "nodes": nodes,
        "edges": edges,
        "table_lineage": table_lineage,
        "coverage": coverage,
    }


def snapshot_path(fixture: Path) -> Path:
    """fixture 对应的基线快照文件路径。"""
    return SNAPSHOTS_DIR / f"{fixture.stem}.json"


def dumps(signature: dict) -> str:
    """规范化 JSON 文本（排序键、UTF-8、末尾换行）。"""
    return json.dumps(signature, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def load_snapshot(fixture: Path) -> dict:
    return json.loads(snapshot_path(fixture).read_text(encoding="utf-8"))


def write_snapshot(fixture: Path, signature: dict) -> None:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path(fixture).write_text(dumps(signature), encoding="utf-8")
