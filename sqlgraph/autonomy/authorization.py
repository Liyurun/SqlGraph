# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Authorization verification contracts and reference grants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from sqlgraph.autonomy.decision import AuthorizationScope


_SCOPE_RANK = {
    AuthorizationScope.NONE: 0,
    AuthorizationScope.SINGLE_L3: 1,
    AuthorizationScope.CONTINUOUS_L5: 2,
}


@dataclass(frozen=True)
class AuthorizationGrant:
    grant_id: str
    identity: str
    max_scope: AuthorizationScope
    allowed_actions: tuple[str, ...]


@dataclass(frozen=True)
class AuthorizationVerification:
    verified: bool
    grant_id: str
    identity: str
    granted_scope: AuthorizationScope
    allowed_actions: tuple[str, ...]
    reason: str
    verifier: str


class AuthorizationVerifier(Protocol):
    def verify(
        self,
        identity: str,
        action_type: str,
        requested_scope: AuthorizationScope,
    ) -> AuthorizationVerification:
        ...


class StaticAuthorizationVerifier:
    """Verify grants from code-owned policy data."""

    name = "static-authorization-v1"

    def __init__(self, grants: Mapping[str, AuthorizationGrant]):
        self._grants = dict(grants)

    def verify(
        self,
        identity: str,
        action_type: str,
        requested_scope: AuthorizationScope,
    ) -> AuthorizationVerification:
        grant = self._grants.get(identity)
        if grant is None:
            return AuthorizationVerification(
                False,
                "",
                identity,
                AuthorizationScope.NONE,
                (),
                "authorization identity is unknown",
                self.name,
            )
        if grant.identity != identity:
            return AuthorizationVerification(
                False,
                grant.grant_id,
                identity,
                AuthorizationScope.NONE,
                (),
                "authorization grant identity does not match the registry key",
                self.name,
            )
        if action_type not in grant.allowed_actions:
            return AuthorizationVerification(
                False,
                grant.grant_id,
                identity,
                grant.max_scope,
                grant.allowed_actions,
                f"action {action_type!r} is not allowed by the grant",
                self.name,
            )
        if _SCOPE_RANK[requested_scope] > _SCOPE_RANK[grant.max_scope]:
            return AuthorizationVerification(
                False,
                grant.grant_id,
                identity,
                grant.max_scope,
                grant.allowed_actions,
                "requested scope exceeds the grant",
                self.name,
            )
        return AuthorizationVerification(
            True,
            grant.grant_id,
            identity,
            grant.max_scope,
            grant.allowed_actions,
            "authorization grant verified",
            self.name,
        )


def reference_authorization_verifier() -> StaticAuthorizationVerifier:
    return StaticAuthorizationVerifier({
        "quickstart-policy": AuthorizationGrant(
            "grant-quickstart",
            "quickstart-policy",
            AuthorizationScope.SINGLE_L3,
            ("sql_patch",),
        ),
        "book-demo-policy": AuthorizationGrant(
            "grant-book-demo",
            "book-demo-policy",
            AuthorizationScope.SINGLE_L3,
            ("sql_patch", "quarantine_cold_table"),
        ),
        "video-workbench-policy": AuthorizationGrant(
            "grant-video-workbench",
            "video-workbench-policy",
            AuthorizationScope.SINGLE_L3,
            ("fix_creative_ctr_ratio",),
        ),
    })
