# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Versioned, deterministic file output for governance snapshots."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlgraph.analyze.contracts import (
    GovernanceSnapshot,
    MetricResult,
    MetricStatus,
    thaw,
)


OUTPUT_SCHEMA_VERSION = "1.0"


def normalize_for_output(value: Any, *, precision: int) -> Any:
    """Convert analysis values to deterministic JSON-compatible objects."""
    value = thaw(value)
    if isinstance(value, MetricResult):
        return normalize_for_output(value.to_dict(), precision=precision)
    if isinstance(value, MetricStatus):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): normalize_for_output(value[key], precision=precision)
            for key in sorted(value, key=str)
        }
    if isinstance(value, (list, tuple)):
        return [normalize_for_output(item, precision=precision) for item in value]
    if isinstance(value, float):
        return round(value, precision)
    return value


def stable_json_dumps(value: Any, *, precision: int) -> str:
    """Dump JSON with stable key ordering and configured float precision."""
    normalized = normalize_for_output(value, precision=precision)
    return json.dumps(
        normalized,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def write_governance_output(
    snapshot: GovernanceSnapshot,
    output_dir: str | Path,
) -> dict[str, str]:
    """Write a governance snapshot into JSON, JSONL, and CSV artifacts."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    precision = snapshot.manifest.float_precision
    payload = snapshot.to_dict()

    written: dict[str, str] = {}
    written["manifest"] = _write_json(
        output_path / "manifest.json",
        payload["manifest"],
        precision=precision,
    )
    written["summary"] = _write_json(
        output_path / "summary.json",
        payload["summary"],
        precision=precision,
    )
    written["layer_matrix"] = _write_json(
        output_path / "layer_matrix.json",
        payload["layer_matrix"],
        precision=precision,
    )
    written["community_matrix"] = _write_json(
        output_path / "community_matrix.json",
        payload["community_matrix"],
        precision=precision,
    )

    jsonl_artifacts = {
        "table_metrics": payload["table_metrics"],
        "column_metrics": payload["column_metrics"],
        "sql_metrics": payload["sql_metrics"],
        "transform_metrics": payload["transform_metrics"],
        "violations": payload["violations"],
        "consistency_groups": payload["consistency_groups"],
        "similarity_candidates": payload["similarity_candidates"],
        "motifs": payload["motif_records"],
        "anomaly_metrics": payload["anomaly_metrics"],
    }
    for name, records in jsonl_artifacts.items():
        written[name] = _write_jsonl(
            output_path / f"{name}.jsonl",
            records,
            precision=precision,
        )

    for name in ("table_metrics", "column_metrics", "sql_metrics", "transform_metrics"):
        written[f"{name}_csv"] = _write_csv(
            output_path / f"{name}.csv",
            jsonl_artifacts[name],
            precision=precision,
        )

    return written


def _write_json(path: Path, value: Any, *, precision: int) -> str:
    path.write_text(stable_json_dumps(value, precision=precision) + "\n", encoding="utf-8")
    return str(path)


def _write_jsonl(
    path: Path,
    records: Iterable[Mapping[str, Any]],
    *,
    precision: int,
) -> str:
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(stable_json_dumps(record, precision=precision))
            stream.write("\n")
    return str(path)


def _write_csv(
    path: Path,
    records: Iterable[Mapping[str, Any]],
    *,
    precision: int,
) -> str:
    normalized_records = [
        normalize_for_output(record, precision=precision)
        for record in records
    ]
    fieldnames = sorted(
        {
            str(key)
            for record in normalized_records
            if isinstance(record, Mapping)
            for key in record
        }
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        if not fieldnames:
            return str(path)
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for record in normalized_records:
            writer.writerow(
                {
                    field: _csv_cell(record.get(field), precision=precision)
                    for field in fieldnames
                }
            )
    return str(path)


def _csv_cell(value: Any, *, precision: int) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return stable_json_dumps(value, precision=precision)
    if isinstance(value, float):
        return round(value, precision)
    return value
