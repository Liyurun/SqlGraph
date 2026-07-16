# SqlGraph 血缘检索浏览器（Lineage Explorer）设计

**目标：** 为 SqlGraph 提供一个轻量的本地展示功能，用检索 + 局部图 + 在线解析三页面替代“把全量图塞进单个巨大 HTML”的旧方式，适合作为 GitHub 项目的展示能力，不做成重型系统。

**架构：** 在现有 `Input → Parser → Builder → PropertyGraph` 链路后新增“索引层（JSONL）”和“本地服务层（HTTP + 页面）”。启动服务时解析生成 JSONL 索引并全量载入内存，浏览器通过 JSON API 按需检索和加载局部子图。核心解析逻辑不改动。

**技术栈：** Python 标准库 `ThreadingHTTPServer`、Jinja2 模板、原生 HTML/CSS/JavaScript、Cytoscape.js（沿用现有可视化栈），无 Node 构建步骤。

---

## 范围与关键决策

以下决策已在 brainstorming 阶段与用户逐项确认：

1. **运行方式**：本地轻量服务（非 GitHub Pages 纯静态）。
2. **索引构建**：服务启动时自动构建（`sqlgraph serve df.csv`），终端持续输出进度日志。
3. **缓存策略**：自动复用，输入变化才重建；保留 `--rebuild` 强制重建。
4. **检索范围（第一版）**：仅表名、字段名。SQL 原文不参与全文检索。
5. **局部图默认范围**：上下游各 1 层，可切换到 2/3 层。
6. **导航**：统一应用壳 + 顶部页签（检索 / 图谱查看 / 在线解析）。
7. **静态 HTML 定位**：保留 `sqlgraph build --format html` 单文件导出用于小型 Demo；大型数据走本地服务。
8. **表节点关联 SQL 展示**：详情面板按“写入 SQL / 读取 SQL”分组，每项先摘要，点开按需取全文。
9. **前端实现**：原生 HTML/CSS/JS + Jinja 模板，无 Node。
10. **内存模型**：全部索引（节点、边、邻接、SQL 原文）在启动时一次性载入内存，运行期不做懒加载。

**非目标（YAGNI）**：不引入 SQLite/数据库；第一版不检索 SQL 原文/表达式/路径；不引入前端框架与打包工具；不做多用户/鉴权/持久化编辑。

---

## 1. 架构与数据流

```text
df.csv / SQL
   │  sqlgraph serve df.csv
   ▼
[构建阶段] build_graph → PropertyGraph → 写出 JSONL 索引（带进度日志）
   │
   ▼
[加载阶段] 读取 JSONL 全量载入内存（GraphIndex 对象）
   │
   ▼
[服务阶段] ThreadingHTTPServer 提供页面 + JSON API
   │
   ▼
浏览器：图谱查看 / 检索 / 在线解析（统一应用壳）
```

- JSONL 只是磁盘持久化格式；运行期全部在内存，检索和子图都走内存结构，无懒加载。
- 启动即构建：`serve df.csv` 首次解析生成 JSONL，终端持续打印阶段/数量/耗时/失败样例/进度。
- 智能复用：根据输入路径 + 文件大小 + mtime + 内容摘要判断；未变直接加载，变了打印原因重建；`--rebuild` 强制重建。

---

## 2. JSONL 索引结构与内存模型

索引产物目录（默认 `.sqlgraph_index/<输入摘要>/`）：

```text
.sqlgraph_index/<hash>/
├── manifest.json     # 版本、输入指纹、统计量、构建时间、文件清单
├── nodes.jsonl       # 表/字段/Transform/SQL 节点元数据（每行一个）
├── edges.jsonl       # 全部血缘边
└── sql.jsonl         # SQL 原文、任务名、来源路径、读写表列表
```

`manifest.json` 示例（输入指纹用于智能复用判断）：

