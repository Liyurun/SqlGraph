# Contributing to SqlGraph

Thanks for your interest in improving SqlGraph! Contributions of all kinds are
welcome — bug reports, feature ideas, docs, and pull requests.

## Development setup

```bash
git clone https://github.com/Liyurun/SqlGraph.git
cd SqlGraph
pip install -e ".[all]"
```

## Running tests

```bash
pytest
```

Please make sure the test suite passes before opening a PR. If you add or change
behavior, add a test that covers it. The end-to-end demo is also a good smoke
test:

```bash
python examples/ads_pipeline/run_demo.py
```

## Guidelines

- Keep the layered architecture intact (see [docs/architecture.md](architecture.md)).
  Input, Parser, Builder, Model and Serialize/Visualize each have a single
  responsibility.
- Node and edge identity must stay **deterministic** — the same SQL should always
  produce the same graph and IDs.
- Source files carry detailed inline comments (Chinese). Follow the existing
  style and keep code minimal and readable.
- For parser changes, add a representative SQL case under `examples/` or a unit
  test under `tests/` demonstrating the new coverage.

## Reporting bugs

Open an issue with a minimal SQL snippet that reproduces the problem, the dialect
you used, and what you expected vs. what you got.

## License

By contributing, you agree that your contributions will be licensed under the
[Apache 2.0](LICENSE) license.
