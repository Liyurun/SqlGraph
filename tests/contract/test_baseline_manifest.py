from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from sqlgraph.baseline import build_baseline
from sqlgraph.input import SqlSource
from sqlgraph.input.csv_schema import SchemaRegistry


def _source() -> SqlSource:
    return SqlSource.from_string(
        "INSERT INTO dst SELECT id FROM src",
        name="build_dst",
    )


def test_baseline_id_is_stable_and_timestamp_is_not_identity():
    first = build_baseline(_source(), dialect="spark")
    second = build_baseline(_source(), dialect="spark")

    assert first.baseline_id == second.baseline_id
    assert first.created_at
    assert first.to_dict()["baseline_id"] == first.baseline_id


def test_missing_schema_and_external_inputs_are_disclosed():
    baseline = build_baseline(_source(), dialect="spark")

    assert set(baseline.missing_dependencies) == {
        "schema",
        "udf_manifest",
        "parameters",
        "scheduler_manifest",
    }


def test_schema_changes_baseline_identity():
    first = SchemaRegistry.from_dict({"src": ["id"]})
    second = SchemaRegistry.from_dict({"src": ["id", "amount"]})

    assert build_baseline(_source(), dialect="spark", schema=first).baseline_id != (
        build_baseline(_source(), dialect="spark", schema=second).baseline_id
    )


def test_baseline_matches_json_schema():
    baseline = build_baseline(_source(), dialect="spark")
    schema_path = (
        Path(__file__).parents[2]
        / "schemas"
        / "baseline-manifest-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    jsonschema.validate(baseline.to_dict(), schema)
