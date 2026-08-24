#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python}"

"$PYTHON" -m ruff check sqlgraph tests tools examples
"$PYTHON" tools/check_layering.py
"$PYTHON" tools/check_random_ids.py
"$PYTHON" tools/check_capabilities.py
"$PYTHON" scripts/opensource_guard.py
"$PYTHON" tools/check_release_assets.py
"$PYTHON" -m pytest --cov=sqlgraph --cov-report=json:coverage.json -q
"$PYTHON" tools/check_coverage.py --report coverage.json --min 85
"$PYTHON" -m build
