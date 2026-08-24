# sqlgraph/contract/__init__.py
"""业务契约模型（REQ-ADP-02）。

业务契约是对"预期业务语义"的版本化权威定义。与已实现语义（图中的实现事实）
冲突时，产出"治理问题"记录，任一方不得覆盖另一方（书稿第 2 章）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BusinessContract:
    """一个指标/字段的业务契约（版本化权威定义）。"""
    metric: str                       # 指标/字段名，如 "gmv"
    version: str                      # 契约版本
    definition: str = ""              # 含义（自然语言）
    include_rules: list[str] = field(default_factory=list)  # 纳入规则
    exclude_rules: list[str] = field(default_factory=list)  # 排除规则
    data_type: str = ""               # 类型
    unit: str = ""                    # 单位
    null_behavior: str = ""           # 空值行为
    owner: str = ""                   # 责任人
    approval_history: list[dict] = field(default_factory=list)  # 审批历史

    def validate_completeness(self) -> list[str]:
        """校验契约字段完备性，返回缺失的必填字段列表（空表示完备）。"""
        missing = []
        if not self.metric:
            missing.append("metric")
        if not self.version:
            missing.append("version")
        if not self.definition:
            missing.append("definition")
        if not self.owner:
            missing.append("owner")
        return missing


@dataclass
class GovernanceIssue:
    """治理问题：已实现语义与业务契约冲突的记录（不改写任何一方）。"""
    metric: str
    contract_version: str
    implemented_semantics: str        # 图中观察到的已实现语义（如指纹/表达式）
    expected_semantics: str           # 契约声明的预期语义
    kind: str = "caliber_conflict"

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "metric": self.metric,
            "contract_version": self.contract_version,
            "implemented": self.implemented_semantics,
            "expected": self.expected_semantics,
            "note": "契约与已实现语义冲突，记录为治理问题；任一方不得覆盖另一方",
        }


def check_conflict(contract: BusinessContract, implemented_semantics: str,
                   expected_marker: str) -> GovernanceIssue | None:
    """对照契约与已实现语义，冲突时产出治理问题记录（REQ-ADP-02 AC2）。

    Args:
        contract: 业务契约
        implemented_semantics: 图中观察到的实现（如表达式/指纹的可读描述）
        expected_marker: 用于判断实现是否符合契约的标记（简化：契约要求实现中
            应包含的关键片段，如 "refund" 表示 gmv 口径应扣退款）

    Returns:
        冲突时返回 GovernanceIssue，否则 None。不改写 contract 或图。
    """
    if expected_marker and expected_marker not in implemented_semantics:
        return GovernanceIssue(
            metric=contract.metric,
            contract_version=contract.version,
            implemented_semantics=implemented_semantics,
            expected_semantics=f"应满足契约标记: {expected_marker}",
        )
    return None
