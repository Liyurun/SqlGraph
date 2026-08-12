# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

# sqlgraph/cli.py
"""
SQLGraph 命令行接口（CLI）模块。

基于 Typer 框架实现，提供多个主要子命令：
  - build: 构建 SQL 血缘图并输出指定格式（CSV/GraphRAG/HTML/JSON）
  - stats: 仅解析 SQL 并输出统计信息，不生成输出文件
  - analyze: 对已生成 graph.json 运行离线治理分析并输出快照
  - profile: 运行离线治理分析并额外生成 dashboard.json 画像
  - playground: 启动本地页面，输入 SQL 后即时生成图谱
  - demo: 运行内置示例（广告素材管道）并自动打开浏览器

使用 Rich 库提供美观的终端输出，包括进度条、彩色表格和状态提示。

使用方式：
  python3 -m sqlgraph.cli --help
  python3 -m sqlgraph.cli build ./sql_files -o ./output --format html,csv
  python3 -m sqlgraph.cli stats ./sql_files
  python3 -m sqlgraph.cli playground
  python3 -m sqlgraph.cli demo
"""
from __future__ import annotations

from dataclasses import fields
import json
import os
import sys
import time
from typing import Any, Mapping, Optional

import typer
from rich.console import Console
from rich.table import Table

from sqlgraph.api import build_graph
from sqlgraph.serialize import to_csv, to_graphrag, to_json
from sqlgraph.visualize import to_html as vis_to_html
from sqlgraph.input.csv_schema import SchemaRegistry
from sqlgraph.utils.notebook import setup_notebook
from sqlgraph.utils.logging import log_info
from sqlgraph.playground import serve_playground

# 创建 Typer 应用实例，设置名称和帮助描述
app = typer.Typer(
    name="sqlgraph",
    help="SQL lineage graph construction tool - SQL 血缘图构建工具",
    add_completion=False,
)

# 创建 Rich 控制台实例，用于美化终端输出
console = Console()

_VALID_ANALYZE_METRICS = {
    "all",
    "inventory",
    "basic",
    "overview",
    "field_lineage",
    "lineage",
    "sql_complexity",
    "sql",
    "complexity",
    "topology",
    "impact",
    "communities",
    "community",
    "consistency",
    "similarity",
    "embedding",
    "embeddings",
    "motifs",
    "anomaly",
    "anomalies",
}


