from __future__ import annotations

from sqlgraph.audit import AuditEvent, AuditLog


def test_reordered_events_break_hash_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append(AuditEvent("task-1", "base-1", "observe", "observe"))
    log.append(AuditEvent("task-1", "base-1", "verify", "verify"))
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")

    report = log.verify_integrity()

    assert not report.valid
    assert report.errors
