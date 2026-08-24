# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Append-only governance audit contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


AUDIT_SCHEMA_VERSION = "audit-event-v1"
GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditEvent:
    task_id: str
    baseline_id: str
    event_type: str
    step: str
    payload: dict[str, Any] = field(default_factory=dict)
    evidence_version: str = ""
    policy_version: str = ""
    authorization_identity: str = ""
    idempotency_key: str = ""
    transition: str = ""
    sequence: int = 0
    timestamp: str = ""
    previous_hash: str = GENESIS_HASH
    event_hash: str = ""
    event_id: str = ""
    schema_version: str = AUDIT_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class IntegrityReport:
    valid: bool
    event_count: int
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplayResult:
    task_id: str
    events: tuple[AuditEvent, ...]
    integrity: IntegrityReport
