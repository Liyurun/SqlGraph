# AI 原生数仓治理参考实现发布设计

## 1. 目标

将 SqlGraph 建设为《AI 原生数仓治理》的可运行参考实现与证据仓库，并满足以下六条对外发布门槛：

1. 全新 Python 3.10-3.12 环境可在十分钟内完成安装、运行示例并生成证据产物。
2. `CAPABILITIES.yaml` 如实记录每项能力的状态、模块、测试和示例。
3. 证据缺失、不可逆动作、授权缺失和验证失败均有自动化拒绝测试。
4. 至少提供口径一致性、成本或冷表治理、不可逆动作转 L4 三条完整案例。
5. 每条案例均能导出从 baseline、证据、提案、授权、执行到验证的可校验事件包。
6. 支持范围、已知限制、外部依赖和规模边界均有公开文档。

最终读者看到的不只是血缘图，而是能验证一个治理结论如何从确定性事实中产生、如何受证据和安全闸门约束，以及执行后如何验证、恢复和追责。

## 2. 范围

### 2.1 本轮包含

- 以 GitHub `origin/main` 为基线，保留现有 `analyze`、`serve`、Explorer、CLI 和开源治理文件。
- 移植并深化本地已有的确定性身份、多语句血缘、表达式 DAG、证据子图、自治决策、七步循环、三层验证和 DuckDB 数仓案例。
- 新增统一 baseline、证据纪律、Grounding、动作安全、独立验证、追加式审计、能力账本和书—代码—测试映射。
- 将治理工作台接入 GitHub Explorer 的共享视觉基线，同时继续输出单文件离线 HTML。
- 建立单元、契约、黄金、端到端、安全和规模六级验证。
- 在功能分支通过全部门禁后推送 GitHub，不直接修改或强推远端 `main`。

### 2.2 本轮不包含

- 企业生产权限中心、审批平台或调度平台的真实接入。
- Neo4j、ByteGraph、云数据库或大模型供应商的强依赖。
- 生产级多租户、在线高可用、分布式锁和长期任务调度。
- 将所有代码迁移到新的 `src/` 目录。
- 把实验性 embedding 或多智能体能力声明为核心能力。

这些能力可以通过后续 adapter 或实验模块接入，但不影响本轮参考实现验收。

## 3. 基线与整合策略

### 3.1 Git 基线

- 功能分支：`feat/book-governance-reference`
- 基线：最新 `origin/main`
- 工作树：独立 clean worktree
- 禁止从当前本地脏 `main` 直接合并或推送
- 禁止提交书稿 ZIP、生成图片、DuckDB 文件、浏览器截图、缓存和本地输出

### 3.2 远端能力必须保留

- `sqlgraph/analyze/` 离线治理分析及 CLI `analyze`、`profile`
- `sqlgraph/serve/` Explorer 搜索、图查看、统计和 Playground
- `sqlgraph/input/ddl_schema.py` 与 DDL 转 Schema 工具
- GitHub issue/PR 模板、`SECURITY.md`、`CODE_OF_CONDUCT.md`
- MIT License、开源检查脚本和发布包资源声明
- 远端保守表达式指纹语义，不恢复代数交换律推断

### 3.3 本地能力按模块移植

不复制整个目录覆盖远端，而是以测试为入口逐模块移植。发生语义冲突时，以以下优先级裁决：

1. 本设计中的安全和证据约束。
2. GitHub 当前公开接口和兼容性。
3. 本地实现细节。

## 4. 目标架构

```text
Input Adapters
    |
    v
Baseline Registry
    |
    v
Deterministic Compiler ---> HeteroGraph ---> TableGraph / Analyze
                                  |
                                  v
                         Evidence Engine
                         | coverage
                         | counterevidence
                         | citations
                                  |
                                  v
                         Autonomy Policy
                                  |
                                  v
                         Action Engine
                         | dry run
                         | idempotency
                         | execute
                         | rollback
                                  |
                                  v
                    Independent Verification
                                  |
                                  v
                       Append-only Audit Log
```