@app.command()
def build(
    input_path: str = typer.Argument(
        ...,
        help="SQL 文件、目录或 df.csv 路径。支持单个 .sql 文件、包含 SQL 文件的目录、"
             "table_name/code 格式的 df.csv，或直接传入 SQL 字符串（自动识别）。",
    ),
    output: str = typer.Option(
        "./sqlgraph_output",
        "-o",
        "--output",
        help="输出目录路径。所有生成的文件将保存在此目录下。",
    ),
    dialect: Optional[str] = typer.Option(
        None,
        "--dialect",
        help="SQL 方言，例如: spark, hive, presto, bigquery, mysql, postgres 等。"
             "不指定则自动检测。",
    ),
    format: str = typer.Option(
        "html",
        "--format",
        help="输出格式，多个格式用逗号分隔。可选值: csv, graphrag, html, json。"
             "例如: --format html,csv,json",
    ),
    view: str = typer.Option(
        "table",
        "--view",
        help="可视化初始视图模式（仅对 HTML 格式生效）。"
             "可选值: table（表级视图，默认）, column（字段级视图）, sql（SQL 依赖视图）。",
    ),
    theme: str = typer.Option(
        "light",
        "--theme",
        help="可视化主题（仅对 HTML 格式生效）。可选值: light（浅色主题，默认）, dark（深色主题）。",
    ),
    schema: Optional[str] = typer.Option(
        None,
        "--schema",
        help="表 Schema CSV 文件路径，用于字段消歧。"
             "CSV 格式要求: table_name,column_name,data_type[,description]",
    ),
    title: str = typer.Option(
        "SQL Lineage",
        "--title",
        help="HTML 可视化页面标题。",
    ),
    open_browser: bool = typer.Option(
        True,
        "--open/--no-open",
        help="构建完成后是否自动在浏览器中打开 HTML 可视化结果（默认自动打开）。",
    ),
):
    """构建 SQL 血缘图并输出指定格式

    解析输入的 SQL 文件/目录，构建完整的血缘关系图，然后根据 --format 参数
    输出为一种或多种格式。支持 CSV（节点和边列表）、GraphRAG（知识图谱 JSON）、
    HTML（交互式可视化）和 JSON（完整图结构）。

    示例:
        # 构建并输出 HTML 可视化（默认）
        sqlgraph build ./sql_queries

        # 输出多种格式，不自动打开浏览器
        sqlgraph build ./sql_queries -o ./output --format html,csv,json --no-open

        # 指定 Spark SQL 方言和 Schema 文件
        sqlgraph build ./sql_queries --dialect spark --schema ./schema.csv

        # 从 table_name/code 格式的 df.csv 构建
        sqlgraph build ./examples/df.csv --dialect spark --format csv,json
    """
    # 初始化 Notebook 环境兼容性
    setup_notebook()

    # 记录开始时间，用于计算耗时
    t0 = time.time()

    # 解析输出格式列表（支持逗号分隔的多格式）
    formats = [f.strip().lower() for f in format.split(",")]
    valid_formats = {"csv", "graphrag", "html", "json"}
    invalid_formats = [f for f in formats if f not in valid_formats]
    if invalid_formats:
        console.print(
            f"[red]✗[/red] 无效的输出格式: {', '.join(invalid_formats)}。"
            f"有效格式: {', '.join(sorted(valid_formats))}"
        )
        raise typer.Exit(1)

    # 使用 Rich 状态指示器显示构建进度
    with console.status("[bold green]Building lineage graph...") as status:
        # 调用高层 API 构建血缘图
        graph = build_graph(input_path, dialect=dialect, schema_path=schema)

    # 计算耗时并收集统计信息
    stats = graph.stats()
    stats["耗时"] = f"{time.time() - t0:.2f}s"

    # 使用 Rich Table 美观输出统计信息
    table = Table(title="构建完成", show_header=True, header_style="bold blue")
    table.add_column("指标", style="cyan", no_wrap=True)
    table.add_column("数值", style="magenta")
    for k, v in stats.items():
        table.add_row(str(k), str(v))
    console.print(table)

    # 确保输出目录存在
    os.makedirs(output, exist_ok=True)

    # 根据指定格式输出文件
    if "csv" in formats:
        # CSV 格式：输出 nodes.csv 和 edges.csv 到 csv 子目录
        csv_dir = os.path.join(output, "csv")
        to_csv(graph, csv_dir)
        console.print(f"[green]✓[/green] CSV 已输出: {csv_dir}")

    if "graphrag" in formats:
        # GraphRAG 格式：输出 GraphRAG schema v2 JSON payload
        gr_path = os.path.join(output, "graphrag.json")
        to_graphrag(graph, gr_path)
        console.print(f"[green]✓[/green] GraphRAG payload 已输出: {gr_path}")

    if "json" in formats:
        # JSON 格式：输出完整图结构 JSON
        j_path = os.path.join(output, "graph.json")
        to_json(graph, j_path)
        console.print(f"[green]✓[/green] JSON 已输出: {j_path}")

    if "html" in formats:
        # HTML 格式：输出交互式可视化 HTML 文件
        html_path = os.path.join(output, "lineage.html")
        vis_to_html(
            graph,
            output_path=html_path,
            view=view,
            theme=theme,
            title=title,
            auto_open=open_browser,
        )
        console.print(f"[green]✓[/green] 可视化 HTML 已输出: {html_path}")


