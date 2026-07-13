# SqlGraph

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![CI](https://github.com/Liyurun/SqlGraph/actions/workflows/ci.yml/badge.svg)](https://github.com/Liyurun/SqlGraph/actions/workflows/ci.yml)
[![SQLGlot](https://img.shields.io/badge/parser-SQLGlot-green.svg)](https://github.com/tobymao/sqlglot)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

**把数据仓库 SQL 加工成一张可交互的知识图谱。**

SqlGraph 通过静态解析一整个目录的 SQL，构建出一张属性图。它不仅刻画 *表/字段血缘*，更把 **SQL 语句与加工逻辑本身** 建模为图节点。跨 SQL 的相同逻辑会通过内容指纹识别，并且只有在输出字段语义一致时才会收敛 —— 让你一眼看清仓库里哪些计算被重复使用，同时避免误合并不同指标别名。

[English](README.md) | 简体中文

<p align="center">
  <img src="assets/sqlgraph-light.png" alt="SqlGraph 表级血缘（浅色主题）" width="49%">
  <img src="assets/sqlgraph-dark.png" alt="SqlGraph 表级血缘（深色主题）" width="49%">
</p>

---

## 为什么用 SqlGraph？

大多数血缘工具止步于"表 A 流向表 B"。SqlGraph 更进一步：

- **逻辑即节点。** 像 `ROUND(SUM(clicks) / COUNT(*), 4)` 这样的复合表达式会成为**一个**转换节点，精确连接它读取的物理列和产出的输出列。
- **相同逻辑自动去重。** Transform 节点按 `表达式指纹 + 输出字段名` 合并：`SUM(clicks) AS clicks` 的重复定义会收敛，但 `SUM(clicks) AS total_clicks` 会保留为独立节点。交换律算子被归一化，因此 `a + b` 与 `b + a` 收敛。
- **物理列精确。** `SUM(impression.ad_id)` 与 `SUM(click.ad_id)` 是*不同*节点 —— 身份绑定到解析出的物理列，而非文本相似度。
- **确定性。** 同样的 SQL 永远生成同样的图和同样的节点 ID，diff 有意义、结果可复现。

最终效果：**图完全反映 SQL 执行逻辑，SQL 执行逻辑也能完全生成这张图。**

## 特性

| | |
|---|---|
| **多方言解析** | Spark / Hive / Presto / BigQuery / MySQL / Postgres …（基于 [SQLGlot](https://github.com/tobymao/sqlglot)） |
| **丰富 SQL 覆盖** | CTE、子查询、`UNION ALL`、`JOIN`、窗口函数、`CASE WHEN`、`CAST`、聚合函数 |
| **内容指纹 DAG** | Merkle 式加工逻辑识别，并按输出字段名进行安全合并 |
| **多种输出** | 交互式 HTML、CSV（节点/边）、GraphRAG JSON、纯 JSON、NetworkX |
| **交互式可视化** | Cytoscape.js 分层布局，浅色/深色主题、搜索、节点大小调节、PNG/SVG 导出，以及本地 SQL Playground |
| **可扩展规模** | 96/128-bit 指纹应对百万级字段仓库；大图默认先渲染度数最高的 1000 个节点，搜索时按需加载 |
| **简洁 API + CLI** | 一个函数或一条命令，从 SQL 目录到图谱 |

## 安装

```bash
# 源码安装（预发布阶段推荐）
git clone https://github.com/Liyurun/SqlGraph.git
cd SqlGraph
pip install -e .

# 或发布后直接安装
pip install sqlgraph-lineage
```

需要 Python 3.9+。

## 快速开始

### Python API

```python
from sqlgraph import build_graph, to_html

# 解析一个 SQL 目录并构建图
graph = build_graph("examples/ads_pipeline/", dialect="spark",
                    schema_path="examples/ads_pipeline/schema.csv")

print(graph.stats())
# {'sql_count': 11, 'table_count': 26, 'column_count': 204,
#  'transform_count': 56, 'edge_count': 552, 'node_count': 297}

# 生成交互式 HTML 可视化
to_html(graph, output_path="lineage.html", theme="dark", auto_open=True)
```

### 命令行

```bash
# 运行内置 AdTech 示例并在浏览器打开
sqlgraph demo

# 从你自己的 SQL 构建，输出多种格式
sqlgraph build ./sql --dialect spark --schema ./schema.csv \
  --format html,csv,json -o ./output

# 从 table_name/code CSV 示例构建
sqlgraph build examples/df_sample.csv --dialect spark --format html,json

# 启动本地 SQL Playground
sqlgraph playground

# 仅打印统计信息，不写文件
sqlgraph stats ./sql --dialect spark
```

## 示例

仓库自带一套完整、真实的 **AdTech ETL 流水线**，位于
[`examples/ads_pipeline/`](examples/ads_pipeline/) —— 11 个 Spark SQL 文件，从原始 ODS
日志经过 staging、DWD、DWS、ADS 各层，包含多 CTE JOIN、`UNION ALL` 漏斗以及多窗口函数汇总。

解析后产出：

| 指标 | 数量 |
|---|---:|
| SQL 文件 | 11 |
| 表 | 26 |
| 字段 | 204 |
| 转换节点 | 56 |
| 边 | 552 |
| **节点总数** | **297** |

自己跑一遍：

```bash
python examples/ads_pipeline/run_demo.py
```

把视图模式切到 **字段级详情**，即可探索完整的表达式 DAG：

<p align="center">
  <img src="assets/sqlgraph-dark-column.png" alt="SqlGraph 字段级表达式 DAG" width="80%">
</p>

## 工作原理

```
 SQL 文件 ──▶ Input ──▶ Parser ──▶ Builder ──▶ Model ──▶ Serialize / Visualize
              (输入源)  (SQLGlot)   (融合)   (PropertyGraph)   (HTML/CSV/JSON…)
```

1. **Input** —— 从文件、目录、字符串或 `table_name,code` CSV 发现 SQL；可选加载 `schema.csv` 用于字段消歧。
2. **Parser** —— SQLGlot 构建 AST；`ColumnResolver` 把每个列绑定到物理 `table.column`。[表达式 DAG 模块](sqlgraph/parser/expr_dag.py) 把每个输出表达式转成带指纹的逻辑节点。
3. **Builder** —— [图构建器](sqlgraph/builder/graph_builder.py) 物化表、字段、转换节点，按“表达式指纹 + 输出字段名”安全合并共享逻辑，并融合跨 SQL 的表级血缘。
4. **Model** —— 内存中的 `PropertyGraph`，包含类型化节点（SQL / Table / Column / Transform）和边（`reads_from`、`writes_to`、`contains`、`compute_dependency`、`produces`、`table_lineage`、`has_column`）。
5. **Serialize / Visualize** —— 导出为 CSV、GraphRAG JSON、纯 JSON、NetworkX，或交互式 Cytoscape.js HTML 页面。

完整设计见 [docs/architecture.md](docs/architecture.md)。

## 目录结构

```
sqlgraph/
├── input/       # SQL 输入源、CSV Schema 注册表、DataFrame 适配器
├── parser/      # 基于 SQLGlot 的解析 + 表达式指纹 DAG
├── builder/     # PropertyGraph 构建与跨 SQL 血缘融合
├── model/       # 节点、边、PropertyGraph
├── serialize/   # csv / graphrag / json / networkx 导出器
├── visualize/   # Cytoscape.js HTML 渲染（分层布局、主题）
├── api.py       # build_graph() 高层入口
├── cli.py       # Typer CLI（build / stats / playground / demo）
└── playground.py # 本地浏览器 Playground，用于临时输入 SQL 生成图谱
examples/ads_pipeline/   # 11 文件 AdTech 示例 + schema.csv
examples/df_sample.csv   # 小型 table_name/code CSV 示例
tests/                   # 单元测试 + 集成测试
```

## 开发

```bash
pip install -e ".[all]"
pytest            # 运行测试套件
```

## 贡献

欢迎提 Issue 和 PR。如果 SqlGraph 对你有帮助，点个 ⭐ 能帮助更多人发现它。

## 许可证

[Apache 2.0](LICENSE)
