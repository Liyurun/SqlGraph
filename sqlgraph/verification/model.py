# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Independent verification result contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


VERIFICATION_SCHEMA_VERSION = "verification-report-v1"


@dataclass(frozen=True)
class LayerResult:
    layer: str
    status: str
    evidence: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"pass", "fail", "not_run"}:
            raise ValueError("status must be pass, fail, or not_run")


@dataclass(frozen=True)
class VerificationReport:
    code: LayerResult
    structure: LayerResult
    runtime: LayerResult
    schema_version: str = VERIFICATION_SCHEMA_VERSION

    @property
    def outcome(self) -> str:
        layers = (self.code, self.structure, self.runtime)
        if any(layer.status == "fail" for layer in layers):
            return "failed"
        if any(layer.status == "not_run" for layer in layers):
            return "incomplete"
        return "success"

    @property
    def closed_loop_status(self) -> str:
        return self.outcome

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "code": asdict(self.code),
            "structure": asdict(self.structure),
            "runtime": asdict(self.runtime),
            "outcome": self.outcome,
            "closed_loop_status": self.outcome,
        }
