# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Local HTTP server for the Lineage Explorer (search / viewer / playground)."""
from __future__ import annotations

import json
import os
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from jinja2 import Environment, FileSystemLoader, select_autoescape

from sqlgraph.serve.graph_index import GraphIndex
from sqlgraph.serve.index_io import (
    load_raw_index,
    prepare_index,
    prepare_index_from_graph_json,
)
from sqlgraph.serve.stats import AnalysisSnapshot, build_index_stats, table_stats
from sqlgraph.playground import graph_to_playground_payload, find_free_port

_WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
_STATIC_DIR = os.path.join(_WEB_DIR, "static")
_ENV = Environment(loader=FileSystemLoader(_WEB_DIR), autoescape=select_autoescape(["html", "j2"]))

_PAGES = {
    "/search": ("search", "检索"),
    "/viewer": ("viewer", "图谱查看"),
    "/stats": ("stats", "统计"),
    "/playground": ("playground", "在线解析"),
}
_CONTENT_TYPES = {".css": "text/css", ".js": "application/javascript"}


class IPv6ThreadingHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def _server_class_for_host(host: str) -> type[ThreadingHTTPServer]:
    return IPv6ThreadingHTTPServer if ":" in host else ThreadingHTTPServer


def _inline_static_asset(name: str) -> str:
    """Return a static asset for same-document embedding."""
    full = os.path.normpath(os.path.join(_STATIC_DIR, name))
    if not full.startswith(_STATIC_DIR) or not os.path.isfile(full):
        raise FileNotFoundError(f"static asset not found: {name}")
    with open(full, encoding="utf-8") as f:
        content = f.read()
    if name.endswith(".js"):
        return content.replace("</script", "<\\/script")
    return content


def _render_page(active: str, title: str) -> str:
    return _ENV.get_template(f"{active}.html.j2").render(
        active=active,
        page_title=title,
        inline_static=_inline_static_asset,
    )


def _analysis_dir_for(index_dir: str | None) -> str | None:
    explicit_profile = os.environ.get("SQLGRAPH_PROFILE_DIR")
    if explicit_profile:
        return explicit_profile
    if index_dir:
        profile_candidate = os.path.join(index_dir, "profile")
        if os.path.isdir(profile_candidate):
            return profile_candidate
    explicit_analysis = os.environ.get("SQLGRAPH_ANALYSIS_DIR")
    if explicit_analysis:
        return explicit_analysis
    if index_dir:
        candidate = os.path.join(index_dir, "analysis")
        if os.path.isdir(candidate):
            return candidate
    return None


def make_handler(index: GraphIndex, analysis_dir: str | None = None):
    index_stats = build_index_stats(index)
    analysis = AnalysisSnapshot.load(analysis_dir)

    class ExplorerHandler(BaseHTTPRequestHandler):
        server_version = "SqlGraphExplorer/1.0"

        def log_message(self, *_args):
            if _args:
                return
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
            if path == "/v1/ping":
                self._json({"ok": True, "status": "alive"}); return
            if path in ("/healthz", "/api/health", "/doc", "/status"):
                self._json({"ok": True, "status": "healthy",
                            "stats": index.meta().get("stats", {})}); return
            if path == "/":
                self._html(_render_page("search", "检索")); return
            if path in _PAGES:
                active, title = _PAGES[path]
                self._html(_render_page(active, title)); return
            if path.startswith("/static/"):
                self._serve_static(path); return
            if path == "/api/meta":
                self._json(index.meta()); return
            if path == "/api/stats":
                profile_payload = analysis.compact()
                self._json({
                    "ok": True,
                    "mode": profile_payload.get("mode", "index_only"),
                    "index": index_stats,
                    "analysis": profile_payload,
                    "profile": profile_payload,
                }); return
            if path.startswith("/api/stats/table/"):
                table_id = path[len("/api/stats/table/"):]
                payload = table_stats(index, analysis, table_id)
                self._json(payload, 200 if payload.get("ok") else 404); return
            if path == "/api/search":
                q = (qs.get("q") or [""])[0]
                etype = (qs.get("type") or ["all"])[0]
                limit = int((qs.get("limit") or ["50"])[0])
                self._json({"ok": True, "hits": index.search(q, etype, limit)}); return
            if path == "/api/subgraph":
                node_id = (qs.get("node_id") or [""])[0]
                if node_id not in index.nodes:
                    self._json({"ok": False, "error": "node not found"}, 404); return
                depth = int((qs.get("depth") or ["2"])[0])
                direction = (qs.get("direction") or ["both"])[0]
                mode = (qs.get("mode") or ["raw"])[0]
                if mode == "table":
                    self._json(index.table_subgraph(node_id, depth, direction)); return
                if mode == "raw":
                    self._json(index.subgraph(node_id, depth, direction)); return
                self._json({"ok": False, "error": f"unknown subgraph mode: {mode}"}, 400); return
            if path == "/api/expand":
                node_id = (qs.get("node_id") or [""])[0]
                if node_id not in index.nodes:
                    self._json({"ok": False, "error": "node not found"}, 404); return
                mode = (qs.get("mode") or ["table"])[0]
                if mode != "table":
                    self._json({"ok": False, "error": f"unknown expand mode: {mode}"}, 400); return
                depth = int((qs.get("depth") or ["1"])[0])
                direction = (qs.get("direction") or ["both"])[0]
                self._json(index.table_expansion(node_id, direction, depth)); return
            if path.startswith("/api/node/"):
                node_id = path[len("/api/node/"):]
                detail = index.node_detail(node_id, analysis)
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

        def do_HEAD(self):
            path = urlparse(self.path).path
            if path in ("/", "/v1/ping", "/healthz", "/api/health", "/doc", "/status", *_PAGES):
                self.send_response(200)
                self.end_headers()
                return
            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                full = os.path.normpath(os.path.join(_STATIC_DIR, rel))
                if full.startswith(_STATIC_DIR) and os.path.isfile(full):
                    self.send_response(200)
                    self.end_headers()
                    return
            self.send_response(404)
            self.end_headers()

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


