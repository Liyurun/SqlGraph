# AI 原生数仓治理参考实现发布 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不破坏 GitHub 现有 Explorer 和离线分析能力的前提下，交付满足六条对外发布门槛的 AI 原生数仓治理参考实现，并将功能分支推送到 GitHub。

**Architecture:** 以 `origin/main` 为唯一整合基线，先补确定性 baseline 和可下钻事实图，再通过 Evidence、Grounding、Autonomy、Actions、Verification、Audit 六个深模块形成受约束闭环。`GovernanceRunner` 只做编排；Explorer 和离线报告共享 GitHub CSS，报告在渲染时将 CSS 内联以保持单文件离线运行。

**Tech Stack:** Python 3.9-3.12、SQLGlot、Typer、Jinja2、DuckDB、JSON Schema、pytest、Ruff、mypy、原生 HTML/CSS/JavaScript。

---

## 文件结构

新增模块：

```text
sqlgraph/
├── baseline/          # 输入清单、baseline_id、缺失依赖
├── evidence/          # 证据收集、扩图、充分性
├── graphrag/          # 断言与结构引用校验
├── autonomy/          # 自治闸门和三维决议
├── actions/           # 动作计划、adapter、幂等、熔断、回滚
├── verification/      # 代码、独立结构、运行态验证
├── audit/             # JSONL 哈希链和重放
└── reasoning/         # 七步 GovernanceRunner
```

新增发布资产：

```text
schemas/
examples/minimal/
examples/book_cases/
tests/contract/
tests/safety/
tests/scale/
docs/book-map.md
docs/theory-vs-implementation.md
docs/limitations.md
CAPABILITIES.yaml
```

兼容层：

- `sqlgraph.agent` 委托 `sqlgraph.reasoning`
- `sqlgraph.verify` 委托 `sqlgraph.verification`
- 现有 `build`、`stats`、`analyze`、`profile`、`serve`、`playground`、`demo` 保持兼容

---

### Task 1: 固化远端基线与回归保护

**Files:**
- Modify: `.gitignore`
- Modify: `.github/workflows/ci.yml`
- Create: `tests/test_release/test_remote_capabilities.py`
- Create: `tests/test_release/__init__.py`

- [ ] **Step 1: 写远端能力回归测试**

```python
from typer.testing import CliRunner

from sqlgraph.cli import app


def test_public_cli_keeps_existing_github_commands():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("build", "stats", "analyze", "profile", "serve", "playground", "demo"):
        assert command in result.stdout
```

- [ ] **Step 2: 运行测试并确认当前远端基线通过**

Run: `python -m pytest tests/test_release/test_remote_capabilities.py -q`

Expected: PASS。

- [ ] **Step 3: 扩充生成物忽略规则**

加入：

```gitignore
*.duckdb
demo_output/
comparison-screenshots/
generated_illustrations*/
book*/
*.zip
.benchmarks/
```

- [ ] **Step 4: 运行远端完整测试**

Run: `python -m pytest -q`

Expected: 远端测试全部通过。

- [ ] **Step 5: 提交**

```bash
git add .gitignore .github/workflows/ci.yml tests/test_release
git commit -m "test: protect github baseline capabilities"
```

### Task 2: 移植确定性编译与多语句事实层

**Files:**
- Create: `sqlgraph/identity/__init__.py`
- Modify: `sqlgraph/input/sql_source.py`
- Modify: `sqlgraph/parser/base.py`
- Modify: `sqlgraph/parser/expr_dag.py`
- Modify: `sqlgraph/builder/graph_builder.py`
- Modify: `sqlgraph/model/nodes.py`
- Modify: `sqlgraph/model/edges.py`
- Modify: `sqlgraph/model/graph.py`
- Create: `tests/test_identity/test_determinism.py`
- Create: `tests/test_identity/__init__.py`
- Create: `tests/test_graph_advanced/test_statement_lineage.py`
- Create: `tests/test_graph_advanced/__init__.py`

- [ ] **Step 1: 写确定性和多语句失败测试**

```python
def test_two_builds_have_identical_full_ids():
    sql = "INSERT INTO d SELECT a + b AS c FROM s"
    assert all_ids(build_graph(sql, dialect="spark")) == all_ids(
        build_graph(sql, dialect="spark")
    )


def test_independent_statements_do_not_cross_link():
    graph = build_graph(
        "INSERT INTO d1 SELECT * FROM s1; INSERT INTO d2 SELECT * FROM s2;",
        dialect="spark",
    )
    assert table_pairs(graph) == {("s1", "d1"), ("s2", "d2")}
```

