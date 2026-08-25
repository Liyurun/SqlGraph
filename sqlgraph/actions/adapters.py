# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Built-in reversible action adapters."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any, Protocol


class AdapterExecutionError(RuntimeError):
    def __init__(self, message: str, rollback_state: dict[str, Any]):
        super().__init__(message)
        self.rollback_state = rollback_state


class ActionAdapter(Protocol):
    name: str

    def dry_run(self, operations: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
        ...

    def execute(
        self,
        operations: tuple[dict[str, Any], ...],
    ) -> tuple[tuple[str, ...], dict[str, Any]]:
        ...

    def rollback(self, state: dict[str, Any]):
        ...


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SqlFilePatchAdapter:
    name = "sql_file_patch"

    def _simulate(
        self,
        operations: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, str], tuple[str, ...]]:
        simulated: dict[str, str] = {}
        checks = []
        for operation in operations:
            path = Path(operation["path"])
            path_key = str(path)
            if path_key not in simulated:
                if not path.is_file():
                    raise ValueError(f"SQL target does not exist: {path}")
                simulated[path_key] = path.read_text(encoding="utf-8")
            content = simulated[path_key]
            if _sha256(content) != operation["expected_sha256"]:
                raise ValueError(f"SQL precondition hash changed: {path}")
            if content.count(operation["before"]) != 1:
                raise ValueError(f"SQL patch must match exactly once: {path}")
            simulated[path_key] = content.replace(
                operation["before"],
                operation["after"],
                1,
            )
            checks.append(f"patch-ready:{path}")
        return simulated, tuple(checks)

    def dry_run(self, operations: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
        _, checks = self._simulate(operations)
        return checks

    def execute(
        self,
        operations: tuple[dict[str, Any], ...],
    ) -> tuple[tuple[str, ...], dict[str, Any]]:
        originals: dict[str, str] = {}
        changed = []
        try:
            for operation in operations:
                path = Path(operation["path"])
                content = path.read_text(encoding="utf-8")
                if _sha256(content) != operation["expected_sha256"]:
                    raise ValueError(f"SQL precondition hash changed: {path}")
                if content.count(operation["before"]) != 1:
                    raise ValueError(f"SQL patch must match exactly once: {path}")
                originals.setdefault(str(path), content)
                path.write_text(
                    content.replace(operation["before"], operation["after"], 1),
                    encoding="utf-8",
                )
                changed.append(str(path))
                if operation.get("inject_failure_after_apply"):
                    raise RuntimeError("injected failure after SQL patch")
        except Exception as exc:
            raise AdapterExecutionError(
                str(exc),
                {
                    "originals": originals,
                    "original_hashes": {
                        path: _sha256(content)
                        for path, content in originals.items()
                    },
                },
            ) from exc
        return tuple(changed), {
            "originals": originals,
            "original_hashes": {
                path: _sha256(content)
                for path, content in originals.items()
            },
        }

    def rollback(self, state: dict[str, Any]):
        from sqlgraph.actions.model import RollbackResult

        originals = state.get("originals", {})
        original_hashes = state.get("original_hashes", {})
        restored = []
        for raw_path, content in originals.items():
            path = Path(raw_path)
            path.write_text(content, encoding="utf-8")
            restored_content = path.read_text(encoding="utf-8")
            expected_hash = original_hashes.get(raw_path, _sha256(content))
            if _sha256(restored_content) != expected_hash:
                return RollbackResult(
                    status="failed",
                    verified=False,
                    restored=tuple(restored),
                    error=f"restore verification failed: {path}",
                )
            restored.append(str(path))
        return RollbackResult(
            status="success",
            verified=True,
            restored=tuple(restored),
        )


class DuckDBTaskAdapter:
    name = "duckdb_tasks"

    def dry_run(self, operations: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
        checks = []
        for operation in operations:
            database = Path(operation["database_path"])
            statements = tuple(operation.get("statements", ()))
            if not database.is_file():
                raise ValueError(f"DuckDB database does not exist: {database}")
            if not statements:
                raise ValueError("DuckDB operation requires statements")
            checks.append(f"duckdb-ready:{database}:{len(statements)}")
        return tuple(checks)

    def execute(
        self,
        operations: tuple[dict[str, Any], ...],
    ) -> tuple[tuple[str, ...], dict[str, Any]]:
        import duckdb

        snapshots = {}
        changed = []
        try:
            for operation in operations:
                database = Path(operation["database_path"]).resolve()
                snapshot = Path(operation.get(
                    "snapshot_path",
                    f"{database}.sqlgraph-backup",
                )).resolve()
                shutil.copy2(database, snapshot)
                snapshots[str(database)] = str(snapshot)
                with duckdb.connect(str(database)) as connection:
                    connection.execute("BEGIN")
                    for statement in operation["statements"]:
                        connection.execute(statement)
                    if operation.get("inject_failure_after_apply"):
                        raise RuntimeError("injected failure after DuckDB execution")
                    connection.execute("COMMIT")
                changed.append(str(database))
        except Exception as exc:
            raise AdapterExecutionError(str(exc), {"snapshots": snapshots}) from exc
        return tuple(changed), {"snapshots": snapshots}

    def rollback(self, state: dict[str, Any]):
        from sqlgraph.actions.model import RollbackResult

        restored = []
        for raw_database, raw_snapshot in state.get("snapshots", {}).items():
            database = Path(raw_database)
            snapshot = Path(raw_snapshot)
            if not snapshot.is_file():
                return RollbackResult(
                    status="failed",
                    verified=False,
                    restored=tuple(restored),
                    error=f"snapshot missing: {snapshot}",
                )
            shutil.copy2(snapshot, database)
            if hashlib.sha256(database.read_bytes()).digest() != hashlib.sha256(
                snapshot.read_bytes()
            ).digest():
                return RollbackResult(
                    status="failed",
                    verified=False,
                    restored=tuple(restored),
                    error=f"snapshot verification failed: {database}",
                )
            restored.append(str(database))
        return RollbackResult(
            status="success",
            verified=True,
            restored=tuple(restored),
        )
