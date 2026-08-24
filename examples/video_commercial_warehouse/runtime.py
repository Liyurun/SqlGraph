"""DuckDB 数仓运行时：种子生成、全量执行与增量任务执行。"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import duckdb

from examples.video_commercial_warehouse.catalog import (
    ALL_TABLES,
    TASKS,
    TaskSpec,
    validate_catalog,
)
from examples.video_commercial_warehouse.generate_sql import ROOT, generate_sql
from examples.video_commercial_warehouse.seed import seed_base_tables


class WarehouseExecutionError(RuntimeError):
    """某个数仓任务执行失败。"""


@dataclass(frozen=True)
class TaskRun:
    order: int
    target: str
    status: str
    row_count: int
    elapsed_ms: float
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RunResult:
    database_path: str
    profile: str
    task_runs: tuple[TaskRun, ...]
    table_rows: dict[str, int]

    @property
    def success_count(self) -> int:
        return sum(run.status == "success" for run in self.task_runs)

    @property
    def failed(self) -> list[TaskRun]:
        return [run for run in self.task_runs if run.status != "success"]

    @property
    def elapsed_ms(self) -> float:
        return round(sum(run.elapsed_ms for run in self.task_runs), 3)

    def to_dict(self) -> dict:
        return {
            "database_path": self.database_path,
            "profile": self.profile,
            "success_count": self.success_count,
            "failed": [run.to_dict() for run in self.failed],
            "elapsed_ms": self.elapsed_ms,
            "task_runs": [run.to_dict() for run in self.task_runs],
            "table_rows": self.table_rows,
        }


def _sql_path(sql_dir: Path, task: TaskSpec) -> Path:
    return sql_dir / f"{task.order:03d}_{task.target}.sql"


def execute_tasks(
    con: duckdb.DuckDBPyConnection,
    tasks: Iterable[TaskSpec],
    sql_dir: Path,
) -> tuple[TaskRun, ...]:
    """按给定顺序执行任务；首个失败立即中断并携带任务上下文。"""
    records: list[TaskRun] = []
    for task in tasks:
        path = _sql_path(sql_dir, task)
        if not path.is_file():
            raise WarehouseExecutionError(f"SQL 文件不存在: {path}")
        sql = path.read_text(encoding="utf-8")
        started = time.perf_counter()
        try:
            con.execute(sql)
            row_count = int(
                con.execute(f'SELECT COUNT(*) FROM "{task.target}"').fetchone()[0]
            )
        except Exception as exc:
            elapsed = round((time.perf_counter() - started) * 1000, 3)
            records.append(TaskRun(task.order, task.target, "failed", 0, elapsed, str(exc)))
            raise WarehouseExecutionError(
                f"任务 {task.order:03d} {task.target} 执行失败: {exc}"
            ) from exc
        elapsed = round((time.perf_counter() - started) * 1000, 3)
        records.append(TaskRun(task.order, task.target, "success", row_count, elapsed))
    return tuple(records)


def collect_table_rows(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """查询 catalog 中全部 94 张表的行数。"""
    rows: dict[str, int] = {}
    for table in ALL_TABLES:
        exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='main' AND table_name=?",
            [table],
        ).fetchone()[0]
        if not exists:
            raise WarehouseExecutionError(f"目标表未生成: {table}")
        rows[table] = int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    return rows


def build_warehouse(
    database_path: Path,
    *,
    profile: str = "smoke",
    sql_dir: Path | None = None,
) -> RunResult:
    """从空 DuckDB 开始生成基础数据并执行完整 62 任务。"""
    validate_catalog()
    database_path = Path(database_path).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()

    if sql_dir is None:
        resolved_sql_dir = ROOT / "sql"
        # 默认运行不得覆盖用户或治理流程已经修改过的真实 SQL；仅在产物缺失时生成。
        if len(list(resolved_sql_dir.glob("*.sql"))) != 62:
            paths = generate_sql(ROOT)
            resolved_sql_dir = paths[0].parent
    else:
        resolved_sql_dir = Path(sql_dir).resolve()
        if len(list(resolved_sql_dir.glob("*.sql"))) != 62:
            raise WarehouseExecutionError(
                f"SQL 目录必须包含 62 个任务文件: {resolved_sql_dir}"
            )

    con = duckdb.connect(str(database_path))
    try:
        seed_base_tables(con, profile)
        records = execute_tasks(con, TASKS, resolved_sql_dir)
        table_rows = collect_table_rows(con)
        con.execute("CHECKPOINT")
    finally:
        con.close()
    return RunResult(str(database_path), profile, records, table_rows)


def rerun_tasks(
    database_path: Path,
    task_names: Iterable[str],
    *,
    sql_dir: Path | None = None,
) -> tuple[TaskRun, ...]:
    """在已有数据库上按 catalog 顺序重跑指定任务集合。"""
    wanted = set(task_names)
    tasks = [task for task in TASKS if task.target in wanted]
    missing = wanted - {task.target for task in tasks}
    if missing:
        raise WarehouseExecutionError(f"增量任务不在 catalog: {sorted(missing)}")
    resolved_sql_dir = Path(sql_dir) if sql_dir else ROOT / "sql"
    con = duckdb.connect(str(Path(database_path).resolve()))
    try:
        records = execute_tasks(con, tasks, resolved_sql_dir)
        con.execute("CHECKPOINT")
    finally:
        con.close()
    return records