@app.command()
def stats(
    input_path: str = typer.Argument(
        ...,
        help="SQL 文件或目录路径。",
    ),
    dialect: Optional[str] = typer.Option(
        None,
        "--dialect",
        help="SQL 方言，不指定则自动检测。",
    ),
    schema: Optional[str] = typer.Option(
        None,
        "--schema",
        help="表 Schema CSV 文件路径。",
    ),
):
    """仅解析并输出统计信息，不生成输出文件

    此命令用于快速检查 SQL 文件的解析结果和图构建统计，不会在磁盘上
    生成任何输出文件。适合用于快速验证 SQL 解析是否正确。

    统计信息包括：
      - SQL 语句数量
      - 表节点数量（包括源表和目标表）
      - 字段节点数量
      - 边数量
      - 各类边的详细计数

    示例:
        sqlgraph stats ./sql_queries
        sqlgraph stats ./sql_queries --dialect spark
    """
    # 初始化 Notebook 环境兼容性
    setup_notebook()

    # 构建图（使用 Rich 状态提示）
    with console.status("[bold green]Analyzing SQL files...") as status:
        graph = build_graph(input_path, dialect=dialect, schema_path=schema)

    # 获取统计信息并用 Rich Table 展示
    s = graph.stats()
    table = Table(title="SQL 血缘统计", show_header=True, header_style="bold blue")
    table.add_column("指标", style="cyan", no_wrap=True)
    table.add_column("数值", style="magenta")
    for k, v in s.items():
        table.add_row(str(k), str(v))
    console.print(table)


@app.command()
def playground(
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Playground 服务监听地址。",
    ),
    port: int = typer.Option(
        8765,
        "--port",
        help="Playground 服务端口。传 0 时自动寻找可用端口。",
    ),
    open_browser: bool = typer.Option(
        True,
        "--open/--no-open",
        help="启动后是否自动打开浏览器。",
    ),
):
    """启动本地 SQL Playground，可在页面中输入 SQL 并即时生成图谱"""
    serve_playground(host=host, port=port, open_browser=open_browser)


@app.command()
def serve(
    input_path: str = typer.Argument(
        ...,
        help="SQL 文件、目录或 df.csv 路径。启动时会解析并构建 JSONL 索引。",
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="服务监听地址。"),
    port: int = typer.Option(8770, "--port", help="服务端口。传 0 时自动寻找可用端口。"),
    dialect: Optional[str] = typer.Option(None, "--dialect", help="SQL 方言，不指定则自动检测。"),
    rebuild: bool = typer.Option(False, "--rebuild", help="强制重建索引，忽略缓存。"),
    index_dir: str = typer.Option(".sqlgraph_index", "--index-dir", help="索引缓存目录。"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="启动后是否自动打开浏览器。"),
):
    """启动本地血缘检索浏览器（检索 / 图谱查看 / 在线解析）"""
    from sqlgraph.serve import serve_explorer

    serve_explorer(
        input_path=input_path,
        host=host,
        port=port,
        dialect=dialect,
        rebuild=rebuild,
        index_dir=index_dir,
        open_browser=open_browser,
    )


@app.command("serve-graph")
def serve_graph(
    graph: str = typer.Argument(
        ...,
        help="已生成的 graph.json 路径。启动时只构建/复用 Explorer JSONL 索引，不重新解析 SQL。",
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="服务监听地址。"),
    port: int = typer.Option(8770, "--port", help="服务端口。传 0 时自动寻找可用端口。"),
    rebuild: bool = typer.Option(False, "--rebuild", help="强制重建索引，忽略缓存。"),
    index_dir: str = typer.Option(".sqlgraph_index", "--index-dir", help="索引缓存目录。"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="启动后是否自动打开浏览器。"),
):
    """从离线 graph.json 启动本地血缘检索浏览器"""
    from sqlgraph.serve import serve_graph_explorer

    serve_graph_explorer(
        graph_json_path=graph,
        host=host,
        port=port,
        rebuild=rebuild,
        index_dir=index_dir,
        open_browser=open_browser,
    )


@app.command("serve-index")
def serve_index(
    index: str = typer.Argument(
        ...,
        help="已预构建的 Explorer JSONL 索引目录，需包含 manifest.json、nodes.jsonl、edges.jsonl、sql.jsonl。",
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="服务监听地址。"),
    port: int = typer.Option(8770, "--port", help="服务端口。传 0 时自动寻找可用端口。"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="启动后是否自动打开浏览器。"),
):
    """从预构建 JSONL 索引目录启动本地血缘检索浏览器"""
    from sqlgraph.serve import serve_index_explorer

    serve_index_explorer(
        prepared_index_dir=index,
        host=host,
        port=port,
        open_browser=open_browser,
    )


