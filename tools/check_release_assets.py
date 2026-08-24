#!/usr/bin/env python3
# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Reject generated or private artifacts from the Git index."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    ".duckdb",
    ".zip",
    "comparison-screenshots/",
    "generated_illustrations",
    "demo_output/",
    "dogfood-output/",
)


def main() -> int:
    tracked = subprocess.check_output(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    bad = [
        path for path in tracked
        if any(marker in path for marker in FORBIDDEN)
    ]
    if bad:
        print("Forbidden release assets:")
        for path in bad:
            print(f"  {path}")
        return 1
    print("Release asset check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
