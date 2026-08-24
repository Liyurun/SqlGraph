# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Shared visual assets for Explorer-derived offline reports."""

from __future__ import annotations

from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"


def load_explorer_css() -> str:
    """Load the canonical GitHub Explorer stylesheet."""
    return (STATIC_DIR / "app.css").read_text(encoding="utf-8")
