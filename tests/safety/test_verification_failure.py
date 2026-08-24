from __future__ import annotations

from sqlgraph.verification import LayerResult, VerificationReport


def test_runtime_not_run_is_incomplete():
    report = VerificationReport(
        code=LayerResult("code", "pass"),
        structure=LayerResult("structure", "pass"),
        runtime=LayerResult("runtime", "not_run"),
    )

    assert report.outcome == "incomplete"


def test_runtime_failure_blocks_success_even_if_code_and_structure_pass():
    report = VerificationReport(
        code=LayerResult("code", "pass"),
        structure=LayerResult("structure", "pass"),
        runtime=LayerResult(
            "runtime",
            "fail",
            evidence={"new_alerts": 1},
        ),
    )

    assert report.outcome == "failed"
