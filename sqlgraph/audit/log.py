# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""JSONL audit log with a verifiable hash chain."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from sqlgraph.audit.model import (
    GENESIS_HASH,
    AuditEvent,
    IntegrityReport,
    ReplayResult,
)
from sqlgraph.identity import stable_id


def _canonical(payload: dict) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _event_hash(payload: dict) -> str:
    content = {key: value for key, value in payload.items() if key != "event_hash"}
    return hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, event: AuditEvent) -> AuditEvent:
        current = self._read()
        sequence = len(current) + 1
        previous_hash = current[-1].event_hash if current else GENESIS_HASH
        timestamp = datetime.now(timezone.utc).isoformat()
        event_id = stable_id(
            "event",
            f"{event.task_id}:{sequence}:{event.event_type}:{previous_hash}",
            128,
        )
        prepared = replace(
            event,
            sequence=sequence,
            timestamp=timestamp,
            previous_hash=previous_hash,
            event_id=event_id,
            event_hash="",
        )
        completed = replace(
            prepared,
            event_hash=_event_hash(prepared.to_dict()),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(_canonical(completed.to_dict()) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return completed

    def verify_integrity(self) -> IntegrityReport:
        errors = []
        previous_hash = GENESIS_HASH
        try:
            events = self._read()
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            return IntegrityReport(False, 0, (f"invalid audit JSON: {exc}",))

        for expected_sequence, event in enumerate(events, start=1):
            if event.sequence != expected_sequence:
                errors.append(
                    f"sequence {event.sequence} expected {expected_sequence}"
                )
            if event.previous_hash != previous_hash:
                errors.append(
                    f"event {event.sequence} previous hash does not match"
                )
            calculated = _event_hash(event.to_dict())
            if calculated != event.event_hash:
                errors.append(f"event {event.sequence} hash does not match")
            previous_hash = event.event_hash
        return IntegrityReport(not errors, len(events), tuple(errors))

    def replay(self, task_id: str) -> ReplayResult:
        integrity = self.verify_integrity()
        events = tuple(
            event for event in self._read() if event.task_id == task_id
        )
        return ReplayResult(task_id, events, integrity)

    def _read(self) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        events = []
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    events.append(AuditEvent(**json.loads(line)))
        return events
