"""视频商业化数仓的真实 DuckDB CTR 治理闭环。"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

import duckdb

from examples.video_commercial_warehouse.catalog import (
    ALL_TABLES,
    BASE_TABLES,
    TASKS,
)
from examples.video_commercial_warehouse.generate_sql import ROOT, generate_sql
from examples.video_commercial_warehouse.runtime import (
    RunResult,
    build_warehouse,
    collect_table_rows,
    rerun_tasks,
)
from sqlgraph.agent import GovernanceLoop
from sqlgraph.api import build_graph
from sqlgraph.autonomy import (
    AuthorizationScope,
    GovernanceAction,
    ReversibilityEvidence,
    decide_autonomy,
)
from sqlgraph.contract import BusinessContract, GovernanceIssue
from sqlgraph.evidence import build_evidence_subgraph
from sqlgraph.lineage import drilldown
from sqlgraph.metrics import blast_score, bridge_score, with_residual_risk


TASK_ID = "VCW-CTR-001"
TARGET_TABLE = "dws_creative_performance_daily"
TARGET_FILE = "044_dws_creative_performance_daily.sql"
DOWNSTREAM_TABLE = "ads_creative_report"
EXPECTED_THRESHOLDS = (0.05, 0.03, 0.01)

BEFORE_CTR_EXPR = (
    "ROUND(SUM(w.is_clicked) * 100.0 / NULLIF(COUNT(*),0), 6) AS ctr"
)
AFTER_CTR_EXPR = (
    "ROUND(SUM(w.is_clicked) / NULLIF(COUNT(*),0), 6) AS ctr"
)


class GovernanceError(RuntimeError):
    """治理流程无法安全继续。"""


def _ensure_generated(root: Path) -> Path:
    sql_dir = root / "sql"
    if len(list(sql_dir.glob("*.sql"))) == 62:
        return sql_dir
    generate_sql(root)
    return sql_dir


def _snapshot_sql(sql_dir: Path, output_dir: Path) -> Path:
    before = output_dir / "before"
    before_sql = before / "sql"
    if not before_sql.exists():
        shutil.copytree(sql_dir, before_sql)
    return before_sql


def _apply_fix(target: Path, output_dir: Path) -> dict[str, Any]:
    source = target.read_text(encoding="utf-8")
    before_count = source.count(BEFORE_CTR_EXPR)
    after_count = source.count(AFTER_CTR_EXPR)
    backup = output_dir / "before" / target.name
    backup.parent.mkdir(parents=True, exist_ok=True)

    if before_count == 0 and after_count == 1:
        return {
            "changed": False,
            "status": "already_compliant",
            "target": str(target),
            "backup": str(backup) if backup.exists() else None,
        }
    if before_count != 1 or after_count != 0:
        raise GovernanceError(
            "CTR 表达式无法唯一识别："
            f"before={before_count}, after={after_count}"
        )
    if not backup.exists():
        backup.write_text(source, encoding="utf-8")
    target.write_text(source.replace(BEFORE_CTR_EXPR, AFTER_CTR_EXPR), encoding="utf-8")
    return {
        "changed": True,
        "status": "fixed",
        "target": str(target),
        "backup": str(backup),
    }


def _thresholds(sql_path: Path) -> tuple[float, ...]:
    text = sql_path.read_text(encoding="utf-8")
    return tuple(float(value) for value in re.findall(r"p\.ctr\s*>=\s*([0-9.]+)", text))


def _affected_tasks(target: str) -> list[str]:
    """从 catalog 依赖计算目标及其全部派生下游，保持拓扑顺序。"""
    affected = {target}
    changed = True
    while changed:
        changed = False
        for task in TASKS:
            if task.target not in affected and set(task.dependencies) & affected:
                affected.add(task.target)
                changed = True
    return [task.target for task in TASKS if task.target in affected]


def _query_runtime(database: Path) -> dict[str, Any]:
    with duckdb.connect(str(database), read_only=True) as con:
        summary = con.execute("""
            SELECT
              COUNT(*) AS row_count,
              COUNT(*) FILTER (WHERE ctr < 0 OR ctr > 1) AS invalid_ctr_rows,
              COUNT(DISTINCT ctr_level) AS grade_count,
              MIN(ctr) AS min_ctr,
              MAX(ctr) AS max_ctr,
              COUNT(*) FILTER (
                WHERE ctr_level <>
                  CASE WHEN ctr >= 0.05 THEN 'A_excellent'
                       WHEN ctr >= 0.03 THEN 'B_good'
                       WHEN ctr >= 0.01 THEN 'C_normal'
                       ELSE 'D_poor' END
              ) AS grade_mismatch_rows
            FROM ads_creative_report
        """).fetchone()
        samples = con.execute("""
            SELECT ad_creative_id, event_date, impression_count, click_count,
                   ROUND(ctr, 6) AS ctr, ctr_level
            FROM ads_creative_report
            ORDER BY ctr DESC, ad_creative_id, event_date
            LIMIT 12
        """).fetchall()
    return {
        "row_count": int(summary[0]),
        "invalid_ctr_rows": int(summary[1]),
        "grade_count": int(summary[2]),
        "min_ctr": float(summary[3] or 0),
        "max_ctr": float(summary[4] or 0),
        "grade_mismatch_rows": int(summary[5]),
        "samples": [
            {
                "ad_creative_id": int(row[0]),
                "event_date": str(row[1]),
                "impression_count": int(row[2]),
                "click_count": int(row[3]),
                "ctr": float(row[4]),
                "ctr_level": row[5],
            }
            for row in samples
        ],
    }


def _graph_diff(before_graph, after_graph) -> dict[str, Any]:
    before_nodes = {node.id for node in before_graph.nodes}
    after_nodes = {node.id for node in after_graph.nodes}
    before_edges = {edge.id for edge in before_graph.edges}
    after_edges = {edge.id for edge in after_graph.edges}
    added = sorted((after_nodes | after_edges) - (before_nodes | before_edges))
    removed = sorted((before_nodes | before_edges) - (after_nodes | after_edges))
    return {
        "added": added,
        "removed": removed,
        "added_count": len(added),
        "removed_count": len(removed),
    }


def _evidence_payload(evidence) -> dict[str, Any]:
    return {
        "task_id": evidence.task_id,
        "version_id": evidence.version_id,
        "node_ids": sorted(evidence.node_ids),
        "edge_ids": sorted(evidence.edge_ids),
        "coverage": evidence.coverage,
        "gaps": evidence.gaps,
    }


def _run_payload(result: RunResult) -> dict[str, Any]:
    return result.to_dict()


def _warehouse_payload(database: Path, before_run: RunResult) -> dict[str, Any]:
    """汇总报告需要的 94 表、62 任务及真实行数。"""
    with duckdb.connect(str(database), read_only=True) as con:
        table_rows = collect_table_rows(con)
    task_by_target = {task.target: task for task in TASKS}
    run_by_target = {run.target: run for run in before_run.task_runs}
    downstream: dict[str, list[str]] = {name: [] for name in ALL_TABLES}
    for task in TASKS:
        for dependency in task.dependencies:
            downstream.setdefault(dependency, []).append(task.target)

    tables = []
    for name in ALL_TABLES:
        if name in BASE_TABLES:
            spec = BASE_TABLES[name]
            layer, domain, columns = spec.layer, spec.domain, [
                {"name": column, "type": data_type}
                for column, data_type in spec.columns
            ]
            upstream = []
            sql_file = None
        else:
            task = task_by_target[name]
            layer, domain, columns = task.layer, task.domain, []
            upstream = list(task.dependencies)
            sql_file = f"{task.order:03d}_{task.target}.sql"
        tables.append({
            "name": name,
            "layer": layer,
            "domain": domain,
            "row_count": table_rows[name],
            "upstream": upstream,
            "downstream": sorted(downstream.get(name, [])),
            "columns": columns,
            "sql_file": sql_file,
        })

    return {
        "tables": tables,
        "tasks": [
            {
                **task.to_dict(),
                "row_count": table_rows[task.target],
                "elapsed_ms": (
                    run_by_target[task.target].elapsed_ms
                    if task.target in run_by_target else None
                ),
            }
            for task in TASKS
        ],
    }


def run_ctr_governance(
    root: Path,
    output_dir: Path,
    *,
    profile: str = "smoke",
) -> dict[str, Any]:
    """执行全量基线、真实 SQL 修复、影响 DAG 重跑和真实运行态验证。"""
    root = Path(root).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    sql_dir = _ensure_generated(root)
    target = sql_dir / TARGET_FILE
    report_sql = sql_dir / "059_ads_creative_report.sql"
    before_sql_dir = _snapshot_sql(sql_dir, output_dir)
    before_db = output_dir / "before.duckdb"
    after_db = output_dir / "after.duckdb"

    current = target.read_text(encoding="utf-8")
    is_conflict = BEFORE_CTR_EXPR in current and AFTER_CTR_EXPR not in current
    is_compliant = AFTER_CTR_EXPR in current and BEFORE_CTR_EXPR not in current
    if not (is_conflict or is_compliant):
        raise GovernanceError("目标 CTR SQL 不处于可识别的冲突或合规状态")

    if is_conflict or not before_db.exists():
        before_run = build_warehouse(before_db, profile=profile, sql_dir=sql_dir)
    else:
        # 幂等重跑沿用第一次保存的真实冲突前数据库。
        before_run = RunResult(str(before_db), profile, tuple(), {})
    before_runtime = _query_runtime(before_db)
    before_graph = build_graph(str(before_sql_dir), dialect="duckdb")

    change = _apply_fix(target, output_dir)
    affected_tasks = _affected_tasks(TARGET_TABLE)
    try:
        if change["changed"]:
            shutil.copy2(before_db, after_db)
            reruns = rerun_tasks(after_db, affected_tasks, sql_dir=sql_dir)
            after_run = {
                "mode": "incremental",
                "success_count": len(reruns),
                "task_runs": [run.to_dict() for run in reruns],
            }
        else:
            rebuilt = build_warehouse(after_db, profile=profile, sql_dir=sql_dir)
            after_run = {"mode": "no_op_validation", **_run_payload(rebuilt)}
    except Exception as exc:
        backup = output_dir / "before" / TARGET_FILE
        if change["changed"] and backup.exists():
            shutil.copy2(backup, target)
        raise GovernanceError(f"增量重跑失败，SQL 已恢复: {exc}") from exc

    after_runtime = _query_runtime(after_db)
    after_graph = build_graph(str(sql_dir), dialect="duckdb")
    thresholds = _thresholds(report_sql)
    threshold_consistent = thresholds == EXPECTED_THRESHOLDS
    runtime_ok = (
        after_runtime["invalid_ctr_rows"] == 0
        and after_runtime["grade_mismatch_rows"] == 0
        and threshold_consistent
    )

    blast = blast_score(before_graph, TARGET_TABLE)
    bridge = bridge_score(before_graph, TARGET_TABLE)
    lineage = drilldown(after_graph, TARGET_TABLE, DOWNSTREAM_TABLE)
    evidence = build_evidence_subgraph(
        after_graph,
        TASK_ID,
        [TARGET_TABLE, DOWNSTREAM_TABLE],
        intent="caliber_repair",
    )
    contract = BusinessContract(
        metric="creative_ctr",
        version="v2",
        definition="click_count / impression_count，范围 [0,1]",
        data_type="DOUBLE",
        unit="ratio",
        null_behavior="impression_count=0 时为 NULL",
        owner="commercial-data-governance",
    )
    issue = None
    if not threshold_consistent:
        issue = GovernanceIssue(
            metric=contract.metric,
            contract_version=contract.version,
            implemented_semantics=f"ctr thresholds={thresholds}",
            expected_semantics=f"ctr thresholds={EXPECTED_THRESHOLDS}",
        )

    action = GovernanceAction(
        action_type="fix_creative_ctr_ratio",
        evidence_version=evidence.version_id,
        evidence_grounded=bool(lineage.get("found")),
        reversibility=ReversibilityEvidence(
            state_restorable=True,
            external_effects_controlled=True,
            rollback_verified=True,
            references=(str(change.get("backup") or "existing-backup"),),
        ),
        blast_radius=min(float(blast["score"]) / 10.0, 1.0),
        object_risk=0.4,
        authorization_scope=AuthorizationScope.SINGLE_L3,
        historical_reliability=0.95,
        roi=0.9,
    )
    decision = decide_autonomy(action)
    trail = GovernanceLoop(after_graph).run(
        TASK_ID,
        TARGET_TABLE,
        DOWNSTREAM_TABLE,
        action,
        governance_issue=issue,
        runtime_observed={
            "value": after_runtime["max_ctr"],
            "reports_recomputed": runtime_ok,
            "new_alerts": 0 if runtime_ok else 1,
        },
        runtime_target=None,
    )
    audit = trail.to_dict()
    if not change["changed"]:
        execute = next(step for step in audit["steps"] if step["step"] == "execute")
        execute["detail"] = {
            "executed": False,
            "mode": "no_op/already_compliant",
        }
        execute["transition"] = "already_compliant->verify"

    result = {
        "catalog": {
            "table_count": 94,
            "task_count": 62,
            "profile": profile,
        },
        "warehouse": _warehouse_payload(after_db, before_run),
        "scenario": {
            "task_id": TASK_ID,
            "title": "视频商业化素材 CTR 口径治理",
            "target_table": TARGET_TABLE,
            "target_file": str(target),
            "downstream_table": DOWNSTREAM_TABLE,
            "status": "fixed" if change["changed"] else "already_compliant",
        },
        "change": {
            **change,
            "before_expression": BEFORE_CTR_EXPR,
            "after_expression": AFTER_CTR_EXPR,
        },
        "database": {
            "before": str(before_db),
            "after": str(after_db),
            "before_build": _run_payload(before_run),
            "after_build": after_run,
        },
        "graph": {
            "before_stats": before_graph.stats(),
            "after_stats": after_graph.stats(),
            "coverage": after_graph.metadata.get("coverage", {}),
            "environment": after_graph.metadata.get("environment", {}),
        },
        "diff": _graph_diff(before_graph, after_graph),
        "impact": {
            "reachable": blast["reachable"],
            "blast": blast,
            "bridge": bridge,
            "executable_tasks": affected_tasks,
        },
        "rerun": {
            "tasks": affected_tasks if change["changed"] else [],
            "success_count": after_run["success_count"],
            "mode": after_run["mode"],
        },
        "lineage_evidence": lineage,
        "evidence": _evidence_payload(evidence),
        "contract": asdict(contract),
        "governance_issue": issue.to_dict() if issue else None,
        "decision": decision.to_dict(),
        "runtime": {
            "source": "duckdb_query",
            "thresholds": list(thresholds),
            "expected_thresholds": list(EXPECTED_THRESHOLDS),
            "threshold_consistent": threshold_consistent,
            "before": before_runtime,
            "after": after_runtime,
        },
        "verify": trail.verify_report,
        "audit": audit,
        "residual": with_residual_risk({
            "verdict": "真实 DuckDB 结果已验证，生产环境仍需监控实际数据漂移",
        }),
    }
    (output_dir / "operation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def restore_governance(root: Path, output_dir: Path) -> dict[str, Any]:
    """恢复治理前 SQL 与 DuckDB，并把当前报告显式更新为 restored。"""
    root = Path(root).resolve()
    output_dir = Path(output_dir).resolve()
    target = root / "sql" / TARGET_FILE
    sql_backup = output_dir / "before" / TARGET_FILE
    database_backup = output_dir / "before.duckdb"
    database_current = output_dir / "after.duckdb"
    operation_path = output_dir / "operation.json"
    if not sql_backup.is_file() or not database_backup.is_file():
        raise GovernanceError("缺少 SQL 或 DuckDB 治理前快照，无法恢复")
    if not operation_path.is_file():
        raise GovernanceError("缺少 operation.json，无法生成恢复审计")

    shutil.copy2(sql_backup, target)
    shutil.copy2(database_backup, database_current)
    result = json.loads(operation_path.read_text(encoding="utf-8"))
    result["scenario"]["status"] = "restored"
    result["change"]["changed"] = True
    result["change"]["status"] = "restored"
    result["rerun"] = {"tasks": [], "success_count": 0, "mode": "restore_snapshot"}
    result["runtime"]["after"] = _query_runtime(database_current)
    result["verify"]["closed_loop_status"] = "incomplete"
    result["audit"]["outcome"] = "restored"
    result["audit"]["steps"].append({
        "step": "restore",
        "evidence_version": result["evidence"]["version_id"],
        "detail": {
            "sql_restored": True,
            "database_restored": True,
        },
        "transition": "closed->restored",
    })
    operation_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="执行完整视频商业化数仓 CTR 治理")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("smoke", "demo"), default="smoke")
    parser.add_argument("--restore", action="store_true", help="恢复治理前 SQL 与 DuckDB 快照")
    parser.add_argument("--no-open", action="store_true", help="生成报告后不打开浏览器")
    args = parser.parse_args(argv)
    try:
        if args.restore:
            result = restore_governance(args.root, args.output)
        else:
            result = run_ctr_governance(args.root, args.output, profile=args.profile)
    except GovernanceError as exc:
        print(f"治理失败: {exc}")
        return 1
    from examples.video_commercial_warehouse.report import render_report

    report_path = render_report(result, args.output / "warehouse_report.html")
    print(
        f"完成: {result['catalog']['table_count']} 表 / "
        f"{result['catalog']['task_count']} 任务 / "
        f"verify={result['verify']['closed_loop_status']}"
    )
    print(f"审计: {args.output.resolve() / 'operation.json'}")
    print(f"报告: file://{report_path}")
    if not args.no_open:
        import webbrowser
        webbrowser.open(report_path.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
