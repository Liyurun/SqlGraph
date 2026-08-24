# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Seven-step governance orchestration over explicit module interfaces."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sqlgraph.actions import (
    ActionEngine,
    ActionPlan,
    ActionRequest,
    ExecutionResult,
)
from sqlgraph.audit import AuditEvent, AuditLog
from sqlgraph.autonomy import (
    AutonomyDecision,
    AutonomyLevel,
    GovernanceAction,
    decide_autonomy,
)
from sqlgraph.baseline import BaselineManifest
from sqlgraph.evidence import EvidenceBundle, EvidenceEngine, EvidenceRequest
from sqlgraph.graphrag import GroundedAssertion, validate_assertions
from sqlgraph.verification import (
    LayerResult,
    VerificationEngine,
    VerificationReport,
)


STEPS = (
    "observe",
    "explain",
    "propose",
    "authorize",
    "execute",
    "verify",
    "learn",
)


@dataclass(frozen=True)
class GovernanceRequest:
    task_id: str
    baseline: BaselineManifest
    graph: Any
    evidence_request: EvidenceRequest
    action: GovernanceAction
    adapter: str
    operations: tuple[dict[str, Any], ...]
    source_path: str
    source_table: str
    target_table: str
    dialect: str | None = None
    rollback_plan: tuple[dict[str, Any], ...] = ()
    runtime_observed: dict | None = None


@dataclass(frozen=True)
class GovernanceResult:
    task_id: str
    outcome: str
    evidence: EvidenceBundle
    decision: AutonomyDecision
    action_plan: ActionPlan | None
    execution: ExecutionResult
    verification: VerificationReport
    events: tuple[AuditEvent, ...]
    audit_path: str

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "outcome": self.outcome,
            "evidence": self.evidence.to_dict(),
            "decision": self.decision.to_dict(),
            "action_plan": (
                self.action_plan.to_dict() if self.action_plan else None
            ),
            "execution": self.execution.to_dict(),
            "verification": self.verification.to_dict(),
            "events": [event.to_dict() for event in self.events],
            "audit_path": self.audit_path,
        }


class GovernanceRunner:
    def __init__(
        self,
        evidence_engine: EvidenceEngine,
        action_engine: ActionEngine,
        verification_engine: VerificationEngine,
        audit_log: AuditLog,
    ):
        self.evidence_engine = evidence_engine
        self.action_engine = action_engine
        self.verification_engine = verification_engine
        self.audit_log = audit_log

    def run(self, request: GovernanceRequest) -> GovernanceResult:
        events = []

        def record(
            step: str,
            payload: dict,
            *,
            evidence_version: str = "",
            policy_version: str = "",
            authorization_identity: str = "",
            idempotency_key: str = "",
            transition: str = "",
        ) -> None:
            events.append(self.audit_log.append(AuditEvent(
                task_id=request.task_id,
                baseline_id=request.baseline.baseline_id,
                event_type=step,
                step=step,
                payload=payload,
                evidence_version=evidence_version,
                policy_version=policy_version,
                authorization_identity=authorization_identity,
                idempotency_key=idempotency_key,
                transition=transition,
            )))

        evidence = self.evidence_engine.collect(request.evidence_request)
        sufficiency = self.evidence_engine.assess(evidence)
        record(
            "observe",
            {
                "evidence_hash": evidence.subgraph_hash,
                "sufficiency": sufficiency.action,
                "missing_obligations": list(sufficiency.missing_obligations),
            },
            evidence_version=evidence.version_id,
        )

        citations = tuple(
            citation
            for finding in evidence.supporting
            for citation in finding.citations
        )
        grounding = validate_assertions(
            [GroundedAssertion(
                statement=(
                    f"{request.target_table} depends on "
                    f"{request.source_table}"
                ),
                citations=citations,
                baseline_id=request.baseline.baseline_id,
                evidence_hash=evidence.subgraph_hash,
            )],
            evidence,
        )
        grounded = grounding.status == "grounded" and sufficiency.sufficient
        record(
            "explain",
            grounding.to_dict(),
            evidence_version=evidence.version_id,
        )
        record(
            "propose",
            {
                "action_type": request.action.action_type,
                "adapter": request.adapter,
                "operation_count": len(request.operations),
            },
            evidence_version=evidence.version_id,
        )

        action = replace(
            request.action,
            evidence_version=evidence.version_id,
            evidence_grounded=grounded,
        )
        decision = decide_autonomy(action)
        record(
            "authorize",
            decision.to_dict(),
            evidence_version=evidence.version_id,
            policy_version=decision.policy_version,
            authorization_identity=action.authorization_identity,
            transition="cognition->action",
        )

        plan = None
        if (
            decision.level == AutonomyLevel.L3_BOUNDED
            and not decision.requires_human_review
        ):
            plan = self.action_engine.plan(ActionRequest(
                task_id=request.task_id,
                baseline_id=request.baseline.baseline_id,
                evidence_version=evidence.version_id,
                decision=decision,
                adapter=request.adapter,
                operations=request.operations,
                rollback_plan=request.rollback_plan,
            ))
            dry_run = self.action_engine.dry_run(plan)
            execution = self.action_engine.execute(plan)
            execute_payload = {
                "dry_run": dry_run.status,
                **execution.to_dict(),
            }
            transition = "authorized->external_execute"
        else:
            execution = ExecutionResult(
                execution_id="",
                idempotency_key="",
                adapter=request.adapter,
                status="blocked",
                error="autonomy decision did not authorize L3 execution",
            )
            execute_payload = execution.to_dict()
            transition = "halt->human_review"
        record(
            "execute",
            execute_payload,
            evidence_version=evidence.version_id,
            policy_version=decision.policy_version,
            authorization_identity=action.authorization_identity,
            idempotency_key=execution.idempotency_key,
            transition=transition,
        )

        if plan is not None and execution.status in {"success", "noop"}:
            verification = self.verification_engine.verify(
                plan,
                execution,
                source_path=request.source_path,
                source_table=request.source_table,
                target_table=request.target_table,
                dialect=request.dialect,
                runtime_observed=request.runtime_observed,
            )
            verification_payload = verification.to_dict()
            if verification.outcome == "failed" and execution.status == "success":
                rollback = self.action_engine.rollback_execution(plan, execution)
                verification_payload["rollback"] = {
                    "status": rollback.status,
                    "verified": rollback.verified,
                    "restored": list(rollback.restored),
                    "error": rollback.error,
                }
        else:
            verification = VerificationReport(
                code=LayerResult("code", "not_run"),
                structure=LayerResult("structure", "not_run"),
                runtime=LayerResult("runtime", "not_run"),
            )
            verification_payload = verification.to_dict()
        record(
            "verify",
            verification_payload,
            evidence_version=evidence.version_id,
            transition="execute->reobserve" if plan else "",
        )

        if execution.status == "blocked":
            outcome = "held_for_human_review"
        else:
            outcome = verification.outcome
        record(
            "learn",
            {
                "outcome": outcome,
                "writeback": "signals_only",
                "authorization_expanded": False,
            },
            evidence_version=evidence.version_id,
        )
        return GovernanceResult(
            task_id=request.task_id,
            outcome=outcome,
            evidence=evidence,
            decision=decision,
            action_plan=plan,
            execution=execution,
            verification=verification,
            events=tuple(events),
            audit_path=str(Path(self.audit_log.path).resolve()),
        )
