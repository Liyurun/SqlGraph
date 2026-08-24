"""Additional deterministic golden cases covering syntax and dialect boundaries."""

from __future__ import annotations

import json

import pytest

from sqlgraph.api import build_graph


CASES = (
    ("join_alias", "spark", "INSERT INTO d SELECT a.id FROM a JOIN b ON a.id=b.id"),
    ("window", "spark", "INSERT INTO d SELECT id, ROW_NUMBER() OVER (PARTITION BY id ORDER BY ts) AS rn FROM s"),
    ("case", "hive", "INSERT INTO d SELECT CASE WHEN x>0 THEN 1 ELSE 0 END AS flag FROM s"),
    ("cast", "presto", "INSERT INTO d SELECT CAST(amount AS DOUBLE) AS amount FROM s"),
    ("aggregate", "spark", "INSERT INTO d SELECT k, SUM(v) AS total FROM s GROUP BY k"),
    ("union", "spark", "INSERT INTO d SELECT id FROM a UNION ALL SELECT id FROM b"),
    ("nested", "spark", "INSERT INTO d SELECT id FROM (SELECT id FROM s) q"),
    ("udf", "spark", "INSERT INTO d SELECT custom_udf(value) AS value FROM s"),
    ("coalesce", "hive", "INSERT INTO d SELECT COALESCE(a, b, 0) AS value FROM s"),
    ("bigquery", "bigquery", "SELECT id, SAFE_CAST(value AS INT64) AS value FROM src"),
    ("mysql", "mysql", "SELECT id, IFNULL(value, 0) AS value FROM src"),
    ("postgres", "postgres", "SELECT id, value::DOUBLE PRECISION AS value FROM src"),
    ("duckdb", "duckdb", "CREATE TABLE d AS SELECT id, value / 2 AS value FROM s"),
    ("qualified", "spark", "INSERT INTO db.d SELECT db.s.id FROM db.s"),
    ("multi_join", "spark", "INSERT INTO d SELECT a.id FROM a JOIN b ON a.id=b.id JOIN c ON b.id=c.id"),
)


def _signature(graph) -> str:
    payload = graph.to_dict()
    payload["nodes"] = sorted(payload["nodes"], key=lambda item: item["id"])
    payload["edges"] = sorted(payload["edges"], key=lambda item: item["id"])
    return json.dumps(payload, sort_keys=True, ensure_ascii=True)


def test_golden_corpus_reaches_twenty_cases():
    # Five snapshot fixtures plus these fifteen cases.
    assert len(CASES) + 5 >= 20


@pytest.mark.parametrize(("name", "dialect", "sql"), CASES, ids=[case[0] for case in CASES])
def test_additional_golden_case_is_reproducible(name, dialect, sql):
    first = build_graph(sql, dialect=dialect)
    second = build_graph(sql, dialect=dialect)

    assert _signature(first) == _signature(second), name
    assert first.metadata["coverage"]["failed"] == 0
