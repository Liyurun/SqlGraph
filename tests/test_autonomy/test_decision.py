from __future__ import annotations

import pytest

from sqlgraph.autonomy import (
    AuthorizationScope,
    AutonomyLevel,
    GovernanceAction,
    ReversibilityEvidence,
    decide_autonomy,
)


def _action(
    *,
    reversible: bool = True,
    grounded: bool = True,
    scope: AuthorizationScope = AuthorizationScope.SINGLE_L3,
    roi: float = 1.0,
) -> GovernanceAction:
    return GovernanceAction(
        action_type="sql_patch",
        evidence_version="task-1@v1#abc",
        evidence_grounded=grounded,
        reversibility=ReversibilityEvidence(
            state_restorable=reversible,
            external_effects_controlled=reversible,
            rollback_verified=reversible,
        ),
        authorization_scope=scope,
        roi=roi,
    )


@pytest.mark.parametrize(
    ("reversible", "grounded", "scope", "expected"),
    [
        (False, True, AuthorizationScope.CONTINUOUS_L5, AutonomyLevel.L4_APPROVED),
        (True, False, AuthorizationScope.SINGLE_L3, AutonomyLevel.L0_OBSERVE),
        (True, True, AuthorizationScope.NONE, AutonomyLevel.L2_PROPOSE),
        (True, True, AuthorizationScope.SINGLE_L3, AutonomyLevel.L3_BOUNDED),
    ],
)
def test_hard_gates_precede_scoring(reversible, grounded, scope, expected):
    decision = decide_autonomy(
        _action(
            reversible=reversible,
            grounded=grounded,
            scope=scope,
            roi=999,
        )
    )

    assert decision.level == expected
    if not reversible or not grounded:
        assert not decision.scoring_performed


def test_continuous_scope_is_separate_from_action_depth():
    decision = decide_autonomy(
        _action(scope=AuthorizationScope.CONTINUOUS_L5)
    )

    assert decision.level == AutonomyLevel.L3_BOUNDED
    assert decision.within_l5_scope
    assert decision.policy_version
    assert decision.evidence_version == "task-1@v1#abc"
