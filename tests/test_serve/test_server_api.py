import json
import os
import threading
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


def _table_id(index, full_name):
    for nid, node in index.nodes.items():
        if node.get("node_type") == "table" and node.get("full_name") == full_name:
            return nid
    raise AssertionError("not found")


def test_meta_and_pages(server):
    base, _ = server
    status, body = _get(f"{base}/api/meta")
    assert status == 200 and json.loads(body)["stats"]["nodes"] > 0
    status, html = _get(f"{base}/search")
    assert status == 200 and "SqlGraph Explorer" in html


def test_search_and_subgraph_and_node(server):
    base, index = server
    status, body = _get(f"{base}/api/search?q=dst&type=table")
    assert status == 200 and any(h["name"] == "dst" for h in json.loads(body)["hits"])
    dst = _table_id(index, "dst")
    status, body = _get(f"{base}/api/subgraph?node_id={dst}&depth=1&direction=both")
    assert status == 200 and len(json.loads(body)["nodes"]) >= 1
    status, body = _get(f"{base}/api/node/{dst}")
    assert status == 200 and json.loads(body)["node"]["id"] == dst


def test_missing_node_returns_404(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{base}/api/node/nope")
    assert exc.value.code == 404


def test_cli_registers_serve_command():
    from typer.testing import CliRunner
    from sqlgraph.cli import app

    result = CliRunner().invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "serve" in result.output.lower()
    assert "--rebuild" in result.output
