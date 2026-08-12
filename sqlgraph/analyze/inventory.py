# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Lineage asset inventory and external schema CSV loading.

Distinguishes between assets discovered in the lineage graph and the full
external schema/DDL catalog, without writing anything back to the original
graph.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlgraph.analyze.contracts import AnalysisView


@dataclass(frozen=True)
class ColumnInfo:
    """One column entry from external schema inventory.

    Attributes:
        column_name: The column name as it appears in the external catalog.
        data_type: The SQL data type; defaults to ``"string"``.
    """

    column_name: str
    data_type: str = "string"


@dataclass(frozen=True)
class TableInfo:
    """One table entry from external schema inventory.

    Attributes:
        table_name: Fully qualified or short table name from the catalog.
        columns: Immutable sequence of column entries.
        column_count: Derived total (stored for fast access).
    """

    table_name: str
    columns: tuple[ColumnInfo, ...] = ()
    column_count: int = 0

    def __post_init__(self) -> None:
        if self.column_count == 0 and self.columns:
            object.__setattr__(self, "column_count", len(self.columns))


@dataclass(frozen=True)
class LineageAssetInventory:
    """Inventory of assets discovered from the lineage graph alone.

    These counters describe *only* what the graph contains; they must never be
    presented as "the complete data warehouse".
    """

    table_ids: tuple[str, ...]
    column_ids: tuple[str, ...]
    table_full_names: tuple[str, ...]
    column_count: int
    table_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_count": self.table_count,
            "column_count": self.column_count,
            "table_ids": list(self.table_ids),
            "column_ids": list(self.column_ids),
            "table_full_names": list(self.table_full_names),
        }


@dataclass(frozen=True)
class ExternalSchemaInventory:
    """Inventory loaded from an external schema/DDL CSV file.

    The CSV format is compatible with the project's lightweight schema CSV:
    ``table_name,column_name[,data_type]``.

    Attributes:
        tables: Immutable sequence of table entries in stable sorted order.
        table_count: Total tables in the catalog.
        column_count: Total columns across all tables.
        source_path: Absolute path to the CSV source, if loaded from disk.
    """

    tables: tuple[TableInfo, ...]
    table_count: int
    column_count: int
    source_path: str | None = None

    def get_columns(self, table_name: str) -> tuple[str, ...] | None:
        """Return column names for a table, or *None* if not found."""
        for t in self.tables:
            if t.table_name == table_name:
                return tuple(c.column_name for c in t.columns)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_count": self.table_count,
            "column_count": self.column_count,
            "source_path": self.source_path,
            "tables": [
                {
                    "table_name": t.table_name,
                    "column_count": t.column_count,
                    "columns": [
                        {"column_name": c.column_name, "data_type": c.data_type}
                        for c in t.columns
                    ],
                }
                for t in self.tables
            ],
        }


@dataclass(frozen=True)
class AssetCoverage:
    """Coverage metrics comparing lineage assets against an external catalog.

    When no external schema is provided every external-* field stays *None*
    and the consumer must not present the lineage numbers as total warehouse
    counts.
    """

    lineage_table_count: int
    lineage_column_count: int
    external_table_count: int | None = None
    external_column_count: int | None = None
    covered_table_count: int | None = None
    covered_column_count: int | None = None
    table_coverage_ratio: float | None = None
    column_coverage_ratio: float | None = None

    def __post_init__(self) -> None:
        if self.external_table_count is not None and self.external_table_count > 0:
            if self.covered_table_count is not None and self.table_coverage_ratio is None:
                object.__setattr__(
                    self,
                    "table_coverage_ratio",
                    round(self.covered_table_count / self.external_table_count, 6),
                )
        if self.external_column_count is not None and self.external_column_count > 0:
            if self.covered_column_count is not None and self.column_coverage_ratio is None:
                object.__setattr__(
                    self,
                    "column_coverage_ratio",
                    round(self.covered_column_count / self.external_column_count, 6),
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lineage_table_count": self.lineage_table_count,
            "lineage_column_count": self.lineage_column_count,
            "external_table_count": self.external_table_count,
            "external_column_count": self.external_column_count,
            "covered_table_count": self.covered_table_count,
            "covered_column_count": self.covered_column_count,
            "table_coverage_ratio": self.table_coverage_ratio,
            "column_coverage_ratio": self.column_coverage_ratio,
        }


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_lineage_inventory(view: AnalysisView) -> LineageAssetInventory:
    """Extract table and column identifiers present in the lineage graph.

    Returns a read-only snapshot; does **not** modify *view* or the original
    graph.
    """
    table_ids: list[str] = []
    column_ids: list[str] = []
    table_full_names: list[str] = []

    for node in view.iter_nodes("table"):
        tid = str(node["id"])
        table_ids.append(tid)

        name = str(node.get("name", ""))
        schema_name = node.get("schema_name")
        catalog = node.get("catalog")
        parts = [str(p) for p in (catalog, schema_name, name) if p]
        table_full_names.append(".".join(parts) if parts else name)

    for node in view.iter_nodes("column"):
        column_ids.append(str(node["id"]))

    table_ids.sort()
    column_ids.sort()
    table_full_names.sort()

    return LineageAssetInventory(
        table_ids=tuple(table_ids),
        column_ids=tuple(column_ids),
        table_full_names=tuple(table_full_names),
        column_count=len(column_ids),
        table_count=len(table_ids),
    )