- [ ] **Step 2: 运行测试确认缺失能力**

Run: `python -m pytest tests/test_identity tests/test_graph_advanced/test_statement_lineage.py -q`

Expected: FAIL，边或 SQL 身份不稳定，或多语句归属不完整。

- [ ] **Step 3: 实现稳定身份与语句归属**

实现：

```python
IDENTITY_RULE_VERSION = "id-v2"


def stable_id(prefix: str, semantic_key: str, bits: int = 96) -> str:
    width = bits // 4
    digest = hashlib.sha256(semantic_key.encode("utf-8")).hexdigest()[:width]
    return f"{prefix}_{digest}"
```

每条语句保存 `stmt_index`；所有边 ID 使用源、目标、类型和语句上下文派生。表达式继续使用远端保守规范化，并增加 `expr_operand` 子表达式边，不引入交换律等价推断。

- [ ] **Step 4: 增加来源位置和 UNRESOLVED 诊断**

节点和诊断属性至少包含：

```python
{
    "source_name": item.name,
    "stmt_index": stmt_index,
    "line": line,
    "column": column,
    "resolution": "resolved" | "unresolved",
}
```

- [ ] **Step 5: 运行解析、构建、分析和 Explorer 回归**

Run: `python -m pytest tests/test_parser tests/test_builder tests/test_analyze tests/test_serve tests/test_identity tests/test_graph_advanced -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add sqlgraph/identity sqlgraph/input sqlgraph/parser sqlgraph/builder sqlgraph/model tests/test_identity tests/test_graph_advanced
git commit -m "feat: add deterministic statement-aware compiler"
```

### Task 3: 增加统一 Baseline Registry

**Files:**
- Create: `sqlgraph/baseline/__init__.py`
- Create: `sqlgraph/baseline/model.py`
- Create: `sqlgraph/baseline/builder.py`
- Create: `schemas/baseline-manifest-v1.schema.json`
- Create: `tests/contract/test_baseline_manifest.py`
- Create: `tests/contract/__init__.py`

- [ ] **Step 1: 写 baseline 确定性和缺失依赖测试**

```python
def test_baseline_id_is_stable_and_timestamp_is_not_identity(tmp_path):
    first = build_test_baseline(tmp_path)
    second = build_test_baseline(tmp_path)
    assert first.baseline_id == second.baseline_id
    assert first.created_at != ""


def test_missing_schema_is_disclosed():
    baseline = build_baseline(SqlSource.from_sql("SELECT a FROM t"))
    assert "schema" in baseline.missing_dependencies
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/contract/test_baseline_manifest.py -q`

Expected: FAIL with `ModuleNotFoundError: sqlgraph.baseline`。

- [ ] **Step 3: 实现 BaselineManifest**

```python
@dataclass(frozen=True)
class BaselineManifest:
    schema_version: str
    baseline_id: str
    source_hashes: tuple[SourceHash, ...]
    dialect: str
    parser_version: str
    identity_rule_version: str
    dependency_hashes: Mapping[str, str]
    missing_dependencies: tuple[str, ...]
    created_at: str
```

`baseline_id` 仅由规范化 source hashes、方言、解析器规则、Schema/UDF/参数/调度哈希生成。

- [ ] **Step 4: 添加 JSON Schema 并验证产物**

使用 `jsonschema` 开发依赖验证 `BaselineManifest.to_dict()`；错误字段必须产生可读异常。

- [ ] **Step 5: 运行契约测试**

Run: `python -m pytest tests/contract/test_baseline_manifest.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add sqlgraph/baseline schemas tests/contract pyproject.toml
git commit -m "feat: add deterministic input baselines"
```

### Task 4: 统一 TableGraph 投影与下钻

**Files:**
- Modify: `sqlgraph/analyze/table_graph.py`
- Create: `sqlgraph/lineage/__init__.py`
- Create: `tests/test_graph_advanced/test_drilldown.py`

- [ ] **Step 1: 写投影可重建测试**

```python
def test_table_edge_drills_to_statement_columns_and_transforms():
    graph = build_graph(
        "INSERT INTO dst SELECT CASE WHEN status='A' THEN amount ELSE 0 END AS value FROM src",
        dialect="spark",
    )
    result = drilldown(graph, "src", "dst")
    assert result.found
    assert result.statements
    assert result.column_paths[0].source_columns == ("amount", "status")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_graph_advanced/test_drilldown.py -q`

