from __future__ import annotations

import hashlib

import pytest

from sqlgraph.actions import (
    ActionEngine,
    ActionRequest,
    AdapterExecutionError,
    SqlFilePatchAdapter,
)
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


def _operation(
    path,
    before,
    after,
    *,
    expected_content=None,
    inject_failure=False,
):
    return {
        "path": str(path),
        "before": before,
        "after": after,
        "expected_sha256": hashlib.sha256(
            (expected_content if expected_content is not None else before).encode()
        ).hexdigest(),
        "inject_failure_after_apply": inject_failure,
    }


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


def test_rolled_back_execution_is_not_cached_as_success(tmp_path):
    path = tmp_path / "query.sql"
    before = "SELECT value * 100 FROM source"
    path.write_text(before, encoding="utf-8")
    engine = ActionEngine([SqlFilePatchAdapter()])
    plan = engine.plan(_request(path, before, "SELECT value FROM source"))

    execution = engine.execute(plan)
    rollback = engine.rollback_execution(plan, execution)
    repeated = engine.execute(plan)

    assert rollback.verified
    assert repeated.status == "blocked"
    assert repeated.status != "noop"
    assert path.read_text(encoding="utf-8") == before


def test_dry_run_does_not_modify_target(tmp_path):
    path = tmp_path / "query.sql"
    before = "SELECT value * 100 FROM source"
    path.write_text(before, encoding="utf-8")
    engine = ActionEngine([SqlFilePatchAdapter()])
    plan = engine.plan(_request(path, before, "SELECT value FROM source"))

    result = engine.dry_run(plan)

    assert result.status == "ready"
    assert path.read_text(encoding="utf-8") == before


def test_sequential_dry_run_uses_simulated_content(tmp_path):
    path = tmp_path / "query.sql"
    path.write_text("A B", encoding="utf-8")
    operations = (
        _operation(path, "A B", "X B"),
        _operation(path, "X B", "X Y"),
    )

    checks = SqlFilePatchAdapter().dry_run(operations)

    assert len(checks) == 2
    assert path.read_text(encoding="utf-8") == "A B"


def test_multi_patch_failure_restores_true_original(tmp_path):
    path = tmp_path / "query.sql"
    path.write_text("A B", encoding="utf-8")
    operations = (
        _operation(path, "A", "X", expected_content="A B"),
        _operation(
            path,
            "B",
            "Y",
            expected_content="X B",
            inject_failure=True,
        ),
    )
    adapter = SqlFilePatchAdapter()

    with pytest.raises(AdapterExecutionError) as caught:
        adapter.execute(operations)
    rollback = adapter.rollback(caught.value.rollback_state)

    assert rollback.verified
    assert path.read_text(encoding="utf-8") == "A B"
