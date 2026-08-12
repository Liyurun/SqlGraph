# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest

from sqlgraph.analyze import (
    AnalysisConfig,
    AnalysisManifest,
    GovernanceSnapshot,
    MetricResult,
    MetricStatus,
    ResourceBudget,
)


def test_analysis_config_has_stable_json_compatible_shape():
    config = AnalysisConfig(
        random_seed=7,
        float_precision=6,
        metrics=("overview", "topology"),
        resource_budget=ResourceBudget(max_nodes=500),
    )

    payload = config.to_dict()

    assert payload["random_seed"] == 7
    assert payload["float_precision"] == 6
    assert payload["metrics"] == ["overview", "topology"]
    assert payload["algorithm_versions"]["analysis"] == "1.0"
    assert payload["resource_budget"]["max_nodes"] == 500


@pytest.mark.parametrize(
    "kwargs",
    [
        {"float_precision": -1},
        {"float_precision": 16},
        {"metrics": ()},
        {"algorithm_versions": (("analysis", "1"), ("analysis", "2"))},
    ],
)
def test_analysis_config_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        AnalysisConfig(**kwargs)


def test_resource_budget_rejects_non_positive_limits():
    with pytest.raises(ValueError, match="max_edges"):
        ResourceBudget(max_edges=0)


def test_non_success_metric_requires_reason():
    with pytest.raises(ValueError, match="reason"):
        MetricResult(name="parse_failures", status=MetricStatus.UNAVAILABLE)


def test_snapshot_serializes_statuses_and_metric_results():
    metric = MetricResult(
        name="lineage_table_count",
        status=MetricStatus.SUCCESS,
        value=3,
        algorithm="count",
        version="1.0",
    )
    unavailable = MetricResult(
        name="parse_failure_count",
        status=MetricStatus.UNAVAILABLE,
        reason="parser diagnostics were not provided",
    )
    manifest = AnalysisManifest(
        graph_fingerprint="graph-1",
        config_fingerprint="config-1",
        analysis_version="1.0",
        metric_statuses={
            metric.name: metric.status,
            unavailable.name: unavailable.status,
        },
    )
    snapshot = GovernanceSnapshot(
        manifest=manifest,
        summary={metric.name: metric, unavailable.name: unavailable},
        table_metrics=({"table_id": "table_1", "score": 0.5},),
    )

    payload = snapshot.to_dict()

    assert payload["manifest"]["schema_version"] == "1.0"
    assert payload["manifest"]["metric_statuses"] == {
        "lineage_table_count": "success",
        "parse_failure_count": "unavailable",
    }
    assert payload["summary"]["parse_failure_count"]["reason"]
    assert payload["table_metrics"] == [{"table_id": "table_1", "score": 0.5}]