七步治理循环只负责编排这些深模块，不复制 baseline、证据、授权、执行或验证规则。

## 5. 模块设计

### 5.1 Baseline Registry

位置：`sqlgraph/baseline/`

主要接口：

```python
def build_baseline(
    source: SqlSource,
    *,
    dialect: str | None,
    schema: SchemaRegistry | None,
    parameters: Mapping[str, object] | None = None,
    udf_manifest: Mapping[str, object] | None = None,
    scheduler_manifest: Mapping[str, object] | None = None,
) -> BaselineManifest
```

`BaselineManifest` 必须包含：

- `schema_version`
- `baseline_id`
- 输入文件及内容 SHA256
- 方言、SQLGlot 版本、身份规则版本
- Schema、UDF、参数和调度快照的哈希
- 创建时间，仅作为元数据，不参与语义身份
- 缺失依赖及其显式状态

同一有效输入必须生成相同 `baseline_id`。缺失 Schema 或 UDF 时不得伪造已解析结论。

### 5.2 Deterministic Compiler

位置：现有 `sqlgraph/input/`、`parser/`、`builder/`、`model/`、`identity/`

要求：

- 全部 SQL 语句独立建模，禁止跨语句笛卡尔伪边。
- 表、字段、表达式、语句和边均使用稳定语义身份。
- Transform 指纹沿用远端保守规范化，不推断 `a+b` 与 `b+a` 等价。
- 物理列无法判定时标记 `UNRESOLVED`，不得使用默认表名猜测。
- 节点、边和诊断包含可定位的来源文件、语句序号和源码范围。
- TableGraph 是 HeteroGraph 的可重建投影，每条边保存来源语句、字段依赖和 transform 引用。

### 5.3 Evidence Engine

位置：`sqlgraph/evidence/`

外部接口收敛为：

```python
class EvidenceEngine:
    def collect(self, request: EvidenceRequest) -> EvidenceBundle: ...
    def expand(self, bundle: EvidenceBundle, reason: str) -> EvidenceBundle: ...
    def assess(self, bundle: EvidenceBundle) -> SufficiencyDecision: ...
```

`EvidenceRequest` 必须声明：

- `task_id`、`baseline_id`
- 治理对象和治理意图
- 锚点
- 方向和最大深度
- 覆盖义务
- 外部事实要求

`EvidenceBundle` 必须输出：

- included / excluded 节点和边
- 支持证据和反对证据
- 覆盖契约、缺口、残余未知
- 来源引用
- 规则版本和稳定 `subgraph_hash`
- 扩图历史

证据不足只能返回 `expand`、`degrade`、`refuse` 或 `escalate`，不得进入自主执行。

### 5.4 GraphRAG Grounding

位置：`sqlgraph/graphrag/`

主要接口：

```python
def validate_assertions(
    assertions: Sequence[GroundedAssertion],
    evidence: EvidenceBundle,
) -> GroundingReport
```

每条结构性断言必须引用当前 baseline 和 evidence 中存在的节点、边或路径。以下情况必须失败：

- 引用不存在。
- 引用属于其他 baseline 或 evidence 版本。
- 断言射程超过覆盖契约。
- 只有自然语言结论，没有结构证据。

GraphRAG 序列化只负责上下文，不自动赋予结论真实性。

### 5.5 Autonomy Policy

位置：`sqlgraph/autonomy/`

保留当前“闸门在前、标定在后”模型，并补充：

- 输入必须引用 `evidence_version` 和授权主体。
- 可逆性由三项证据组成：状态可恢复、外部后果可控、回滚路径已验证。
- 证据、授权或可逆性任一闸门失败时，收益分不得补偿。
- 输出继续使用动作深度、L4 开关和 L5 范围三维模型。
- 所有规则携带 `policy_version`。

### 5.6 Action Engine

位置：`sqlgraph/actions/`

核心接口：

```python
class ActionEngine:
    def plan(self, request: ActionRequest) -> ActionPlan: ...
    def dry_run(self, plan: ActionPlan) -> DryRunResult: ...
    def execute(self, plan: ActionPlan) -> ExecutionResult: ...
    def rollback(self, execution: ExecutionResult) -> RollbackResult: ...
```

