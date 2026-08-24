# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Verify actual code, independently rebuilt structure, and runtime effects."""

from __future__ import annotations

from pathlib import Path

from sqlgraph.actions import ActionPlan, ExecutionResult
from sqlgraph.api import build_graph
from sqlgraph.lineage import drilldown
from sqlgraph.verification.model import LayerResult, VerificationReport


class VerificationEngine:
    def verify(
        self,
        plan: ActionPlan,
        execution: ExecutionResult,
        *,
        source_path: str | Path,
        source_table: str,
        target_table: str,
        dialect: str | None = None,
        runtime_observed: dict | None = None,
    ) -> VerificationReport:
        return VerificationReport(
            code=self.verify_code(plan, execution),
            structure=self.verify_structure(
                source_path,
                source_table,
                target_table,
                dialect=dialect,
            ),
            runtime=self.verify_runtime(runtime_observed),
        )

    def verify_code(
        self,
        plan: ActionPlan,
        execution: ExecutionResult,
    ) -> LayerResult:
        if execution.status not in {"success", "noop"}:
            return LayerResult(
                "code",
                "fail",
                evidence={"execution_status": execution.status},
                note="the planned change did not complete",
            )
        mismatches = []
        checked = []
        for operation in plan.operations:
            raw_path = operation.get("path")
            expected = operation.get("after")
            if not raw_path or expected is None:
                continue
            path = Path(raw_path)
            content = path.read_text(encoding="utf-8") if path.is_file() else ""
            checked.append(str(path))
            if content.count(str(expected)) != 1:
                mismatches.append(str(path))
        return LayerResult(
            "code",
            "fail" if mismatches else "pass",
            evidence={
                "checked_paths": checked,
                "mismatches": mismatches,
                "execution_id": execution.execution_id,
            },
            note="actual files were compared with the approved action plan",
        )

    def verify_structure(
        self,
        source_path: str | Path,
        source_table: str,
        target_table: str,
        *,
        dialect: str | None = None,
    ) -> LayerResult:
        path = Path(source_path)
        if not path.exists():
            return LayerResult(
                "structure",
                "fail",
                evidence={"source_path": str(path)},
                note="changed source is missing",
            )
        graph = build_graph(str(path), dialect=dialect)
        evidence = drilldown(graph, source_table, target_table)
        return LayerResult(
            "structure",
            "pass" if evidence.get("found") else "fail",
            evidence={
                "rebuilt_from_source": True,
                "source_path": str(path.resolve()),
                "graph_environment": graph.metadata.get("environment", {}),
                "lineage": evidence,
            },
            note="structure was rebuilt from the changed source",
        )

    def verify_runtime(self, observed: dict | None) -> LayerResult:
        if observed is None:
            return LayerResult(
                "runtime",
                "not_run",
                note="runtime verification was not executed",
            )
        checks_passed = bool(observed.get("checks_passed", False))
        reports_recomputed = bool(observed.get("reports_recomputed", False))
        new_alerts = int(observed.get("new_alerts", 0))
        passed = checks_passed and reports_recomputed and new_alerts == 0
        return LayerResult(
            "runtime",
            "pass" if passed else "fail",
            evidence=dict(observed),
            note="runtime effects were checked independently",
        )
