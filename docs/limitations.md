# Limitations

- SQL parsing depends on SQLGlot. Unsupported or dynamic SQL must be materialized
  before analysis; the system does not execute templates to guess their output.
- Multi-source columns without enough schema information are marked `UNKNOWN`.
  Evidence containing them cannot pass the `no_unresolved` obligation.
- Expression fingerprints are conservative. Algebraically equivalent expressions
  such as reordered addition are intentionally not merged.
- Counterevidence search is structural. Domain counterexamples and external facts
  must be supplied through adapters.
- The included action adapters support local SQL files and DuckDB only. They are
  reference implementations, not production warehouse credentials or schedulers.
- JSONL audit storage detects local mutation, deletion, and reordering but is not
  a distributed consensus ledger.
- Runtime verification trusts the configured runtime adapter's observations.
  Production deployments must isolate that adapter from the execution path.
- Embeddings and model-based anomaly detection are optional analysis features and
  cannot authorize governance actions.
- The ordinary CI scale smoke test uses 100 generated SQL statements. The 1,000
  and 10,000 statement benchmarks run in a separate workflow.
- SqlGraph does not bundle an LLM, approval platform, identity provider, metadata
  catalog, or production scheduler.
