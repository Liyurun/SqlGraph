from __future__ import annotations

from tools.benchmark_scale import run_scale_benchmark


def test_generated_sql_scale_smoke():
    result = run_scale_benchmark(100)

    assert result.parsed == 100
    assert result.deterministic
    assert result.peak_memory_mb > 0
    assert result.node_count > 100
    assert result.edge_count > 100
