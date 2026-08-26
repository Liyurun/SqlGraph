# Governance Reference Release Evidence

## Release Gates

| Gate | Evidence | Result |
|---|---|---|
| Ten-minute runnable | Wheel installed in a clean Python 3.12 virtual environment; `governance run`, `verify`, and `replay` completed | Pass |
| Honest capability status | `CAPABILITIES.yaml` validated against JSON Schema and repository paths | Pass |
| Core safety | Evidence, Grounding, autonomy, idempotency, rollback, verification, and audit tamper tests | Pass |
| Three book cases | Caliber consistency, cold-table quarantine, and destructive action held at the verified grant boundary | Pass |
| Full replay | Every case emits seven hash-chained events and passes integrity verification | Pass |
| Explicit limitations | `docs/limitations.md` and capability-level limitations | Pass |

## Automated Validation

- Unified release gate: `PYTHON=python bash tools/ci_checks.sh`
- Tests: 361 passed in the v0.1.1 complete release-gate run.
- Foundation coverage: 89.29%, above the 85% gate.
- Golden corpus: 5 byte-for-byte graph snapshots plus 15 syntax/dialect cases.
- Package build: source distribution and wheel completed.
- Installed-wheel gate: Python 3.12 clean environment, successful minimal
  governance run, valid verification, and exactly seven audit events.
- Open-source guard, layering, deterministic-ID, capability, and release-asset
  checks passed.

## v0.1.1 Hardening

- Chained statements retain target-to-source lineage and self-read ownership.
- Sequential patches restore the true pre-action state.
- Rolled-back executions cannot be returned as successful idempotent no-ops.
- L3 execution requires a code-owned verified authorization grant.
- Reversibility is derived from isolated adapter probes, not scenario claims.
- Release CI installs the built wheel before running the governance Quickstart.

## Scale Evidence

| SQL statements | Elapsed | Peak memory | Nodes | Edges | Artifact | Deterministic |
|---:|---:|---:|---:|---:|---:|---|
| 1,000 | 1.12 s | 11.45 MB | 5,003 | 9,002 | 2.52 MB | yes |
| 10,000 | 11.53 s | 112.91 MB | 50,003 | 90,002 | 25.25 MB | yes |

The benchmark uses a deterministic generated SQL chain. Results are local
reference measurements, not production latency guarantees.

## Browser Evidence

- Desktop viewport: 1440x1000, no horizontal overflow.
- Mobile viewport: 390x844, no horizontal overflow.
- Mobile lineage canvas switches to the list representation.
- No task tabs are off-screen.
- Explorer brand, dark tokens, and active navigation are present.
- Browser console produced no errors.

Screenshots and generated HTML remain local test artifacts and are intentionally
excluded from Git.