@app.command("analyze")
def analyze(
    graph: str = typer.Argument(
        ...,
        help="已生成的 graph.json 路径，格式需包含 nodes 和 edges 列表。",
    ),
    output: str = typer.Option(
        "./sqlgraph_analysis",
        "-o",
        "--output",
        help="治理分析输出目录。将写入 manifest、summary、JSONL 和 CSV 快照。",
    ),
    config_file: Optional[str] = typer.Option(
        None,
        "--config",
        help="JSON 配置文件路径。字段与 AnalysisConfig/ResourceBudget 保持一致。",
    ),
    schema: Optional[str] = typer.Option(
        None,
        "--schema",
        help="外部 schema.csv 路径，用于资产覆盖率口径。",
    ),
    diagnostics: Optional[str] = typer.Option(
        None,
        "--diagnostics",
        help="解析诊断 JSON 文件路径，支持对象或对象数组。",
    ),
    metrics: Optional[str] = typer.Option(
        None,
        "--metrics",
        help="逗号分隔的指标集合，例如 basic,topology,impact。默认使用配置或 all。",
    ),
    cache_dir: Optional[str] = typer.Option(
        None,
        "--cache-dir",
        help="分析缓存目录。传入后会复用投影和快照缓存。",
    ),
    seed: Optional[int] = typer.Option(
        None,
        "--seed",
        help="随机算法种子，覆盖配置文件 random_seed。",
    ),
    precision: Optional[int] = typer.Option(
        None,
        "--precision",
        help="浮点输出精度，覆盖配置文件 float_precision。",
    ),
    community_backend: Optional[str] = typer.Option(
        None,
        "--community-backend",
        help="社区发现后端：label_propagation、louvain 或 leiden。",
    ),
    graph_backend: Optional[str] = typer.Option(
        None,
        "--graph-backend",
        help="图算法后端，例如 auto 或 networkx。",
    ),
    fail_fast: bool = typer.Option(
        False,
        "--fail-fast",
        help="非关键指标失败时立即失败，而不是记录 failed 后继续。",
    ),
    max_nodes: Optional[int] = typer.Option(
        None,
        "--max-nodes",
        help="资源预算：最大节点数。",
    ),
    max_edges: Optional[int] = typer.Option(
        None,
        "--max-edges",
        help="资源预算：最大边数。",
    ),
    max_memory_mb: Optional[int] = typer.Option(
        None,
        "--max-memory-mb",
        help="资源预算：最大内存 MB。",
    ),
    timeout_seconds: Optional[int] = typer.Option(
        None,
        "--timeout-seconds",
        help="资源预算：最长运行秒数。",
    ),
    exact_algorithm_max_nodes: Optional[int] = typer.Option(
        None,
        "--exact-algorithm-max-nodes",
        help="资源预算：精确算法最大节点数。",
    ),
    betweenness_samples: Optional[int] = typer.Option(
        None,
        "--betweenness-samples",
        help="资源预算：近似 Betweenness 采样数。",
    ),
    similarity_candidates_per_node: Optional[int] = typer.Option(
        None,
        "--similarity-candidates-per-node",
        help="资源预算：每个节点保留的相似候选数。",
    ),
    top_k_removal_simulation: Optional[int] = typer.Option(
        None,
        "--top-k-removal-simulation",
        help="资源预算：删除模拟 Top-K 候选数。",
    ),
):
    """运行离线治理分析快照

    输入为 `build --format json` 生成的 graph.json，输出治理分析 manifest、
    summary、表/字段/SQL/Transform 指标、违规、社区矩阵、相似候选、Motif 和异常分。

    示例:
        sqlgraph analyze ./sqlgraph_output/graph.json -o ./analysis --metrics basic,topology
        sqlgraph analyze ./graph.json --config ./analysis_config.json --cache-dir ./.analysis_cache
    """
    graph_path = os.path.abspath(graph)
    if not os.path.isfile(graph_path):
        console.print(f"[red]✗[/red] graph input file not found: {graph}")
        raise typer.Exit(2)
    if os.path.exists(output) and not os.path.isdir(output):
        console.print(f"[red]✗[/red] output path is not a directory: {output}")
        raise typer.Exit(2)

    budget_overrides = {
        "max_nodes": max_nodes,
        "max_edges": max_edges,
        "max_memory_mb": max_memory_mb,
        "timeout_seconds": timeout_seconds,
        "exact_algorithm_max_nodes": exact_algorithm_max_nodes,
        "betweenness_samples": betweenness_samples,
        "similarity_candidates_per_node": similarity_candidates_per_node,
        "top_k_removal_simulation": top_k_removal_simulation,
    }
    try:
        config = _build_analysis_config(
            config_file=config_file,
            metrics=metrics,
            seed=seed,
            precision=precision,
            community_backend=community_backend,
            graph_backend=graph_backend,
            fail_fast=fail_fast,
            budget_overrides={
                name: value
                for name, value in budget_overrides.items()
                if value is not None
            },
        )
        parse_diagnostics = _load_optional_json(diagnostics, "diagnostics")
        from sqlgraph.analyze.pipeline import run_governance_analysis

        with console.status("[bold green]Running governance analysis..."):
            snapshot = run_governance_analysis(
                graph_path,
                config=config,
                external_schema=schema,
                parse_diagnostics=parse_diagnostics,
                output_dir=output,
                cache_dir=cache_dir,
            )
    except (OSError, TypeError, ValueError) as exc:
        console.print(f"[red]✗[/red] invalid analyze input: {exc}")
        raise typer.Exit(2)
    except RuntimeError as exc:
        console.print(f"[red]✗[/red] governance analysis failed: {exc}")
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red]✗[/red] unexpected governance analysis failure: {exc}")
        raise typer.Exit(1)

    _print_analysis_summary(snapshot, output)


