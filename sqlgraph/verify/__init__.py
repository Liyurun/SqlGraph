# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Compatibility verification helpers for graph-only callers."""

from __future__ import annotations

from sqlgraph.lineage import drilldown
from sqlgraph.verification import LayerResult, VerificationReport


def verify(
    graph,
    source_table: str,
    target_table: str,
    governance_issue=None,
    runtime_observed: dict | None = None,
    runtime_target: float | None = None,
) -> VerificationReport:
    lineage = drilldown(graph, source_table, target_table)
    structure = LayerResult(
        "structure",
        "pass" if lineage.get("found") else "fail",
        evidence=lineage,
    )
    contract = LayerResult(
        "code",
        "fail" if governance_issue is not None else "pass",
        evidence=(
            governance_issue.to_dict()
            if hasattr(governance_issue, "to_dict")
            else governance_issue or {}
        ),
        note="legacy contract check exposed through the code layer",
    )
    if runtime_observed is None:
        runtime = LayerResult("runtime", "not_run")
    else:
        value = runtime_observed.get("value")
        passed = (
            runtime_observed.get("reports_recomputed", True)
            and runtime_observed.get("new_alerts", 0) == 0
        )
        evidence = dict(runtime_observed)
        if runtime_target is not None and value is not None:
            relative_error = (
                abs(value - runtime_target) / abs(runtime_target)
                if runtime_target
                else float("inf")
            )
            evidence["relative_error"] = relative_error
            passed = passed and relative_error <= 0.05
        runtime = LayerResult(
            "runtime",
            "pass" if passed else "fail",
            evidence=evidence,
        )
    return VerificationReport(
        code=contract,
        structure=structure,
        runtime=runtime,
    )


__all__ = ["LayerResult", "VerificationReport", "verify"]
