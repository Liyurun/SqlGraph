from pathlib import Path


def test_ci_installs_built_wheel_and_runs_quickstart():
    script = Path("tools/ci_checks.sh").read_text(encoding="utf-8")

    assert "pip install" in script
    assert "dist/*.whl" in script
    assert "governance run examples/minimal/scenario.yaml" in script
    assert "governance verify" in script
    assert "event_count" in script
