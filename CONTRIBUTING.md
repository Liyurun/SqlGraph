# Contributing to SqlGraph

First off, thank you for taking the time to contribute! 🎉 Contributions of all
kinds are welcome — bug reports, feature ideas, documentation, and pull
requests. Following these guidelines helps us review your work quickly and
respectfully, and helps you get your change merged with less back-and-forth.

## Table of contents

- [Code of conduct](#code-of-conduct)
- [Quick links](#quick-links)
- [What kinds of contributions we're looking for](#what-kinds-of-contributions-were-looking-for)
- [Ground rules](#ground-rules)
- [Development setup](#development-setup)
- [Running tests](#running-tests)
- [Your first contribution](#your-first-contribution)
- [Submitting a change (pull requests)](#submitting-a-change-pull-requests)
- [Contributor License Agreement](#contributor-license-agreement)
- [Commit message conventions](#commit-message-conventions)
- [Reporting bugs](#reporting-bugs)
- [Reporting a security vulnerability](#reporting-a-security-vulnerability)
- [Suggesting a feature or enhancement](#suggesting-a-feature-or-enhancement)
- [Code review process](#code-review-process)
- [Community & getting help](#community--getting-help)
- [License](#license)

## Code of conduct

This project and everyone participating in it is governed by the
[SqlGraph Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are
expected to uphold this code. Please be welcoming to newcomers and encourage
diverse new contributors from all backgrounds — everyone was a beginner once.

## Quick links

- **Docs:** [README](README.md) · [architecture](docs/architecture.md)
- **Bugs:** [issue tracker](https://github.com/Liyurun/SqlGraph/issues)
- **Discussion / questions:** [GitHub Discussions](https://github.com/Liyurun/SqlGraph/discussions)
- **Security:** see [SECURITY.md](SECURITY.md) — do **not** open a public issue

## What kinds of contributions we're looking for

Keep an open mind! Improving documentation, triaging bugs, adding SQL dialect
test cases, or writing tutorials are all valuable and mean less work for the
maintainers. In particular we love:

- Bug fixes with a minimal reproducing SQL case.
- New parser coverage (dialects, expressions) backed by tests.
- Documentation and example improvements.

Please **do not** use the issue tracker for general support questions or
"how do I…" usage help — open a [GitHub Discussion](https://github.com/Liyurun/SqlGraph/discussions)
instead so the issue tracker stays focused on actionable bugs and features.

## Ground rules

- Be respectful and considerate in all interactions (see the
  [Code of Conduct](CODE_OF_CONDUCT.md)).
- **Discuss significant changes first.** For anything beyond a small fix, open
  an issue or discussion describing the change before you start, so we can agree
  on scope and avoid wasted effort.
- Keep the layered architecture intact (see [docs/architecture.md](docs/architecture.md)):
  Input, Parser, Builder, Model, and Serialize/Visualize each have a single
  responsibility.
- Node and edge identity must stay **deterministic** — the same SQL should
  always produce the same graph and the same IDs.
- Every behavior change ships with a test. Keep the test suite green.
- Source files carry detailed inline comments (Chinese). Follow the existing
  style and keep code minimal and readable.

## Development setup

```bash
git clone https://github.com/Liyurun/SqlGraph.git
cd SqlGraph
pip install -e ".[all]"
```

SqlGraph targets **Python 3.9+** (CI runs 3.9, 3.10, 3.11, and 3.12).

## Running tests

```bash
pytest
```

Please make sure the full test suite passes before opening a PR. If you add or
change behavior, add a test that covers it. The end-to-end demo is also a good
smoke test:

```bash
python examples/ads_pipeline/run_demo.py
```

For parser changes, add a representative SQL case under `examples/` or a unit
test under `tests/` demonstrating the new coverage.

## Your first contribution

Unsure where to begin? Look for issues labeled
[`good first issue`](https://github.com/Liyurun/SqlGraph/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
(small, self-contained) and
[`help wanted`](https://github.com/Liyurun/SqlGraph/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22)
(a bit more involved).

Never contributed to open source before? These friendly guides walk you through
the whole flow: [How to Contribute to an Open Source Project on GitHub](https://egghead.io/courses/how-to-contribute-to-an-open-source-project-on-github),
[makeapullrequest.com](https://makeapullrequest.com/), and
[firsttimersonly.com](https://www.firsttimersonly.com/). Feel free to ask for
help — if a maintainer asks you to "rebase", they just mean update your branch
against the latest `main` so it merges cleanly.

## Submitting a change (pull requests)

For anything bigger than a one- or two-line fix:

1. **Fork** the repository and create a descriptive branch from `main`
   (e.g. `fix/create-view-parsing` or `feat/subgraph-depth`).
2. Make your change in your fork, following the [ground rules](#ground-rules)
   and [commit conventions](#commit-message-conventions).
3. **Add or update tests** and make sure `pytest` passes locally.
4. Push your branch and **open a pull request** against `main`. Describe what
   changed and why, and link any related issue (e.g. `Closes #123`).
5. Make sure the **CI checks are green**. If a specific Python version fails,
   reproduce and fix it locally before requesting review.

**Obvious fixes** — spelling/grammar, typos, whitespace/formatting, comment
cleanup, or changes to metadata files like `.gitignore` — do not need a prior
issue and can go straight to a PR.

## Contributor License Agreement

Before a pull request can be accepted, contributors may be asked to sign the
[ByteDance Contributor License Agreement v1.1](CLA.md). The CLA clarifies the
intellectual property license granted with contributions and protects both
contributors and project users.

If you are contributing on your own behalf, sign the individual CLA through the
project's CLA flow. If you are contributing on behalf of a company or other
legal entity, follow the corporate CLA instructions in [CLA.md](CLA.md).

## Commit message conventions

We use [Conventional Commits](https://www.conventionalcommits.org/). The commit
subject line follows `type: short imperative summary`, where `type` is one of:

- `feat:` a new feature
- `fix:` a bug fix
- `docs:` documentation only
- `test:` adding or fixing tests
- `refactor:` code change that neither fixes a bug nor adds a feature
- `chore:` tooling, build, or housekeeping

We also follow the [seven rules of a great commit message](https://cbea.ms/git-commit/#seven-rules):
separate subject from body with a blank line, limit the subject to ~50
characters, capitalize the subject, no trailing period, use the imperative mood,
wrap the body at ~72 characters, and use the body to explain *what* and *why*
rather than *how*. Example:

```
fix: support create view lineage parsing

sqlglot falls back to a Command node for Hive/Spark CREATE VIEW with
PARTITIONED ON / TBLPROPERTIES. Extract the view name and AS query so the
target table and its columns are still linked into the graph.
```

## Reporting bugs

Open an [issue](https://github.com/Liyurun/SqlGraph/issues/new/choose) and
include:

1. A **minimal SQL snippet** that reproduces the problem.
2. The **dialect** you used (e.g. `spark`, `hive`).
3. What you **expected** to see.
4. What you **saw instead** (error message, wrong graph, etc.).
5. Your **SqlGraph / Python version** and OS.

## Reporting a security vulnerability

**Do not open a public issue for security problems.** If you discover a
vulnerability, please follow the private disclosure process described in
[SECURITY.md](SECURITY.md). We will acknowledge your report and work with you on
a fix and coordinated disclosure.

## Suggesting a feature or enhancement

SqlGraph's philosophy is to be a focused, deterministic SQL-to-graph engine:
every SQL expression is fingerprinted and merged only when output field
semantics match, so reused logic is visible without collapsing distinct metric
aliases. Feature proposals that reinforce this focus are most likely to land.

Before writing code for a significant feature, open an
[issue](https://github.com/Liyurun/SqlGraph/issues/new/choose) or
[discussion](https://github.com/Liyurun/SqlGraph/discussions) describing:

- the feature you'd like to see,
- **why** you need it (the use case), and
- **how** you think it should work.

This lets us align on scope before anyone invests significant effort.

## Code review process

- A maintainer reviews open pull requests and aims to give initial feedback
  within about **one week**.
- Changes are merged once they have passing CI, adequate tests, and maintainer
  approval.
- If a PR needs changes and shows no activity for an extended period, we may
  close it to keep the queue tidy — you're always welcome to reopen or resubmit.

## Community & getting help

- **Questions & ideas:** [GitHub Discussions](https://github.com/Liyurun/SqlGraph/discussions)
- **Bugs & features:** [GitHub Issues](https://github.com/Liyurun/SqlGraph/issues)

We try to respond as promptly as we can — thank you for your patience and for
helping make SqlGraph better.

## License

By contributing, you agree that your contributions will be licensed under the
[Apache 2.0](LICENSE) license.