Expected: FAIL，当前无统一 `drilldown` 契约。

- [ ] **Step 3: 实现 TableGraph 来源映射**

`TableGraphEdge` 增加：

```python
statement_refs: tuple[StatementRef, ...]
column_dependency_ids: tuple[str, ...]
transform_ids: tuple[str, ...]
```

`drilldown()` 仅从这些引用返回细粒度证据，不按名称重新猜测。

- [ ] **Step 4: 运行分析与下钻测试**

Run: `python -m pytest tests/test_analyze tests/test_graph_advanced/test_drilldown.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add sqlgraph/analyze/table_graph.py sqlgraph/lineage tests/test_graph_advanced/test_drilldown.py
git commit -m "feat: make table lineage fully drillable"
```

### Task 5: 深化 Evidence Engine

**Files:**
- Create: `sqlgraph/evidence/__init__.py`
- Create: `sqlgraph/evidence/model.py`
- Create: `sqlgraph/evidence/engine.py`
- Create: `schemas/evidence-bundle-v1.schema.json`
- Create: `tests/test_evidence/test_engine.py`
- Create: `tests/test_evidence/__init__.py`
- Create: `tests/safety/test_evidence_gates.py`
- Create: `tests/safety/__init__.py`

- [ ] **Step 1: 写覆盖、反证和稳定哈希测试**

```python
def test_evidence_bundle_contains_support_counterevidence_and_exclusions():
    bundle = engine.collect(request)
    assert bundle.supporting
    assert bundle.counterevidence
    assert bundle.excluded
    assert bundle.coverage_contract.required


def test_removed_required_evidence_cannot_remain_sufficient():
    bundle = replace(bundle, included_edges=())
    decision = engine.assess(bundle)
    assert decision.action in {"expand", "degrade", "refuse", "escalate"}
    assert not decision.sufficient
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_evidence tests/safety/test_evidence_gates.py -q`

Expected: FAIL with missing EvidenceEngine。

- [ ] **Step 3: 实现请求、证据包和充分性决议**

实现不可变数据模型：

```python
@dataclass(frozen=True)
class EvidenceRequest:
    task_id: str
    baseline_id: str
    intent: str
    anchors: tuple[str, ...]
    direction: str
    max_depth: int
    coverage_obligations: tuple[str, ...]
    required_external_facts: tuple[str, ...] = ()
```

`subgraph_hash` 对 included、excluded、支持、反对、缺口和规则版本规范化后使用 SHA256。

- [ ] **Step 4: 实现扩图和判停**

`expand()` 必须返回新版本，不可原地篡改；`assess()` 在存在未满足覆盖义务、UNKNOWN/UNRESOLVED 或外部事实缺失时禁止 `stop`。

- [ ] **Step 5: 运行证据和安全测试**

Run: `python -m pytest tests/test_evidence tests/safety/test_evidence_gates.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add sqlgraph/evidence schemas/evidence-bundle-v1.schema.json tests/test_evidence tests/safety
git commit -m "feat: enforce evidence coverage and counterevidence"
```

### Task 6: 增加 GraphRAG 引用校验

**Files:**
- Create: `sqlgraph/graphrag/__init__.py`
- Create: `sqlgraph/graphrag/grounding.py`
- Create: `tests/test_graphrag/test_grounding.py`
- Create: `tests/test_graphrag/__init__.py`
- Modify: `sqlgraph/serialize/graphrag.py`

- [ ] **Step 1: 写伪造引用拒绝测试**

```python
def test_nonexistent_reference_rejects_assertion():
    report = validate_assertions(
        [GroundedAssertion("dst depends on src", citations=("edge_missing",))],
        evidence,
    )
    assert report.status == "rejected"
    assert report.invalid_citations == ("edge_missing",)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_graphrag/test_grounding.py -q`

Expected: FAIL with missing grounding module。

- [ ] **Step 3: 实现 GroundedAssertion 和 GroundingReport**

校验 citation 存在性、baseline/evidence 版本一致性和 coverage 射程。无 citation 的结构性断言状态为 `rejected`。

- [ ] **Step 4: 运行 GraphRAG 测试**