@app.command("profile")
def profile(
    graph: str = typer.Argument(
        ...,
        help="已生成的 graph.json 路径，格式需包含 nodes 和 edges 列表。",
    ),
    output: str = typer.Option(
        "./warehouse_profile",
        "-o",
        "--output",
        help="画像输出目录。将写入治理分析产物和 dashboard.json。",
    ),
    config_file: Optional[str] = typer.Option(
        None,
        "--config",
        help="JSON 配置文件路径。字段与 AnalysisConfig/ResourceBudget 保持一致。",
    ),
    schema: Optional[str] = typer.Option(
        None,
        "--schema",
        help="外部 schema.csv 路径，用于资产覆盖率口径。",
    ),
    diagnostics: Optional[str] = typer.Option(
        None,
        "--diagnostics",
        help="解析诊断 JSON 文件路径，支持对象或对象数组。",
    ),
    metrics: Optional[str] = typer.Option(
        None,
        "--metrics",
        help="逗号分隔的指标集合，例如 basic,topology,impact。默认使用配置或 all。",
    ),
    cache_dir: Optional[str] = typer.Option(
        None,
        "--cache-dir",
        help="分析缓存目录。传入后会复用投影和快照缓存。",
    ),
    seed: Optional[int] = typer.Option(
        None,
        "--seed",
        help="随机算法种子，覆盖配置文件 random_seed。",
    ),
    precision: Optional[int] = typer.Option(
        None,
        "--precision",
        help="浮点输出精度，覆盖配置文件 float_precision。",
    ),
    community_backend: Optional[str] = typer.Option(
        None,
        "--community-backend",
        help="社区发现后端：label_propagation、louvain 或 leiden。",
    ),
    graph_backend: Optional[str] = typer.Option(
        None,
        "--graph-backend",
        help="图算法后端，例如 auto 或 networkx。",
    ),
    fail_fast: bool = typer.Option(
        False,
        "--fail-fast",
        help="非关键指标失败时立即失败，而不是记录 failed 后继续。",
    ),
    max_nodes: Optional[int] = typer.Option(
        None,
        "--max-nodes",
        help="资源预算：最大节点数。",
    ),
    max_edges: Optional[int] = typer.Option(
        None,
        "--max-edges",
        help="资源预算：最大边数。",
    ),
    max_memory_mb: Optional[int] = typer.Option(
        None,
        "--max-memory-mb",
        help="资源预算：最大内存 MB。",
    ),
    timeout_seconds: Optional[int] = typer.Option(
        None,
        "--timeout-seconds",
        help="资源预算：最长运行秒数。",
    ),
    exact_algorithm_max_nodes: Optional[int] = typer.Option(
        None,
        "--exact-algorithm-max-nodes",
        help="资源预算：精确算法最大节点数。",
    ),
    betweenness_samples: Optional[int] = typer.Option(
        None,
        "--betweenness-samples",
        help="资源预算：近似 Betweenness 采样数。",
    ),
    similarity_candidates_per_node: Optional[int] = typer.Option(
        None,
        "--similarity-candidates-per-node",
        help="资源预算：每个节点保留的相似候选数。",
    ),
    top_k_removal_simulation: Optional[int] = typer.Option(
        None,
        "--top-k-removal-simulation",
        help="资源预算：删除模拟 Top-K 候选数。",
    ),
    top_n: int = typer.Option(
        20,
        "--top-n",
        help="dashboard.json 中每类列表保留的 Top-N 数量。",
    ),
):
    """运行离线数仓治理画像并生成 dashboard.json。

    `profile` 是 `analyze` 的展示层封装：它复用治理分析管线写出标准快照，
    再生成供 Explorer `/stats` 读取的紧凑 dashboard.json。
    """
    graph_path = os.path.abspath(graph)
    if not os.path.isfile(graph_path):
        console.print(f"[red]✗[/red] graph input file not found: {graph}")
        raise typer.Exit(2)
    if os.path.exists(output) and not os.path.isdir(output):
        console.print(f"[red]✗[/red] output path is not a directory: {output}")
        raise typer.Exit(2)
    if top_n <= 0:
        console.print("[red]✗[/red] --top-n must be greater than zero")
        raise typer.Exit(2)

    budget_overrides = {
        "max_nodes": max_nodes,
        "max_edges": max_edges,
        "max_memory_mb": max_memory_mb,
        "timeout_seconds": timeout_seconds,
        "exact_algorithm_max_nodes": exact_algorithm_max_nodes,
        "betweenness_samples": betweenness_samples,
        "similarity_candidates_per_node": similarity_candidates_per_node,
        "top_k_removal_simulation": top_k_removal_simulation,
    }
    try:
        config = _build_analysis_config(
            config_file=config_file,
            metrics=metrics,
            seed=seed,
            precision=precision,
            community_backend=community_backend,
            graph_backend=graph_backend,
            fail_fast=fail_fast,
            budget_overrides={
                name: value
                for name, value in budget_overrides.items()
                if value is not None
            },
        )
        parse_diagnostics = _load_optional_json(diagnostics, "diagnostics")
        from sqlgraph.analyze.pipeline import run_governance_analysis
        from sqlgraph.analyze.profile import write_profile_output

        with console.status("[bold green]Running warehouse profile..."):
            snapshot = run_governance_analysis(
                graph_path,
                config=config,
                external_schema=schema,
                parse_diagnostics=parse_diagnostics,
                output_dir=output,
                cache_dir=cache_dir,
            )
            written = write_profile_output(snapshot, output, top_n=top_n)
    except (OSError, TypeError, ValueError) as exc:
        console.print(f"[red]✗[/red] invalid profile input: {exc}")
        raise typer.Exit(2)
    except RuntimeError as exc:
        console.print(f"[red]✗[/red] warehouse profile failed: {exc}")
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red]✗[/red] unexpected warehouse profile failure: {exc}")
        raise typer.Exit(1)

    _print_analysis_summary(snapshot, output)
    console.print(f"[green]✓[/green] 画像生成完成: {written['dashboard']}")