首批两个 adapter：

- `SqlFilePatchAdapter`：精确修改、前置内容哈希、备份和恢复验证。
- `DuckDBTaskAdapter`：事务或快照执行、增量任务重跑、故障注入和恢复。

执行前必须验证：

- 自治决议允许该动作。
- 幂等键未产生成功副作用。
- 预演结果与计划一致。
- 回滚计划已实际验证，而不只是存在文本。

执行失败或验证失败时触发熔断；自动回滚仅适用于已验证可恢复的 adapter。

### 5.7 Independent Verification

位置：`sqlgraph/verification/`

三层定义：

1. `code`：计划变更与实际变更是否一致。
2. `structure`：从变更后的实际 SQL 和 baseline 独立重建图，再比较边界。
3. `runtime`：由 DuckDB adapter 查询真实结果、质量信号和下游重算状态。

验证模块不得复用执行阶段缓存的“成功”布尔值。任一关键层 `fail` 时结果只能是 `failed`；运行态未执行时只能是 `incomplete`。

为兼容现有调用，`sqlgraph.verify` 暂时作为迁移适配器，内部委托给 `sqlgraph.verification`。

### 5.8 Append-only Audit

位置：`sqlgraph/audit/`

主要接口：

```python
class AuditLog:
    def append(self, event: AuditEvent) -> AuditEvent: ...
    def verify_integrity(self) -> IntegrityReport: ...
    def replay(self, task_id: str) -> ReplayResult: ...
```

每个事件包含：

- `event_id`、`task_id`、`baseline_id`
- 事件类型、schema 版本和策略版本
- 授权身份、证据引用、幂等键
- 前一事件哈希和当前事件哈希
- 输入、输出和状态转换

事件采用 JSONL 追加写入。篡改、删除或重排事件必须被完整性检查发现。

### 5.9 Governance Runner

位置：`sqlgraph/reasoning/`

`GovernanceRunner.run()` 编排 Observe、Explain、Propose、Authorize、Execute、Verify、Learn。每步产生版本化产物和审计事件；失败后可从允许的步骤恢复，但不能绕过 Authorize 或 Verify。

现有 `sqlgraph.agent` 保留为兼容入口，委托给新 runner。

## 6. 数据契约

在 `schemas/` 提供以下 JSON Schema：

- `baseline-manifest-v1.schema.json`
- `evidence-bundle-v1.schema.json`
- `autonomy-decision-v1.schema.json`
- `action-plan-v1.schema.json`
- `verification-report-v1.schema.json`
- `audit-event-v1.schema.json`
- `capabilities-v1.schema.json`

所有持久化产物包含 `schema_version`。契约测试验证必填字段、拒绝语义和兼容读取。

## 7. 示例与用户体验

### 7.1 十分钟示例

`examples/minimal/` 提供一条小型 SQL 流程和一条命令：

```bash
sqlgraph governance run examples/minimal/scenario.yaml -o demo_output/minimal
```

输出：

- baseline manifest
- graph snapshot
- evidence bundle
- autonomy decision
- action/verification records
- audit JSONL 和 replay summary
- 单文件 HTML 报告

### 7.2 三条书中案例

- `caliber_consistency`：CTR 百分数与比率冲突，允许 L3 可逆修复。
- `cold_table_retirement`：先停写或隔离，保留恢复路径，验证成本与下游影响。
- `irreversible_drop`：无已验证恢复路径的删除动作，稳定拒绝 L3/L5 并转 L4。

现有 94 表、62 任务视频商业化数仓作为综合案例保留，不作为十分钟 Quickstart 的前置条件。

### 7.3 GitHub 样式

- `sqlgraph/serve/web/static/app.css` 是共享视觉基线。
- 治理报告渲染器读取并内联共享 CSS，再追加治理页面专用规则。
- 页面保持 `#0b1020`、`#0f172a`、`#34d399`、`#38bdf8` 等远端 token。
- 保留顶部 `app-tabs` 导航、深色网格图谱、键盘焦点和移动端列表模式。
- 报告不得引用外部 CDN，必须可离线打开并适配 390x844。

