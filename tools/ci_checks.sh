#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python}"
RELEASE_PYTHON="${RELEASE_PYTHON:-$PYTHON}"

"$PYTHON" -m ruff check sqlgraph tests tools examples
"$PYTHON" tools/check_layering.py
"$PYTHON" tools/check_random_ids.py
"$PYTHON" tools/check_capabilities.py
"$PYTHON" scripts/opensource_guard.py
"$PYTHON" tools/check_release_assets.py
"$PYTHON" -m pytest --cov=sqlgraph --cov-report=json:coverage.json -q
"$PYTHON" tools/check_coverage.py --report coverage.json --min 85
rm -rf dist
"$PYTHON" -m build

RELEASE_TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$RELEASE_TEST_ROOT"' EXIT
VENV_DIR="$RELEASE_TEST_ROOT/venv"
VENV_PYTHON="$VENV_DIR/bin/python"

"$RELEASE_PYTHON" -m venv "$VENV_DIR"
"$VENV_PYTHON" -m pip install --disable-pip-version-check dist/*.whl
mkdir -p "$RELEASE_TEST_ROOT/run/examples"
cp -R examples/minimal "$RELEASE_TEST_ROOT/run/examples/minimal"
(
  cd "$RELEASE_TEST_ROOT/run"
  "$VENV_DIR/bin/sqlgraph" governance run examples/minimal/scenario.yaml \
    --output governance_output
  "$VENV_DIR/bin/sqlgraph" governance verify governance_output
  event_count="$("$VENV_PYTHON" -c \
    'from pathlib import Path; print(len(Path("governance_output/audit.jsonl").read_text().splitlines()))')"
  test "$event_count" -eq 7
)
