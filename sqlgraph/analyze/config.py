# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Configuration contracts shared by governance analysis modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any


DEFAULT_ALGORITHM_VERSIONS = (
    ("analysis", "1.0"),
    ("complexity_score", "1.0"),
    ("blast_score", "1.0"),
    ("product_score", "1.0"),
)


@dataclass(frozen=True)
class ResourceBudget:
    """Hard limits used by expensive or approximate algorithms."""

    max_nodes: int = 100_000
    max_edges: int = 1_000_000
    max_memory_mb: int = 4096
    timeout_seconds: int = 3600
    exact_algorithm_max_nodes: int = 20_000
    betweenness_samples: int = 512
    similarity_candidates_per_node: int = 100
    top_k_removal_simulation: int = 100

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")


@dataclass(frozen=True)
class AnalysisConfig:
    """Deterministic configuration for one governance analysis run."""

    analysis_version: str = "1.0.0"
    random_seed: int = 42
    float_precision: int = 8
    metrics: tuple[str, ...] = ("all",)
    community_backend: str = "label_propagation"
    graph_backend: str = "auto"
    allow_degraded: bool = True
    include_sql_content: bool = False
    algorithm_versions: tuple[tuple[str, str], ...] = DEFAULT_ALGORITHM_VERSIONS
    layer_patterns: tuple[tuple[str, str], ...] = (
        ("ods", "ods"),
        ("dwd", "dwd"),
        ("dwi", "dwi"),
        ("dwa", "dwa"),
        ("dim", "dim"),
        ("dm", "dm"),
        ("ads", "ads"),
        ("app", "app"),
    )
    layer_violation_rules: tuple[tuple[str, str, str, str], ...] = ()
    metric_candidate_patterns: tuple[str, ...] = (
        "amount",
        "avg",
        "cnt",
        "count",
        "gmv",
        "metric",
        "rate",
        "ratio",
        "revenue",
        "score",
        "sum",
        "total",
    )
    resource_budget: ResourceBudget = field(default_factory=ResourceBudget)

    def __post_init__(self) -> None:
        if not self.analysis_version.strip():
            raise ValueError("analysis_version must not be empty")
        if self.float_precision < 0 or self.float_precision > 15:
            raise ValueError("float_precision must be between 0 and 15")
        if not self.metrics:
            raise ValueError("metrics must not be empty")
        if any(not metric.strip() for metric in self.metrics):
            raise ValueError("metrics must not contain empty names")
        algorithm_names = [name for name, _ in self.algorithm_versions]
        if len(algorithm_names) != len(set(algorithm_names)):
            raise ValueError("algorithm version names must be unique")
        if any(not name.strip() or not version.strip()
               for name, version in self.algorithm_versions):
            raise ValueError("algorithm versions must contain non-empty values")
        for rule in self.layer_violation_rules:
            if len(rule) != 4:
                raise ValueError(
                    "layer violation rules must be "
                    "(source_layer, target_layer, rule_id, severity) tuples"
                )
            source_layer, target_layer, rule_id, severity = rule
            if not all(
                str(value).strip()
                for value in (source_layer, target_layer, rule_id, severity)
            ):
                raise ValueError("layer violation rules must not contain empty values")
        if any(not str(pattern).strip() for pattern in self.metric_candidate_patterns):
            raise ValueError("metric candidate patterns must not contain empty values")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation with stable containers."""
        data = asdict(self)
        data["metrics"] = list(self.metrics)
        data["algorithm_versions"] = {
            name: version for name, version in self.algorithm_versions
        }
        data["layer_patterns"] = [list(item) for item in self.layer_patterns]
        data["layer_violation_rules"] = [
            list(item) for item in self.layer_violation_rules
        ]
        data["metric_candidate_patterns"] = list(self.metric_candidate_patterns)
        return data

    def fingerprint(self) -> str:
        """Return a stable SHA-256 fingerprint for cache compatibility."""
        payload = json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
