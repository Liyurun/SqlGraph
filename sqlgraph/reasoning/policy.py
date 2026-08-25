# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Shared preparation for evidence-bound autonomy decisions."""

from __future__ import annotations

from dataclasses import replace

from sqlgraph.autonomy import (
    AuthorizationVerifier,
    AutonomyDecision,
    GovernanceAction,
    ReversibilityEvidence,
    decide_autonomy,
)


def prepare_autonomy_decision(
    action: GovernanceAction,
    authorization_verifier: AuthorizationVerifier,
    reversibility: ReversibilityEvidence,
) -> tuple[GovernanceAction, AutonomyDecision]:
    verified_action = replace(action, reversibility=reversibility)
    authorization = authorization_verifier.verify(
        verified_action.authorization_identity,
        verified_action.action_type,
        verified_action.authorization_scope,
    )
    return verified_action, decide_autonomy(
        verified_action,
        authorization,
    )