Run: `python -m pytest tests/test_graphrag tests/test_serialize -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add sqlgraph/graphrag sqlgraph/serialize/graphrag.py tests/test_graphrag
git commit -m "feat: validate graphrag assertions against evidence"
```

### Task 7: 移植自治策略并绑定证据版本

**Files:**
- Create: `sqlgraph/autonomy/__init__.py`
- Create: `sqlgraph/autonomy/decision.py`
- Create: `schemas/autonomy-decision-v1.schema.json`
- Create: `tests/test_autonomy/test_decision.py`
- Create: `tests/test_autonomy/__init__.py`
- Create: `tests/safety/test_autonomy_gates.py`

- [ ] **Step 1: 写表驱动安全测试**

```python
@pytest.mark.parametrize(
    ("reversible", "grounded", "scope", "expected"),
    [
        (False, True, "continuous_l5", "L4"),
        (True, False, "single_l3", "L0"),
        (True, True, "none", "L2"),
        (True, True, "single_l3", "L3"),
    ],
)
def test_hard_gates_precede_scoring(reversible, grounded, scope, expected):
    decision = decide_autonomy(action(reversible, grounded, scope, roi=999))
    assert decision.level.value == expected
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_autonomy tests/safety/test_autonomy_gates.py -q`

Expected: FAIL with missing autonomy module。

- [ ] **Step 3: 实现三维决议和可逆性三证据**

`GovernanceAction` 使用：

```python
reversibility = ReversibilityEvidence(
    state_restorable=True,
    external_effects_controlled=True,
    rollback_verified=True,
)
```

输出包含 `level`、`requires_human_review`、`within_l5_scope`、`policy_version`、`evidence_version` 和命中闸门。

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/test_autonomy tests/safety/test_autonomy_gates.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add sqlgraph/autonomy schemas/autonomy-decision-v1.schema.json tests/test_autonomy tests/safety/test_autonomy_gates.py
git commit -m "feat: enforce evidence and reversibility autonomy gates"
```

### Task 8: 实现 Action Engine、幂等和回滚

**Files:**
- Create: `sqlgraph/actions/__init__.py`
- Create: `sqlgraph/actions/model.py`
- Create: `sqlgraph/actions/engine.py`
- Create: `sqlgraph/actions/adapters.py`
- Create: `schemas/action-plan-v1.schema.json`
- Create: `tests/test_actions/test_engine.py`
- Create: `tests/test_actions/__init__.py`
- Create: `tests/safety/test_execution_recovery.py`

- [ ] **Step 1: 写幂等、故障和回滚测试**

```python
def test_repeat_execution_is_noop(engine, plan):
    first = engine.execute(plan)
    second = engine.execute(plan)
    assert first.status == "success"
    assert second.status == "noop"
    assert second.execution_id == first.execution_id


def test_injected_failure_opens_circuit_and_restores_snapshot(engine, failing_plan):
    result = engine.execute(failing_plan)
    assert result.status == "rolled_back"
    assert result.circuit_open
    assert result.rollback.verified
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_actions tests/safety/test_execution_recovery.py -q`

Expected: FAIL with missing ActionEngine。

- [ ] **Step 3: 实现动作模型和 engine**

`ActionPlan` 必须包含 `task_id`、`baseline_id`、`evidence_version`、`decision_id`、`idempotency_key`、`adapter`、`operations` 和 `rollback_plan`。

- [ ] **Step 4: 实现两个 adapter**

`SqlFilePatchAdapter` 使用前置 SHA256 和备份恢复；`DuckDBTaskAdapter` 使用数据库快照、任务白名单和故障注入点。二者都实现 `dry_run/execute/rollback/verify_rollback`。

- [ ] **Step 5: 运行测试**

Run: `python -m pytest tests/test_actions tests/safety/test_execution_recovery.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add sqlgraph/actions schemas/action-plan-v1.schema.json tests/test_actions tests/safety/test_execution_recovery.py
git commit -m "feat: add idempotent actions and verified rollback"
```

### Task 9: 实现独立三层 Verification

**Files:**
- Create: `sqlgraph/verification/__init__.py`
- Create: `sqlgraph/verification/model.py`
- Create: `sqlgraph/verification/engine.py`
- Create: `schemas/verification-report-v1.schema.json`
- Create: `sqlgraph/verify/__init__.py`
- Create: `tests/test_verification/test_engine.py`
- Create: `tests/test_verification/__init__.py`
- Create: `tests/safety/test_verification_failure.py`

- [ ] **Step 1: 写独立重抽和失败决议测试**

```python
def test_structure_verification_rebuilds_from_changed_source(tmp_path):
    report = verifier.verify(plan, execution)
    assert report.structure.evidence["rebuilt_from_source"] is True


