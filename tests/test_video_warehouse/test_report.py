from __future__ import annotations

from examples.video_commercial_warehouse.generate_sql import generate_sql
from examples.video_commercial_warehouse.governance import run_ctr_governance
from examples.video_commercial_warehouse.report import render_report
from sqlgraph.serve.theme import load_explorer_css


def test_report_contains_real_warehouse_evidence(tmp_path):
    root = tmp_path / "warehouse"
    output = tmp_path / "out"
    generate_sql(root)
    result = run_ctr_governance(root, output, profile="smoke")
    path = render_report(result, output / "warehouse_report.html")
    text = path.read_text(encoding="utf-8")

    assert '"table_count":94' in text
    assert '"task_count":62' in text
    assert '"source":"duckdb_query"' in text
    assert "data-node-id" in text
    assert "switchView(" in text
    assert "setLayer(" in text
    assert "setDomain(" in text
    assert "selectTable(" in text
    assert "https://" not in text


def test_report_uses_html_buttons_for_reliable_node_clicks(tmp_path):
    root = tmp_path / "warehouse"
    output = tmp_path / "out"
    generate_sql(root)
    result = run_ctr_governance(root, output, profile="smoke")
    path = render_report(result, output / "warehouse_report.html")
    text = path.read_text(encoding="utf-8")

    assert '<div id="graph-nodes"' in text
    assert "document.createElement('button')" in text
    assert "nodeButton.addEventListener('click'" in text
    assert 'aria-label="数仓血缘图"' in text


def test_report_has_mobile_list_mode_and_real_query_comparison(tmp_path):
    root = tmp_path / "warehouse"
    output = tmp_path / "out"
    generate_sql(root)
    result = run_ctr_governance(root, output, profile="smoke")
    path = render_report(result, output / "warehouse_report.html")
    text = path.read_text(encoding="utf-8")

    assert "mobile-assets" in text
    assert "DuckDB 真实查询" in text
    assert "invalid_ctr_rows" in text
    assert "grade_mismatch_rows" in text


def test_report_has_five_task_views_and_url_state(tmp_path):
    root = tmp_path / "warehouse"
    output = tmp_path / "out"
    generate_sql(root)
    result = run_ctr_governance(root, output, profile="smoke")
    text = render_report(
        result, output / "warehouse_report.html"
    ).read_text(encoding="utf-8")

    for view in ("overview", "lineage", "execution", "verification", "audit"):
        assert f'data-view="{view}"' in text
        assert f'id="view-{view}"' in text
    assert "history.replaceState" in text
    assert "URLSearchParams" in text


def test_report_has_search_empty_state_and_accessible_controls(tmp_path):
    root = tmp_path / "warehouse"
    output = tmp_path / "out"
    generate_sql(root)
    result = run_ctr_governance(root, output, profile="smoke")
    text = render_report(
        result, output / "warehouse_report.html"
    ).read_text(encoding="utf-8")

    assert 'class="skip-link"' in text
    assert 'type="search"' in text
    assert 'id="asset-search"' in text
    assert 'id="empty-state"' in text
    assert ":focus-visible" in text
    assert "clearFilters(" in text


def test_table_and_task_views_use_distinct_node_models(tmp_path):
    root = tmp_path / "warehouse"
    output = tmp_path / "out"
    generate_sql(root)
    result = run_ctr_governance(root, output, profile="smoke")
    text = render_report(
        result, output / "warehouse_report.html"
    ).read_text(encoding="utf-8")

    assert "renderTableGraph(" in text
    assert "renderTaskGraph(" in text
    assert "selectTable(" in text
    assert "selectTask(" in text
    assert 'id="table-detail"' in text
    assert 'id="task-detail"' in text


def test_audit_defaults_to_readable_summary_with_raw_json_collapsed(tmp_path):
    root = tmp_path / "warehouse"
    output = tmp_path / "out"
    generate_sql(root)
    result = run_ctr_governance(root, output, profile="smoke")
    text = render_report(
        result, output / "warehouse_report.html"
    ).read_text(encoding="utf-8")

    assert "审计摘要" in text
    assert "<details" in text
    assert "查看原始审计记录" in text
    assert 'id="raw-audit"' in text


def test_report_uses_github_explorer_visual_tokens(tmp_path):
    root = tmp_path / "warehouse"
    output = tmp_path / "out"
    generate_sql(root)
    result = run_ctr_governance(root, output, profile="smoke")
    text = render_report(
        result, output / "warehouse_report.html"
    ).read_text(encoding="utf-8")

    assert 'color-scheme:dark' in text
    assert "--bg:#0b1020" in text
    assert "--panel:#0f172a" in text
    assert "--accent:#34d399" in text
    assert "--accent-2:#38bdf8" in text
    assert "--font-ui:" in text
    assert "--font-mono:" in text
    assert 'class="app-tabs product-nav"' in text
    assert "SqlGraph Explorer" in text
    assert ".task-tabs{overflow-x:auto;flex-wrap:nowrap" not in text
    assert ".product-nav{position:sticky;top:0;height:100vh" not in text
    assert "background:#fff" not in text
    assert 'content="dark light"' not in text
    assert load_explorer_css() in text
