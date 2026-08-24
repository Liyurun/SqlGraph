from pathlib import Path

import duckdb

from examples.video_commercial_warehouse.catalog import ALL_TABLES
from examples.video_commercial_warehouse.generate_sql import generate_sql
from examples.video_commercial_warehouse.runtime import build_warehouse
from examples.video_commercial_warehouse.seed import PROFILES


def test_smoke_profile_executes_all_tasks(tmp_path):
    result = build_warehouse(tmp_path / "warehouse.duckdb", profile="smoke")

    assert result.success_count == 62
    assert result.failed == []
    assert len(result.table_rows) == 94
    assert set(result.table_rows) == set(ALL_TABLES)
    assert result.table_rows["ods_recommend_request"] == 5000
    assert result.table_rows["ads_creative_report"] > 0
    assert result.table_rows["ads_revenue_dashboard"] > 0


def test_smoke_build_is_deterministic(tmp_path):
    first = build_warehouse(tmp_path / "first.duckdb", profile="smoke")
    second = build_warehouse(tmp_path / "second.duckdb", profile="smoke")
    assert first.table_rows == second.table_rows

    with duckdb.connect(str(tmp_path / "first.duckdb"), read_only=True) as con1:
        rows1 = con1.execute(
            "SELECT * FROM ads_creative_report ORDER BY ad_creative_id, event_date"
        ).fetchall()
    with duckdb.connect(str(tmp_path / "second.duckdb"), read_only=True) as con2:
        rows2 = con2.execute(
            "SELECT * FROM ads_creative_report ORDER BY ad_creative_id, event_date"
        ).fetchall()
    assert rows1 == rows2


def test_profiles_have_declared_scale():
    smoke = PROFILES["smoke"]
    demo = PROFILES["demo"]
    assert smoke.recommend_requests == 5000
    assert demo.recommend_requests == 200_000
    assert demo.users > smoke.users
    assert demo.videos > smoke.videos


def test_default_runtime_does_not_overwrite_existing_sql(tmp_path, monkeypatch):
    import examples.video_commercial_warehouse.runtime as runtime

    root = tmp_path / "warehouse"
    generate_sql(root)
    target = root / "sql" / "044_dws_creative_performance_daily.sql"
    marker = "-- user-governed\n"
    target.write_text(marker + target.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(runtime, "ROOT", root)

    build_warehouse(tmp_path / "warehouse.duckdb", profile="smoke")
    assert target.read_text(encoding="utf-8").startswith(marker)
