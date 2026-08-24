from __future__ import annotations

import hashlib

from sqlgraph.actions import ActionEngine, ActionRequest, SqlFilePatchAdapter
from sqlgraph.autonomy import (
    AuthorizationScope,
    GovernanceAction,
    ReversibilityEvidence,
    decide_autonomy,
)
from sqlgraph.verification import (
    LayerResult,
    VerificationEngine,
    VerificationReport,
)


def _executed_patch(tmp_path):
    path = tmp_path / "query.sql"
    before = "INSERT INTO dst SELECT value * 100 AS value FROM src"
    after = "INSERT INTO dst SELECT value AS value FROM src"
    path.write_text(before, encoding="utf-8")
    decision = decide_autonomy(GovernanceAction(
        action_type="sql_patch",
        evidence_version="task-1@v1#abc",
        evidence_grounded=True,
        reversibility=ReversibilityEvidence(True, True, True),
        authorization_scope=AuthorizationScope.SINGLE_L3,
    ))
    request = ActionRequest(
        task_id="task-1",
        baseline_id="base-1",
        evidence_version=decision.evidence_version,
        decision=decision,
        adapter="sql_file_patch",
        operations=({
            "path": str(path),
            "before": before,
            "after": after,
            "expected_sha256": hashlib.sha256(before.encode()).hexdigest(),
        },),
    )
    engine = ActionEngine([SqlFilePatchAdapter()])
    plan = engine.plan(request)
    execution = engine.execute(plan)
    return plan, execution, path


def test_structure_verification_rebuilds_from_changed_source(tmp_path):
    plan, execution, path = _executed_patch(tmp_path)

    report = VerificationEngine().verify(
        plan,
        execution,
        source_path=path,
        source_table="src",
        target_table="dst",
        dialect="spark",
        runtime_observed={
            "checks_passed": True,
            "reports_recomputed": True,
            "new_alerts": 0,
        },
    )

    assert report.structure.status == "pass"
    assert report.structure.evidence["rebuilt_from_source"] is True
    assert report.outcome == "success"


def test_any_critical_failure_blocks_success():
    report = VerificationReport(
        code=LayerResult("code", "pass"),
        structure=LayerResult("structure", "fail"),
        runtime=LayerResult("runtime", "pass"),
    )

    assert report.outcome == "failed"
