# sqlGraph 设计文档

> **一句话定位：** 一个面向 SQL 血缘和数据资产关系的轻量级图构建与召回框架，支持从 SQL 构建 property graph，并适配多种图数据库和 GraphRAG 后端。

## 1. 项目概述

sqlGraph 是一个开源 Python 库，专注于 SQL 血缘分析与图构建。核心能力包括：

- 从 SQL / CSV / DataFrame 输入解析构建属性图（Property Graph）
- 支持丰富的 SQL 语法：Spark SQL、INSERT OVERWRITE、SELECT、CTE、子查询、UNION、Window 函数等
- 表级和字段级血缘追踪，包含 Transform 计算表达式节点
- 多格式输出：CSV、GraphR payload、NetworkX、精美交互式 HTML 可视化
- 批处理韧性：单条失败不影响整体，完善的错误记录与进度日志
- Notebook / 线上环境开箱即用，Python 3.9+ 兼容

## 2. 架构设计

采用**分层流水线架构**，数据在各层间单向流动，职责清晰：

```
Input → Parser → Builder → Model → Serialize
                                  ↘
                                    Visualize
```

### 2.1 模块划分

| 层级 | 模块 | 职责 |
|------|------|------|
| **Input** | `sqlgraph.input` | 统一输入源适配（SQL 字符串/文件/目录、CSV Schema、DataFrame） |
| **Parser** | `sqlgraph.parser` | SQLGlot 解析 + 语法增强（子查询、UNION、Window、表达式） |
| **Builder** | `sqlgraph.builder` | 从 AST 构建节点/边，CTE 处理，跨 SQL 血缘融合 |
| **Model** | `sqlgraph.model` | 图数据模型定义（Node/Edge/PropertyGraph 类型） |
| **Serialize** | `sqlgraph.serialize` | 多格式输出：CSV、GraphR payload、JSON、NetworkX |
| **Visualize** | `sqlgraph.visualize` | Cytoscape.js 交互式 HTML 可视化生成 |
| **API/CLI** | `sqlgraph.api` / `sqlgraph.cli` | 高层 Python API 和 Typer CLI 入口 |
| **Utils** | `sqlgraph.utils` | 日志、错误处理、批处理韧性、Notebook 兼容 |

## 3. 数据模型

### 3.1 节点类型（Node Types）

