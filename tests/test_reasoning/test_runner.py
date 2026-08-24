from __future__ import annotations

import hashlib

from sqlgraph.actions import ActionEngine, SqlFilePatchAdapter
from sqlgraph.audit import AuditLog
from sqlgraph.autonomy import (
    AuthorizationScope,
    GovernanceAction,
    ReversibilityEvidence,
)
from sqlgraph.baseline import build_baseline
from sqlgraph.evidence import EvidenceEngine, EvidenceRequest
from sqlgraph.input import SqlSource
from sqlgraph.reasoning import GovernanceRequest, GovernanceRunner
from sqlgraph.verification import VerificationEngine


def test_runner_exports_all_seven_steps(tmp_path):
    path = tmp_path / "query.sql"
    before = "INSERT INTO dst SELECT value * 100 AS value FROM src"
    after = "INSERT INTO dst SELECT value AS value FROM src"
    path.write_text(before, encoding="utf-8")
    source = SqlSource.from_file(str(path))
    baseline = build_baseline(source, dialect="spark")
    from sqlgraph.api import build_graph

    graph = build_graph(source, dialect="spark")
    evidence_request = EvidenceRequest(
        task_id="task-1",
        baseline_id=baseline.baseline_id,
        intent="caliber_repair",
        anchors=("src", "dst"),
        max_depth=1,
    )
    action = GovernanceAction(
        action_type="sql_patch",
        evidence_version="pending",
        evidence_grounded=True,
        reversibility=ReversibilityEvidence(True, True, True),
        authorization_scope=AuthorizationScope.SINGLE_L3,
    )
    request = GovernanceRequest(
        task_id="task-1",
        baseline=baseline,
        graph=graph,
        evidence_request=evidence_request,
        action=action,
        adapter="sql_file_patch",
        operations=({
            "path": str(path),
            "before": before,
            "after": after,
            "expected_sha256": hashlib.sha256(before.encode()).hexdigest(),
        },),
        source_path=str(path),
        source_table="src",
        target_table="dst",
        dialect="spark",
        runtime_observed={
            "checks_passed": True,
            "reports_recomputed": True,
            "new_alerts": 0,
        },
    )
    runner = GovernanceRunner(
        EvidenceEngine(graph),
        ActionEngine([SqlFilePatchAdapter()]),
        VerificationEngine(),
        AuditLog(tmp_path / "audit.jsonl"),
    )

    result = runner.run(request)

    assert [event.step for event in result.events] == [
        "observe",
        "explain",
        "propose",
        "authorize",
        "execute",
        "verify",
        "learn",
    ]
    assert result.outcome == "success"
    assert AuditLog(result.audit_path).verify_integrity().valid