def build_app_server(
    index: GraphIndex,
    host: str = "127.0.0.1",
    port: int = 0,
    analysis_dir: str | None = None,
) -> ThreadingHTTPServer:
    """Create (but do not start) the HTTP server bound to an in-memory index."""
    if port <= 0:
        port = find_free_port(host)
    return _server_class_for_host(host)((host, port), make_handler(index, analysis_dir))


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

    httpd = build_app_server(
        index,
        host=host,
        port=port,
        analysis_dir=_analysis_dir_for(concrete_dir),
    )
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


def serve_graph_explorer(
    graph_json_path: str,
    host: str = "127.0.0.1",
    port: int = 8770,
    rebuild: bool = False,
    index_dir: str = ".sqlgraph_index",
    open_browser: bool = True,
) -> str:
    """Serve the explorer from a prebuilt graph.json artifact."""
    def log(msg: str) -> None:
        print(msg, flush=True)

    size = (
        os.path.getsize(graph_json_path) / 1e6
        if os.path.isfile(graph_json_path)
        else 0
    )
    log(f"[serve-graph] graph: {graph_json_path} ({size:.1f} MB)")
    concrete_dir = prepare_index_from_graph_json(
        graph_json_path,
        index_dir,
        rebuild=rebuild,
        log=log,
    )
    log("[load]  loading index into memory ...")
    index = GraphIndex.from_raw(load_raw_index(concrete_dir))
    log(
        f"[load]  ready | nodes={len(index.nodes)} "
        f"edges={len(index.edges)} sql={len(index.sql_by_id)}"
    )

    httpd = build_app_server(
        index,
        host=host,
        port=port,
        analysis_dir=_analysis_dir_for(concrete_dir),
    )
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


def serve_index_explorer(
    prepared_index_dir: str,
    host: str = "127.0.0.1",
    port: int = 8770,
    open_browser: bool = True,
) -> str:
    """Serve the explorer directly from a prepared JSONL index directory."""
    def log(msg: str) -> None:
        print(msg, flush=True)

    manifest_path = os.path.join(prepared_index_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(
            f"prepared index manifest not found: {manifest_path}"
        )
    log(f"[serve-index] index: {prepared_index_dir}")
    log("[load]  loading index into memory ...")
    index = GraphIndex.from_raw(load_raw_index(prepared_index_dir))
    log(
        f"[load]  ready | nodes={len(index.nodes)} "
        f"edges={len(index.edges)} sql={len(index.sql_by_id)}"
    )

    httpd = build_app_server(
        index,
        host=host,
        port=port,
        analysis_dir=_analysis_dir_for(prepared_index_dir),
    )
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
