"""Local HTTP server for the Lineage Explorer (search / viewer / playground)."""
from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from jinja2 import Environment, FileSystemLoader, select_autoescape

from sqlgraph.serve.graph_index import GraphIndex
from sqlgraph.serve.index_io import prepare_index, load_raw_index
from sqlgraph.playground import graph_to_playground_payload, find_free_port

_WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
_STATIC_DIR = os.path.join(_WEB_DIR, "static")
_ENV = Environment(loader=FileSystemLoader(_WEB_DIR), autoescape=select_autoescape(["html", "j2"]))

_PAGES = {
    "/search": ("search", "检索"),
    "/viewer": ("viewer", "图谱查看"),
    "/playground": ("playground", "在线解析"),
}
_CONTENT_TYPES = {".css": "text/css", ".js": "application/javascript"}


def _render_page(active: str, title: str) -> str:
    body = _ENV.get_template(f"{active}.html.j2").render()
    return _ENV.get_template("shell.html.j2").render(
        active=active, page_title=title, body=body
    )


def make_handler(index: GraphIndex):
    class ExplorerHandler(BaseHTTPRequestHandler):
        server_version = "SqlGraphExplorer/1.0"

        def log_message(self, *args):
            return

        def _send(self, data: bytes, status: int, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, payload, status: int = 200):
            self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       status, "application/json; charset=utf-8")

        def _html(self, html: str, status: int = 200):
            self._send(html.encode("utf-8"), status, "text/html; charset=utf-8")

        def do_GET(self):
            parsed = urlparse(self.path)
            path, qs = parsed.path, parse_qs(parsed.query)
            if path == "/":
                self.send_response(302); self.send_header("Location", "/search"); self.end_headers(); return
            if path in _PAGES:
                active, title = _PAGES[path]
                self._html(_render_page(active, title)); return
            if path.startswith("/static/"):
                self._serve_static(path); return
            if path == "/api/meta":
                self._json(index.meta()); return
            if path == "/api/search":
                q = (qs.get("q") or [""])[0]
                etype = (qs.get("type") or ["all"])[0]
                limit = int((qs.get("limit") or ["50"])[0])
                self._json({"ok": True, "hits": index.search(q, etype, limit)}); return
            if path == "/api/subgraph":
                node_id = (qs.get("node_id") or [""])[0]
                if node_id not in index.nodes:
                    self._json({"ok": False, "error": "node not found"}, 404); return
                depth = int((qs.get("depth") or ["1"])[0])
                direction = (qs.get("direction") or ["both"])[0]
                self._json(index.subgraph(node_id, depth, direction)); return
            if path.startswith("/api/node/"):
                node_id = path[len("/api/node/"):]
                detail = index.node_detail(node_id)
                if detail is None:
                    self._json({"ok": False, "error": "node not found"}, 404); return
                self._json(detail); return
            if path.startswith("/api/sql/"):
                sql_id = path[len("/api/sql/"):]
                sql = index.sql_detail(sql_id)
                if sql is None:
                    self._json({"ok": False, "error": "sql not found"}, 404); return
                self._json(sql); return
            self._json({"ok": False, "error": "not found"}, 404)

        def do_POST(self):
            if urlparse(self.path).path != "/api/parse":
                self._json({"ok": False, "error": "not found"}, 404); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                sql = (payload.get("sql") or "").strip()
                if not sql:
                    raise ValueError("SQL 不能为空")
                self._json(graph_to_playground_payload(
                    sql=sql, dialect=payload.get("dialect") or None))
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)}, 400)

        def _serve_static(self, path: str):
            rel = path[len("/static/"):]
            full = os.path.normpath(os.path.join(_STATIC_DIR, rel))
            if not full.startswith(_STATIC_DIR) or not os.path.isfile(full):
                self._json({"ok": False, "error": "not found"}, 404); return
            ext = os.path.splitext(full)[1]
            with open(full, "rb") as f:
                self._send(f.read(), 200, _CONTENT_TYPES.get(ext, "application/octet-stream"))

    return ExplorerHandler


def build_app_server(index: GraphIndex, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """Create (but do not start) the HTTP server bound to an in-memory index."""
    if port <= 0:
        port = find_free_port(host)
    return ThreadingHTTPServer((host, port), make_handler(index))


def serve_explorer(
    input_path: str,
    host: str = "127.0.0.1",
    port: int = 8770,
    dialect: str | None = None,
    rebuild: bool = False,
    index_dir: str = ".sqlgraph_index",
    open_browser: bool = True,
) -> str:
    """Build-or-reuse the index, load it into memory, then serve the explorer."""
    def log(msg: str) -> None:
        print(msg, flush=True)

    size = os.path.getsize(input_path) / 1e6 if os.path.isfile(input_path) else 0
    log(f"[serve] input: {input_path} ({size:.1f} MB)")
    concrete_dir = prepare_index(input_path, index_dir, dialect=dialect, rebuild=rebuild, log=log)
    log("[load]  loading index into memory ...")
    index = GraphIndex.from_raw(load_raw_index(concrete_dir))
    log(f"[load]  ready | nodes={len(index.nodes)} edges={len(index.edges)} sql={len(index.sql_by_id)}")

    httpd = build_app_server(index, host=host, port=port)
    actual_port = httpd.server_address[1]
    url = f"http://{host}:{actual_port}/"
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    log(f"[serve] {url} (search / viewer / playground)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return url
