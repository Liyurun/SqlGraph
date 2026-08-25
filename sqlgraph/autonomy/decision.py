# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Evidence-bound autonomy decisions with pre-emptive safety gates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from sqlgraph.identity import stable_id

if TYPE_CHECKING:
    from sqlgraph.autonomy.authorization import AuthorizationVerification


POLICY_VERSION = "autonomy-v1"
BLAST_RADIUS_REVIEW_THRESHOLD = 0.7
OBJECT_RISK_REVIEW_THRESHOLD = 0.7
HISTORICAL_RELIABILITY_MIN = 0.3


class AutonomyLevel(str, Enum):
    L0_OBSERVE = "L0"
    L1_EXPLAIN = "L1"
    L2_PROPOSE = "L2"
    L3_BOUNDED = "L3"
    L4_APPROVED = "L4"
    L5_CONTINUOUS = "L5"


class AuthorizationScope(str, Enum):
    NONE = "none"
    SINGLE_L3 = "single_l3"
    CONTINUOUS_L5 = "continuous_l5"


@dataclass(frozen=True)
class ReversibilityEvidence:
    state_restorable: bool
    external_effects_controlled: bool
    rollback_verified: bool
    references: tuple[str, ...] = ()

    @property
    def verified(self) -> bool:
        return (
            self.state_restorable
            and self.external_effects_controlled
            and self.rollback_verified
        )


@dataclass(frozen=True)
class GovernanceAction:
    action_type: str
    evidence_version: str
    evidence_grounded: bool
    reversibility: ReversibilityEvidence
    authorization_scope: AuthorizationScope = AuthorizationScope.NONE
    authorization_identity: str = ""
    blast_radius: float = 0.0
    object_risk: float = 0.0
    historical_reliability: float = 1.0
    roi: float = 0.0

    def __post_init__(self) -> None:
        for field_name in (
            "blast_radius",
            "object_risk",
            "historical_reliability",
        ):
            value = getattr(self, field_name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0 and 1")


@dataclass(frozen=True)
class AutonomyDecision:
    level: AutonomyLevel
    requires_human_review: bool
    evidence_version: str
    reasons: tuple[str, ...] = ()
    reversibility_veto: bool = False
    evidence_veto: bool = False
    authorization_veto: bool = False
    authorization_grant_id: str = ""
    authorization_verifier: str = ""
    scoring_performed: bool = False
    within_l5_scope: bool = False
    policy_version: str = POLICY_VERSION
    decision_id: str = field(init=False)

    def __post_init__(self) -> None:
        key = "|".join((
            self.policy_version,
            self.evidence_version,
            self.level.value,
            str(self.requires_human_review),
            str(self.reversibility_veto),
            str(self.evidence_veto),
            str(self.authorization_veto),
            self.authorization_grant_id,
            self.authorization_verifier,
            *self.reasons,
        ))
        object.__setattr__(self, "decision_id", stable_id("decision", key, 128))

    def to_dict(self) -> dict:
        result = asdict(self)
        result["level"] = self.level.value
        return result


def decide_autonomy(
    action: GovernanceAction,
    authorization: "AuthorizationVerification | None" = None,
) -> AutonomyDecision:
    reasons = []

    if not action.reversibility.verified:
        reasons.append(
            "reversibility gate failed: state recovery, external effects, "
            "and verified rollback are all required"
        )
        return AutonomyDecision(
            level=AutonomyLevel.L4_APPROVED,
            requires_human_review=True,
            evidence_version=action.evidence_version,
            reasons=tuple(reasons),
            reversibility_veto=True,
        )

    reasons.append("reversibility gate passed")
    if not action.evidence_grounded or not action.evidence_version:
        reasons.append(
            "evidence gate failed: a grounded, versioned evidence bundle is required"
        )
        return AutonomyDecision(
            level=AutonomyLevel.L0_OBSERVE,
            requires_human_review=True,
            evidence_version=action.evidence_version,
            reasons=tuple(reasons),
            evidence_veto=True,
        )

    reasons.append("evidence gate passed")
    if action.authorization_scope == AuthorizationScope.NONE:
        reasons.append("authorization gate stopped execution at proposal")
        return AutonomyDecision(
            level=AutonomyLevel.L2_PROPOSE,
            requires_human_review=True,
            evidence_version=action.evidence_version,
            reasons=tuple(reasons),
            authorization_veto=True,
        )
    if (
        authorization is None
        or not authorization.verified
        or authorization.identity != action.authorization_identity
    ):
        reasons.append(
            authorization.reason
            if authorization is not None
            else "authorization verification is required"
        )
        return AutonomyDecision(
            level=AutonomyLevel.L2_PROPOSE,
            requires_human_review=True,
            evidence_version=action.evidence_version,
            reasons=tuple(reasons),
            authorization_veto=True,
            authorization_grant_id=(
                authorization.grant_id if authorization is not None else ""
            ),
            authorization_verifier=(
                authorization.verifier if authorization is not None else ""
            ),
        )

    review_reasons = []
    if action.blast_radius >= BLAST_RADIUS_REVIEW_THRESHOLD:
        review_reasons.append("blast radius requires per-action approval")
    if action.object_risk >= OBJECT_RISK_REVIEW_THRESHOLD:
        review_reasons.append("object risk requires per-action approval")
    if action.historical_reliability < HISTORICAL_RELIABILITY_MIN:
        review_reasons.append("historical reliability is below the safe threshold")
    reasons.extend(review_reasons)
    reasons.append(f"roi={action.roi} evaluated only after all hard gates")

    if review_reasons:
        return AutonomyDecision(
            level=AutonomyLevel.L4_APPROVED,
            requires_human_review=True,
            evidence_version=action.evidence_version,
            reasons=tuple(reasons),
            authorization_grant_id=authorization.grant_id,
            authorization_verifier=authorization.verifier,
            scoring_performed=True,
        )

    within_l5 = action.authorization_scope == AuthorizationScope.CONTINUOUS_L5
    reasons.append(
        "action is allowed as bounded L3 execution"
        + (" inside an L5 scope" if within_l5 else "")
    )
    return AutonomyDecision(
        level=AutonomyLevel.L3_BOUNDED,
        requires_human_review=False,
        evidence_version=action.evidence_version,
        reasons=tuple(reasons),
        authorization_grant_id=authorization.grant_id,
        authorization_verifier=authorization.verifier,
        scoring_performed=True,
        within_l5_scope=within_l5,
    )
