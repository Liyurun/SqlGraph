# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Versioned input baseline contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping


@dataclass(frozen=True, order=True)
class SourceHash:
    name: str
    source_type: str
    source_path: str
    sha256: str


@dataclass(frozen=True)
class BaselineManifest:
    schema_version: str
    baseline_id: str
    source_hashes: tuple[SourceHash, ...]
    dialect: str
    parser_version: str
    identity_rule_version: str
    dependency_hashes: Mapping[str, str]
    missing_dependencies: tuple[str, ...]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "baseline_id": self.baseline_id,
            "source_hashes": [asdict(item) for item in self.source_hashes],
            "dialect": self.dialect,
            "parser_version": self.parser_version,
            "identity_rule_version": self.identity_rule_version,
            "dependency_hashes": dict(self.dependency_hashes),
            "missing_dependencies": list(self.missing_dependencies),
            "created_at": self.created_at,
        }
