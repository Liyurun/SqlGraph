# SqlGraph

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![CI](https://github.com/Liyurun/SqlGraph/actions/workflows/ci.yml/badge.svg)](https://github.com/Liyurun/SqlGraph/actions/workflows/ci.yml)
[![SQLGlot](https://img.shields.io/badge/parser-SQLGlot-green.svg)](https://github.com/tobymao/sqlglot)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

**Turn your data-warehouse SQL into an interactive knowledge graph.**

SqlGraph statically parses a folder of SQL and builds a property graph that captures not just *table/column lineage* but the **transformation logic** itself. Identical logic across different SQL files collapses onto **one shared node** via content fingerprinting — so you can see, at a glance, where the same computation is reused across your warehouse.

English | [简体中文](README.zh-CN.md)

<p align="center">
  <img src="assets/sqlgraph-light.png" alt="SqlGraph table-level lineage (light theme)" width="49%">
  <img src="assets/sqlgraph-dark.png" alt="SqlGraph table-level lineage (dark theme)" width="49%">
</p>

---

## Why SqlGraph?

Most lineage tools stop at "table A feeds table B". SqlGraph goes further:

- **Logic as first-class nodes.** A composite expression like `ROUND(SUM(clicks) / COUNT(*), 4)` becomes a single transformation node, wired to the exact physical columns it reads and the output column it produces.
- **Shared logic is deduplicated.** The same expression in two different SQL files resolves to the **same** node (identical 128-bit content fingerprint). Commutative operators are normalized, so `a + b` and `b + a` converge.
- **Physically precise.** `SUM(impression.ad_id)` and `SUM(click.ad_id)` are *different* nodes — identity is bound to resolved physical columns, not textual similarity.
- **Deterministic.** The same SQL always produces the same graph and the same node IDs, so diffs are meaningful and results are reproducible.

The result: **the graph fully reflects the SQL execution logic, and the SQL logic fully generates the graph.**

## Features

| | |
|---|---|
| **Multi-dialect parsing** | Spark / Hive / Presto / BigQuery / MySQL / Postgres … (powered by [SQLGlot](https://github.com/tobymao/sqlglot)) |
| **Rich SQL coverage** | CTEs, sub-queries, `UNION ALL`, `JOIN`s, window functions, `CASE WHEN`, `CAST`, aggregates |
| **Content-fingerprint DAG** | Merkle-style dedup of transformation logic across the whole codebase |
| **Multiple outputs** | Interactive HTML, CSV (nodes/edges), GraphRAG JSON, plain JSON, NetworkX |
| **Interactive visualization** | Cytoscape.js + ELK layered layout, light/dark themes, search, node-size control, PNG/SVG export |
| **Scales** | 96/128-bit fingerprints for warehouses with millions of columns; large graphs render the top-1000 nodes first and load more on search |
| **Simple API + CLI** | One function or one command to go from SQL folder to graph |

## Installation

```bash
# from source (recommended while pre-release)
git clone https://github.com/Liyurun/SqlGraph.git
cd SqlGraph
pip install -e .

# or, once published
pip install sqlgraph-lineage
```

Requires Python 3.9+.

## Quick start

### Python API

```python
from sqlgraph import build_graph, to_html

# Parse a folder of SQL and build the graph
graph = build_graph("examples/ads_pipeline/", dialect="spark",
                    schema_path="examples/ads_pipeline/schema.csv")

print(graph.stats())
# {'sql_count': 11, 'table_count': 26, 'column_count': 204,
#  'transform_count': 56, 'edge_count': 552, 'node_count': 297}

# Render an interactive HTML visualization
to_html(graph, output_path="lineage.html", theme="dark", auto_open=True)
```

### CLI

```bash
# Run the built-in AdTech demo and open it in your browser
sqlgraph demo

# Build from your own SQL, emit multiple formats
sqlgraph build ./sql --dialect spark --schema ./schema.csv \
  --format html,csv,json -o ./output

# Just print stats, no files written
sqlgraph stats ./sql --dialect spark
```

## The demo

The repository ships with a complete, realistic **AdTech ETL pipeline** under
[`examples/ads_pipeline/`](examples/ads_pipeline/) — 11 Spark SQL files flowing from raw
ODS logs through staging, DWD, DWS and ADS layers, including multi-CTE joins, `UNION ALL`
funnels and multi-window-function rollups.

Parsed, it produces:

| Metric | Count |
|---|---:|
| SQL files | 11 |
| Tables | 26 |
| Columns | 204 |
| Transformation nodes | 56 |
| Edges | 552 |
| **Total nodes** | **297** |

Run it yourself:

```bash
python examples/ads_pipeline/run_demo.py
```

Switch the view mode to **字段级详情 / column-level** to explore the full expression DAG:

<p align="center">
  <img src="assets/sqlgraph-dark-column.png" alt="SqlGraph column-level expression DAG" width="80%">
</p>

## How it works

```
 SQL files ──▶ Input ──▶ Parser ──▶ Builder ──▶ Model ──▶ Serialize / Visualize
              (source)  (SQLGlot)   (fusion)  (PropertyGraph)   (HTML/CSV/JSON…)
```

1. **Input** — discover SQL from files, directories, strings, or DataFrames; optionally load a `schema.csv` for column disambiguation.
2. **Parser** — SQLGlot builds the AST; a `ColumnResolver` binds every column to a physical `table.column`. The [expression DAG module](sqlgraph/parser/expr_dag.py) turns each output expression into a fingerprinted logic node.
3. **Builder** — the [graph builder](sqlgraph/builder/graph_builder.py) materializes tables, columns and transformation nodes, deduplicates shared logic, and fuses cross-SQL table lineage.
4. **Model** — an in-memory `PropertyGraph` of typed nodes (SQL / Table / Column / Transform) and edges (`reads_from`, `writes_to`, `contains`, `compute_dependency`, `produces`, `table_lineage`, `has_column`).
5. **Serialize / Visualize** — export to CSV, GraphRAG JSON, plain JSON, NetworkX, or an interactive Cytoscape.js HTML page.

See [docs/architecture.md](docs/architecture.md) for the full design.

## Project layout

```
sqlgraph/
├── input/       # SQL sources, CSV schema registry, DataFrame adapter
├── parser/      # SQLGlot-based parsing + expression fingerprint DAG
├── builder/     # PropertyGraph construction & cross-SQL lineage fusion
├── model/       # nodes, edges, PropertyGraph
├── serialize/   # csv / graphrag / json / networkx exporters
├── visualize/   # Cytoscape.js HTML renderer (ELK layout, themes)
├── api.py       # build_graph() high-level entry
└── cli.py       # Typer CLI (build / stats / demo)
examples/ads_pipeline/   # 11-file AdTech demo + schema.csv
tests/                   # unit + integration tests
```

## Development

```bash
pip install -e ".[all]"
pytest            # run the test suite
```

## Contributing

Issues and PRs are welcome. If SqlGraph is useful to you, a ⭐ helps others discover it.

## License

[Apache 2.0](LICENSE)
