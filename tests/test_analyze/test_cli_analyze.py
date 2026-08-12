"""CLI coverage for the governance analyze command."""

from __future__ import annotations

import builtins
import importlib
import json
import sys

from typer.main import get_command
from typer.testing import CliRunner

from sqlgraph.model import (
    ColumnNode,
    Edge,
    EdgeType,
    PropertyGraph,
    SqlNode,
    TableNode,
)


def _graph_json(path):
    graph = PropertyGraph()
    graph.add_node(
        SqlNode(
            id="sql_mid",
            name="build_mid",
            sql_content="insert overwrite table dwd.mid select id from ods.src",
            dialect="spark",
        )
    )
    graph.add_node(TableNode(id="tbl_src", name="src", schema_name="ods"))
    graph.add_node(TableNode(id="tbl_mid", name="mid", schema_name="dwd"))
    graph.add_node(
        ColumnNode(id="col_src_id", name="id", table_id="tbl_src", data_type="bigint")
    )
    graph.add_node(
        ColumnNode(id="col_mid_id", name="id", table_id="tbl_mid", data_type="bigint")
    )
    graph.add_edge(
        Edge("has_src_id", "tbl_src", "col_src_id", EdgeType.HAS_COLUMN)
    )
    graph.add_edge(
        Edge("has_mid_id", "tbl_mid", "col_mid_id", EdgeType.HAS_COLUMN)
    )
    graph.add_edge(Edge("read_src", "sql_mid", "tbl_src", EdgeType.READS_FROM))
    graph.add_edge(Edge("write_mid", "sql_mid", "tbl_mid", EdgeType.WRITES_TO))
    graph.add_edge(
        Edge("lineage_src_mid", "tbl_src", "tbl_mid", EdgeType.TABLE_LINEAGE)
    )
    graph.add_edge(
        Edge(
            "dep_src_id_mid_id",
            "col_src_id",
            "col_mid_id",
            EdgeType.COMPUTE_DEPENDENCY,
        )
    )
    path.write_text(json.dumps(graph.to_dict(), ensure_ascii=True), encoding="utf-8")
    return path


def test_analyze_cli_runs_with_config_overrides_and_cache_reuse(tmp_path):
    from sqlgraph.cli import app

    graph_path = _graph_json(tmp_path / "graph.json")
    config_path = tmp_path / "analysis_config.json"
    config_path.write_text(
        json.dumps(
            {
                "metrics": ["basic"],
                "float_precision": 4,
                "resource_budget": {"max_nodes": 1000, "max_edges": 1000},
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "analysis"
    cache_dir = tmp_path / "cache"
    runner = CliRunner()
    args = [
        "analyze",
        str(graph_path),
        "-o",
        str(output_dir),
        "--config",
        str(config_path),
        "--metrics",
        "basic,topology",
        "--seed",
        "13",
        "--cache-dir",
        str(cache_dir),
    ]

    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.stdout
    assert "治理分析完成" in first.stdout
    first_manifest = json.loads((output_dir / "manifest.json").read_text())
    assert first_manifest["random_seed"] == 13
    assert first_manifest["float_precision"] == 4
    assert first_manifest["metadata"]["config"]["metrics"] == ["basic", "topology"]
    assert first_manifest["metadata"]["resource_budget"]["max_nodes"] == 1000
    assert (
        first_manifest["metadata"]["cache"]["metrics"]["governance_snapshot"]
        == "miss"
    )
    assert (output_dir / "summary.json").is_file()
    assert (output_dir / "table_metrics.jsonl").is_file()

    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.stdout
    second_manifest = json.loads((output_dir / "manifest.json").read_text())
    assert (
        second_manifest["metadata"]["cache"]["metrics"]["governance_snapshot"]
        == "hit"
    )


def test_profile_cli_writes_dashboard_json(tmp_path):
    from sqlgraph.cli import app

    graph_path = _graph_json(tmp_path / "graph.json")
    output_dir = tmp_path / "profile"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "profile",
            str(graph_path),
            "-o",
            str(output_dir),
            "--metrics",
            "basic,topology,impact",
            "--max-nodes",
            "1000",
            "--max-edges",
            "1000",
            "--top-n",
            "5",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "画像生成完成" in result.stdout
    dashboard = json.loads((output_dir / "dashboard.json").read_text())
    assert dashboard["overview"]["cards"]["table_count"] == 2
    assert "layerHealth" in dashboard
    assert len(dashboard["coreAssets"]["topBlastScoreTables"]) <= 5


def test_analyze_cli_rejects_missing_graph_and_unknown_metric(tmp_path):
    from sqlgraph.cli import app

    runner = CliRunner()
    missing = runner.invoke(
        app,
        ["analyze", str(tmp_path / "missing.json"), "-o", str(tmp_path / "out")],
    )
    assert missing.exit_code == 2
    assert "graph input file not found" in missing.stdout

    graph_path = _graph_json(tmp_path / "graph.json")
    bad_metric = runner.invoke(
        app,
        ["analyze", str(graph_path), "--metrics", "basic,unknown_metric"],
    )
    assert bad_metric.exit_code == 2
    assert "unknown metrics" in bad_metric.stdout


def test_cli_registers_analyze_command_and_keeps_existing_commands():
    from sqlgraph.cli import app

    command = get_command(app)
    for name in ("build", "stats", "serve", "analyze", "profile"):
        assert name in command.commands
    analyze_cmd = command.commands["analyze"]
    option_names = {
        option
        for param in analyze_cmd.params
        for option in getattr(param, "opts", [])
    }
    assert "--config" in option_names
    assert "--metrics" in option_names
    assert "--cache-dir" in option_names
    assert "--max-nodes" in option_names
    profile_cmd = command.commands["profile"]
    profile_options = {
        option
        for param in profile_cmd.params
        for option in getattr(param, "opts", [])
    }
    assert "--top-n" in profile_options
    assert "--metrics" in profile_options


def test_cli_registration_does_not_import_analyze_package(monkeypatch):
    original_import = builtins.__import__
    for module_name in list(sys.modules):
        if module_name == "sqlgraph.cli" or module_name.startswith("sqlgraph.analyze"):
            sys.modules.pop(module_name)

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sqlgraph.analyze" or name.startswith("sqlgraph.analyze."):
            raise AssertionError(f"unexpected analysis import: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    cli_module = importlib.import_module("sqlgraph.cli")
    command = get_command(cli_module.app)

    assert "analyze" in command.commands
    assert "profile" in command.commands
