# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Statistics helpers for the Explorer HTTP server."""
from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

TOP_LIMIT = 20


def _sorted_counts(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {"type": key, "count": value}
        for key, value in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _table_name(index, table_id: str) -> str:
    node = index.nodes.get(table_id, {})
    return str(node.get("full_name") or node.get("name") or table_id)


def _table_row(index, table_id: str) -> dict[str, Any]:
    adj = index.table_adjacency.get(table_id, {"in": [], "out": []})
    read_count = len(index.table_read_sqls.get(table_id, []))
    write_count = len(index.table_write_sqls.get(table_id, []))
    in_degree = len(adj["in"])
    out_degree = len(adj["out"])
    return {
        "id": table_id,
        "name": index.nodes.get(table_id, {}).get("name") or table_id,
        "fullName": _table_name(index, table_id),
        "readSqlCount": read_count,
        "writeSqlCount": write_count,
        "inDegree": in_degree,
        "outDegree": out_degree,
        "degree": in_degree + out_degree,
    }


def _top(rows: list[dict[str, Any]], key: str, limit: int) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda row: (-int(row.get(key) or 0), row["fullName"]))
    return [row for row in ranked[:limit] if int(row.get(key) or 0) > 0]


def _read_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)
    return data if isinstance(data, dict) else {}


def _read_jsonl_by_table(path: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            table_id = str(row.get("table_id") or "")
            if table_id:
                rows[table_id] = row
    return rows


def build_index_stats(index, limit: int = TOP_LIMIT) -> dict[str, Any]:
    """Build cheap statistics from an already loaded GraphIndex."""
    node_types = Counter(
        str(node.get("node_type") or "unknown") for node in index.nodes.values()
    )
    edge_types = Counter(str(edge.get("type") or "unknown") for edge in index.edges)
    table_rows = [_table_row(index, table_id) for table_id in index.table_adjacency]
    no_upstream = sum(1 for row in table_rows if row["inDegree"] == 0)
    no_downstream = sum(1 for row in table_rows if row["outDegree"] == 0)
    risk_rows = _top(table_rows, "degree", limit)
    return {
        "stats": index.meta().get("stats", {}),
        "builtAt": index.meta().get("built_at"),
        "source": index.meta().get("source", {}),
        "nodeTypes": _sorted_counts(node_types),
        "edgeTypes": _sorted_counts(edge_types),
        "tableCount": node_types.get("table", 0),
        "columnCount": node_types.get("column", 0),
        "transformCount": node_types.get("transform", 0),
        "tableLineageEdges": len(index.table_lineage_edges),
        "topReadTables": _top(table_rows, "readSqlCount", limit),
        "topWriteTables": _top(table_rows, "writeSqlCount", limit),
        "topDegreeTables": risk_rows,
        "analysisRiskTables": risk_rows,
        "noUpstreamTables": no_upstream,
        "noDownstreamTables": no_downstream,
    }


@dataclass(frozen=True)
class AnalysisSnapshot:
    """Optional governance-analysis artifacts loaded from disk."""

    available: bool = False
    mode: str = "index_only"
    source: str | None = None
    error: str | None = None
    manifest: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    dashboard: dict[str, Any] = field(default_factory=dict)
    table_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def unavailable(
        cls,
        source: str | None = None,
        error: str | None = None,
    ) -> "AnalysisSnapshot":
        return cls(available=False, source=source, error=error)

    @classmethod
    def load(cls, analysis_dir: str | None) -> "AnalysisSnapshot":
        if not analysis_dir:
            return cls.unavailable()
        if not os.path.isdir(analysis_dir):
            return cls.unavailable(
                analysis_dir,
                f"analysis directory not found: {analysis_dir}",
            )
        try:
            manifest_path = os.path.join(analysis_dir, "manifest.json")
            manifest = _read_json(manifest_path) if os.path.isfile(manifest_path) else {}
            summary = (
                _read_json(os.path.join(analysis_dir, "summary.json"))
                if os.path.isfile(os.path.join(analysis_dir, "summary.json"))
                else {}
            )
            dashboard_path = os.path.join(analysis_dir, "dashboard.json")
            dashboard = (
                _read_json(dashboard_path)
                if os.path.isfile(dashboard_path)
                else {}
            )
            table_metrics = _read_jsonl_by_table(
                os.path.join(analysis_dir, "table_metrics.jsonl")
            )
        except (OSError, json.JSONDecodeError) as exc:
            return cls.unavailable(analysis_dir, f"{type(exc).__name__}: {exc}")
        return cls(
            available=True,
            mode="profile" if dashboard else "analysis",
            source=analysis_dir,
            manifest=manifest,
            summary=summary,
            dashboard=dashboard,
            table_metrics=table_metrics,
        )

    def compact(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "mode": self.mode,
            "source": self.source,
            "error": self.error,
            "manifest": self.manifest,
            "summary": self.summary,
            "dashboard": self.dashboard,
        }

    def metrics_for_table(self, table_id: str) -> dict[str, Any]:
        return dict(self.table_metrics.get(table_id, {}))


def table_stats(index, analysis: AnalysisSnapshot, table_id: str) -> dict[str, Any]:
    if table_id not in index.nodes or table_id not in index.table_adjacency:
        return {"ok": False, "error": "table not found"}
    row = _table_row(index, table_id)
    return {
        "ok": True,
        "tableId": table_id,
        "index": {
            "readSqlCount": row["readSqlCount"],
            "writeSqlCount": row["writeSqlCount"],
            "upstreamCount": row["inDegree"],
            "downstreamCount": row["outDegree"],
            "degree": row["degree"],
        },
        "analysis": {
            "available": analysis.available,
            "mode": analysis.mode,
            "metrics": analysis.metrics_for_table(table_id),
            "error": analysis.error,
        },
    }
