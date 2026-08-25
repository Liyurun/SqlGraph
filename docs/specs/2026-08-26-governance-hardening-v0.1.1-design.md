# Governance Hardening v0.1.1 Design

## Goal

Fix the correctness and trust-boundary defects found after the v0.1.0 review,
then publish a backward-conscious v0.1.1 patch release.

The patch must:

1. preserve existing build, analyze, profile, serve, playground, and demo flows;
2. restore complete lineage for statement chains in one SQL file;
3. make multi-operation rollback restore the true pre-action state;
4. prevent rolled-back executions from being treated as successful idempotent runs;
5. prevent scenario files from self-asserting authorization or reversibility;
6. verify the built wheel through an installed Quickstart in CI;
7. align documentation and capability claims with actual behavior.

## Scope

### Included

- SQL parser statement-local source/target ownership.
- Sequential file-patch dry runs and rollback state.
- Action-engine idempotency state transitions.
- Authorization verifier contract and reference static grant registry.
- Adapter-generated reversibility evidence.
- Governance runner integration with the two trust verifiers.
- CI wheel installation and Quickstart execution.
- Documentation and capability-ledger corrections.
- v0.1.1 branch, pull request, release assets, and release verification.
- PyPI upload only after a credential is visible to the publishing process.

### Excluded

- Enterprise IAM, approval platforms, distributed locks, or remote schedulers.
- Redesigning the graph model or Explorer UI.
- Changing the v0.1.0 tag or its immutable release assets.
- Publishing an unverified package to PyPI.

## 1. Statement-Local Lineage

The parser must treat every table appearing in a `FROM` or `JOIN` clause as a
source for that statement, even if the same table was a target of an earlier
statement in the same file.

The current global check against `result.target_tables` is removed. Source
deduplication remains local to the current statement.

Acceptance case:

```sql
INSERT INTO mid SELECT id FROM src;
INSERT INTO dst SELECT id FROM mid;
```

Expected table lineage:

```text
src -> mid
mid -> dst
```

Self-read statements retain both `reads_from` and `writes_to`; the table-level
self-loop remains excluded by the graph projection.

## 2. Sequential File Patches and Rollback

`SqlFilePatchAdapter` must evaluate operations in order.

### Dry run

- Load each target file once into an in-memory state map.
- For each operation, validate its precondition against the simulated current
  content, apply the replacement in memory, and continue.
- Reject ambiguous matches before touching disk.

### Execution

- Save the original content once with `setdefault`.
- Apply operations sequentially.
- Preserve the first pre-action state even when several operations target the
  same file.

### Rollback

- Restore the first pre-action state.
- Read the file back and compare SHA256 with the original.
- Report success only when every target matches its original hash.

## 3. Idempotency After Rollback

Execution state is no longer represented only by a cached successful result.

The engine maintains a terminal state per idempotency key:

- `success`: repeat returns `noop`.
- `rolled_back`: repeat is blocked while the circuit is open.
- `rollback_failed`: repeat is blocked and requires human recovery.
- `failed`: repeat is blocked while the circuit is open.

`rollback_execution()` replaces the cached success record with a rolled-back or
rollback-failed record. A reverted action can never return a successful `noop`.

## 4. Authorization Trust Boundary

Add an authorization verifier interface:

```python
class AuthorizationVerifier(Protocol):
    def verify(
        self,
        identity: str,
        action_type: str,
        requested_scope: AuthorizationScope,
    ) -> AuthorizationVerification:
        ...
```

`AuthorizationVerification` includes:

- `verified`
- `grant_id`
- `identity`
- `granted_scope`
- `allowed_actions`
- `reason`
- `verifier`

`decide_autonomy()` accepts a verification result rather than trusting
`authorization_scope` alone. Any non-`NONE` scope without a verified grant stops
at L2.

The repository supplies a `StaticAuthorizationVerifier` for examples. Its grants
are code-owned policy data, not read from scenario YAML:

- `quickstart-policy`: `sql_patch`, maximum `single_l3`
- `book-demo-policy`: `sql_patch` and `quarantine_cold_table`, maximum `single_l3`
- `video-workbench-policy`: `fix_creative_ctr_ratio`, maximum `single_l3`

Production callers must inject their own verifier.

## 5. Adapter-Generated Reversibility Evidence

Scenario YAML may describe the intended action but cannot assert that rollback
was verified.

Action adapters add:

```python
def verify_reversibility(
    operations: tuple[dict[str, Any], ...],
) -> ReversibilityEvidence:
    ...
```

### SQL file adapter

- Performs the sequential dry-run simulation.
- Applies and restores the operation sequence on an isolated temporary copy.
- Compares the restored copy with the original SHA256.
- Returns evidence references generated by the adapter.

### DuckDB adapter

- Copies the database to an isolated temporary directory.
- Executes the statements on the temporary database.
- Restores from its snapshot.
- Verifies restored bytes against the pre-execution hash.

`GovernanceRunner` replaces any caller-supplied reversibility fields with the
adapter result before calling `decide_autonomy()`.

## 6. Compatibility GovernanceLoop

`sqlgraph.agent.GovernanceLoop` remains importable for v0.1.x compatibility, but
must not contain independent authorization or reversibility rules.

Shared decision preparation moves to a helper used by both `GovernanceRunner`
and the compatibility facade. The compatibility facade is documented as
deprecated and only adapts its legacy report shape.

## 7. CI Installed Quickstart

After building wheel and sdist, `tools/ci_checks.sh` must:

1. create a temporary Python virtual environment;
2. install the built wheel with dependencies;
3. run `sqlgraph governance run examples/minimal/scenario.yaml`;
4. run `sqlgraph governance verify`;
5. assert seven audit events and successful integrity;
6. delete the temporary environment.

The Python 3.12 GitHub job executes this release gate. Python 3.10 and 3.11
continue to run the full test suite.

## 8. Documentation and Capability Status

Update:

- `CONTRIBUTING.md`: Python 3.10-3.12.
- `docs/architecture.md`: SHA256 identities and root-plus-operands expression DAG.
- `CAPABILITIES.yaml`: explicitly state that the bundled verifier and adapters are
  reference implementations; production authorization remains adapter-defined.
- `docs/limitations.md`: idempotency and rollback are local-process guarantees.
- `docs/release-evidence.md`: add v0.1.1 regression and installed-wheel evidence.

## Tests

Required new tests:

- chained multi-statement target-to-source lineage;
- self-read statement ownership;
- two patches on the same file restore the original content;
- sequential dry-run preconditions;
- post-verification rollback cannot return `noop`;
- unknown authorization identity is rejected;
- action outside a grant is rejected;
- known grant is accepted;
- scenario-provided reversibility booleans cannot override adapter evidence;
- SQL-file and DuckDB reversibility probes produce verified evidence;
- CI script contains and successfully runs installed-wheel Quickstart.

All existing tests, open-source checks, golden tests, 100-SQL smoke benchmark,
and browser regressions must remain green.

## Release

- Branch: `fix/governance-hardening-v0.1.1`
- Version: `0.1.1`
- Pull request into `main`
- GitHub Release: `v0.1.1`
- Attach wheel, sdist, and path-independent `SHA256SUMS`
- Verify downloaded assets and a clean PyPI-style installation
- Upload to PyPI only when the publishing process can read a valid token