def load_external_schema_csv(csv_path: str | Path) -> ExternalSchemaInventory:
    """Load an external schema CSV compatible with the project format.

    **Required columns:** ``table_name``, ``column_name``.
    **Optional:** ``data_type`` (defaults to ``"string"``).

    Raises:
        FileNotFoundError: The CSV path does not exist.
        ValueError: Required columns are missing or the CSV is malformed.
    """
    path = Path(csv_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Schema CSV not found: {path}")

    _REQUIRED = {"table_name", "column_name"}

    tables: dict[str, list[ColumnInfo]] = {}

    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise ValueError("Schema CSV has no header row")

            actual = {name.strip() for name in reader.fieldnames}
            missing = _REQUIRED - actual
            if missing:
                raise ValueError(
                    f"Schema CSV is missing required columns: {sorted(missing)}. "
                    f"Found columns: {sorted(actual)}"
                )

            for row_num, row in enumerate(reader, start=2):
                tname = str(row.get("table_name", "")).strip()
                cname = str(row.get("column_name", "")).strip()
                dtype = str(row.get("data_type", "string")).strip() or "string"

                if not tname:
                    raise ValueError(f"Row {row_num}: table_name is empty")
                if not cname:
                    raise ValueError(f"Row {row_num}: column_name is empty")

                tables.setdefault(tname, []).append(
                    ColumnInfo(column_name=cname, data_type=dtype)
                )
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"Failed to parse schema CSV: {exc}") from exc

    total_columns = 0
    table_infos: list[TableInfo] = []
    for tname in sorted(tables):
        cols = tuple(tables[tname])
        total_columns += len(cols)
        table_infos.append(
            TableInfo(table_name=tname, columns=cols, column_count=len(cols))
        )

    return ExternalSchemaInventory(
        tables=tuple(table_infos),
        table_count=len(table_infos),
        column_count=total_columns,
        source_path=str(path),
    )


def compute_coverage(
    view: AnalysisView,
    external: ExternalSchemaInventory | None,
) -> AssetCoverage:
    """Compare lineage assets with an external schema catalog.

    Args:
        view: An immutable analysis view of the lineage graph.
        external: An external schema inventory, or *None*.

    Returns:
        Coverage metrics.  When *external* is *None*, all external-* and
        coverage-* fields are *None* and the caller must treat lineage numbers
        as partial.
    """
    # -- lineage side --------------------------------------------------------
    lineage_table_names: set[str] = set()
    table_id_to_name: dict[str, str] = {}
    lineage_cols_by_table: dict[str, set[str]] = {}

    for node in view.iter_nodes("table"):
        tid = str(node["id"])
        name = str(node.get("name", ""))
        schema_name = node.get("schema_name")
        catalog = node.get("catalog")
        parts = [str(p) for p in (catalog, schema_name, name) if p]
        full_name = ".".join(parts) if parts else name
        table_id_to_name[tid] = full_name
        lineage_table_names.add(full_name)
        lineage_cols_by_table.setdefault(full_name, set())

    lineage_column_count = 0
    for node in view.iter_nodes("column"):
        table_id = node.get("table_id")
        col_name = str(node.get("name", ""))
        if table_id and table_id in table_id_to_name:
            tname = table_id_to_name[table_id]
            lineage_cols_by_table.setdefault(tname, set()).add(col_name)
            lineage_column_count += 1

    if external is None:
        return AssetCoverage(
            lineage_table_count=len(lineage_table_names),
            lineage_column_count=lineage_column_count,
        )

    # -- external side -------------------------------------------------------
    external_table_set = {t.table_name for t in external.tables}
    external_col_map: dict[str, set[str]] = {}
    for t in external.tables:
        external_col_map[t.table_name] = {c.column_name for c in t.columns}

    # -- coverage ------------------------------------------------------------
    covered_tables = lineage_table_names & external_table_set

    covered_columns = 0
    for tname in covered_tables:
        lineage_cols = lineage_cols_by_table.get(tname, set())
        external_cols = external_col_map.get(tname, set())
        covered_columns += len(lineage_cols & external_cols)

    return AssetCoverage(
        lineage_table_count=len(lineage_table_names),
        lineage_column_count=lineage_column_count,
        external_table_count=external.table_count,
        external_column_count=external.column_count,
        covered_table_count=len(covered_tables),
        covered_column_count=covered_columns,
    )
