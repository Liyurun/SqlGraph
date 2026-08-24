# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Action planning and execution result contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlgraph.autonomy import AutonomyDecision


ACTION_SCHEMA_VERSION = "action-plan-v1"


@dataclass(frozen=True)
class ActionRequest:
    task_id: str
    baseline_id: str
    evidence_version: str
    decision: AutonomyDecision
    adapter: str
    operations: tuple[dict[str, Any], ...]
    rollback_plan: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ActionPlan:
    task_id: str
    baseline_id: str
    evidence_version: str
    decision_id: str
    adapter: str
    operations: tuple[dict[str, Any], ...]
    rollback_plan: tuple[dict[str, Any], ...]
    idempotency_key: str
    schema_version: str = ACTION_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DryRunResult:
    status: str
    checks: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RollbackResult:
    status: str
    verified: bool
    restored: tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class ExecutionResult:
    execution_id: str
    idempotency_key: str
    adapter: str
    status: str
    changes: tuple[str, ...] = ()
    circuit_open: bool = False
    rollback: RollbackResult | None = None
    error: str = ""

    def to_dict(self) -> dict:
        result = asdict(self)
        return result
