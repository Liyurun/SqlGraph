from __future__ import annotations

from sqlgraph.autonomy import (
    AuthorizationScope,
    AutonomyLevel,
    GovernanceAction,
    ReversibilityEvidence,
    decide_autonomy,
)


def test_high_roi_cannot_override_unverified_rollback():
    action = GovernanceAction(
        action_type="drop_table",
        evidence_version="task-1@v1#abc",
        evidence_grounded=True,
        reversibility=ReversibilityEvidence(
            state_restorable=True,
            external_effects_controlled=True,
            rollback_verified=False,
        ),
        authorization_scope=AuthorizationScope.CONTINUOUS_L5,
        historical_reliability=1.0,
        roi=1_000_000,
    )

    decision = decide_autonomy(action)

    assert decision.level == AutonomyLevel.L4_APPROVED
    assert decision.requires_human_review
    assert decision.reversibility_veto
    assert not decision.scoring_performed


def test_missing_evidence_version_rejects_explanation():
    action = GovernanceAction(
        action_type="add_tag",
        evidence_version="",
        evidence_grounded=True,
        reversibility=ReversibilityEvidence(True, True, True),
        authorization_scope=AuthorizationScope.SINGLE_L3,
    )

    decision = decide_autonomy(action)

    assert decision.level == AutonomyLevel.L0_OBSERVE
    assert decision.evidence_veto
