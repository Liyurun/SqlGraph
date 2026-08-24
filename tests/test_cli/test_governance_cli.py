from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sqlgraph.cli import app


ROOT = Path(__file__).parents[2]


def test_governance_run_replay_and_verify(tmp_path):
    runner = CliRunner()
    scenario = ROOT / "examples" / "minimal" / "scenario.yaml"
    output = tmp_path / "result"

    run = runner.invoke(
        app,
        ["governance", "run", str(scenario), "-o", str(output)],
    )
    assert run.exit_code == 0, run.stdout
    assert "outcome=success" in run.stdout

    verify = runner.invoke(
        app,
        ["governance", "verify", str(output)],
    )
    assert verify.exit_code == 0, verify.stdout
    assert "valid=True" in verify.stdout

    replay = runner.invoke(
        app,
        ["governance", "replay", str(output / "audit.jsonl")],
    )
    assert replay.exit_code == 0, replay.stdout
    assert "observe" in replay.stdout
    assert "learn" in replay.stdout
