# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Compatibility exports for the governance reasoning module."""

from dataclasses import dataclass, field

from sqlgraph.autonomy import AutonomyLevel, decide_autonomy
from sqlgraph.evidence import assess_sufficiency, build_evidence_subgraph
from sqlgraph.lineage import drilldown
from sqlgraph.reasoning import (
    STEPS,
    GovernanceRequest,
    GovernanceResult,
    GovernanceRunner,
)
from sqlgraph.verify import verify


@dataclass
class StepRecord:
    step: str
    evidence_version: str
    detail: dict = field(default_factory=dict)
    transition: str | None = None


@dataclass
class AuditTrail:
    task_id: str
    action_type: str
    records: list[StepRecord] = field(default_factory=list)
    decision: dict | None = None
    verify_report: dict | None = None
    outcome: str = "pending"

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "action_type": self.action_type,
            "steps": [
                {
                    "step": record.step,
                    "evidence_version": record.evidence_version,
                    "detail": record.detail,
                    "transition": record.transition,
                }
                for record in self.records
            ],
            "decision": self.decision,
            "verify_report": self.verify_report,
            "outcome": self.outcome,
        }

    def replay(self) -> list[str]:
        return [
            f"{record.step}@{record.evidence_version}"
            + (f" [{record.transition}]" if record.transition else "")
            for record in self.records
        ]


class GovernanceLoop:
    """Compatibility facade for the original graph-only demonstration."""

    def __init__(self, graph):
        self.graph = graph

    def run(
        self,
        task_id,
        source_table,
        target_table,
        action,
        *,
        governance_issue=None,
        runtime_observed=None,
        runtime_target=None,
    ):
        evidence = build_evidence_subgraph(
            self.graph,
            task_id,
            [source_table, target_table],
        )
        sufficiency = assess_sufficiency(evidence)
        lineage = drilldown(self.graph, source_table, target_table)
        decision = decide_autonomy(action)
        executed = (
            decision.level == AutonomyLevel.L3_BOUNDED
            and not decision.requires_human_review
            and sufficiency.sufficient
            and lineage.get("found")
        )
        report = verify(
            self.graph,
            source_table,
            target_table,
            governance_issue=governance_issue,
            runtime_observed=runtime_observed if executed else None,
            runtime_target=runtime_target,
        )
        raw_report = report.to_dict()
        compatibility_report = {
            "structure": raw_report["structure"],
            "contract": raw_report["code"],
            "runtime": raw_report["runtime"],
            "closed_loop_status": raw_report["closed_loop_status"],
        }
        trail = AuditTrail(task_id, action.action_type)
        version = evidence.version_id
        details = (
            ("observe", {"sufficiency": sufficiency.action}, None),
            ("explain", {"grounded": bool(lineage.get("found"))}, None),
            ("propose", {"proposed_action": action.action_type}, None),
            (
                "authorize",
                decision.to_dict(),
                "cognition->action",
            ),
            (
                "execute",
                {"executed": executed},
                "authorized->external_execute" if executed else "halt->human_review",
            ),
            (
                "verify",
                {"closed_loop": compatibility_report["closed_loop_status"]},
                "execute->reobserve" if executed else None,
            ),
            (
                "learn",
                {"writeback": "signals_only"},
                None,
            ),
        )
        trail.records.extend(
            StepRecord(step, version, detail, transition)
            for step, detail, transition in details
        )
        trail.decision = decision.to_dict()
        trail.verify_report = compatibility_report
        trail.outcome = (
            (
                "closed"
                if compatibility_report["closed_loop_status"] == "success"
                else compatibility_report["closed_loop_status"]
            )
            if executed
            else "held_for_human_review"
        )
        return trail

__all__ = [
    "STEPS",
    "GovernanceRequest",
    "GovernanceResult",
    "GovernanceRunner",
    "AuditTrail",
    "GovernanceLoop",
    "StepRecord",
]