```json
{
  "version": 1,
  "source": {"path": "df.csv", "size": 275000000, "mtime": 1752600000, "sha1_16": "abcd..."},
  "stats": {"nodes": 120000, "edges": 480000, "sql": 30000},
  "built_at": "2026-07-16T10:00:00"
}
```

内存模型（一个 `GraphIndex` 对象，启动时一次性构建）：

- `nodes: dict[node_id → node]` — 全量节点
- `edges: list[edge]` — 全量边
- `adjacency: dict[node_id → {"in": [...], "out": [...]}]` — 预建邻接，子图 BFS 直接用
- `sql_by_id: dict[sql_id → sql记录]` — SQL 原文直接驻留内存
- `table_write_sqls / table_read_sqls: dict[table_id → [sql_id]]` — 表的读写 SQL 分组
- `name_index: dict[str → [node_id]]` — 表名、字段名归一化小写（第一版仅覆盖表和字段）

取舍说明：

- 不引入 SQLite，纯 JSONL；逐行 JSON 便于增量写、流式读、`git diff` 友好。
- 邻接表和读写分组在加载时构建一次，避免每个请求重复扫全量边。

---

## 3. HTTP 接口设计

统一用 `ThreadingHTTPServer`，页面路由返回 HTML，`/api/*` 返回 JSON。

页面路由：

```text
GET /            → 重定向到 /search（检索为默认落地）
GET /search      → 检索页
GET /viewer      → 局部图谱页
GET /playground  → 在线解析页
GET /static/*    → CSS/JS 静态资源
```

数据接口：

```text
GET  /api/meta
     → 索引统计：节点/边/SQL 数量、构建时间、输入指纹

GET  /api/search?q=<kw>&type=table|column|all&limit=50
     → 命中列表：{id, type, name, fullName, tableName, sqlCount}
     → 第一版仅检索表名、字段名

GET  /api/node/{node_id}
     → 节点详情 + 表节点的读写 SQL 分组摘要
       {node, writeSqls:[{sqlId,name,sourceUri,preview}],
              readSqls:[...], columns:[...]}

GET  /api/subgraph?node_id=<id>&depth=1&direction=both
     → 内存 BFS 返回局部子图 {nodes:[...], edges:[...]}
     → depth ∈ {1,2,3}，direction ∈ {up,down,both}，默认 1 / both

GET  /api/sql/{sql_id}
     → 单条 SQL 完整原文（详情面板“展开”时调用）

POST /api/parse   (body: {sql, dialect})
     → 复用现有 graph_to_playground_payload，返回即时图
```

设计要点：

- 子图按需：`/viewer` 不加载全量图，只按 `node_id + depth` 取邻域。
- SQL 原文分两级：`/api/node` 只给摘要（任务名 + 截断预览），`/api/sql/{id}` 才返回全文。
- 子图节点自带读写 SQL 计数，表节点可直接标注关联 SQL 数量。
- 错误约定：统一返回 `{"ok": false, "error": "..."}`；404 未找到节点，400 参数非法，500 解析异常。

---

## 4. 前端结构与交互

统一应用壳：顶部页签 `检索 / 图谱查看 / 在线解析`，共享暗色模式、图例、节点样式和详情面板。原生 HTML/CSS/JS + Jinja 模板，无 Node 构建。

文件结构：

```text
sqlgraph/serve/
├── __init__.py
├── index.py        # JSONL 读写 + GraphIndex 内存模型
├── builder_io.py   # PropertyGraph → JSONL，带进度日志
├── server.py       # HTTP 路由 + /api 处理
└── web/
    ├── shell.html.j2   # 应用壳（页签 + 主题 + 详情面板）
    ├── search.html.j2
    ├── viewer.html.j2
    ├── playground.html.j2
    └── static/
        ├── app.css
        ├── graph.js    # Cytoscape 渲染 + 子图加载（三页共用）
        └── detail.js   # 详情面板 + 读写 SQL 分组（共用）
```

