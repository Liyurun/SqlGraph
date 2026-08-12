# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Small file-backed cache for deterministic governance analysis artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


CACHE_SCHEMA_VERSION = "1.0"


class AnalysisCache:
    """Cache JSON-compatible projections and metric payloads by fingerprint.

    Cache entries are conservative: a read is a hit only when the stored key,
    schema version, and artifact kind/name all match. Corrupt entries are
    ignored so callers recompute instead of returning stale or partial data.
    """

    def __init__(self, cache_dir: str | Path):
        self.root = Path(cache_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def load_projection(self, name: str, cache_key: str) -> Mapping[str, Any] | None:
        return self._load("projections", name, cache_key)

    def store_projection(
        self,
        name: str,
        cache_key: str,
        payload: Mapping[str, Any],
    ) -> None:
        self._store("projections", name, cache_key, payload)

    def load_metric(self, name: str, cache_key: str) -> Mapping[str, Any] | None:
        return self._load("metrics", name, cache_key)

    def store_metric(
        self,
        name: str,
        cache_key: str,
        payload: Mapping[str, Any],
    ) -> None:
        self._store("metrics", name, cache_key, payload)

    def _path(self, kind: str, name: str, cache_key: str) -> Path:
        safe_name = "".join(
            char if char.isalnum() or char in {"-", "_"} else "_"
            for char in name
        )
        return self.root / kind / safe_name / f"{cache_key}.json"

    def _load(
        self,
        kind: str,
        name: str,
        cache_key: str,
    ) -> Mapping[str, Any] | None:
        path = self._path(kind, name, cache_key)
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as stream:
                envelope = json.load(stream)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(envelope, dict):
            return None
        if envelope.get("schema_version") != CACHE_SCHEMA_VERSION:
            return None
        if envelope.get("kind") != kind or envelope.get("name") != name:
            return None
        if envelope.get("cache_key") != cache_key:
            return None
        payload = envelope.get("payload")
        return payload if isinstance(payload, Mapping) else None

    def _store(
        self,
        kind: str,
        name: str,
        cache_key: str,
        payload: Mapping[str, Any],
    ) -> None:
        path = self._path(kind, name, cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "kind": kind,
            "name": name,
            "cache_key": cache_key,
            "payload": payload,
        }
        data = json.dumps(
            envelope,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        path.write_text(data + "\n", encoding="utf-8")


def fingerprint_payload(payload: Any) -> str:
    """Return a stable SHA-256 fingerprint for a JSON-compatible payload."""
    data = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
