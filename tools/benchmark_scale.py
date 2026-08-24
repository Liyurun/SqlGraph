#!/usr/bin/env python3
# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Generate deterministic SQL scale benchmarks."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlgraph.api import build_graph
from sqlgraph.input import SqlSource, SqlSourceItem


@dataclass(frozen=True)
class ScaleResult:
    sql_count: int
    parsed: int
    elapsed_ms: float
    p50_ms: float
    p95_ms: float
    peak_memory_mb: float
    node_count: int
    edge_count: int
    unknown_count: int
    artifact_bytes: int
    deterministic: bool


def _source(count: int) -> SqlSource:
    source = SqlSource()
    for index in range(count):
        source.add_item(SqlSourceItem(
            name=f"task_{index:05d}",
            content=(
                f"INSERT INTO table_{index + 1:05d} "
                f"SELECT id, value + {index} AS value FROM table_{index:05d}"
            ),
        ))
    return source


def _digest(graph) -> str:
    ids = sorted(
        [node.id for node in graph.nodes] + [edge.id for edge in graph.edges]
    )
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def run_scale_benchmark(count: int) -> ScaleResult:
    sample_times = []
    for index in range(min(count, 20)):
        started = time.perf_counter()
        build_graph(
            f"INSERT INTO d{index} SELECT id FROM s{index}",
            dialect="spark",
        )
        sample_times.append((time.perf_counter() - started) * 1000)

    source = _source(count)
    tracemalloc.start()
    started = time.perf_counter()
    graph = build_graph(source, dialect="spark")
    elapsed_ms = (time.perf_counter() - started) * 1000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    second = build_graph(_source(count), dialect="spark")
    payload = json.dumps(graph.to_dict(), sort_keys=True, ensure_ascii=True)
    unknown_count = sum(
        getattr(node, "name", "") == "UNKNOWN" for node in graph.nodes
    )
    ordered = sorted(sample_times)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return ScaleResult(
        sql_count=count,
        parsed=graph.metadata["coverage"]["ok"],
        elapsed_ms=round(elapsed_ms, 3),
        p50_ms=round(statistics.median(sample_times), 3),
        p95_ms=round(ordered[p95_index], 3),
        peak_memory_mb=round(peak / 1024 / 1024, 3),
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        unknown_count=unknown_count,
        artifact_bytes=len(payload.encode("utf-8")),
        deterministic=_digest(graph) == _digest(second),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", default="100")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [
        asdict(run_scale_benchmark(int(raw)))
        for raw in args.counts.split(",")
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
