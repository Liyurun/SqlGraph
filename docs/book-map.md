# Book to Code Map

| Book topic | Module | Tests | Observable artifact |
|---|---|---|---|
| Object and provenance model | `sqlgraph.baseline`, `sqlgraph.model` | `tests/contract/test_baseline_manifest.py` | `baseline.json`, `graph.json` |
| Semantic runtime | `sqlgraph.parser`, `sqlgraph.builder`, `sqlgraph.analyze` | `tests/test_identity`, `tests/test_analyze` | deterministic graph and analysis snapshot |
| Evidence chain | `sqlgraph.evidence`, `sqlgraph.graphrag` | `tests/test_evidence`, `tests/test_graphrag` | `evidence.json` |
| Graded autonomy | `sqlgraph.autonomy` | `tests/test_autonomy` | `decision.json` |
| Reversibility red line | `sqlgraph.actions` | `tests/safety/test_execution_recovery.py` | execution and rollback events |
| Seven-step loop | `sqlgraph.reasoning` | `tests/test_reasoning/test_runner.py` | seven hash-chained audit events |
| Structural insight | `sqlgraph.analyze` | `tests/test_analyze` | profile and governance snapshot |
| Caliber consistency | `examples/book_cases/caliber_consistency` | `tests/test_integration/test_book_cases.py` | successful L3 repair |
| Cost governance | `examples/book_cases/cold_table_retirement` | `tests/test_integration/test_book_cases.py` | reversible quarantine proposal |
| Verification | `sqlgraph.verification` | `tests/test_verification` | `verification.json` |
| Three objections | `sqlgraph.graphrag`, `sqlgraph.autonomy`, `sqlgraph.audit` | `tests/safety` | rejection, escalation, and replay records |
| Engineering implementation | `sqlgraph.cli`, `sqlgraph.serve` | `tests/test_cli`, `tests/test_serve` | CLI package and Explorer |
| Boundaries and future work | `CAPABILITIES.yaml`, `docs/limitations.md` | `tests/contract/test_capabilities.py` | explicit capability status |

Claims without a module, current test, and observable artifact must be marked
`experimental`, `planned`, or `concept-only` in `CAPABILITIES.yaml`.
