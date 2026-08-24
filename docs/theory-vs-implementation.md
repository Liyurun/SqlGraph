# Theory vs. Reference Implementation

SqlGraph treats the book's reliability rules as invariants while keeping
technology choices replaceable.

| Invariant | Reference implementation | Replaceable part |
|---|---|---|
| Same effective input produces the same semantic identity | SHA256 baseline and graph identity | hash library and storage |
| Conclusions must cite inspectable evidence | `EvidenceBundle` and Grounding validation | graph database and retrieval engine |
| Evidence gaps stop or reduce action | coverage obligations and sufficiency decisions | expansion strategy |
| Irreversible actions do not run autonomously | reversibility veto and L4 decision | approval system |
| Execution must be idempotent and recoverable | file and DuckDB adapters | production scheduler adapter |
| Verification is independent of execution success | source rebuild and runtime observations | runtime query adapter |
| Governance history is replayable | JSONL hash chain | append-only database or object store |

The repository does not claim that an LLM summary is reasoning evidence, that a
dry run proves reversibility, or that a graph path alone is a sufficient
evidence subgraph.
