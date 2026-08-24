# sqlgraph/metrics/__init__.py
"""结构风险指标与残余风险（REQ-MET-01 / REQ-MET-02）。

基于 TableGraph 计算可达性（潜在结构影响面）、桥接分等结构指标。核心纪律：
**指标结果必须可还原为图上可指认的证据**（可达路径 / 桥接边），不得由模型
语感或单一分数直接裁决治理结论。
"""
from __future__ import annotations

from sqlgraph.model import EdgeType, TableNode


def _table_adjacency(graph) -> dict[str, list[str]]:
    """由 table_lineage 边构造表级有向邻接表 (src -> [dst])。"""
    adj: dict[str, list[str]] = {}
    for e in graph.edges:
        if e.edge_type == EdgeType.TABLE_LINEAGE:
            adj.setdefault(e.source_id, []).append(e.target_id)
    return adj


def reachable_set(graph, table_name: str) -> list[str]:
    """沿已收录血缘可达的下游表集合（潜在结构影响面上界，非实际变化集）。"""
    node = graph.get_node_by_name(table_name)
    if not node:
        return []
    adj = _table_adjacency(graph)
    seen: set[str] = set()
    stack = list(adj.get(node.id, []))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj.get(cur, []))
    return sorted(
        graph.get_node(tid).full_name for tid in seen if graph.get_node(tid)
    )


def blast_score(graph, table_name: str) -> dict:
    """影响面分数（REQ-MET-01）：可达下游表数量 + 可解释的可达集证据。

    Returns: {"score", "reachable", "evidence": {"paths": ...}}
    """
    reachable = reachable_set(graph, table_name)
    return {
        "table": table_name,
        "score": len(reachable),
        "reachable": reachable,
        "evidence": {
            "kind": "reachable_set",
            "note": "沿已收录 table_lineage 边可达的下游集合，是潜在结构影响面上界，非实际变化集",
            "members": reachable,
        },
    }


def bridge_score(graph, table_name: str) -> dict:
    """桥接分（REQ-MET-01，简化参考实现）：删点后有多少下游可达性被切断。

    以"删除该表后，其直接下游从该表上游不再可达的比例"近似桥接性。结果附带
    被切断的下游作为可指认证据。真正的割点判定需完整连通性测试，此处是参考
    实现，可替换。
    """
    node = graph.get_node_by_name(table_name)
    if not node:
        return {"table": table_name, "score": 0.0, "evidence": {}}
    adj = _table_adjacency(graph)
    # 该表的上游（谁指向它）与下游
    upstream = [s for s, dsts in adj.items() if node.id in dsts]
    downstream = adj.get(node.id, [])
    if not downstream:
        return {"table": table_name, "score": 0.0,
                "evidence": {"kind": "cut_test", "cut_off": []}}
    # 删除 node 后，从上游还能否到达每个下游
    def _reach_without(start: str, blocked: str) -> set[str]:
        seen, stack = set(), list(adj.get(start, []))
        while stack:
            c = stack.pop()
            if c == blocked or c in seen:
                continue
            seen.add(c)
            stack.extend(x for x in adj.get(c, []) if x != blocked)
        return seen
    reachable_after: set[str] = set()
    for up in upstream:
        reachable_after |= _reach_without(up, node.id)
    cut_off = [d for d in downstream if d not in reachable_after]
    score = len(cut_off) / len(downstream) if downstream else 0.0
    return {
        "table": table_name,
        "score": round(score, 4),
        "evidence": {
            "kind": "cut_test",
            "cut_off": [graph.get_node(d).full_name for d in cut_off if graph.get_node(d)],
            "note": "删除该表后，从其上游不再可达的直接下游（近似桥接性证据）",
        },
    }


# --- REQ-MET-02: roi 与残余风险 ---------------------------------------------

# 残余风险的已知类别（书稿第五部）：证据边界、解析遗漏、共同模式错误、
# 监控延迟、回滚失败。
RESIDUAL_RISK_CATEGORIES = [
    "evidence_boundary",       # 证据边界（如可达集只是上界）
    "parse_omission",          # 解析遗漏（动态 SQL / UNKNOWN 列）
    "common_mode_error",       # 共同模式错误
    "monitoring_delay",        # 监控延迟
    "rollback_failure",        # 回滚失败
]


def roi(before: float, after: float, target: float | None = None,
        tolerance: float = 0.05) -> dict:
    """口径/成本修复的 roi 指标（REQ-MET-02）。

    可复算：给定修复前后值，返回变化与（可选）相对预演目标的误差带判定。
    书稿示例：0.9 -> 1.78（预演目标约 1.8，落在可接受误差内）。
    """
    result = {
        "before": before,
        "after": after,
        "delta": round(after - before, 6),
    }
    if target is not None:
        rel_err = abs(after - target) / abs(target) if target else float("inf")
        result["target"] = target
        result["relative_error"] = round(rel_err, 6)
        result["within_tolerance"] = rel_err <= tolerance
    return result


def with_residual_risk(conclusion: dict, categories: list[str] | None = None) -> dict:
    """给一个治理结论附加残余风险披露字段（REQ-MET-02 AC2）。

    residual_risk 非空，显式列举已知残余风险类别，不允许"零风险"承诺。
    """
    cats = categories if categories is not None else list(RESIDUAL_RISK_CATEGORIES)
    out = dict(conclusion)
    out["residual_risk"] = cats
    return out
