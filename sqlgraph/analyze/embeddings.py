# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Deterministic graph embeddings for governance similarity analysis.

The default backend is a lightweight random-walk co-occurrence embedding.  It
is intentionally pure Python so the base package does not require Node2Vec,
gensim, or ANN libraries.  Callers may explicitly request ``node2vec``; if the
optional backend is not installed this module records a degraded or skipped
metric instead of failing structural similarity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from importlib import import_module
import math
import random  # allow-random: deterministic analysis sampling uses an explicit seed
from typing import Any, Mapping

from sqlgraph.analyze.config import AnalysisConfig
from sqlgraph.analyze.contracts import MetricResult, MetricStatus, freeze, thaw
from sqlgraph.analyze.table_graph import TableGraph


EMBEDDING_VERSION = "1.0"
DEFAULT_EMBEDDING_DIMENSIONS = 16
DEFAULT_WALK_LENGTH = 8
DEFAULT_WALKS_PER_NODE = 4
DEFAULT_WINDOW_SIZE = 2


@dataclass(frozen=True)
class GraphEmbeddingResult:
    """Embedding vectors plus their execution envelope."""

    metric: MetricResult
    vectors: Mapping[str, tuple[float, ...]] = field(default_factory=dict)
    node_mapping: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "vectors", freeze(self.vectors))
        object.__setattr__(self, "node_mapping", freeze(self.node_mapping))

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric.to_dict(),
            "vectors": thaw(self.vectors),
            "node_mapping": thaw(self.node_mapping),
        }


def build_graph_embeddings(
    table_graph: TableGraph,
    config: AnalysisConfig | None = None,
    *,
    enabled: bool = True,
    backend: str = "auto",
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    walk_length: int = DEFAULT_WALK_LENGTH,
    walks_per_node: int = DEFAULT_WALKS_PER_NODE,
    window_size: int = DEFAULT_WINDOW_SIZE,
) -> GraphEmbeddingResult:
    """Build deterministic graph embeddings without mutating *table_graph*."""
    config = config or AnalysisConfig()
    backend = backend.strip().lower()
    if not enabled:
        return _skipped_result(
            "graph embeddings were disabled",
            backend=backend,
            dimensions=dimensions,
        )
    if table_graph.node_count == 0:
        metric = MetricResult(
            name="graph_embeddings",
            status=MetricStatus.SUCCESS,
            value={
                "backend": "random_walk_cooccurrence",
                "requested_backend": backend,
                "node_count": 0,
                "dimension_count": dimensions,
                "node_mapping": {},
            },
            algorithm="embeddings.empty_graph",
            version=EMBEDDING_VERSION,
        )
        return GraphEmbeddingResult(metric=metric, vectors={}, node_mapping={})
    if table_graph.node_count > config.resource_budget.exact_algorithm_max_nodes:
        return _skipped_result(
            "node count exceeds embedding resource budget",
            backend=backend,
            dimensions=dimensions,
            node_count=table_graph.node_count,
            max_nodes=config.resource_budget.exact_algorithm_max_nodes,
        )
    if dimensions <= 0:
        raise ValueError("dimensions must be greater than zero")
    if walk_length <= 0:
        raise ValueError("walk_length must be greater than zero")
    if walks_per_node <= 0:
        raise ValueError("walks_per_node must be greater than zero")
    if window_size <= 0:
        raise ValueError("window_size must be greater than zero")

    requested_backend = backend
    status = MetricStatus.SUCCESS
    reason = None
    actual_backend = "random_walk_cooccurrence"
    algorithm = "embeddings.random_walk_cooccurrence"
    if backend == "node2vec":
        optional_backend = _load_node2vec_backend()
        if optional_backend is None:
            if not config.allow_degraded:
                return _skipped_result(
                    "node2vec backend is not available",
                    backend=backend,
                    dimensions=dimensions,
                )
            status = MetricStatus.DEGRADED
            reason = (
                "node2vec backend is not available; "
                "fell back to random_walk_cooccurrence"
            )
        else:
            status = MetricStatus.DEGRADED
            reason = (
                "node2vec backend is available but the deterministic pure-Python "
                "co-occurrence backend is used in base analysis"
            )
    elif backend not in {"auto", "random_walk", "random_walk_cooccurrence"}:
        if not config.allow_degraded:
            return _skipped_result(
                f"unknown embedding backend {backend!r}",
                backend=backend,
                dimensions=dimensions,
            )
        status = MetricStatus.DEGRADED
        reason = (
            f"unknown embedding backend {backend!r}; "
            "fell back to random_walk_cooccurrence"
        )

    vectors = _random_walk_cooccurrence_vectors(
        table_graph,
        config,
        dimensions=dimensions,
        walk_length=walk_length,
        walks_per_node=walks_per_node,
        window_size=window_size,
    )
    node_mapping = {node_id: index for index, node_id in enumerate(table_graph.nodes)}
    metric = MetricResult(
        name="graph_embeddings",
        status=status,
        value={
            "backend": actual_backend,
            "requested_backend": requested_backend,
            "node_count": table_graph.node_count,
            "dimension_count": dimensions,
            "node_mapping": node_mapping,
            "vectors_available": True,
        },
        reason=reason,
        algorithm=algorithm,
        version=EMBEDDING_VERSION,
        parameters={
            "random_seed": config.random_seed,
            "walk_length": walk_length,
            "walks_per_node": walks_per_node,
            "window_size": window_size,
            "stable_node_mapping": True,
        },
    )
    return GraphEmbeddingResult(
        metric=metric,
        vectors=vectors,
        node_mapping=node_mapping,
    )


