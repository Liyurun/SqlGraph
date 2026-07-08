# Architecture

SqlGraph is a layered pipeline. Each stage has a single responsibility and a
clean boundary, so you can swap or extend any layer independently.

```
 SQL files ──▶ Input ──▶ Parser ──▶ Builder ──▶ Model ──▶ Serialize / Visualize
              (source)  (SQLGlot)   (fusion)  (PropertyGraph)   (HTML/CSV/JSON…)
```

## 1. Input (`sqlgraph/input`)

- **`SqlSource`** discovers SQL from a single file, a directory of `.sql` files,
  a raw SQL string, a list of any of those, or a pandas DataFrame. `from_any()`
  auto-detects the input type.
- **`SchemaRegistry`** loads an optional `schema.csv`
  (`table_name,column_name,data_type[,description]`). Schema information lets the
  parser resolve ambiguous columns to the correct physical table.

## 2. Parser (`sqlgraph/parser`)

- **`SqlParser`** wraps [SQLGlot](https://github.com/tobymao/sqlglot). It parses
  each statement into an AST and extracts source tables, target tables, CTEs and
  output columns. It handles `SELECT` / `INSERT`, CTEs, sub-queries, `UNION ALL`,
  `JOIN`s and window functions.
- **`ColumnResolver`** binds every `exp.Column` to a physical `table.column`,
  using the query's source tables (CTE-inclusive) and the schema registry to
  disambiguate. Unresolvable columns fall back to `UNKNOWN.col`.
- **`expr_dag.decompose()`** turns each non-passthrough output expression into a
  single **fingerprinted logic node**:
  - all column references inside the expression are replaced with their resolved
    physical-column strings;
  - commutative operators (`+ * AND OR`) have their operands sorted, so
    `a + b` and `b + a` produce the same canonical form;
  - the canonical SQL string is hashed (SHA1, 128-bit) into the fingerprint;
  - every physical column the expression reads is recorded as a dependency.

  This is what makes identical logic across different SQL files collapse onto one
  node. A whole composite expression such as `ROUND(SUM(clicks)/COUNT(*), 4)` is
  **one** node — it is not decomposed into sub-nodes.

## 3. Builder (`sqlgraph/builder`)

- **`GraphBuilder`** materializes the graph from parse results:
  - tables and columns get **deterministic IDs** (96-bit SHA1 of their content
    key) so the same entity is stable across files and runs;
  - transformation nodes are deduplicated by fingerprint (`_ensure_expr_node`);
  - for each output column it adds `contains` (SQL→expr),
    `compute_dependency` (physical col→expr) and `produces` (expr→output col)
    edges; passthrough columns get a direct `compute_dependency` col→col edge.
- **Cross-SQL lineage fusion** links `source_table → target_table`
  (`table_lineage`) across statements, skipping CTEs.

## 4. Model (`sqlgraph/model`)

An in-memory **`PropertyGraph`** of typed nodes and edges.

| Node type | Meaning |
|---|---|
| `sql` | a SQL statement / file |
| `table` | a physical table or CTE |
| `column` | a table column |
| `transform` | a fingerprinted computation (expression node) |

| Edge type | Meaning |
|---|---|
| `reads_from` | SQL reads a source table |
| `writes_to` | SQL writes a target table |
| `has_column` | table → its column |
| `contains` | SQL → a transformation it defines |
| `compute_dependency` | physical column → transformation that consumes it |
| `produces` | transformation → output column |
| `table_lineage` | source table → target table (cross-SQL) |

## 5. Serialize / Visualize

- **`serialize`** exports the graph to CSV (`nodes.csv` / `edges.csv`),
  GraphRAG-schema JSON, plain JSON, or a NetworkX `DiGraph`.
- **`visualize.to_html`** renders an interactive Cytoscape.js page: ELK layered
  layout (with Dagre fallback), light/dark themes, node-type filters,
  view modes (table / lineage / column), search, node-size control and PNG/SVG
  export. Large graphs render the top-1000 nodes by degree first and load more
  on search.

## Design principles

- **Determinism** — same SQL ⇒ same graph ⇒ same node IDs. Diffs are meaningful.
- **Physical precision** — node identity binds to resolved physical columns, not
  text, so lookalike expressions on different columns stay distinct.
- **Scale** — 96/128-bit fingerprints keep collisions negligible even for
  warehouses with millions of columns.