## 8. 能力账本与文档

根目录新增 `CAPABILITIES.yaml`，每项包含：

- `id`
- `status`
- `description`
- `modules`
- `tests`
- `examples`
- `limitations`

状态只能是：

- `implemented`
- `experimental`
- `planned`
- `concept-only`

新增：

- `docs/book-map.md`
- `docs/theory-vs-implementation.md`
- `docs/limitations.md`
- 更新后的中英文 README 和 architecture

CI 校验账本中的模块、测试和示例路径真实存在；书中尚未实现的能力不得标记为 implemented。

## 9. 验证体系

### 9.1 单元测试

覆盖规范化、稳定身份、baseline、证据扩图、反证、Grounding、自治规则、幂等、哈希链和回滚状态机。

### 9.2 契约测试

位置：`tests/contract/`

验证 JSON Schema、CLI 输出、版本兼容、错误码和拒绝语义。

### 9.3 黄金语料

位置：`tests/golden/`

从当前 5 组扩展到至少 20 组，覆盖：

- 多语句
- CTE 与嵌套子查询
- JOIN 同名列与缺 Schema
- 窗口、CASE、CAST、聚合
- UDF 与缺 UDF
- 动态 SQL 的明确不支持诊断
- Spark、Hive、Presto、BigQuery、MySQL、Postgres、DuckDB
- 仅格式变化的稳定性

### 9.4 端到端测试

三条案例均从 baseline 运行到 replay，并验证完整事件包。

### 9.5 安全测试

位置：`tests/safety/`

覆盖：

- 删除关键证据后降级或拒绝。
- 伪造引用被 Grounding 拒绝。
- 不可逆动作强制 L4。
- 无授权动作止于提案。
- 重复执行不产生重复副作用。
- 执行中故障触发熔断和恢复。
- 独立验证失败触发回滚或转人工。
- 审计事件被篡改后完整性失败。

### 9.6 规模测试

位置：`tests/scale/`

生成 `10^2`、`10^3`、`10^4` SQL 的确定性基准，记录：

- 总耗时和 p50/p95
- 峰值内存
- 解析成功率
- UNKNOWN / UNRESOLVED 数
- 节点、边和产物体积

默认 CI 运行 `10^2`，定时或手工 workflow 运行 `10^3` 和 `10^4`，避免普通 PR 被长基准阻塞。

## 10. CI 与发布门禁

CI 阶段：

1. Ruff 和基础类型检查。
2. 分层依赖、随机 ID 和敏感产物扫描。
3. 单元、契约、黄金、端到端和安全测试。
4. 能力账本与书—代码映射一致性。
5. 构建 wheel/sdist 并在全新虚拟环境运行十分钟 Quickstart。
6. Explorer 与治理报告样式契约测试。
7. 开源 guard、License 和包内容检查。

发布前再运行：

- 完整 `10^3` / `10^4` 规模基准。
- 桌面和 390x844 浏览器验证。
- 三条案例的审计重放和恢复演练。
- `git status` 白名单检查，确保没有本地生成物。

## 11. 完成标准

只有同时满足以下条件，功能分支才可推送：

- 六条发布门槛全部有当前版本自动化证据。
- 远端 `analyze`、`profile`、`serve`、`build`、`playground`、`demo` 回归通过。
- 新增 `governance` 命令可运行三条案例。
- 至少 20 组黄金 SQL 通过。
- 安全测试证明四类硬拒绝和恢复路径成立。
- 审计包能通过 hash-chain 完整性校验并按 task 重放。
- README、能力账本、book map 和 limitations 与代码一致。
- Explorer 与治理报告桌面/移动端无布局回归。
- 分支基于最新 `origin/main`，提交不包含生成数据库、报告、截图或书稿。

推送目标为 `origin/feat/book-governance-reference`。不自动合并 `main`，由 GitHub Pull Request 和 CI 完成最终审查。
