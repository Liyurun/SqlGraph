#!/usr/bin/env python3
# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Validate the public capability ledger against the repository."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "CAPABILITIES.yaml"
SCHEMA = ROOT / "schemas" / "capabilities-v1.schema.json"


def check_capabilities(root: Path = ROOT) -> list[str]:
    ledger_path = root / "CAPABILITIES.yaml"
    schema_path = root / "schemas" / "capabilities-v1.schema.json"
    payload = yaml.safe_load(ledger_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = []
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        errors.append(f"schema: {exc.message}")
        return errors

    seen = set()
    for capability in payload["capabilities"]:
        capability_id = capability["id"]
        if capability_id in seen:
            errors.append(f"duplicate capability id: {capability_id}")
        seen.add(capability_id)
        if capability["status"] != "implemented":
            continue
        for field in ("modules", "tests", "examples"):
            if not capability[field]:
                errors.append(
                    f"{capability_id}: implemented capability has no {field}"
                )
            for relative in capability[field]:
                if not (root / relative).exists():
                    errors.append(
                        f"{capability_id}: missing {field} path {relative}"
                    )
    return errors


def main() -> int:
    errors = check_capabilities()
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Capability ledger passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