def test_any_critical_failure_blocks_success():
    report = VerificationReport(code=passed(), structure=failed(), runtime=passed())
    assert report.outcome == "failed"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_verification tests/safety/test_verification_failure.py -q`

Expected: FAIL with missing verification module。

- [ ] **Step 3: 实现 code/structure/runtime verifier**

结构 verifier 从变更后的 SQL 路径调用 `build_baseline()` 和 `build_graph()`，不得读取执行阶段保存的图成功标志。

- [ ] **Step 4: 提供旧接口兼容层**

`sqlgraph.verify.verify()` 构造新 verifier 所需的只读输入并返回兼容字典，不复制验证规则。

- [ ] **Step 5: 运行验证和分析回归**

Run: `python -m pytest tests/test_verification tests/safety/test_verification_failure.py tests/test_analyze -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add sqlgraph/verification sqlgraph/verify schemas/verification-report-v1.schema.json tests/test_verification tests/safety/test_verification_failure.py
git commit -m "feat: add independent three-layer verification"
```

### Task 10: 实现追加式 Audit 与 GovernanceRunner

**Files:**
- Create: `sqlgraph/audit/__init__.py`
- Create: `sqlgraph/audit/model.py`
- Create: `sqlgraph/audit/log.py`
- Create: `schemas/audit-event-v1.schema.json`
- Create: `sqlgraph/reasoning/__init__.py`
- Create: `sqlgraph/reasoning/runner.py`
- Create: `sqlgraph/agent/__init__.py`
- Create: `tests/test_audit/test_log.py`
- Create: `tests/test_audit/__init__.py`
- Create: `tests/test_reasoning/test_runner.py`
- Create: `tests/test_reasoning/__init__.py`
- Create: `tests/safety/test_audit_integrity.py`

- [ ] **Step 1: 写哈希链、篡改和七步重放测试**

```python
def test_tampered_event_breaks_integrity(audit_path):
    log = AuditLog(audit_path)
    append_three_events(log)
    tamper_second_line(audit_path)
    assert not log.verify_integrity().valid


