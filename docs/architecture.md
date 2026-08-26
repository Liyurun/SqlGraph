# Architecture

SqlGraph is a layered pipeline. Each stage has a single responsibility and a
clean boundary, so you can swap or extend any layer independently.

```
 SQL files ──▶ Input ──▶ Parser ──▶ Builder ──▶ Model ──▶ Serialize / Visualize
              (source)  (SQLGlot)   (fusion)  (PropertyGraph)   (HTML/CSV/JSON…)
```

## 1. Input (`sqlgraph/input`)

- **`SqlSource`** discovers SQL from a single file, a directory of `.sql` files,
  a raw SQL string, a list of any of those, or a `table_name,code` CSV export.
  `from_any()` auto-detects the input type.
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
- **`expr_dag.decompose()`** preserves each non-passthrough output expression as
  a stable root node, while **`decompose_operands()`** records nested operators
  as a child-to-parent operand DAG:
  - all column references inside the expression are replaced with their resolved
    physical-column strings;
  - SQLGlot serializes the rewritten expression with `normalize=True`, giving a
    conservative canonical SQL string without algebraic equivalence inference;
  - the canonical SQL string produces a conservative 128-bit logic fingerprint;
  - every physical column the expression reads is recorded as a dependency;
  - nested functions and arithmetic operators are connected with
    `expr_operand` edges without changing the root fingerprint.

  This fingerprint identifies identical physical-column-bound expression shapes
  across different SQL files. It intentionally does not treat `a + b` and
  `b + a` as equivalent. The builder combines the fingerprint with the output
  field name to decide Transform identity, so identical logic only collapses
  when it produces the same downstream field. A composite expression such as
  `ROUND(SUM(clicks)/COUNT(*), 4)` therefore has one stable output root plus
  inspectable nested operand nodes.

## 3. Builder (`sqlgraph/builder`)

- **`GraphBuilder`** materializes the graph from parse results:
  - graph nodes and edges use deterministic `id-v2` identities derived from
    SHA256 semantic keys, so the same entity is stable across files and runs;
  - transformation nodes are deduplicated by `expression fingerprint + output
    field name` (`_ensure_expr_node`);
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
| `expr_operand` | nested transformation → parent transformation |
| `produces` | transformation → output column |
| `table_lineage` | source table → target table (cross-SQL) |

## 5. Serialize / Visualize

- **`serialize`** exports the graph to CSV (`nodes.csv` / `edges.csv`),
  GraphRAG-schema JSON, plain JSON, or a NetworkX `DiGraph`.
- **`visualize.to_html`** renders an interactive Cytoscape.js page: layered
  layouts, light/dark themes, node-type filters,
  view modes (table / lineage / column), search, node-size control and PNG/SVG
  export. Large graphs render the top-1000 nodes by degree first and load more
  on search.

## Design principles

- **Determinism** — same SQL ⇒ same graph ⇒ the same SHA256-derived `id-v2`
  node and edge IDs. Diffs are meaningful.
- **Physical precision** — node identity binds to resolved physical columns, not
  text, so lookalike expressions on different columns stay distinct.
- **Scale** — 96/128-bit truncated identities keep collisions negligible for
  the reference warehouse scale, with collision detection during construction.

## Governance reference pipeline

The governance modules build on the graph without coupling the compiler to an
execution environment:

```text
Baseline -> HeteroGraph/TableGraph -> Evidence/Grounding -> Autonomy
         -> Action Adapter -> Independent Verification -> Audit Replay
```

- `baseline` identifies the effective input and discloses missing dependencies.
- `evidence` collects an intent-bound, versioned subgraph with coverage duties.
- `graphrag` rejects assertions with missing, stale, or out-of-scope citations.
- `autonomy` accepts authorization only from an injected verifier before scoring.
- `actions` derives reversibility evidence from isolated file and DuckDB probes,
  then provides idempotent execution with verified rollback.
- `verification` compares actual code, rebuilds structure, and checks runtime effects.
- `audit` appends hash-chained events; `reasoning` orchestrates the seven steps.

No analysis score directly authorizes an action. The action and verification
adapters are explicit seams for production integrations.
