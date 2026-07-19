# SqlGraph

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![SQLGlot](https://img.shields.io/badge/parser-SQLGlot-green.svg)](https://github.com/tobymao/sqlglot)

> ## 🚧 This repository is being restructured
>
> The source code has been **temporarily removed** while SqlGraph is prepared
> for release under **ByteDance's open-source organization**.
>
> The full implementation will be published here again once the migration is
> complete. Thanks for your patience — please check back later.

English | [简体中文](README.zh-CN.md)

---

**A SQL-to-Knowledge-Graph engine for modern data warehouses.**

SqlGraph turns scattered warehouse SQL into an interactive knowledge graph of
tables, columns, SQL statements, and reusable transformation logic. It goes
beyond traditional lineage tools: every SQL expression is fingerprinted and
merged only when the output field semantics match, so reused business logic is
visible without collapsing distinct metric aliases.

Use SqlGraph to discover duplicated metrics, audit transformation logic, explain
data flows, and turn your SQL assets into graph-ready knowledge for GraphRAG.

## What SqlGraph does

- **Expression-level knowledge graph** — SQL files, tables, columns, and
  transformation logic are all first-class graph nodes.
- **Reusable business logic detection** — identical expressions share a 128-bit
  content fingerprint, and Transform nodes merge by
  `expression fingerprint + output field name`.
- **Column-accurate dependencies** — each transformation node links to the exact
  physical columns it reads and the output columns it produces.
- **Graph-ready outputs** — export to HTML, CSV, JSON, GraphRAG payloads, and
  NetworkX for downstream analysis and AI workflows.

## Status

The code is currently under restructuring for open-source release within
ByteDance. Documentation, installation instructions, and examples will return
alongside the republished source.

## License

[Apache 2.0](LICENSE)
