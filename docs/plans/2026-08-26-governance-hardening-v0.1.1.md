# Governance Hardening v0.1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the v0.1.0 lineage, rollback, idempotency, authorization, reversibility, CI, and documentation defects and publish a verified v0.1.1 patch release.

**Architecture:** Keep existing public graph and governance modules, but move trust decisions behind explicit verifier/adapter interfaces. Parser ownership remains statement-local; action state becomes terminal-state aware; release validation installs the built wheel in a clean environment.

**Tech Stack:** Python 3.10-3.12, SQLGlot, DuckDB, Typer, pytest, Ruff, GitHub Actions, Twine.

---

### Task 1: Fix chained multi-statement lineage

**Files:**
- Modify: `sqlgraph/parser/base.py:350-378`
- Modify: `tests/test_identity/test_determinism.py`

- [ ] **Step 1: Add failing chained-statement tests**

```python
def test_previous_target_can_be_next_statement_source():
    graph = build_graph(
        "INSERT INTO mid SELECT id FROM src;"
        "INSERT INTO dst SELECT id FROM mid;",
        dialect="spark",
    )
    assert _table_pairs(graph) == {("src", "mid"), ("mid", "dst")}


def test_self_read_keeps_read_and_write_ownership():
    graph = build_graph(
        "INSERT INTO snapshot SELECT id FROM snapshot",
        dialect="spark",
    )
    edge_types = {
        edge.edge_type
        for edge in graph.edges
        if edge.target_id == graph.get_node_by_name("snapshot").id
    }
    assert EdgeType.READS_FROM in edge_types
    assert EdgeType.WRITES_TO in edge_types
```

- [ ] **Step 2: Verify red**

Run: `python -m pytest tests/test_identity/test_determinism.py -q`

Expected: chained case misses `mid -> dst`; self-read misses `reads_from`.

- [ ] **Step 3: Remove global target suppression**

In `_parse_select`, deduplicate only against sources added since
`_statement_source_start`. Do not suppress a real `FROM` table because it exists
in `result.target_tables`.

- [ ] **Step 4: Verify parser and graph tests**

Run: `python -m pytest tests/test_parser tests/test_builder tests/test_identity tests/test_graph_advanced -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sqlgraph/parser/base.py tests/test_identity/test_determinism.py
git commit -m "fix: preserve chained statement lineage"
```

### Task 2: Fix sequential file patches and rollback

**Files:**
- Modify: `sqlgraph/actions/adapters.py`
- Modify: `tests/test_actions/test_engine.py`
- Modify: `tests/safety/test_execution_recovery.py`

- [ ] **Step 1: Add failing sequential-operation tests**

```python
def test_sequential_dry_run_uses_simulated_content(tmp_path):
    path = tmp_path / "q.sql"
    path.write_text("A B", encoding="utf-8")
    operations = (
        operation(path, "A B", "X B"),
        operation(path, "X B", "X Y"),
    )
    assert SqlFilePatchAdapter().dry_run(operations)
    assert path.read_text() == "A B"


def test_multi_patch_failure_restores_true_original(tmp_path):
    path = tmp_path / "q.sql"
    path.write_text("A B", encoding="utf-8")
    operations = (
        operation(path, "A", "X"),
        operation(path, "B", "Y", inject_failure=True),
    )
    with pytest.raises(AdapterExecutionError) as caught:
        SqlFilePatchAdapter().execute(operations)
    rollback = SqlFilePatchAdapter().rollback(caught.value.rollback_state)
    assert rollback.verified
    assert path.read_text() == "A B"
```

- [ ] **Step 2: Verify red**

Run: `python -m pytest tests/test_actions tests/safety/test_execution_recovery.py -q`

Expected: dry run rejects the second sequential operation or rollback restores
`X B`.

- [ ] **Step 3: Implement sequential simulation**

Add a private `_simulate(operations)` helper that loads each path once, validates
each operation against the simulated current content, and returns final
contents plus checks. `dry_run()` must not write files.

- [ ] **Step 4: Preserve original state once**

Use:

```python
originals.setdefault(str(path), content)
```

Rollback verifies SHA256 for every restored path before reporting success.

- [ ] **Step 5: Verify**

Run: `python -m pytest tests/test_actions tests/safety/test_execution_recovery.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sqlgraph/actions/adapters.py tests/test_actions tests/safety/test_execution_recovery.py
git commit -m "fix: restore original state for sequential patches"
```

### Task 3: Fix idempotency state after rollback

**Files:**
- Modify: `sqlgraph/actions/engine.py`
- Modify: `tests/test_actions/test_engine.py`
- Modify: `tests/safety/test_verification_failure.py`

- [ ] **Step 1: Add failing post-rollback test**

