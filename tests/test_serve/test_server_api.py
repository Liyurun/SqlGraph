# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from sqlgraph.serve.index_io import prepare_index
from sqlgraph.serve.graph_index import GraphIndex
from sqlgraph.serve.index_io import load_raw_index
from sqlgraph.serve.server import build_app_server


@pytest.fixture()
def server(tmp_path):
    sql_file = os.path.join(tmp_path, "q.sql")
    with open(sql_file, "w", encoding="utf-8") as f:
        f.write("INSERT OVERWRITE TABLE dst SELECT id FROM src")
    index_dir = prepare_index(sql_file, os.path.join(tmp_path, "idx"), dialect="spark")
    index = GraphIndex.from_raw(load_raw_index(index_dir))
    httpd = build_app_server(index, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base, index
    httpd.shutdown()
    httpd.server_close()


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, resp.read().decode("utf-8")


def _head(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def _table_id(index, full_name):
    for nid, node in index.nodes.items():
        if node.get("node_type") == "table" and node.get("full_name") == full_name:
            return nid
    raise AssertionError("not found")


def _column_id(index, table_full_name, column_name):
    table_id = _table_id(index, table_full_name)
    for nid, node in index.nodes.items():
        if (
            node.get("node_type") == "column"
            and node.get("table_id") == table_id
            and node.get("name") == column_name
        ):
            return nid
    raise AssertionError("not found")


def test_meta_and_pages(server):
    base, _ = server
    status, body = _get(f"{base}/v1/ping")
    assert status == 200 and json.loads(body)["status"] == "alive"
    assert _head(f"{base}/v1/ping") == 200
    status, body = _get(f"{base}/api/meta")
    assert status == 200 and json.loads(body)["stats"]["nodes"] > 0
    status, html = _get(f"{base}/")
    assert status == 200 and "SqlGraph Explorer" in html
    assert _head(f"{base}/") == 200
    status, html = _get(f"{base}/search")
    assert status == 200 and "SqlGraph Explorer" in html
    status, stats_html = _get(f"{base}/stats")
    assert status == 200 and "图谱统计" in stats_html
    assert _head(f"{base}/stats") == 200
    assert _head(f"{base}/status") == 200
    assert 'aria-live="polite"' in html
    assert 'name="q"' in html
    assert "推荐探索入口" in html
    assert "query: 'ad_dwa'" in html
    assert "query: 'creative_id'" in html
    assert "搜索表名或字段名..." not in html


def test_viewer_page_defaults_to_table_mode_and_has_expand_controls(server):
    base, _ = server
    status, html = _get(f"{base}/viewer")

    assert status == 200
    assert 'id="mode"' in html
    assert 'value="table" selected' in html
    assert 'id="depth"' in html
    assert 'type="number"' in html
    assert 'value="1"' in html
    assert 'id="expand-up"' in html
    assert 'id="expand-down"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-label="SqlGraph 血缘图"' in html
    assert "/api/expand" in html
    assert "window.mergeGraph" in html
    assert "data.truncated" in html
    assert "data.message" in html
    assert "params.get('mode')" in html
    assert "params.get('direction')" in html
    assert "params.get('depth')" in html
    assert "setControlValue('mode'" in html


def test_pages_inline_owned_static_assets(server):
    base, _ = server

    for path in ("/", "/search", "/viewer", "/stats", "/playground"):
        status, html = _get(f"{base}{path}")

        assert status == 200
        assert "/static/app.css" not in html
        assert "/static/graph.js" not in html
        assert "/static/detail.js" not in html
        assert "--accent: #34d399" in html
        assert "window.renderGraph = function" in html
        assert "window.renderDetail = function" in html
        assert "字段列表" in html
        assert "字段详情" in html or "ownerTable" in html
        assert "field-link" in html


def test_stats_api_index_only_payload(server):
    base, _ = server
    status, body = _get(f"{base}/api/stats")
    payload = json.loads(body)

    assert status == 200
    assert payload["ok"] is True
    assert payload["mode"] == "index_only"
    assert payload["index"]["stats"]["nodes"] > 0
    assert any(row["type"] == "table" for row in payload["index"]["nodeTypes"])
    assert payload["analysis"]["available"] is False
    assert payload["analysis"]["mode"] == "index_only"
    assert payload["profile"]["mode"] == "index_only"


def test_table_stats_api_returns_table_profile(server):
    base, index = server
    dst = _table_id(index, "dst")
    status, body = _get(f"{base}/api/stats/table/{dst}")
    payload = json.loads(body)

    assert status == 200
    assert payload["ok"] is True
    assert payload["index"]["writeSqlCount"] == 1
    assert payload["index"]["upstreamCount"] == 1
    assert payload["analysis"]["metrics"] == {}


def test_search_and_subgraph_and_node(server):
    base, index = server
    status, body = _get(f"{base}/api/search?q=dst&type=table")
    assert status == 200 and any(h["name"] == "dst" for h in json.loads(body)["hits"])
    dst = _table_id(index, "dst")
    status, body = _get(f"{base}/api/subgraph?node_id={dst}&depth=1&direction=both")
    assert status == 200 and len(json.loads(body)["nodes"]) >= 1
    status, body = _get(f"{base}/api/node/{dst}")
    payload = json.loads(body)
    assert status == 200 and payload["node"]["id"] == dst
    assert payload["stats"]["index"]["writeSqlCount"] == 1
    assert payload["stats"]["index"]["upstreamCount"] == 1
    assert any(col["name"] == "id" for col in payload["columns"])


def test_column_node_api_returns_field_detail(server):
    base, index = server
    dst_id_col = _column_id(index, "dst", "id")

    status, body = _get(f"{base}/api/node/{dst_id_col}")
    payload = json.loads(body)

    assert status == 200
    assert payload["node"]["id"] == dst_id_col
    assert payload["node"]["node_type"] == "column"
    assert payload["ownerTable"]["fullName"] == "dst"
    assert isinstance(payload["upstream"], list)
    assert isinstance(payload["downstream"], list)
    assert isinstance(payload["transforms"], list)
    assert isinstance(payload["sqls"], list)


def test_subgraph_table_mode_returns_only_tables(server):
    base, index = server
    dst = _table_id(index, "dst")
    status, body = _get(f"{base}/api/subgraph?node_id={dst}&depth=4&direction=up&mode=table")
    payload = json.loads(body)

    assert status == 200
    assert payload["mode"] == "table"
    assert {node["node_type"] for node in payload["nodes"]} == {"table"}
    assert all(edge["type"] == "table_lineage" for edge in payload["edges"])


def test_subgraph_raw_mode_preserves_existing_behavior(server):
    base, index = server
    dst = _table_id(index, "dst")
    status, body = _get(f"{base}/api/subgraph?node_id={dst}&depth=1&direction=both&mode=raw")
    payload = json.loads(body)

    assert status == 200
    assert "mode" not in payload
    assert len(payload["nodes"]) >= 1


def test_subgraph_rejects_unknown_mode(server):
    base, index = server
    dst = _table_id(index, "dst")
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{base}/api/subgraph?node_id={dst}&mode=banana")
    assert exc.value.code == 400


def test_expand_returns_table_mode_increment(server):
    base, index = server
    dst = _table_id(index, "dst")
    status, body = _get(f"{base}/api/expand?node_id={dst}&direction=up&depth=1&mode=table")
    payload = json.loads(body)

    assert status == 200
    assert payload["mode"] == "table"
    assert {node["node_type"] for node in payload["nodes"]} == {"table"}


def test_missing_node_returns_404(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{base}/api/node/nope")
    assert exc.value.code == 404


def test_cli_registers_serve_command():
    from typer.main import get_command
    from sqlgraph.cli import app

    # Introspect the registered command instead of parsing rendered --help text,
    # which is sensitive to terminal width / rich version (wraps CJK descriptions
    # and can split "--rebuild" across lines in a no-TTY CI environment).
    command = get_command(app)
    assert "serve" in command.commands
    serve_cmd = command.commands["serve"]
    option_names = set()
    for param in serve_cmd.params:
        option_names.update(getattr(param, "opts", []))
    assert "--rebuild" in option_names
    assert "serve-graph" in command.commands
    serve_graph_cmd = command.commands["serve-graph"]
    serve_graph_options = set()
    for param in serve_graph_cmd.params:
        serve_graph_options.update(getattr(param, "opts", []))
    assert "--index-dir" in serve_graph_options
    assert "serve-index" in command.commands
    serve_index_cmd = command.commands["serve-index"]
    serve_index_options = set()
    for param in serve_index_cmd.params:
        serve_index_options.update(getattr(param, "opts", []))
    assert "--port" in serve_index_options
