# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Load declarative governance scenarios and export their evidence packages."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import yaml

from sqlgraph.actions import (
    ActionEngine,
    DuckDBTaskAdapter,
    SqlFilePatchAdapter,
)
from sqlgraph.audit import AuditLog
from sqlgraph.autonomy import (
    AuthorizationScope,
    GovernanceAction,
    ReversibilityEvidence,
)
from sqlgraph.baseline import build_baseline
from sqlgraph.evidence import EvidenceEngine, EvidenceRequest
from sqlgraph.input import SqlSource
from sqlgraph.reasoning.runner import (
    GovernanceRequest,
    GovernanceResult,
    GovernanceRunner,
)
from sqlgraph.serialize.json_output import to_json
from sqlgraph.verification import VerificationEngine


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_scenario(path: str | Path) -> dict:
    scenario_path = Path(path).resolve()
    payload = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("scenario must be a YAML object")
    required = {
        "task_id",
        "intent",
        "dialect",
        "sql_file",
        "source_table",
        "target_table",
        "action",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"scenario is missing fields: {', '.join(missing)}")
    payload["_scenario_path"] = str(scenario_path)
    return payload


def run_scenario(
    scenario_path: str | Path,
    output_dir: str | Path,
) -> GovernanceResult:
    scenario = load_scenario(scenario_path)
    source_scenario = Path(scenario["_scenario_path"])
    output = Path(output_dir).resolve()
    workspace = output / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    source_sql = (source_scenario.parent / scenario["sql_file"]).resolve()
    working_sql = workspace / source_sql.name
    shutil.copy2(source_sql, working_sql)

    source = SqlSource.from_file(str(working_sql))
    baseline = build_baseline(
        source,
        dialect=scenario["dialect"],
        parameters=scenario.get("parameters", {}),
        udf_manifest=scenario.get("udf_manifest", {}),
        scheduler_manifest=scenario.get("scheduler_manifest", {}),
    )
    from sqlgraph.api import build_graph

    graph = build_graph(source, dialect=scenario["dialect"])
    graph.metadata["baseline_id"] = baseline.baseline_id
    action_data = scenario["action"]
    reversibility = action_data["reversibility"]
    action = GovernanceAction(
        action_type=action_data["type"],
        evidence_version="pending",
        evidence_grounded=False,
        reversibility=ReversibilityEvidence(
            state_restorable=bool(reversibility["state_restorable"]),
            external_effects_controlled=bool(
                reversibility["external_effects_controlled"]
            ),
            rollback_verified=bool(reversibility["rollback_verified"]),
            references=tuple(reversibility.get("references", ())),
        ),
        authorization_scope=AuthorizationScope(
            action_data.get("authorization_scope", "none")
        ),
        authorization_identity=action_data.get("authorization_identity", ""),
        blast_radius=float(action_data.get("blast_radius", 0.0)),
        object_risk=float(action_data.get("object_risk", 0.0)),
        historical_reliability=float(
            action_data.get("historical_reliability", 1.0)
        ),
        roi=float(action_data.get("roi", 0.0)),
    )
    before = working_sql.read_text(encoding="utf-8")
    after = action_data.get("after", before)
    operations = ({
        "path": str(working_sql),
        "before": before,
        "after": after,
        "expected_sha256": hashlib.sha256(before.encode("utf-8")).hexdigest(),
    },)
    audit_path = output / "audit.jsonl"
    if audit_path.exists():
        audit_path.unlink()
    runner = GovernanceRunner(
        EvidenceEngine(graph),
        ActionEngine([SqlFilePatchAdapter(), DuckDBTaskAdapter()]),
        VerificationEngine(),
        AuditLog(audit_path),
    )
    request = GovernanceRequest(
        task_id=scenario["task_id"],
        baseline=baseline,
        graph=graph,
        evidence_request=EvidenceRequest(
            task_id=scenario["task_id"],
            baseline_id=baseline.baseline_id,
            intent=scenario["intent"],
            anchors=(
                scenario["source_table"],
                scenario["target_table"],
            ),
            direction="both",
            max_depth=int(scenario.get("max_depth", 2)),
            coverage_obligations=(
                "anchors_resolved",
                "lineage_path",
                "counterevidence_checked",
                "no_unresolved",
            ),
        ),
        action=action,
        adapter=action_data.get("adapter", "sql_file_patch"),
        operations=operations,
        source_path=str(working_sql),
        source_table=scenario["source_table"],
        target_table=scenario["target_table"],
        dialect=scenario["dialect"],
        runtime_observed=scenario.get("runtime"),
    )
    result = runner.run(request)
    _write_json(output / "baseline.json", baseline.to_dict())
    _write_json(output / "graph.json", to_json(graph))
    _write_json(output / "evidence.json", result.evidence.to_dict())
    _write_json(output / "decision.json", result.decision.to_dict())
    _write_json(output / "verification.json", result.verification.to_dict())
    _write_json(output / "result.json", result.to_dict())
    return result


def verify_scenario_output(output_dir: str | Path) -> dict:
    output = Path(output_dir).resolve()
    required = (
        "baseline.json",
        "graph.json",
        "evidence.json",
        "decision.json",
        "verification.json",
        "result.json",
        "audit.jsonl",
    )
    missing = [name for name in required if not (output / name).is_file()]
    integrity = AuditLog(output / "audit.jsonl").verify_integrity()
    result = (
        json.loads((output / "result.json").read_text(encoding="utf-8"))
        if not missing
        else {}
    )
    return {
        "valid": not missing and integrity.valid,
        "missing": missing,
        "integrity": {
            "valid": integrity.valid,
            "event_count": integrity.event_count,
            "errors": list(integrity.errors),
        },
        "outcome": result.get("outcome"),
    }