```python
def test_rolled_back_execution_is_not_cached_as_success(engine, plan):
    execution = engine.execute(plan)
    rollback = engine.rollback_execution(plan, execution)
    repeated = engine.execute(plan)
    assert rollback.verified
    assert repeated.status == "blocked"
    assert repeated.status != "noop"
```

- [ ] **Step 2: Verify red**

Run: `python -m pytest tests/test_actions tests/safety/test_verification_failure.py -q`

Expected: repeat returns `noop`.

- [ ] **Step 3: Record terminal state**

`rollback_execution()` replaces `_executions[plan.idempotency_key]` with an
`ExecutionResult` whose status is `rolled_back` or `rollback_failed`. It removes
the consumed rollback state and opens the circuit.

- [ ] **Step 4: Verify**

Run: `python -m pytest tests/test_actions tests/safety/test_verification_failure.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sqlgraph/actions/engine.py tests/test_actions tests/safety/test_verification_failure.py
git commit -m "fix: invalidate idempotency success after rollback"
```

### Task 4: Add verified authorization grants

**Files:**
- Create: `sqlgraph/autonomy/authorization.py`
- Modify: `sqlgraph/autonomy/__init__.py`
- Modify: `sqlgraph/autonomy/decision.py`
- Modify: `sqlgraph/reasoning/runner.py`
- Modify: `sqlgraph/reasoning/scenario.py`
- Modify: `examples/video_commercial_warehouse/governance.py`
- Modify: `tests/test_autonomy/test_decision.py`
- Modify: `tests/safety/test_autonomy_gates.py`

- [ ] **Step 1: Add failing authorization tests**

```python
def test_unknown_identity_cannot_authorize_l3():
    verifier = StaticAuthorizationVerifier({})
    verification = verifier.verify(
        "invented-policy", "sql_patch", AuthorizationScope.SINGLE_L3
    )
    decision = decide_autonomy(action("invented-policy"), verification)
    assert decision.level == AutonomyLevel.L2_PROPOSE
    assert decision.authorization_veto


def test_action_outside_grant_is_rejected():
    verifier = reference_authorization_verifier()
    verification = verifier.verify(
        "quickstart-policy", "drop_table", AuthorizationScope.SINGLE_L3
    )
    assert not verification.verified
```

- [ ] **Step 2: Verify red**

Run: `python -m pytest tests/test_autonomy tests/safety/test_autonomy_gates.py -q`

Expected: authorization verifier symbols are missing.

- [ ] **Step 3: Implement verifier contracts**

Create immutable `AuthorizationGrant` and `AuthorizationVerification`, a
protocol, and `StaticAuthorizationVerifier`. Scope ordering is:

```python
NONE < SINGLE_L3 < CONTINUOUS_L5
```

Verification requires known identity, allowed action, and requested scope no
greater than the grant.

- [ ] **Step 4: Require verification in autonomy decisions**

`decide_autonomy(action, authorization)` stops at L2 when a non-NONE request
lacks a verified grant. Decision output records grant ID and verifier.

- [ ] **Step 5: Wire reference grants**

Scenario execution resolves authorization through the code-owned reference
registry. Add `video-workbench-policy` to the video case. YAML identity is only
a lookup key.

- [ ] **Step 6: Verify**

Run: `python -m pytest tests/test_autonomy tests/safety/test_autonomy_gates.py tests/test_reasoning tests/test_video_warehouse -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add sqlgraph/autonomy sqlgraph/reasoning examples/video_commercial_warehouse/governance.py tests/test_autonomy tests/safety/test_autonomy_gates.py tests/test_reasoning tests/test_video_warehouse
git commit -m "fix: verify authorization grants before autonomy"
```

### Task 5: Generate reversibility evidence in adapters

**Files:**
- Modify: `sqlgraph/actions/adapters.py`
- Modify: `sqlgraph/actions/engine.py`
- Modify: `sqlgraph/reasoning/runner.py`
- Modify: `sqlgraph/agent/__init__.py`
- Modify: `tests/test_actions/test_engine.py`
- Modify: `tests/test_reasoning/test_runner.py`
- Modify: `tests/safety/test_execution_recovery.py`

- [ ] **Step 1: Add failing trust-boundary tests**

```python
def test_runner_ignores_caller_reversibility_claim(tmp_path):
    action = replace(
        authorized_action(),
        reversibility=ReversibilityEvidence(True, True, True),
    )
    engine = ActionEngine([RejectingReversibilityAdapter()])
    result = runner(engine).run(request(action))
    assert result.decision.reversibility_veto
    assert result.execution.status == "blocked"


def test_sql_file_adapter_verifies_recovery_on_isolated_copy(tmp_path):
    evidence = SqlFilePatchAdapter().verify_reversibility(operations(tmp_path))
    assert evidence.verified
    assert evidence.references
```

- [ ] **Step 2: Verify red**

Run: `python -m pytest tests/test_actions tests/test_reasoning tests/safety/test_execution_recovery.py -q`

