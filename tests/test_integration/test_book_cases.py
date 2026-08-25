from __future__ import annotations

from pathlib import Path

import pytest

from sqlgraph.audit import AuditLog
from sqlgraph.reasoning.scenario import run_scenario


ROOT = Path(__file__).parents[2] / "examples" / "book_cases"


@pytest.mark.parametrize(
    ("case", "outcome"),
    [
        ("caliber_consistency", "success"),
        ("cold_table_retirement", "success"),
        ("irreversible_drop", "held_for_human_review"),
    ],
)
def test_book_case_exports_replayable_bundle(case, outcome, tmp_path):
    result = run_scenario(ROOT / case / "scenario.yaml", tmp_path / case)

    assert result.outcome == outcome
    assert AuditLog(result.audit_path).verify_integrity().valid
    assert len(result.events) == 7
    if case == "irreversible_drop":
        assert not result.decision.reversibility_veto
        assert result.decision.authorization_veto
        assert result.execution.status == "blocked"
