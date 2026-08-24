from __future__ import annotations

import hashlib
import json

from examples.video_commercial_warehouse.generate_sql import generate_sql


def _hashes(paths):
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


def test_generate_sql_is_complete_and_deterministic(tmp_path):
    first = generate_sql(tmp_path)
    first_hashes = _hashes(first)
    second = generate_sql(tmp_path)
    second_hashes = _hashes(second)

    assert len(first) == 62
    assert first_hashes == second_hashes
    assert first[0].name == "001_stg_recommend_request.sql"
    assert first[-1].name == "062_ads_risk_dashboard.sql"


def test_manifest_describes_all_tables_tasks_and_dependencies(tmp_path):
    generate_sql(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["table_count"] == 94
    assert manifest["base_table_count"] == 32
    assert manifest["task_count"] == 62
    assert len(manifest["tables"]) == 94
    assert len(manifest["tasks"]) == 62
    assert manifest["layer_counts"] == {
        "ADS": 10,
        "DIM": 14,
        "DWD": 18,
        "DWS": 16,
        "ODS": 18,
        "STG": 18,
    }