Expected: adapters lack `verify_reversibility`, or caller claim is accepted.

- [ ] **Step 3: Add adapter probes**

SQL files use a temporary copy and compare the restored SHA256. DuckDB uses a
temporary database copy, executes statements, restores the snapshot, and
compares bytes.

- [ ] **Step 4: Make runner authoritative**

Before autonomy calculation:

```python
verified = action_engine.verify_reversibility(adapter, operations)
action = replace(action, reversibility=verified)
```

Scenario-provided reversibility booleans are removed from decision input.

- [ ] **Step 5: Reduce legacy facade duplication**

Move shared evidence, authorization, decision, and verification preparation into
helpers under `sqlgraph/reasoning/`. `GovernanceLoop` delegates to those helpers
and only adapts the old result shape.

- [ ] **Step 6: Verify**

Run: `python -m pytest tests/test_actions tests/test_reasoning tests/safety tests/test_video_warehouse -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add sqlgraph/actions sqlgraph/reasoning sqlgraph/agent tests/test_actions tests/test_reasoning tests/safety
git commit -m "fix: derive reversibility from action adapters"
```

### Task 6: Add installed-wheel CI and align documentation

**Files:**
- Modify: `tools/ci_checks.sh`
- Modify: `.github/workflows/ci.yml`
- Modify: `pyproject.toml`
- Modify: `CONTRIBUTING.md`
- Modify: `docs/architecture.md`
- Modify: `docs/limitations.md`
- Modify: `CAPABILITIES.yaml`
- Modify: `docs/release-evidence.md`
- Create: `tests/test_release/test_installed_quickstart_gate.py`

- [ ] **Step 1: Add failing CI-contract test**

```python
def test_ci_installs_built_wheel_and_runs_quickstart():
    script = Path("tools/ci_checks.sh").read_text()
    assert "pip install" in script
    assert "dist/*.whl" in script
    assert "governance run examples/minimal/scenario.yaml" in script
    assert "governance verify" in script
```

- [ ] **Step 2: Verify red**

Run: `python -m pytest tests/test_release/test_installed_quickstart_gate.py -q`

Expected: FAIL.

- [ ] **Step 3: Add clean installed-wheel gate**

Use `mktemp -d`, `python -m venv`, install `dist/*.whl`, run and verify the
minimal scenario, assert seven audit records, and clean with `trap`.

- [ ] **Step 4: Align docs and capability claims**

Set version to `0.1.1`; update Python 3.10-3.12, SHA256, expression operand DAG,
reference authorization, adapter-generated reversibility, and local-process
limitations.

- [ ] **Step 5: Run complete release checks**

Run: `PYTHON=python bash tools/ci_checks.sh`

Expected: all tests, 85% foundation coverage, clean-wheel Quickstart, and package
build pass.

- [ ] **Step 6: Run scale and browser regressions**

Run:

```bash
python tools/benchmark_scale.py --counts 1000,10000 --output .benchmarks/v0.1.1.json
```

Verify governance workbench at 1440x1000 and 390x844 with no overflow or console
errors.

- [ ] **Step 7: Commit**

```bash
git add tools/ci_checks.sh .github/workflows/ci.yml pyproject.toml CONTRIBUTING.md docs CAPABILITIES.yaml tests/test_release
git commit -m "chore: prepare governance hardening v0.1.1"
```

### Task 7: Publish v0.1.1

**Files:**
- No source changes expected.

- [ ] **Step 1: Audit branch**

Run:

```bash
git status --short
git diff origin/main...HEAD --check
python scripts/opensource_guard.py
python tools/check_release_assets.py
```

Expected: clean worktree and all checks pass.

- [ ] **Step 2: Push and open PR**

Push `fix/governance-hardening-v0.1.1`, create a PR to `main`, and wait for
Python 3.10-3.12 CI.

- [ ] **Step 3: Merge after green CI**

Use a merge commit, fetch `origin/main`, and verify the merge tree matches the
reviewed branch tree.

- [ ] **Step 4: Build and verify release assets**

Build wheel/sdist from the merged tree, install the wheel in a clean Python 3.12
environment, run governance Quickstart, and generate path-independent
`SHA256SUMS`.

- [ ] **Step 5: Create GitHub Release**

Create `v0.1.1` against the merge commit and upload wheel, sdist, and
`SHA256SUMS`. Download all three and verify checksums.

- [ ] **Step 6: Upload to PyPI when credentials are visible**

Run:

```bash
python -m twine check dist/sqlgraph_lineage-0.1.1*
python -m twine upload --non-interactive \
  dist/sqlgraph_lineage-0.1.1-py3-none-any.whl \
  dist/sqlgraph_lineage-0.1.1.tar.gz
```

Then query `https://pypi.org/pypi/sqlgraph-lineage/0.1.1/json`, install from
PyPI in a fresh environment, and run the minimal governance Quickstart.
