# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Immutable data contracts for governance analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"
ANALYSIS_VERSION = "1.0.0"


class MetricStatus(str, Enum):
    """Execution state of one analysis metric."""

    SUCCESS = "success"
    DEGRADED = "degraded"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True)
class MetricResult:
    """Result envelope that never conflates missing data with zero."""

    name: str
    status: MetricStatus
    value: Any = None
    reason: str | None = None
    algorithm: str | None = None
    version: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("metric name must not be empty")
        if self.status != MetricStatus.SUCCESS and self.reason is None:
            raise ValueError("non-success metric results require a reason")
        object.__setattr__(self, "value", freeze(self.value))
        object.__setattr__(self, "parameters", freeze(self.parameters))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "value": thaw(self.value),
            "reason": self.reason,
            "algorithm": self.algorithm,
            "version": self.version,
            "parameters": thaw(self.parameters),
        }


@dataclass(frozen=True)
class AnalysisManifest:
    """Version and provenance metadata for a governance snapshot."""

    graph_fingerprint: str
    config_fingerprint: str
    schema_version: str = SCHEMA_VERSION
    analysis_version: str = ANALYSIS_VERSION
    input_kind: str = "property_graph"
    random_seed: int = 42
    float_precision: int = 8
    completed_metrics: tuple[str, ...] = ()
    degraded_metrics: tuple[str, ...] = ()
    skipped_metrics: tuple[str, ...] = ()
    failed_metrics: tuple[str, ...] = ()
    metric_statuses: Mapping[str, MetricStatus] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.graph_fingerprint:
            raise ValueError("graph_fingerprint must not be empty")
        if not self.config_fingerprint:
            raise ValueError("config_fingerprint must not be empty")
        object.__setattr__(self, "metric_statuses", freeze(self.metric_statuses))
        object.__setattr__(self, "metadata", freeze(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_fingerprint": self.graph_fingerprint,
            "config_fingerprint": self.config_fingerprint,
            "schema_version": self.schema_version,
            "analysis_version": self.analysis_version,
            "input_kind": self.input_kind,
            "random_seed": self.random_seed,
            "float_precision": self.float_precision,
            "completed_metrics": list(self.completed_metrics),
            "degraded_metrics": list(self.degraded_metrics),
            "skipped_metrics": list(self.skipped_metrics),
            "failed_metrics": list(self.failed_metrics),
            "metric_statuses": {
                name: (
                    status.value
                    if isinstance(status, MetricStatus)
                    else str(status)
                )
                for name, status in self.metric_statuses.items()
            },
            "metadata": thaw(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisView:
    """Deeply immutable copy of the graph serialization contract."""

    nodes: tuple[Mapping[str, Any], ...]
    edges: tuple[Mapping[str, Any], ...]
    node_by_id: Mapping[str, Mapping[str, Any]]
    graph_fingerprint: str
    input_kind: str
    source_path: str | None = None

    @property
    def nodes_by_id(self) -> Mapping[str, Mapping[str, Any]]:
        """Compatibility alias for callers that prefer a plural index name."""
        return self.node_by_id

    def get_node(self, node_id: str) -> Mapping[str, Any] | None:
        """Return one immutable node by ID."""
        return self.node_by_id.get(node_id)

    def iter_nodes(self, node_type: str | None = None):
        """Iterate nodes in stable ID order, optionally filtered by type."""
        for node in self.nodes:
            if node_type is None or node.get("node_type") == node_type:
                yield node

    def iter_edges(self, edge_type: str | None = None):
        """Iterate edges in stable order, optionally filtered by type."""
        for edge in self.edges:
            if edge_type is None or edge.get("type") == edge_type:
                yield edge

    def to_dict(self) -> dict[str, Any]:
        """Return a mutable copy suitable for serialization and tests."""
        return {
            "nodes": [thaw(node) for node in self.nodes],
            "edges": [thaw(edge) for edge in self.edges],
        }


@dataclass(frozen=True)
class GovernanceSnapshot:
    """Top-level result returned by the future analysis pipeline."""

    manifest: AnalysisManifest
    summary: Mapping[str, Any] = field(default_factory=dict)
    metrics: tuple[MetricResult, ...] = ()
    table_metrics: tuple[Mapping[str, Any], ...] = ()
    column_metrics: tuple[Mapping[str, Any], ...] = ()
    sql_metrics: tuple[Mapping[str, Any], ...] = ()
    transform_metrics: tuple[Mapping[str, Any], ...] = ()
    layer_matrix: tuple[Mapping[str, Any], ...] = ()
    community_matrix: tuple[Mapping[str, Any], ...] = ()
    violations: tuple[Mapping[str, Any], ...] = ()
    consistency_groups: tuple[Mapping[str, Any], ...] = ()
    similarity_candidates: tuple[Mapping[str, Any], ...] = ()
    motif_records: tuple[Mapping[str, Any], ...] = ()
    anomaly_metrics: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", freeze(self.summary))
        for field_name in (
            "table_metrics",
            "column_metrics",
            "sql_metrics",
            "transform_metrics",
            "layer_matrix",
            "community_matrix",
            "violations",
            "consistency_groups",
            "similarity_candidates",
            "motif_records",
            "anomaly_metrics",
        ):
            object.__setattr__(
                self,
                field_name,
                tuple(freeze(item) for item in getattr(self, field_name)),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "summary": {
                str(name): (
                    value.to_dict()
                    if isinstance(value, MetricResult)
                    else thaw(value)
                )
                for name, value in self.summary.items()
            },
            "metrics": [metric.to_dict() for metric in self.metrics],
            "table_metrics": [thaw(item) for item in self.table_metrics],
            "column_metrics": [thaw(item) for item in self.column_metrics],
            "sql_metrics": [thaw(item) for item in self.sql_metrics],
            "transform_metrics": [
                thaw(item) for item in self.transform_metrics
            ],
            "layer_matrix": [thaw(item) for item in self.layer_matrix],
            "community_matrix": [thaw(item) for item in self.community_matrix],
            "violations": [thaw(item) for item in self.violations],
            "consistency_groups": [
                thaw(item) for item in self.consistency_groups
            ],
            "similarity_candidates": [
                thaw(item) for item in self.similarity_candidates
            ],
            "motif_records": [thaw(item) for item in self.motif_records],
            "anomaly_metrics": [thaw(item) for item in self.anomaly_metrics],
        }


def freeze(value: Any) -> Any:
    """Recursively convert mutable JSON-like containers to immutable ones."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """Recursively copy immutable contract values to JSON-like containers."""
    if isinstance(value, Mapping):
        return {str(key): thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((thaw(item) for item in value), key=repr)
    if isinstance(value, Enum):
        return value.value
    return value