| 节点类型 | 颜色标识 | 属性 | 说明 |
|----------|----------|------|------|
| **SqlNode** | 紫色 (#9c27b0) | id, name, file_path, sql_content, dialect, created_at | SQL 任务或 SQL 文件 |
| **TableNode** | 蓝色 (#2196f3) | id, name, catalog, schema, is_cte, columns | 物理表或 CTE |
| **ColumnNode** | 绿色 (#4caf50) | id, name, table_id, data_type, is_primary_key | 字段 |
| **TransformNode** | 橙色 (#ff9800) | id, expression, expression_type | 字段计算表达式 |

TransformNode.expression_type 枚举值：
- `CASE_WHEN` - CASE WHEN 条件表达式
- `AGG` - 聚合函数（SUM/MAX/COUNT/AVG/MIN）
- `CAST` - 类型转换
- `ARITHMETIC` - 算术运算（ROUND、除法比例等）
- `COALESCE` - COALESCE / NULLIF
- `WINDOW` - 窗口函数
- `UNION` - UNION/UNION ALL 合并
- `LITERAL` - 常量/字面量
- `COLUMN_REF` - 直接字段引用
- `FUNCTION` - 其他函数调用

### 3.2 边类型（Edge Types）

| 边类型 | 颜色 | 连接关系 | 说明 |
|--------|------|----------|------|
| **WRITES_TO** | 红色 (#d32f2f) | SqlNode → TableNode | SQL 写入目标表 |
| **READS_FROM** | 蓝色 (#1976d2) | SqlNode → TableNode | SQL 读取源表（READ_BY 的反向） |
| **TABLE_LINEAGE** | 绿色 (#388e3c) | TableNode → TableNode | 表级血缘（跨 SQL 融合后生成） |
| **PRODUCES** | 紫色 (#7b1fa2) | TransformNode → ColumnNode | Transform 产出字段 |
| **COMPUTE_DEPENDENCY** | 橙色 (#f57c00) | ColumnNode → TransformNode | 字段参与计算 |
| **HAS_COLUMN** | 灰色 (#607d8b) | TableNode → ColumnNode | 表包含字段 |
| **CONTAINS** | 青色 (#0097a7) | SqlNode → TransformNode | SQL 包含转换表达式 |

## 4. Parser 增强设计

### 4.1 匿名子查询逐层 Transform 串联

**策略：** 为每个匿名子查询生成内部唯一别名（如 `__subquery_0`），视为临时 CTE 处理。

**实现：**
1. 使用 SQLGlot Visitor 递归遍历子查询
2. 为每层子查询生成虚拟 TransformNode 链
3. 逐层向上传播字段依赖，确保链路不丢失
4. 子查询内字段 Transform → 外层字段引用完整串联

### 4.2 UNION / UNION ALL 多分支血缘

**策略：** UNION 的输出字段依赖所有分支同位置字段。

**实现：**
1. 检测 UNION/UNION ALL 语法节点
2. 创建 `UnionTransformNode`（expression_type='UNION'）
3. 收集每个 SELECT 分支的字段列表
4. 按位置建立 COMPUTE_DEPENDENCY 边（每个分支字段 → UnionTransformNode）
5. UnionTransformNode → 输出字段（PRODUCES 边）

### 4.3 Window 函数派生字段

**策略：** Window 函数的 PARTITION BY 和 ORDER BY 字段均为其依赖。

**实现：**
1. 处理 Window 节点，提取 function name
2. 提取 PARTITION BY 表达式中的所有字段引用
3. 提取 ORDER BY 表达式中的所有字段引用
4. 记录 frame 规格（ROWS/RANGE BETWEEN）
5. 所有引用字段建立 COMPUTE_DEPENDENCY 边

### 4.4 Schema-aware 字段消歧

**策略：** 可选 SchemaRegistry 组件，利用用户提供的表结构信息消歧。

**实现：**
1. SchemaRegistry 从 CSV/DataFrame/catalog 加载 table → columns 映射
2. 字段引用解析优先级：
   - 显式 table.column 限定名 → 直接解析
   - SchemaRegistry 查询 → 消歧
   - SQL 上下文（别名、CTE）→ 推断
   - 无法确定 → 标记 ambiguous 并报告，不强行建立依赖
3. 无 Schema 时按最大可能性推断，保守策略避免错误血缘

### 4.5 多 SQL 跨任务深层链路融合

**策略：** Builder 层维护全局 TableRegistry。

**实现：**
1. 预扫描：先收集所有 INSERT/CREATE TABLE 语句，建立初步表→SQL映射
2. 逐 SQL 解析时通过 TableRegistry 链接上游 SqlNode
3. 自动生成 TABLE_LINEAGE 边：源表 → 目标表（通过中间 SqlNode 传递）
4. 循环依赖检测：发现循环时记录警告但不中断
5. 支持按文件顺序/依赖拓扑排序处理

## 5. 可视化设计

### 5.1 技术选型

- **渲染引擎：** Cytoscape.js
- **默认布局：** cytoscape-dagre（DAG 分层布局，最适合血缘图）
- **模板引擎：** Jinja2
- **输出：** 自包含单 HTML 文件（JS/CSS 内联或 CDN）

### 5.2 视觉设计

- **深色科技主题**（默认），提供 light 主题选项
- 节点按类型配色（紫/蓝/绿/橙）
- 节点大小根据度数（连接数）自适应
- 渐变填充 + 阴影效果
- 边按类型着色 + 方向箭头
- 最终目标表节点金色边框高亮

### 5.3 交互能力

- 缩放、平移、拖拽节点
- 点击节点：右侧面板展示详情（类型、属性、字段列表、上下游数量）
- 悬停高亮相邻节点/边
- 左侧图层控制面板：按节点类型筛选显示/隐藏
- 布局切换：Dagre / CoSE 力导向 / Circle / Breadthfirst
- 节点搜索定位
- 适配视图按钮

### 5.4 视图模式

| 视图模式 | 说明 |
|----------|------|
| `table` | 表级视图（默认），显示 SQL + Table 节点 |
| `column` | 字段级视图，展开 Column + Transform 节点 |
| `sql` | SQL 依赖视图，仅显示 SQL 节点依赖关系 |
| `focus:<table_name>` | 单表聚焦视图，展示指定表的完整上下游链路 |

### 5.5 导出能力

- 自包含 HTML（默认输出）
- PNG 高清图片
- SVG 矢量图
- Graphviz DOT 格式
- Jupyter Notebook 内嵌展示

## 6. API 设计

### 6.1 Python API

```python
from sqlgraph import build_graph, visualize, serialize
from sqlgraph.input import SqlSource

# 最简方式：从目录构建
graph = build_graph(
    "examples/ads_pipeline/",
    dialect="spark",
    schema_path="examples/ads_pipeline/schema.csv",  # 可选
)

# 多源混合输入
sources = [
    SqlSource.from_file("sql/etl1.sql"),
    SqlSource.from_dir("sql/daily/"),
    SqlSource.from_string("INSERT INTO t SELECT * FROM s", name="inline"),
    SqlSource.from_dataframe(df, table_name="input_df"),
]
graph = build_graph(sources, dialect="spark")

# 输出序列化
serialize.to_csv(graph, output_dir="./output_csv/")
serialize.to_graphrag(graph, output_path="./output_graph.json")
serialize.to_networkx(graph)  # 返回 networkx.DiGraph

# 精美可视化
visualize.to_html(
    graph,
    output_path="lineage.html",
    view="table",        # table | column | sql | focus:<name>
    theme="dark",        # dark | light
    title="广告素材血缘图",
)

# 编程式访问
graph.nodes              # List[Node]
graph.edges              # List[Edge]
graph.get_upstream("dws_ad_daily")    # 上游表血缘
graph.get_downstream("dws_ad_daily")  # 下游表血缘
graph.stats()            # {sql_count, table_count, column_count, ...}
```

### 6.2 CLI（Typer）

```bash
# 从目录构建并生成可视化（默认）
sqlgraph build examples/ads_pipeline/ -o ./output --dialect spark --view table

# 生成 CSV 输出
sqlgraph build sql/ --format csv -o ./csv_output

# 生成 GraphR payload
sqlgraph build sql/ --format graphrag -o ./payload.json

# 同时输出多种格式 + 可视化
sqlgraph build sql/ --format csv,graphrag,html --view column -o ./output/

# 指定 schema
sqlgraph build sql/ --schema schema.csv --dialect spark

# 一键运行 demo
sqlgraph demo  # 使用内置示例，生成 lineage.html 并自动打开浏览器

# 查看统计
sqlgraph stats examples/ads_pipeline/
```

**CLI 选项：**

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `INPUT` | SQL 文件或目录路径 | 必填 |
| `-o, --output` | 输出目录/文件 | `./sqlgraph_output` |
| `--dialect` | SQL 方言（spark/hive/presto/...） | 自动检测 |
| `--format` | 输出格式（csv/graphrag/html/json，逗号分隔） | `html` |
| `--view` | 可视化视图（table/column/sql/focus:&lt;table_name&gt;） | `table` |
| `--theme` | 主题（dark/light） | `dark` |
| `--schema` | 表 schema CSV 路径（可选） | 无 |
| `--title` | 图谱标题 | "SQL Lineage" |
| `--open/--no-open` | 完成后自动打开浏览器 | `--open` |

## 7. 核心特性

### 7.1 批处理韧性

- 单条 SQL 解析失败不中断整体流程
- `failed_cases.json` 记录失败详情（文件路径、错误信息、SQL 内容）
- `print(..., flush=True)` 实时进度日志
- 完成后输出统计：成功/失败数量、节点/边数量、耗时

### 7.2 Notebook / 线上环境适配

- Python 3.9+ 兼容
- 非交互依赖安装（quiet 模式）
- 自动 patch GraphR client 的 `str | None` 类型兼容问题
- `visualize.to_notebook(graph)` 内嵌展示
- `smoke_result.json` 烟测输出

### 7.3 类型化 I/O

- 所有 Node/Edge 使用 Python dataclass 定义
- 节点执行前后严格类型校验
- 统一错误类型体系
- 完整类型注解（mypy 兼容）
- LLM 模块预留封装（扩展点）

## 8. 项目配置

| 配置项 | 值 |
|--------|-----|
| Python 包名 | `sqlgraph` |
| PyPI 包名 | `sqlgraph-lineage` |
| 构建工具 | Poetry |
| Python 版本 | 3.9+ |
| License | Apache 2.0 |
| 代码托管 | GitHub |
| CLI 框架 | Typer |
| 核心依赖 | sqlglot, pandas, typer, jinja2, rich |
| 可选依赖 | networkx, ipython (Notebook) |

## 9. 目录结构

```
sqlgraph/
├── __init__.py              # 导出 build_graph, visualize, serialize
├── api.py                   # 高层 Python API
├── cli.py                   # Typer CLI 入口
├── model/                   # 数据模型
│   ├── __init__.py
│   ├── graph.py             # PropertyGraph
│   ├── nodes.py             # SqlNode/TableNode/ColumnNode/TransformNode
│   └── edges.py             # Edge 类型定义
├── input/                   # 输入源
│   ├── __init__.py
│   ├── sql_source.py        # SqlSource: file/dir/string/dataframe
│   ├── csv_schema.py        # SchemaRegistry (CSV 读取)
│   └── dataframe.py         # DataFrame 输入
├── parser/                  # SQL 解析
│   ├── __init__.py
│   ├── base.py              # BaseVisitor + SQLGlot 封装
│   ├── select.py            # SELECT 解析
│   ├── insert.py            # INSERT OVERWRITE 解析
│   ├── cte.py               # CTE 处理
│   ├── subquery.py          # 匿名子查询逐层串联
│   ├── union.py             # UNION/UNION ALL
│   ├── window.py            # Window 函数
│   ├── expressions.py       # CASE WHEN/AGG/CAST/COALESCE/ROUND
│   └── column_resolver.py   # schema-aware 字段消歧
├── builder/                 # 图构建
│   ├── __init__.py
│   ├── graph_builder.py     # 核心构建器
│   ├── table_registry.py    # 全局表映射 & 跨SQL融合
│   └── lineage_linker.py    # TABLE_LINEAGE 边生成
├── serialize/               # 输出序列化
│   ├── __init__.py
│   ├── csv.py               # nodes.csv + edges.csv
│   ├── graphrag.py          # GraphR entity/relation payload
│   ├── json_output.py       # JSON/Dict 输出
│   └── networkx.py          # NetworkX 转换
├── visualize/               # 可视化
│   ├── __init__.py
│   ├── html.py              # Cytoscape.js HTML 生成 (Jinja2模板)
│   ├── templates/
│   │   └── graph.html.j2    # Jinja2 模板
│   ├── colors.py            # 配色方案
│   └── layouts.py           # 布局配置
└── utils/                   # 工具
    ├── __init__.py
    ├── logging.py           # print(..., flush=True) 实时日志
    ├── errors.py            # 异常类型体系
    ├── batch.py             # 批处理韧性 & failed_cases
    └── notebook.py          # Notebook 兼容 patch

examples/
└── ads_pipeline/            # AdTech 领域示例（6个SQL文件）
    ├── 01_stg_impressions.sql
    ├── 02_stg_clicks.sql
    ├── 03_dwd_ad_event.sql
    ├── 04_dws_ad_daily.sql
    ├── 05_dws_creative_daily.sql
    ├── 06_ads_creative_report.sql
    ├── schema.csv
    └── run_demo.py          # 一键运行脚本

tests/                       # 单元测试 & 集成测试
docs/                        # 文档
pyproject.toml               # Poetry 配置
README.md
LICENSE
```

## 10. 测试数据示例：examples/ads_pipeline/

提供模拟广告技术（AdTech）领域的数据处理链路，覆盖所有支持的 SQL 特性：

1. **01_stg_impressions.sql** - 原始曝光日志 ETL（CAST、COALESCE、CASE WHEN）
2. **02_stg_clicks.sql** - 原始点击日志 ETL
3. **03_dwd_ad_event.sql** - 曝光点击关联（JOIN、子查询、Window 函数去重）
4. **04_dws_ad_daily.sql** - 广告日粒度聚合（SUM/MAX/COUNT、ROUND 比例计算）
5. **05_dws_creative_daily.sql** - 素材粒度聚合（CTE、UNION ALL 多来源合并）
6. **06_ads_creative_report.sql** - 最终报表（多层子查询、复杂 CASE WHEN、Window 排序）

配套 `schema.csv` 提供源表结构，`run_demo.py` 一键运行并打开可视化。

## 11. 图后端解耦策略

核心层**只构建内存中的 PropertyGraph 对象**，不绑定任何具体图数据库：

- 图数据库写入完全通过独立的 adapter 模块（可在同仓库 `adapters/` 目录或独立包实现）
- 内置通用 CSV 和 GraphR payload 作为 serialize 格式
- PropertyGraph 提供 to_dict()/from_dict() 方法，方便第三方 adapter 对接
- ByteGraph/Neo4j/Neptune 等后端作为可选扩展，不在核心依赖中

## 12. 错误处理

| 错误类型 | 处理策略 |
|----------|----------|
| SQL 语法错误 | 单条失败，记录到 failed_cases.json，继续处理其他 SQL |
| 方言不支持 | 警告并尝试通用解析，解析失败则记录失败 |
| 字段消歧失败 | 标记 ambiguous，不强行建立错误依赖，日志告警 |
| 循环依赖 | 记录警告，打破循环继续 |
| Schema 文件不存在 | 降级到无 schema 模式，日志提示 |
| IO 错误（文件读取） | 立即失败（输入错误属于配置问题） |