def cosine_similarity(
    left: tuple[float, ...] | list[float] | None,
    right: tuple[float, ...] | list[float] | None,
    *,
    precision: int = 8,
) -> float | None:
    """Return cosine similarity for two normalized-ish vectors."""
    if left is None or right is None or len(left) != len(right):
        return None
    dot = sum(
        float(a) * float(b)
        for a, b in zip(left, right, strict=False)
    )
    left_norm = math.sqrt(sum(float(item) * float(item) for item in left))
    right_norm = math.sqrt(sum(float(item) * float(item) for item in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return None
    return round(dot / (left_norm * right_norm), precision)


def embedding_ann_buckets(
    vectors: Mapping[str, tuple[float, ...]],
    *,
    band_count: int = 4,
) -> dict[str, tuple[str, ...]]:
    """Build deterministic ANN-style buckets from vector sign bands."""
    if not vectors or band_count <= 0:
        return {}
    dimension_count = len(next(iter(vectors.values()), ()))
    if dimension_count == 0:
        return {}
    band_size = max(1, math.ceil(dimension_count / band_count))
    buckets: dict[str, list[str]] = {}
    for node_id in sorted(vectors):
        vector = tuple(float(item) for item in vectors[node_id])
        for band_index, start in enumerate(range(0, dimension_count, band_size)):
            band = vector[start:start + band_size]
            signature = "".join("1" if value >= 0 else "0" for value in band)
            key = f"ann:{band_index}:{signature}"
            buckets.setdefault(key, []).append(node_id)
    return {
        key: tuple(sorted(value))
        for key, value in sorted(buckets.items())
        if len(value) > 1
    }


def _random_walk_cooccurrence_vectors(
    table_graph: TableGraph,
    config: AnalysisConfig,
    *,
    dimensions: int,
    walk_length: int,
    walks_per_node: int,
    window_size: int,
) -> dict[str, tuple[float, ...]]:
    rng = random.Random(config.random_seed)
    neighbors = _weighted_undirected_neighbors(table_graph)
    vectors: dict[str, list[float]] = {
        node_id: [0.0 for _ in range(dimensions)]
        for node_id in table_graph.nodes
    }

    for _ in range(walks_per_node):
        for start in table_graph.nodes:
            walk = _random_walk(start, neighbors, rng, walk_length)
            for position, center in enumerate(walk):
                left = max(0, position - window_size)
                right = min(len(walk), position + window_size + 1)
                for context_position in range(left, right):
                    if context_position == position:
                        continue
                    context = walk[context_position]
                    distance = abs(context_position - position)
                    weight = 1.0 / max(distance, 1)
                    _add_hashed_context(
                        vectors[center],
                        context,
                        weight,
                        seed=config.random_seed,
                    )

    return {
        node_id: _normalize_vector(values, precision=config.float_precision)
        for node_id, values in vectors.items()
    }


def _random_walk(
    start: str,
    neighbors: Mapping[str, tuple[tuple[str, float], ...]],
    rng: random.Random,
    walk_length: int,
) -> list[str]:
    walk = [start]
    current = start
    for _ in range(walk_length - 1):
        weighted_neighbors = neighbors.get(current, ())
        if not weighted_neighbors:
            break
        current = _weighted_choice(weighted_neighbors, rng)
        walk.append(current)
    return walk


def _weighted_choice(
    weighted_neighbors: tuple[tuple[str, float], ...],
    rng: random.Random,
) -> str:
    total = sum(weight for _, weight in weighted_neighbors)
    if total <= 0:
        return weighted_neighbors[0][0]
    threshold = rng.random() * total
    cumulative = 0.0
    for node_id, weight in weighted_neighbors:
        cumulative += weight
        if cumulative >= threshold:
            return node_id
    return weighted_neighbors[-1][0]


def _add_hashed_context(
    vector: list[float],
    context: str,
    weight: float,
    *,
    seed: int,
) -> None:
    digest = hashlib.sha256(f"{seed}:{context}".encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % len(vector)
    sign = 1.0 if digest[4] % 2 == 0 else -1.0
    vector[index] += sign * weight


def _normalize_vector(values: list[float], *, precision: int) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0.0:
        return tuple(0.0 for _ in values)
    return tuple(round(value / norm, precision) for value in values)


def _weighted_undirected_neighbors(
    table_graph: TableGraph,
) -> dict[str, tuple[tuple[str, float], ...]]:
    neighbors: dict[str, dict[str, float]] = {
        node_id: {} for node_id in table_graph.nodes
    }
    for edge in table_graph.edges:
        weight = float(max(edge.total_weight, 1))
        neighbors[edge.source_id][edge.target_id] = (
            neighbors[edge.source_id].get(edge.target_id, 0.0) + weight
        )
        neighbors[edge.target_id][edge.source_id] = (
            neighbors[edge.target_id].get(edge.source_id, 0.0) + weight
        )
    return {
        node_id: tuple(
            (neighbor_id, weights[neighbor_id])
            for neighbor_id in sorted(weights)
        )
        for node_id, weights in neighbors.items()
    }


def _skipped_result(
    reason: str,
    *,
    backend: str,
    dimensions: int,
    node_count: int | None = None,
    max_nodes: int | None = None,
) -> GraphEmbeddingResult:
    value: dict[str, Any] = {
        "backend": None,
        "requested_backend": backend,
        "dimension_count": dimensions,
        "vectors_available": False,
    }
    if node_count is not None:
        value["node_count"] = node_count
    if max_nodes is not None:
        value["max_nodes"] = max_nodes
    metric = MetricResult(
        name="graph_embeddings",
        status=MetricStatus.SKIPPED,
        value=value,
        reason=reason,
        algorithm="embeddings.backend_selection",
        version=EMBEDDING_VERSION,
    )
    return GraphEmbeddingResult(metric=metric, vectors={}, node_mapping={})


def _load_node2vec_backend() -> Any | None:
    try:
        module = import_module("node2vec")
    except ImportError:
        return None
    return getattr(module, "Node2Vec", None)
