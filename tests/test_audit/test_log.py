from __future__ import annotations

import json

from sqlgraph.audit import AuditEvent, AuditLog


def _event(step: str) -> AuditEvent:
    return AuditEvent(
        task_id="task-1",
        baseline_id="base-1",
        event_type=step,
        step=step,
        payload={"status": "ok"},
    )


def test_append_only_log_verifies_and_replays(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for step in ("observe", "authorize", "verify"):
        log.append(_event(step))

    integrity = log.verify_integrity()
    replay = log.replay("task-1")

    assert integrity.valid
    assert [event.sequence for event in replay.events] == [1, 2, 3]
    assert replay.integrity.valid


def test_tampered_event_breaks_integrity(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append(_event("observe"))
    log.append(_event("verify"))
    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    payload["payload"]["status"] = "tampered"
    lines[0] = json.dumps(payload, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert not log.verify_integrity().valid