def test_runner_exports_all_seven_steps(runner):
    result = runner.run(request)
    assert [event.step for event in result.events] == [
        "observe", "explain", "propose", "authorize", "execute", "verify", "learn"
    ]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_audit tests/test_reasoning tests/safety/test_audit_integrity.py -q`

Expected: FAIL with missing audit/reasoning modules。

- [ ] **Step 3: 实现 canonical JSON 哈希链**

`event_hash = SHA256(canonical_json(event_without_hash))`，每条事件保存 `previous_hash`。首事件使用 64 个零字符。

- [ ] **Step 4: 实现 GovernanceRunner**

runner 通过构造参数接收 Baseline、Evidence、Autonomy、Action、Verification 和 Audit 模块。证据不足在 `authorize` 前停止；执行或验证失败时记录熔断和回滚事件。

- [ ] **Step 5: 增加兼容入口并运行测试**

Run: `python -m pytest tests/test_audit tests/test_reasoning tests/safety/test_audit_integrity.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add sqlgraph/audit sqlgraph/reasoning sqlgraph/agent schemas/audit-event-v1.schema.json tests/test_audit tests/test_reasoning tests/safety/test_audit_integrity.py
git commit -m "feat: add replayable governance audit chain"
```

### Task 11: 增加治理 CLI 和三条书中案例

**Files:**
- Modify: `sqlgraph/cli.py`
- Create: `examples/minimal/scenario.yaml`
- Create: `examples/minimal/sql/source.sql`
- Create: `examples/book_cases/caliber_consistency/scenario.yaml`
- Create: `examples/book_cases/cold_table_retirement/scenario.yaml`
- Create: `examples/book_cases/irreversible_drop/scenario.yaml`
- Create: `sqlgraph/reasoning/scenario.py`
- Create: `tests/test_integration/test_book_cases.py`
- Create: `tests/test_cli/test_governance_cli.py`

- [ ] **Step 1: 写 CLI 和场景验收测试**

```python
@pytest.mark.parametrize(
    ("case", "outcome"),
    [
        ("caliber_consistency", "success"),
        ("cold_table_retirement", "success"),
        ("irreversible_drop", "held_for_human_review"),
    ],
)
def test_book_case_exports_replayable_bundle(case, outcome, tmp_path):
    result = run_case(case, tmp_path)
    assert result.outcome == outcome
    assert AuditLog(result.audit_path).verify_integrity().valid
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_cli/test_governance_cli.py tests/test_integration/test_book_cases.py -q`

Expected: FAIL，`governance` 命令和场景不存在。

- [ ] **Step 3: 实现 YAML 场景加载与 CLI**

新增：

```text
sqlgraph governance run <scenario> -o <output>
sqlgraph governance replay <audit.jsonl>
sqlgraph governance verify <output>
```

场景只允许引用注册 adapter 和动作模板，不执行任意 Python。

- [ ] **Step 4: 运行三条案例**

Run: `python -m pytest tests/test_cli/test_governance_cli.py tests/test_integration/test_book_cases.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add sqlgraph/cli.py sqlgraph/reasoning/scenario.py examples/minimal examples/book_cases tests/test_cli/test_governance_cli.py tests/test_integration/test_book_cases.py
git commit -m "feat: add runnable book governance cases"
```

### Task 12: 移植视频商业化数仓与 GitHub 样式工作台

**Files:**
- Create: `examples/video_commercial_warehouse/`
- Create: `tests/test_video_warehouse/`
- Create: `sqlgraph/serve/theme.py`
- Modify: `examples/video_commercial_warehouse/report.py`
- Modify: `examples/video_commercial_warehouse/templates/workbench.html`
- Modify: `sqlgraph/serve/web/static/app.css`

- [ ] **Step 1: 写共享样式和离线报告测试**

```python
def test_workbench_inlines_explorer_theme(tmp_path):
    html = render_demo_report(tmp_path).read_text()
    assert "--bg: #0b1020" in html or "--bg:#0b1020" in html
    assert "SqlGraph Explorer" in html
    assert "https://" not in html
    assert 'class="app-tabs product-nav"' in html
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_video_warehouse/test_report.py -q`

Expected: FAIL，综合案例尚未移植。

- [ ] **Step 3: 移植 94 表、62 任务 DuckDB 案例**

只移植 `examples/video_commercial_warehouse/` 和对应测试；数据库、生成报告和截图不进入 Git。

- [ ] **Step 4: 共享 Explorer CSS**

`sqlgraph.serve.theme.load_explorer_css()` 读取包内 `app.css`。报告渲染器将其内容注入 `__EXPLORER_CSS__`，再注入工作台专用 CSS，确保离线单文件运行。

- [ ] **Step 5: 运行报告和浏览器测试**

Run: `python -m pytest tests/test_video_warehouse tests/test_serve -q`

Expected: PASS。浏览器验证 1440x1000 和 390x844 无横向溢出。

- [ ] **Step 6: 提交**

```bash
git add examples/video_commercial_warehouse tests/test_video_warehouse sqlgraph/serve/theme.py sqlgraph/serve/web/static/app.css
git commit -m "feat: add github-aligned governance workbench"
```

### Task 13: 建立能力账本和书—代码映射

**Files:**
- Create: `CAPABILITIES.yaml`
- Create: `schemas/capabilities-v1.schema.json`
- Create: `docs/book-map.md`
- Create: `docs/theory-vs-implementation.md`
- Create: `docs/limitations.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/architecture.md`
- Create: `tools/check_capabilities.py`
- Create: `tests/contract/test_capabilities.py`

- [ ] **Step 1: 写能力账本路径真实性测试**

```python
def test_implemented_capabilities_reference_existing_assets():
    ledger = load_capabilities("CAPABILITIES.yaml")
    for capability in ledger["capabilities"]:
        if capability["status"] == "implemented":
            assert all(Path(path).exists() for path in capability["modules"])
            assert all(Path(path).exists() for path in capability["tests"])
            assert all(Path(path).exists() for path in capability["examples"])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/contract/test_capabilities.py -q`

Expected: FAIL，能力账本不存在。

- [ ] **Step 3: 写能力账本和三份边界文档**

十二类最低能力逐项填写状态。embedding、多智能体和生产 adapter 标为 `experimental` 或 `planned`；未通过当前测试的能力不得标为 `implemented`。

- [ ] **Step 4: 更新中英文 README**

Quickstart 必须从 clone、安装到生成并验证完整事件包；命令仅引用当前实际存在的 CLI。

- [ ] **Step 5: 运行账本检查**

Run: `python tools/check_capabilities.py && python -m pytest tests/contract/test_capabilities.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add CAPABILITIES.yaml schemas/capabilities-v1.schema.json docs README.md README.zh-CN.md tools/check_capabilities.py tests/contract/test_capabilities.py
git commit -m "docs: publish capability and book mappings"
```

### Task 14: 扩展黄金、安全和规模验证

**Files:**
- Modify: `tests/golden/`
- Create: `tests/scale/test_generated_warehouse.py`
- Create: `tools/benchmark_scale.py`
- Create: `.github/workflows/scale.yml`
- Modify: `.github/workflows/ci.yml`
- Create: `tools/ci_checks.sh`
- Create: `tools/check_layering.py`
- Create: `tools/check_random_ids.py`
- Create: `tools/check_release_assets.py`

- [ ] **Step 1: 增加至少 20 组黄金 SQL**

每组 fixture 配套规范化 snapshot，覆盖设计规格列出的语法、方言和失败诊断。测试断言 fixture 数量不少于 20。

- [ ] **Step 2: 增加分层规模基准**

```python
@pytest.mark.parametrize("count", [100])
def test_generated_sql_scale_smoke(count, tmp_path):
    result = run_scale_benchmark(count, tmp_path)
    assert result.parsed == count
    assert result.deterministic
    assert result.peak_memory_mb > 0