@app.command()
def demo(
    output: str = typer.Option(
        "./demo_output",
        "-o",
        "--output",
        help="示例输出目录。",
    ),
    theme: str = typer.Option(
        "light",
        "--theme",
        help="可视化主题，可选 light/dark。",
    ),
):
    """运行内置示例并自动打开浏览器

    内置示例为广告素材管道（ads_pipeline），包含多条 Spark SQL 语句，
    展示了从源表经过多层 ETL 到最终应用表的完整血缘链路。

    示例文件位置：examples/ads_pipeline/
      - 多个 .sql 文件构成完整的 ETL 流程
      - schema.csv 定义了所有表的字段结构

    运行后将自动生成 HTML 可视化并在浏览器中打开。

    示例:
        sqlgraph demo
        sqlgraph demo --theme light -o ./my_demo
    """
    # 初始化 Notebook 环境兼容性
    setup_notebook()

    # 获取内置示例目录路径
    demo_dir = _get_demo_dir()
    if not demo_dir:
        console.print("[red]✗[/red] 示例目录 examples/ads_pipeline/ 未找到")
        console.print("请确保在项目根目录下运行此命令，或 examples/ads_pipeline/ 目录存在。")
        raise typer.Exit(1)

    console.print(f"[bold blue]运行内置示例: {demo_dir}")

    # 检查是否存在 schema.csv 文件
    schema_path = os.path.join(demo_dir, "schema.csv")
    if not os.path.isfile(schema_path):
        schema_path = None
        console.print("[yellow]![/yellow] 未找到 schema.csv，将不使用 Schema 消歧")

    # 调用 build 命令执行构建
    build(
        input_path=demo_dir,
        output=output,
        dialect="spark",
        format="html",
        view="table",
        theme=theme,
        schema=schema_path,
        title="SqlGraph",
        open_browser=True,
    )


