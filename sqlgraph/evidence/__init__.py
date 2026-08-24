# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Public evidence collection and sufficiency interface."""

from __future__ import annotations

from sqlgraph.evidence.engine import EvidenceEngine
from sqlgraph.evidence.model import (
    EVIDENCE_RULE_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    EvidenceBundle,
    EvidenceFinding,
    EvidenceRequest,
    SufficiencyDecision,
)


def build_evidence_subgraph(
    graph,
    task_id: str,
    anchor_tables: list[str],
    intent: str = "generic",
) -> EvidenceBundle:
    """Compatibility helper for callers that do not yet pass a baseline."""
    request = EvidenceRequest(
        task_id=task_id,
        baseline_id=graph.metadata.get("baseline_id", "baseline-unbound"),
        intent=intent,
        anchors=tuple(anchor_tables),
        direction="both",
        max_depth=1,
    )
    return EvidenceEngine(graph).collect(request)


def assess_sufficiency(
    evidence: EvidenceBundle,
    required_sources: list[str] | None = None,
) -> SufficiencyDecision:
    """Compatibility sufficiency check using the bundle's coverage contract."""
    if required_sources is not None:
        resolved_names = set(
            evidence.coverage_contract.get("anchor_names", ())
        )
        missing_sources = sorted(set(required_sources) - resolved_names)
        if missing_sources:
            return SufficiencyDecision(
                sufficient=False,
                action="expand",
                missing_obligations=("anchors_resolved",),
                reasons=(
                    "required sources are outside the current evidence scope: "
                    + ", ".join(missing_sources),
                ),
                coverage_contract=evidence.coverage_contract,
                disclosed_gaps=evidence.gaps,
                residual_unknowns=evidence.residual_unknowns,
            )
    if evidence.gaps or evidence.residual_unknowns:
        return SufficiencyDecision(
            sufficient=False,
            action="escalate",
            missing_obligations=("no_unresolved",),
            reasons=evidence.gaps,
            coverage_contract=evidence.coverage_contract,
            disclosed_gaps=evidence.gaps,
            residual_unknowns=evidence.residual_unknowns,
        )
    return SufficiencyDecision(
        sufficient=True,
        action="stop",
        coverage_contract=evidence.coverage_contract,
    )


__all__ = [
    "EVIDENCE_RULE_VERSION",
    "EVIDENCE_SCHEMA_VERSION",
    "EvidenceBundle",
    "EvidenceEngine",
    "EvidenceFinding",
    "EvidenceRequest",
    "SufficiencyDecision",
    "assess_sufficiency",
    "build_evidence_subgraph",
]