### ① 检索页 `/search`

```text
┌──────────┬───────────────────────────┐
│ 搜索框    │ 结果列表（表/字段分组）      │
│ 类型筛选  │  → 点击结果进入 /viewer     │
└──────────┴───────────────────────────┘
```

输入关键词 → `/api/search` → 按“表 / 字段”分组展示 → 点击跳 `/viewer?node_id=...`。

### ② 图谱查看页 `/viewer`

```text
┌───────────────────────────┬───────────┐
│ Cytoscape 局部图           │ 详情面板   │
│ 深度切换 1/2/3             │ 表基础信息 │
│ 方向切换 上/下/双向         │ 写入 SQL   │
│                           │ 读取 SQL   │
│                           │ 字段列表   │
└───────────────────────────┴───────────┘
```

进入即调 `/api/subgraph`（默认 1 层双向）；点节点走 `/api/node` 填详情；表节点右侧列“写入 SQL / 读取 SQL”，每条先摘要，点开调 `/api/sql/{id}` 取全文。

### ③ 在线解析页 `/playground`

保留现有能力：输入 SQL → `/api/parse` → 即时渲染，复用同一套 `graph.js` 和详情面板。

设计要点：

- `graph.js` / `detail.js` 三页共用，语义规范化（CTE 折叠、direct/rename、SQL 虚线等）沉淀到共享 JS，避免逻辑再分叉。
- 详情面板“读写 SQL 分组 + 按需取全文”是解决大 HTML 的核心。

---

## 5. 进度日志、错误处理与测试

### 构建进度日志（`serve df.csv` 启动时输出到终端）

```text
[serve] input: df.csv (262.5 MB)
[serve] index cache miss (size changed) → rebuilding
[parse] 12000/30000 rows | ok=11800 skipped=180 failed=20 | 45.2s
[parse] done: 30000 rows, 20 failed (see samples below)
[parse] failed sample: dm_xxx#L102: <error>
[index] writing nodes.jsonl ... 120000 nodes
[index] writing edges.jsonl ... 480000 edges
[index] writing sql.jsonl ... 30000 sql
[load]  loading index into memory ...
[load]  adjacency built | ready in 6.1s
[serve] http://127.0.0.1:8770/  (search / viewer / playground)
```

- 解析每 N 行打印一次累计计数和耗时；失败不中断，累计并抽样展示（复用现有 df 跳过逻辑）。
- 命中缓存时打印 `index cache hit`，直接进加载阶段。

### 错误处理

- 单条 SQL 解析失败 → 跳过 + 计数 + 抽样，不影响整体。
- API 层：节点不存在 404，参数非法 400，解析异常 500，统一 `{"ok": false, "error"}`。
- 端口占用 → 复用现有自动寻找空闲端口逻辑。

### 测试策略（TDD，pytest）

```text
tests/test_serve/
├── test_index_io.py    # PropertyGraph → JSONL → GraphIndex 往返一致；manifest 指纹；缓存命中/失效判断
├── test_graph_index.py # 内存邻接、subgraph BFS（depth/direction）、表读写 SQL 分组、表/字段检索
└── test_server_api.py  # /api/meta /search /node /subgraph /sql /parse 正常与错误路径
```

- 前端 JS 不做单测；用小型固定 df 样例做 API 层集成断言。
- 复用现有 `graph_to_playground_payload` 的既有测试，保证 `/playground` 不回归。

---

## CLI 变更

新增 `sqlgraph serve` 子命令：

```text
sqlgraph serve <df.csv|sql目录|sql文件>
    --host 127.0.0.1
    --port 8770          # 0 时自动寻找空闲端口
    --dialect spark
    --rebuild            # 强制重建索引，忽略缓存
    --index-dir .sqlgraph_index
    --open/--no-open
```

现有 `build / stats / playground / demo` 子命令保持不变。
