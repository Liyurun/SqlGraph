from __future__ import annotations

import hashlib

from sqlgraph.actions import ActionEngine, ActionRequest, SqlFilePatchAdapter
from sqlgraph.autonomy import (
    AuthorizationScope,
    GovernanceAction,
    ReversibilityEvidence,
    decide_autonomy,
)


def _decision():
    return decide_autonomy(GovernanceAction(
        action_type="sql_patch",
        evidence_version="task-1@v1#abc",
        evidence_grounded=True,
        reversibility=ReversibilityEvidence(True, True, True),
        authorization_scope=AuthorizationScope.SINGLE_L3,
    ))


def _request(path, before, after, *, inject_failure=False):
    return ActionRequest(
        task_id="task-1",
        baseline_id="base-1",
        evidence_version="task-1@v1#abc",
        decision=_decision(),
        adapter="sql_file_patch",
        operations=({
            "path": str(path),
            "before": before,
            "after": after,
            "expected_sha256": hashlib.sha256(before.encode()).hexdigest(),
            "inject_failure_after_apply": inject_failure,
        },),
    )


def test_repeat_execution_is_noop(tmp_path):
    path = tmp_path / "query.sql"
    path.write_text("SELECT value * 100 FROM source", encoding="utf-8")
    engine = ActionEngine([SqlFilePatchAdapter()])
    plan = engine.plan(_request(
        path,
        "SELECT value * 100 FROM source",
        "SELECT value FROM source",
    ))

    first = engine.execute(plan)
    second = engine.execute(plan)

    assert first.status == "success"
    assert second.status == "noop"
    assert second.execution_id == first.execution_id
    assert path.read_text(encoding="utf-8") == "SELECT value FROM source"


def test_dry_run_does_not_modify_target(tmp_path):
    path = tmp_path / "query.sql"
    before = "SELECT value * 100 FROM source"
    path.write_text(before, encoding="utf-8")
    engine = ActionEngine([SqlFilePatchAdapter()])
    plan = engine.plan(_request(path, before, "SELECT value FROM source"))

    result = engine.dry_run(plan)

    assert result.status == "ready"
    assert path.read_text(encoding="utf-8") == before