def _get_demo_dir() -> Optional[str]:
    """获取内置示例目录路径

    按优先级搜索以下位置：
      1. 相对于当前文件的 ../examples/ads_pipeline（开发模式）
      2. 当前工作目录下的 examples/ads_pipeline（已安装模式）

    Returns:
        示例目录的绝对路径，如果未找到则返回 None
    """
    # 可能的候选路径
    candidates = [
        # 相对于 cli.py 的上级目录（包内路径）
        os.path.join(os.path.dirname(__file__), "..", "examples", "ads_pipeline"),
        # 当前工作目录下
        os.path.join(os.getcwd(), "examples", "ads_pipeline"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return os.path.abspath(c)
    return None


def _build_analysis_config(
    *,
    config_file: Optional[str],
    metrics: Optional[str],
    seed: Optional[int],
    precision: Optional[int],
    community_backend: Optional[str],
    graph_backend: Optional[str],
    fail_fast: bool,
    budget_overrides: Mapping[str, int],
):
    from sqlgraph.analyze.config import AnalysisConfig, ResourceBudget

    raw_config: dict[str, Any] = {}
    if config_file is not None:
        raw_config = _load_json_object(config_file, "config")

    config_fields = {field.name for field in fields(AnalysisConfig)}
    budget_fields = {field.name for field in fields(ResourceBudget)}
    resource_payload = raw_config.pop("resource_budget", {})
    if resource_payload is None:
        resource_payload = {}
    if not isinstance(resource_payload, Mapping):
        raise ValueError("resource_budget must be a JSON object")

    unknown_config = sorted(set(raw_config) - config_fields)
    if unknown_config:
        raise ValueError(f"unknown AnalysisConfig keys: {', '.join(unknown_config)}")
    unknown_budget = sorted(set(resource_payload) - budget_fields)
    if unknown_budget:
        raise ValueError(f"unknown ResourceBudget keys: {', '.join(unknown_budget)}")
    unknown_budget_overrides = sorted(set(budget_overrides) - budget_fields)
    if unknown_budget_overrides:
        raise ValueError(
            f"unknown ResourceBudget overrides: {', '.join(unknown_budget_overrides)}"
        )

    raw_config = _normalize_analysis_config_payload(raw_config)
    if metrics is not None:
        raw_config["metrics"] = _parse_analyze_metrics(metrics)
    elif "metrics" in raw_config:
        raw_config["metrics"] = _validate_metric_names(
            tuple(str(item).strip().lower() for item in raw_config["metrics"])
        )
    if seed is not None:
        raw_config["random_seed"] = seed
    if precision is not None:
        raw_config["float_precision"] = precision
    if community_backend is not None:
        raw_config["community_backend"] = community_backend
    if graph_backend is not None:
        raw_config["graph_backend"] = graph_backend
    if fail_fast:
        raw_config["allow_degraded"] = False

    budget_data = dict(resource_payload)
    budget_data.update(budget_overrides)
    return AnalysisConfig(
        **raw_config,
        resource_budget=ResourceBudget(**budget_data),
    )


def _normalize_analysis_config_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if "metrics" in normalized:
        metrics_value = normalized["metrics"]
        if isinstance(metrics_value, str):
            normalized["metrics"] = _parse_analyze_metrics(metrics_value)
        elif isinstance(metrics_value, list):
            normalized["metrics"] = tuple(str(item) for item in metrics_value)
        else:
            raise ValueError("metrics must be a string or array of strings")
    if "algorithm_versions" in normalized:
        versions = normalized["algorithm_versions"]
        if isinstance(versions, Mapping):
            normalized["algorithm_versions"] = tuple(
                (str(name), str(version))
                for name, version in sorted(versions.items())
            )
        elif isinstance(versions, list):
            normalized["algorithm_versions"] = tuple(
                _tuple_of_strings(item, "algorithm_versions", 2)
                for item in versions
            )
        else:
            raise ValueError("algorithm_versions must be an object or array")
    for name, width in (
        ("layer_patterns", 2),
        ("layer_violation_rules", 4),
    ):
        if name in normalized:
            value = normalized[name]
            if not isinstance(value, list):
                raise ValueError(f"{name} must be an array")
            normalized[name] = tuple(
                _tuple_of_strings(item, name, width)
                for item in value
            )
    if "metric_candidate_patterns" in normalized:
        value = normalized["metric_candidate_patterns"]
        if not isinstance(value, list):
            raise ValueError("metric_candidate_patterns must be an array")
        normalized["metric_candidate_patterns"] = tuple(str(item) for item in value)
    return normalized


def _tuple_of_strings(value: Any, field_name: str, width: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != width:
        raise ValueError(f"{field_name} entries must contain {width} values")
    return tuple(str(item) for item in value)


def _parse_analyze_metrics(raw: str) -> tuple[str, ...]:
    metrics = tuple(
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    )
    return _validate_metric_names(metrics)


def _validate_metric_names(metrics: tuple[str, ...]) -> tuple[str, ...]:
    if not metrics:
        raise ValueError("metrics must contain at least one metric name")
    invalid = sorted(set(metrics) - _VALID_ANALYZE_METRICS)
    if invalid:
        raise ValueError(
            f"unknown metrics: {', '.join(invalid)}; "
            f"valid metrics: {', '.join(sorted(_VALID_ANALYZE_METRICS))}"
        )
    return metrics


def _load_json_object(path: str, label: str) -> dict[str, Any]:
    payload = _load_optional_json(path, label)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _load_optional_json(path: Optional[str], label: str) -> Any:
    if path is None:
        return None
    if not os.path.isfile(path):
        raise ValueError(f"{label} file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return json.load(stream)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc


def _print_analysis_summary(snapshot, output: str) -> None:
    manifest = snapshot.manifest
    table = Table(title="治理分析完成", show_header=True, header_style="bold blue")
    table.add_column("状态", style="cyan", no_wrap=True)
    table.add_column("数量", style="magenta", no_wrap=True)
    table.add_column("指标", style="white")
    rows = (
        ("success", manifest.completed_metrics),
        ("degraded", manifest.degraded_metrics),
        ("skipped", manifest.skipped_metrics),
        ("failed", manifest.failed_metrics),
    )
    for status, names in rows:
        table.add_row(status, str(len(names)), _format_metric_names(names))
    console.print(table)
    console.print(f"[green]✓[/green] 治理分析输出目录: {output}")


def _format_metric_names(names) -> str:
    return ", ".join(str(name) for name in names) if names else "-"


def main():
    """CLI 主入口函数"""
    app()


if __name__ == "__main__":
    main()