```

手工 workflow 执行：

```bash
python tools/benchmark_scale.py --counts 1000,10000 --output .benchmarks/result.json
```

- [ ] **Step 3: 接入 CI 门禁**

普通 CI 运行 lint、类型、分层、随机 ID、单元、契约、黄金、端到端、安全、100 SQL 规模、能力账本、开源 guard 和构建包 Quickstart。

- [ ] **Step 4: 运行完整本地门禁**

Run: `PYTHON=python bash tools/ci_checks.sh`

Expected: 所有阶段通过，覆盖率达到脚本设定阈值。

- [ ] **Step 5: 提交**

```bash
git add tests/golden tests/scale tools .github/workflows
git commit -m "test: enforce release governance gates"
```

### Task 15: 发布验收、敏感文件审计和 GitHub 推送

**Files:**
- Modify: `pyproject.toml`
- Modify: `LICENSE`
- Modify: `CONTRIBUTING.md`
- Create: `docs/release-evidence.md`

- [ ] **Step 1: 验证打包和十分钟 Quickstart**

Run:

```bash
python -m build
python -m venv /tmp/sqlgraph-release-venv
/tmp/sqlgraph-release-venv/bin/pip install dist/*.whl
/tmp/sqlgraph-release-venv/bin/sqlgraph governance run examples/minimal/scenario.yaml -o /tmp/sqlgraph-quickstart
/tmp/sqlgraph-release-venv/bin/sqlgraph governance verify /tmp/sqlgraph-quickstart
```

Expected: 安装成功、案例成功、审计完整性通过。

- [ ] **Step 2: 运行全部测试与规模基准**

Run:

```bash
PYTHON=python bash tools/ci_checks.sh
python tools/benchmark_scale.py --counts 1000,10000 --output .benchmarks/release.json
```

Expected: 全部通过，并输出资源指标。

- [ ] **Step 3: 浏览器验证**

启动本地服务，验证 Explorer 和治理工作台在 1440x1000、390x844 下无空白、遮挡或横向溢出，且控制台无错误。

- [ ] **Step 4: 写发布证据**

`docs/release-evidence.md` 记录六条门槛对应命令、测试、产物和结果摘要，不提交 `.benchmarks/`、HTML、DuckDB 或截图。

- [ ] **Step 5: 审计提交范围**

Run:

```bash
git status --short
git diff origin/main...HEAD --check
python scripts/opensource_guard.py
git ls-files | rg '(^book|\\.zip$|\\.duckdb$|comparison-screenshots|generated_illustrations)'
```

Expected: 最后一条无输出；其余检查通过。

- [ ] **Step 6: 最终提交**

```bash
git add pyproject.toml LICENSE CONTRIBUTING.md docs/release-evidence.md
git commit -m "chore: prepare governance reference release"
```

- [ ] **Step 7: 推送功能分支**

```bash
git push -u origin feat/book-governance-reference
```

Expected: 推送成功，远端分支可用于 Pull Request；不直接合并或强推 `main`。
