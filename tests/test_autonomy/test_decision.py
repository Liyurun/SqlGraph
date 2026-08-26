from __future__ import annotations

import pytest

from sqlgraph.autonomy import (
    AuthorizationGrant,
    AuthorizationScope,
    AutonomyLevel,
    GovernanceAction,
    ReversibilityEvidence,
    StaticAuthorizationVerifier,
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
        authorization_identity="test-policy",
        roi=roi,
    )


def _authorization(action):
    return StaticAuthorizationVerifier({
        "test-policy": AuthorizationGrant(
            grant_id="grant-test",
            identity="test-policy",
            max_scope=AuthorizationScope.CONTINUOUS_L5,
            allowed_actions=("sql_patch",),
        )
    }).verify(
        action.authorization_identity,
        action.action_type,
        action.authorization_scope,
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
    action = _action(
        reversible=reversible,
        grounded=grounded,
        scope=scope,
        roi=999,
    )
    decision = decide_autonomy(action, _authorization(action))

    assert decision.level == expected
    if not reversible or not grounded:
        assert not decision.scoring_performed


def test_continuous_scope_is_separate_from_action_depth():
    action = _action(scope=AuthorizationScope.CONTINUOUS_L5)
    decision = decide_autonomy(action, _authorization(action))

    assert decision.level == AutonomyLevel.L3_BOUNDED
    assert decision.within_l5_scope
    assert decision.policy_version
    assert decision.evidence_version == "task-1@v1#abc"


def test_unknown_identity_cannot_authorize_l3():
    action = _action()
    authorization = StaticAuthorizationVerifier({}).verify(
        action.authorization_identity,
        action.action_type,
        action.authorization_scope,
    )

    decision = decide_autonomy(action, authorization)

    assert decision.level == AutonomyLevel.L2_PROPOSE
    assert decision.authorization_veto


def test_action_outside_grant_is_rejected():
    verifier = StaticAuthorizationVerifier({
        "test-policy": AuthorizationGrant(
            grant_id="grant-test",
            identity="test-policy",
            max_scope=AuthorizationScope.SINGLE_L3,
            allowed_actions=("sql_patch",),
        )
    })

    verification = verifier.verify(
        "test-policy",
        "drop_table",
        AuthorizationScope.SINGLE_L3,
    )

    assert not verification.verified
    assert "not allowed" in verification.reason


def test_scope_outside_grant_is_rejected():
    verifier = StaticAuthorizationVerifier({
        "test-policy": AuthorizationGrant(
            grant_id="grant-test",
            identity="test-policy",
            max_scope=AuthorizationScope.SINGLE_L3,
            allowed_actions=("sql_patch",),
        )
    })

    verification = verifier.verify(
        "test-policy",
        "sql_patch",
        AuthorizationScope.CONTINUOUS_L5,
    )

    assert not verification.verified
    assert "exceeds" in verification.reason


def test_grant_identity_must_match_registry_key():
    verifier = StaticAuthorizationVerifier({
        "test-policy": AuthorizationGrant(
            grant_id="grant-test",
            identity="different-policy",
            max_scope=AuthorizationScope.SINGLE_L3,
            allowed_actions=("sql_patch",),
        )
    })

    verification = verifier.verify(
        "test-policy",
        "sql_patch",
        AuthorizationScope.SINGLE_L3,
    )

    assert not verification.verified
    assert "identity" in verification.reason
