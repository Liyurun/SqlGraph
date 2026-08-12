# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
import json

import pytest

from sqlgraph.serve.graph_index import GraphIndex
from sqlgraph.serve.index_io import load_raw_index, prepare_index
from sqlgraph.serve.stats import AnalysisSnapshot, build_index_stats, table_stats


@pytest.fixture()
def sample_index(tmp_path):
    sql_file = os.path.join(tmp_path, "q.sql")
    with open(sql_file, "w", encoding="utf-8") as f:
        f.write("INSERT OVERWRITE TABLE dst SELECT id FROM src")
    index_dir = prepare_index(sql_file, os.path.join(tmp_path, "idx"), dialect="spark")
    return GraphIndex.from_raw(load_raw_index(index_dir))


def test_build_index_stats_counts_types_and_top_tables(sample_index):
    stats = build_index_stats(sample_index, limit=5)

    assert stats["stats"]["nodes"] == len(sample_index.nodes)
    assert stats["stats"]["edges"] == len(sample_index.edges)
    assert stats["stats"]["sql"] == len(sample_index.sql_by_id)
    assert {"type": "table", "count": 2} in stats["nodeTypes"]
    assert any(row["type"] == "table_lineage" for row in stats["edgeTypes"])
    assert stats["tableLineageEdges"] == 1

    top_read = {row["fullName"]: row for row in stats["topReadTables"]}
    top_write = {row["fullName"]: row for row in stats["topWriteTables"]}
    assert top_read["src"]["readSqlCount"] == 1
    assert top_write["dst"]["writeSqlCount"] == 1

    degree_rows = {row["fullName"]: row for row in stats["topDegreeTables"]}
    assert degree_rows["src"]["outDegree"] == 1
    assert degree_rows["dst"]["inDegree"] == 1
    assert stats["analysisRiskTables"][0]["degree"] >= 1


def test_table_stats_returns_index_only_payload(sample_index):
    dst = next(
        node_id
        for node_id, node in sample_index.nodes.items()
        if node.get("node_type") == "table" and node.get("full_name") == "dst"
    )

    payload = table_stats(sample_index, AnalysisSnapshot.unavailable(), dst)

    assert payload["ok"] is True
    assert payload["tableId"] == dst
    assert payload["index"]["writeSqlCount"] == 1
    assert payload["index"]["readSqlCount"] == 0
    assert payload["index"]["upstreamCount"] == 1
    assert payload["index"]["downstreamCount"] == 0
    assert payload["analysis"]["available"] is False
    assert payload["analysis"]["mode"] == "index_only"
    assert payload["analysis"]["metrics"] == {}


def test_analysis_snapshot_prefers_dashboard_json(tmp_path, sample_index):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "manifest.json").write_text(
        json.dumps({"metric_statuses": {"basic": "success"}}),
        encoding="utf-8",
    )
    (profile_dir / "summary.json").write_text(
        json.dumps({"basic": {"overview": {"table_count": {"value": 2}}}}),
        encoding="utf-8",
    )
    (profile_dir / "dashboard.json").write_text(
        json.dumps(
            {
                "version": 1,
                "overview": {"cards": {"table_count": 2}},
                "layerHealth": {},
                "coreAssets": {},
                "domains": {},
                "riskAssets": {},
                "consistency": {},
            }
        ),
        encoding="utf-8",
    )
    dst = next(
        node_id
        for node_id, node in sample_index.nodes.items()
        if node.get("node_type") == "table" and node.get("full_name") == "dst"
    )
    (profile_dir / "table_metrics.jsonl").write_text(
        json.dumps(
            {
                "table_id": dst,
                "table_name": "dst",
                "declared_layer": "dwd",
                "graph_layer_max": 1,
                "blast_score": 0.8,
                "product_score": 73.5,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = AnalysisSnapshot.load(str(profile_dir))
    payload = table_stats(sample_index, snapshot, dst)

    assert snapshot.available is True
    assert snapshot.mode == "profile"
    assert snapshot.compact()["dashboard"]["overview"]["cards"]["table_count"] == 2
    assert payload["analysis"]["mode"] == "profile"
    assert payload["analysis"]["metrics"]["product_score"] == 73.5


def test_analysis_snapshot_loads_summary_and_table_metrics(tmp_path, sample_index):
    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir()
    (analysis_dir / "manifest.json").write_text(
        json.dumps(
            {
                "metric_statuses": {
                    "basic": "success",
                    "topology": "success",
                    "impact": "success",
                }
            }
        ),
        encoding="utf-8",
    )
    (analysis_dir / "summary.json").write_text(
        json.dumps(
            {
                "impact": {
                    "top_blast_score_tables": {
                        "value": [{"table_id": "dst", "blast_score": 0.8}]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    dst = next(
        node_id
        for node_id, node in sample_index.nodes.items()
        if node.get("node_type") == "table" and node.get("full_name") == "dst"
    )
    (analysis_dir / "table_metrics.jsonl").write_text(
        json.dumps(
            {
                "table_id": dst,
                "table_name": "dst",
                "blast_score": 0.8,
                "community_id": "community_0001",
                "rule_anomaly_score": 0.1,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = AnalysisSnapshot.load(str(analysis_dir))
    payload = table_stats(sample_index, snapshot, dst)

    assert snapshot.available is True
    assert snapshot.mode == "analysis"
    assert snapshot.compact()["manifest"]["metric_statuses"]["impact"] == "success"
    assert payload["analysis"]["available"] is True
    assert payload["analysis"]["mode"] == "analysis"
    assert payload["analysis"]["metrics"]["blast_score"] == 0.8
    assert payload["analysis"]["metrics"]["community_id"] == "community_0001"


def test_analysis_snapshot_is_optional_and_reports_error(tmp_path):
    missing = tmp_path / "missing-analysis"

    snapshot = AnalysisSnapshot.load(str(missing))

    assert snapshot.available is False
    assert snapshot.mode == "index_only"
    assert snapshot.source == str(missing)
    assert "not found" in snapshot.error
