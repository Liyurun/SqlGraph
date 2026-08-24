from __future__ import annotations

import hashlib

from sqlgraph.actions import ActionEngine, ActionRequest, SqlFilePatchAdapter
from sqlgraph.autonomy import (
    AuthorizationScope,
    GovernanceAction,
    ReversibilityEvidence,
    decide_autonomy,
)


def test_injected_failure_opens_circuit_and_restores_snapshot(tmp_path):
    path = tmp_path / "query.sql"
    before = "SELECT value * 100 FROM source"
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
        evidence_version="task-1@v1#abc",
        decision=decision,
        adapter="sql_file_patch",
        operations=({
            "path": str(path),
            "before": before,
            "after": "SELECT value FROM source",
            "expected_sha256": hashlib.sha256(before.encode()).hexdigest(),
            "inject_failure_after_apply": True,
        },),
    )
    engine = ActionEngine([SqlFilePatchAdapter()])

    result = engine.execute(engine.plan(request))

    assert result.status == "rolled_back"
    assert result.circuit_open
    assert result.rollback is not None
    assert result.rollback.verified
    assert path.read_text(encoding="utf-8") == before
