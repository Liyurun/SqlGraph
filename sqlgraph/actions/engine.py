# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Policy-aware action planning and execution."""

from __future__ import annotations

import json
from dataclasses import replace

from sqlgraph.actions.adapters import ActionAdapter, AdapterExecutionError
from sqlgraph.actions.model import (
    ActionPlan,
    ActionRequest,
    DryRunResult,
    ExecutionResult,
)
from sqlgraph.autonomy import AutonomyLevel
from sqlgraph.identity import stable_id


class ActionEngine:
    def __init__(self, adapters: list[ActionAdapter]):
        self._adapters = {adapter.name: adapter for adapter in adapters}
        self._executions: dict[str, ExecutionResult] = {}
        self._rollback_states: dict[str, dict] = {}
        self.circuit_open = False

    def plan(self, request: ActionRequest) -> ActionPlan:
        decision = request.decision
        if decision.level != AutonomyLevel.L3_BOUNDED:
            raise PermissionError(
                f"decision {decision.level.value} does not authorize execution"
            )
        if decision.requires_human_review:
            raise PermissionError("human approval is required")
        if decision.evidence_version != request.evidence_version:
            raise PermissionError("decision and action evidence versions differ")
        if request.adapter not in self._adapters:
            raise ValueError(f"unknown action adapter: {request.adapter}")
        payload = {
            "task_id": request.task_id,
            "baseline_id": request.baseline_id,
            "evidence_version": request.evidence_version,
            "decision_id": decision.decision_id,
            "adapter": request.adapter,
            "operations": request.operations,
            "rollback_plan": request.rollback_plan,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return ActionPlan(
            **payload,
            idempotency_key=stable_id("idem", canonical, 128),
        )

    def dry_run(self, plan: ActionPlan) -> DryRunResult:
        if self.circuit_open:
            return DryRunResult(
                status="blocked",
                checks=("circuit-open",),
            )
        checks = self._adapters[plan.adapter].dry_run(plan.operations)
        return DryRunResult(status="ready", checks=checks)

    def execute(self, plan: ActionPlan) -> ExecutionResult:
        previous = self._executions.get(plan.idempotency_key)
        if previous and previous.status == "success":
            return replace(previous, status="noop")
        if self.circuit_open:
            return ExecutionResult(
                execution_id=stable_id("execution", plan.idempotency_key, 128),
                idempotency_key=plan.idempotency_key,
                adapter=plan.adapter,
                status="blocked",
                circuit_open=True,
                error="circuit is open",
            )

        adapter = self._adapters[plan.adapter]
        try:
            adapter.dry_run(plan.operations)
            changes, rollback_state = adapter.execute(plan.operations)
        except AdapterExecutionError as exc:
            rollback = adapter.rollback(exc.rollback_state)
            self.circuit_open = True
            return ExecutionResult(
                execution_id=stable_id("execution", plan.idempotency_key, 128),
                idempotency_key=plan.idempotency_key,
                adapter=plan.adapter,
                status="rolled_back" if rollback.verified else "failed",
                changes=(),
                circuit_open=True,
                rollback=rollback,
                error=str(exc),
            )
        except Exception as exc:
            self.circuit_open = True
            return ExecutionResult(
                execution_id=stable_id("execution", plan.idempotency_key, 128),
                idempotency_key=plan.idempotency_key,
                adapter=plan.adapter,
                status="failed",
                circuit_open=True,
                error=str(exc),
            )

        result = ExecutionResult(
            execution_id=stable_id("execution", plan.idempotency_key, 128),
            idempotency_key=plan.idempotency_key,
            adapter=plan.adapter,
            status="success",
            changes=changes,
        )
        self._executions[plan.idempotency_key] = result
        self._rollback_states[result.execution_id] = rollback_state
        return result

    def rollback(self, plan: ActionPlan, state: dict):
        return self._adapters[plan.adapter].rollback(state)

    def rollback_execution(
        self,
        plan: ActionPlan,
        execution: ExecutionResult,
    ):
        state = self._rollback_states.get(execution.execution_id)
        if state is None:
            raise ValueError(
                f"rollback state is unavailable: {execution.execution_id}"
            )
        result = self._adapters[plan.adapter].rollback(state)
        self.circuit_open = True
        return result
