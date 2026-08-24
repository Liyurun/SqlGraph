from __future__ import annotations

from pathlib import Path

from examples.video_commercial_warehouse.generate_sql import generate_sql
from examples.video_commercial_warehouse.governance import (
    AFTER_CTR_EXPR,
    BEFORE_CTR_EXPR,
    restore_governance,
    run_ctr_governance,
)


def _scenario(tmp_path: Path) -> Path:
    root = tmp_path / "warehouse"
    generate_sql(root)
    return root


def test_ctr_governance_uses_real_duckdb_results(tmp_path):
    root = _scenario(tmp_path)
    result = run_ctr_governance(root, tmp_path / "out", profile="smoke")

    assert result["catalog"]["table_count"] == 94
    assert result["catalog"]["task_count"] == 62
    assert result["graph"]["coverage"]["failed"] == 0
    assert result["runtime"]["source"] == "duckdb_query"
    assert result["runtime"]["before"]["invalid_ctr_rows"] > 0
    assert result["runtime"]["after"]["invalid_ctr_rows"] == 0
    assert result["runtime"]["after"]["grade_mismatch_rows"] == 0
    assert result["runtime"]["threshold_consistent"] is True
    assert result["verify"]["closed_loop_status"] == "success"
    assert result["audit"]["outcome"] == "closed"


def test_governance_only_reruns_affected_dag(tmp_path):
    result = run_ctr_governance(
        _scenario(tmp_path), tmp_path / "out", profile="smoke"
    )
    assert result["rerun"]["tasks"] == [
        "dws_creative_performance_daily",
        "ads_creative_report",
    ]
    assert result["rerun"]["success_count"] == 2
    assert set(result["impact"]["reachable"]) == {"ads_creative_report"}


def test_wrong_downstream_threshold_fails_runtime_verification(tmp_path):
    root = _scenario(tmp_path)
    report_sql = root / "sql" / "059_ads_creative_report.sql"
    text = report_sql.read_text(encoding="utf-8")
    text = (
        text.replace("p.ctr >= 0.05", "p.ctr >= 0.50")
        .replace("p.ctr >= 0.03", "p.ctr >= 0.30")
        .replace("p.ctr >= 0.01", "p.ctr >= 0.10")
    )
    report_sql.write_text(text, encoding="utf-8")

    result = run_ctr_governance(root, tmp_path / "out", profile="smoke")
    assert result["runtime"]["threshold_consistent"] is False
    assert result["verify"]["contract"]["status"] == "fail"
    assert result["verify"]["closed_loop_status"] == "failed"
    assert result["audit"]["outcome"] == "failed"


def test_idempotent_rerun_is_recorded_as_noop(tmp_path):
    root = _scenario(tmp_path)
    output = tmp_path / "out"
    first = run_ctr_governance(root, output, profile="smoke")
    second = run_ctr_governance(root, output, profile="smoke")

    assert first["change"]["changed"] is True
    assert second["change"]["changed"] is False
    execute = next(step for step in second["audit"]["steps"] if step["step"] == "execute")
    assert execute["detail"]["executed"] is False
    assert execute["detail"]["mode"] == "no_op/already_compliant"


def test_sql_fix_is_exact_and_backup_is_preserved(tmp_path):
    root = _scenario(tmp_path)
    output = tmp_path / "out"
    target = root / "sql" / "044_dws_creative_performance_daily.sql"
    original = target.read_text(encoding="utf-8")

    result = run_ctr_governance(root, output, profile="smoke")
    changed = target.read_text(encoding="utf-8")
    assert result["change"]["changed"] is True
    assert BEFORE_CTR_EXPR in original
    assert BEFORE_CTR_EXPR not in changed
    assert AFTER_CTR_EXPR in changed
    assert (output / "before" / target.name).read_text(encoding="utf-8") == original


def test_restore_updates_sql_database_and_audit_state(tmp_path):
    root = _scenario(tmp_path)
    output = tmp_path / "out"
    run_ctr_governance(root, output, profile="smoke")

    restored = restore_governance(root, output)
    target = root / "sql" / "044_dws_creative_performance_daily.sql"
    assert BEFORE_CTR_EXPR in target.read_text(encoding="utf-8")
    assert restored["scenario"]["status"] == "restored"
    assert restored["audit"]["outcome"] == "restored"
    assert restored["verify"]["closed_loop_status"] == "incomplete"
    assert restored["runtime"]["after"]["invalid_ctr_rows"] > 0
    assert restored["audit"]["steps"][-1]["step"] == "restore"
