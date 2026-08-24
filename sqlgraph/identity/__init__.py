# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Deterministic identities for graph and governance artifacts."""

from __future__ import annotations

import hashlib


IDENTITY_RULE_VERSION = "id-v2"


def _digest(text: str, bits: int) -> str:
    if bits <= 0 or bits % 4:
        raise ValueError("bits must be a positive multiple of four")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[: bits // 4]


def stable_id(prefix: str, semantic_key: str, bits: int = 96) -> str:
    """Return a stable identifier derived from a semantic key."""
    return f"{prefix}_{_digest(semantic_key, bits)}"


def node_id(prefix: str, semantic_key: str) -> str:
    return stable_id(prefix, semantic_key, bits=96)


def edge_id(
    source_id: str,
    target_id: str,
    edge_type,
    context: str = "",
) -> str:
    edge_name = getattr(edge_type, "value", str(edge_type))
    semantic_key = f"{source_id}->{target_id}:{edge_name}:{context}"
    return stable_id("e", semantic_key, bits=96)


def content_fingerprint(text: str, bits: int = 128) -> str:
    return _digest(text, bits)


class CollisionRegistry:
    """Detect the same derived ID being assigned to different semantic keys."""

    def __init__(self):
        self._seen: dict[str, str] = {}
        self.collisions: list[tuple[str, str, str]] = []

    def register(self, identifier: str, semantic_key: str) -> bool:
        existing = self._seen.get(identifier)
        if existing is None:
            self._seen[identifier] = semantic_key
            return True
        if existing == semantic_key:
            return True
        self.collisions.append((identifier, existing, semantic_key))
        return False

    def has_collision(self) -> bool:
        return bool(self.collisions)


def environment_fingerprint(
    dialect: str | None,
    parser_version: str,
    config_hash: str = "",
) -> dict[str, str]:
    return {
        "identity_rule_version": IDENTITY_RULE_VERSION,
        "dialect": dialect or "",
        "parser_version": parser_version,
        "config_hash": config_hash,
    }
