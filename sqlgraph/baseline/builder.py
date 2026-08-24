# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Build deterministic manifests for all governance inputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

import sqlglot

from sqlgraph.baseline.model import BaselineManifest, SourceHash
from sqlgraph.identity import IDENTITY_RULE_VERSION
from sqlgraph.input import SqlSource
from sqlgraph.input.csv_schema import SchemaRegistry


SCHEMA_VERSION = "baseline-manifest-v1"
_DEPENDENCIES = ("schema", "udf_manifest", "parameters", "scheduler_manifest")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _plain(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, SchemaRegistry):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _hash_dependency(value: Any) -> str:
    return _sha256_bytes(_canonical_json(_plain(value)).encode("utf-8"))


def build_baseline(
    source: SqlSource,
    *,
    dialect: str | None = None,
    schema: SchemaRegistry | None = None,
    parameters: Mapping[str, object] | None = None,
    udf_manifest: Mapping[str, object] | None = None,
    scheduler_manifest: Mapping[str, object] | None = None,
) -> BaselineManifest:
    """Build a stable baseline ID while keeping creation time informational."""
    source_hashes = tuple(sorted(
        (
            SourceHash(
                name=item.name,
                source_type=item.source_type,
                source_path=item.source_path or "",
                sha256=_sha256_bytes(item.content.encode("utf-8")),
            )
            for item in source
        ),
        key=lambda item: (
            item.source_path,
            item.name,
            item.source_type,
            item.sha256,
        ),
    ))
    dependencies = {
        "schema": schema,
        "udf_manifest": udf_manifest,
        "parameters": parameters,
        "scheduler_manifest": scheduler_manifest,
    }
    dependency_hashes = {
        name: _hash_dependency(value)
        for name, value in dependencies.items()
        if value is not None
    }
    missing = tuple(
        name for name in _DEPENDENCIES if dependencies[name] is None
    )
    identity_payload = {
        "schema_version": SCHEMA_VERSION,
        "sources": [asdict(item) for item in source_hashes],
        "dialect": dialect or "",
        "parser_version": f"sqlglot-{sqlglot.__version__}",
        "identity_rule_version": IDENTITY_RULE_VERSION,
        "dependency_hashes": dependency_hashes,
        "missing_dependencies": missing,
    }
    baseline_id = "base_" + _sha256_bytes(
        _canonical_json(identity_payload).encode("utf-8")
    )
    return BaselineManifest(
        schema_version=SCHEMA_VERSION,
        baseline_id=baseline_id,
        source_hashes=source_hashes,
        dialect=dialect or "",
        parser_version=f"sqlglot-{sqlglot.__version__}",
        identity_rule_version=IDENTITY_RULE_VERSION,
        dependency_hashes=dependency_hashes,
        missing_dependencies=missing,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
