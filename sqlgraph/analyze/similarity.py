# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Similar-asset candidate recall and ranking over TableGraph."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
from typing import Any, Iterator, Mapping

from sqlgraph.analyze.communities import CommunityAnalysisResult, analyze_communities
from sqlgraph.analyze.config import AnalysisConfig
from sqlgraph.analyze.contracts import AnalysisView, MetricResult, MetricStatus, freeze, thaw
from sqlgraph.analyze.embeddings import (
    EMBEDDING_VERSION,
    GraphEmbeddingResult,
    build_graph_embeddings,
    cosine_similarity,
    embedding_ann_buckets,
)
from sqlgraph.analyze.table_graph import TableGraph
from sqlgraph.analyze.topology import TopologyAnalysisResult, analyze_topology


SIMILARITY_VERSION = "1.0"
SIMILARITY_WEIGHTS: Mapping[str, float] = {
    "upstream_jaccard": 0.15,
    "downstream_jaccard": 0.15,
    "schema_jaccard": 0.45,
    "neighborhood_jaccard": 0.15,
    "embedding_cosine": 0.10,
}


@dataclass(frozen=True)
class SimilarityAnalysisResult:
    """Task 9 result bundle for similar assets and embeddings."""

    summary: Mapping[str, MetricResult] = field(default_factory=dict)
    candidate_recall: MetricResult = field(
        default_factory=lambda: MetricResult(
            name="similarity_candidate_recall",
            status=MetricStatus.SUCCESS,
            value={
                "candidate_pair_count": 0,
                "scored_pair_count": 0,
                "full_pair_count": 0,
                "full_pair_scan_avoided": True,
            },
            algorithm="similarity.empty_graph",
            version=SIMILARITY_VERSION,
        )
    )
    embedding: MetricResult = field(
        default_factory=lambda: MetricResult(
            name="graph_embeddings",
            status=MetricStatus.SUCCESS,
            value={
                "backend": "random_walk_cooccurrence",
                "node_count": 0,
                "vectors_available": False,
            },
            algorithm="embeddings.empty_graph",
            version=EMBEDDING_VERSION,
        )
    )
    similarity_candidates: tuple[Mapping[str, Any], ...] = ()
    table_metrics: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", freeze(self.summary))
        object.__setattr__(
            self,
            "similarity_candidates",
            tuple(freeze(item) for item in self.similarity_candidates),
        )
        object.__setattr__(
            self,
            "table_metrics",
            tuple(freeze(item) for item in self.table_metrics),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                name: result.to_dict() for name, result in self.summary.items()
            },
            "candidate_recall": self.candidate_recall.to_dict(),
            "embedding": self.embedding.to_dict(),
            "similarity_candidates": [
                thaw(item) for item in self.similarity_candidates
            ],
            "table_metrics": [thaw(item) for item in self.table_metrics],
        }


@dataclass(frozen=True)
class _TableFeatures:
    upstream: Mapping[str, tuple[str, ...]]
    downstream: Mapping[str, tuple[str, ...]]
    neighbors: Mapping[str, tuple[str, ...]]
    schema_tokens: Mapping[str, tuple[str, ...]]
    schema_signature: Mapping[str, str]
    declared_layers: Mapping[str, str]
    communities: Mapping[str, str]


def analyze_similarity(
    table_graph: TableGraph,
    view: AnalysisView | None = None,
    topology: TopologyAnalysisResult | None = None,
    communities: CommunityAnalysisResult | Mapping[str, str] | None = None,
    config: AnalysisConfig | None = None,
    *,
    embedding_enabled: bool = True,
    embedding_backend: str = "auto",
    top_k_per_table: int | None = None,
) -> SimilarityAnalysisResult:
    """Compute Task 9 similarity metrics using bounded candidate recall."""
    config = config or AnalysisConfig()
    large_graph = table_graph.node_count > config.resource_budget.exact_algorithm_max_nodes
    topology = (
        topology
        if topology is not None or large_graph
        else analyze_topology(table_graph, config=config)
    )
    communities_by_table = _communities_by_table(
        table_graph,
        communities,
        config,
        use_default_unknown=large_graph and communities is None,
    )
    embedding_result = build_graph_embeddings(
        table_graph,
        config=config,
        enabled=embedding_enabled,
        backend=embedding_backend,
    )
    features = _table_features(
        table_graph,
        view,
        topology,
        communities_by_table,
        config,
    )
    pair_limit = (
        config.resource_budget.similarity_candidates_per_node
        if top_k_per_table is None
        else max(1, int(top_k_per_table))
    )
    candidate_pairs, recall_sources = _recall_candidate_pairs(
        table_graph,
        features,
        embedding_result,
        per_node_limit=pair_limit,
    )
    ranked = _rank_candidates(
        table_graph,
        features,
        candidate_pairs,
        recall_sources,
        embedding_result,
        config,
    )
    table_metrics = _table_metrics(table_graph, ranked)
    candidate_recall = _candidate_recall_metric(
        table_graph,
        candidate_pairs,
        ranked,
        recall_sources,
        pair_limit,
        config,
    )
    return SimilarityAnalysisResult(
        summary=_summary_metrics(table_graph, candidate_recall, ranked, config),
        candidate_recall=candidate_recall,
        embedding=embedding_result.metric,
        similarity_candidates=ranked,
        table_metrics=table_metrics,
    )


def jaccard_similarity(
    left: tuple[str, ...] | set[str] | frozenset[str],
    right: tuple[str, ...] | set[str] | frozenset[str],
    *,
    precision: int = 8,
) -> float:
    """Return Jaccard similarity for two token sets."""
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 1.0
    union = left_set | right_set
    if not union:
        return 0.0
    return round(len(left_set & right_set) / len(union), precision)


def _communities_by_table(
    table_graph: TableGraph,
    communities: CommunityAnalysisResult | Mapping[str, str] | None,
    config: AnalysisConfig,
    *,
    use_default_unknown: bool = False,
) -> Mapping[str, str]:
    if use_default_unknown:
        return {node_id: "unknown" for node_id in table_graph.nodes}
    if communities is None:
        return analyze_communities(table_graph, config=config).community_detection.value[
            "communities_by_table"
        ]
    if isinstance(communities, CommunityAnalysisResult):
        return communities.community_detection.value["communities_by_table"]
    return {str(key): str(value) for key, value in communities.items()}


def _table_features(
    table_graph: TableGraph,
    view: AnalysisView | None,
    topology: TopologyAnalysisResult | None,
    communities_by_table: Mapping[str, str],
    config: AnalysisConfig,
) -> _TableFeatures:
    downstream_builder: dict[str, set[str]] = {
        node_id: set() for node_id in table_graph.nodes
    }
    upstream_builder: dict[str, set[str]] = {
        node_id: set() for node_id in table_graph.nodes
    }
    for edge in table_graph.edges:
        downstream_builder[edge.source_id].add(edge.target_id)
        upstream_builder[edge.target_id].add(edge.source_id)
    upstream = {
        node_id: tuple(sorted(values))
        for node_id, values in upstream_builder.items()
    }
    downstream = {
        node_id: tuple(sorted(values))
        for node_id, values in downstream_builder.items()
    }
    neighbors = {
        node_id: tuple(sorted(set(upstream[node_id]) | set(downstream[node_id])))
        for node_id in table_graph.nodes
    }
    schema_tokens = _schema_tokens(table_graph, view)
    schema_signature = {
        table_id: _schema_signature(tokens)
        for table_id, tokens in schema_tokens.items()
    }
    topology_by_table = {
        str(item["table_id"]): item
        for item in topology.table_metrics
    } if topology is not None else {}
    declared_layers = {
        table_id: str(
            topology_by_table.get(table_id, {}).get(
                "declared_layer",
                _declared_layer(table_graph.nodes_by_id.get(table_id, {}), config),
            )
        )
        for table_id in table_graph.nodes
    }
    return _TableFeatures(
        upstream=upstream,
        downstream=downstream,
        neighbors=neighbors,
        schema_tokens=schema_tokens,
        schema_signature=schema_signature,
        declared_layers=declared_layers,
        communities={str(key): str(value) for key, value in communities_by_table.items()},
    )


def _schema_tokens(
    table_graph: TableGraph,
    view: AnalysisView | None,
) -> dict[str, tuple[str, ...]]:
    tokens = {table_id: set() for table_id in table_graph.nodes}
    if view is not None:
        for node in view.iter_nodes("column"):
            table_id = node.get("table_id")
            if table_id not in tokens:
                continue
            column_name = str(node.get("name", "")).strip().lower()
            data_type = str(node.get("data_type") or "").strip().lower()
            if column_name:
                tokens[str(table_id)].add(f"name:{column_name}")
            if data_type:
                tokens[str(table_id)].add(f"type:{data_type}")
    for table_id in table_graph.nodes:
        snapshot = table_graph.nodes_by_id.get(table_id, {})
        columns = snapshot.get("columns", ())
        for column in columns or ():
            if isinstance(column, Mapping):
                column_name = str(column.get("name", "")).strip().lower()
                data_type = str(column.get("data_type") or "").strip().lower()
            else:
                column_name = str(column).strip().lower()
                data_type = ""
            if column_name:
                tokens[table_id].add(f"name:{column_name}")
            if data_type:
                tokens[table_id].add(f"type:{data_type}")
    return {
        table_id: tuple(sorted(values))
        for table_id, values in tokens.items()
    }


def _recall_candidate_pairs(
    table_graph: TableGraph,
    features: _TableFeatures,
    embedding_result: GraphEmbeddingResult,
    *,
    per_node_limit: int,
) -> tuple[set[tuple[str, str]], dict[tuple[str, str], set[str]]]:
    buckets: dict[str, set[str]] = {}
    for table_id in table_graph.nodes:
        layer = features.declared_layers.get(table_id, "unknown")
        community = features.communities.get(table_id, "unknown")
        schema_signature = features.schema_signature.get(table_id, "empty")
        buckets.setdefault(f"layer:{layer}", set()).add(table_id)
        buckets.setdefault(f"community:{community}", set()).add(table_id)
        buckets.setdefault(f"schema:{schema_signature}", set()).add(table_id)
        for key in _minhash_lsh_keys(features.schema_tokens.get(table_id, ())):
            buckets.setdefault(f"lsh:{key}", set()).add(table_id)

    for key, members in embedding_ann_buckets(embedding_result.vectors).items():
        buckets.setdefault(key, set()).update(members)

    selected_pairs: set[tuple[str, str]] = set()
    recall_sources: dict[tuple[str, str], set[str]] = {}
    per_node_counts = {node_id: 0 for node_id in table_graph.nodes}
    source_priority = {
        "schema": 0,
        "lsh": 1,
        "ann": 2,
        "community": 3,
        "layer": 4,
    }
    bucket_entries = (
        (
            bucket_key.split(":", 1)[0],
            bucket_key,
            tuple(sorted(members)),
        )
        for bucket_key, members in buckets.items()
        if len(members) >= 2
    )
    for source, bucket_key, ordered in sorted(
        bucket_entries,
        key=lambda item: (
            source_priority.get(item[0], 99),
            len(item[2]),
            item[1],
        ),
    ):
        del bucket_key
        for left, right in _bounded_bucket_pairs(ordered, per_node_limit):
            pair = (left, right) if left < right else (right, left)
            if pair in selected_pairs:
                recall_sources[pair].add(source)
                continue
            if (
                per_node_counts[pair[0]] >= per_node_limit
                or per_node_counts[pair[1]] >= per_node_limit
            ):
                continue
            selected_pairs.add(pair)
            recall_sources[pair] = {source}
            per_node_counts[pair[0]] += 1
            per_node_counts[pair[1]] += 1

    return selected_pairs, recall_sources


def _bounded_bucket_pairs(
    ordered: tuple[str, ...],
    per_node_limit: int,
) -> Iterator[tuple[str, str]]:
    if len(ordered) < 2:
        return
    window = min(max(per_node_limit, 1), len(ordered) - 1)
    for offset in range(1, window + 1):
        for index in range(0, len(ordered) - offset):
            yield ordered[index], ordered[index + offset]


def _evidence_jaccard(
    left: tuple[str, ...],
    right: tuple[str, ...],
    *,
    precision: int,
) -> float:
    if not left and not right:
        return 0.0
    return jaccard_similarity(left, right, precision=precision)


def _rank_candidates(
    table_graph: TableGraph,
    features: _TableFeatures,
    candidate_pairs: set[tuple[str, str]],
    recall_sources: Mapping[tuple[str, str], set[str]],
    embedding_result: GraphEmbeddingResult,
    config: AnalysisConfig,
) -> tuple[Mapping[str, Any], ...]:
    ranked: list[Mapping[str, Any]] = []
    for left, right in sorted(candidate_pairs):
        upstream_common = _intersection(features.upstream[left], features.upstream[right])
        downstream_common = _intersection(
            features.downstream[left],
            features.downstream[right],
        )
        schema_common = _intersection(
            features.schema_tokens[left],
            features.schema_tokens[right],
        )
        neighbor_common = _intersection(
            features.neighbors[left],
            features.neighbors[right],
        )
        upstream_jaccard = _evidence_jaccard(
            features.upstream[left],
            features.upstream[right],
            precision=config.float_precision,
        )
        downstream_jaccard = _evidence_jaccard(
            features.downstream[left],
            features.downstream[right],
            precision=config.float_precision,
        )
        schema_jaccard = _evidence_jaccard(
            features.schema_tokens[left],
            features.schema_tokens[right],
            precision=config.float_precision,
        )
        neighborhood_jaccard = _evidence_jaccard(
            features.neighbors[left],
            features.neighbors[right],
            precision=config.float_precision,
        )
        embedding_cosine = cosine_similarity(
            embedding_result.vectors.get(left),
            embedding_result.vectors.get(right),
            precision=config.float_precision,
        )
        submetrics = {
            "upstream_jaccard": upstream_jaccard,
            "downstream_jaccard": downstream_jaccard,
            "schema_jaccard": schema_jaccard,
            "neighborhood_jaccard": neighborhood_jaccard,
            "embedding_cosine": embedding_cosine,
        }
        score = _weighted_score(submetrics, config.float_precision)
        ranked.append(
            {
                "left_table_id": left,
                "right_table_id": right,
                "left_table_name": _table_full_name(
                    table_graph.nodes_by_id.get(left, {})
                ),
                "right_table_name": _table_full_name(
                    table_graph.nodes_by_id.get(right, {})
                ),
                "similarity_score": score,
                "similarity_score_version": _similarity_score_version(config),
                "similarity_score_weights": _active_weights(submetrics),
                "similarity_score_submetrics": submetrics,
                "recall_sources": tuple(sorted(recall_sources.get((left, right), ()))),
                "common_upstream": upstream_common,
                "common_downstream": downstream_common,
                "common_neighbors": neighbor_common,
                "schema_overlap": schema_common,
                "embedding_evidence": {
                    "available": embedding_cosine is not None,
                    "cosine": embedding_cosine,
                    "left_vector_index": embedding_result.node_mapping.get(left),
                    "right_vector_index": embedding_result.node_mapping.get(right),
                    "backend": embedding_result.metric.value.get("backend"),
                },
            }
        )
    return tuple(
        sorted(
            ranked,
            key=lambda item: (
                -float(item["similarity_score"] or 0.0),
                str(item["left_table_id"]),
                str(item["right_table_id"]),
            ),
        )
    )


def _candidate_recall_metric(
    table_graph: TableGraph,
    candidate_pairs: set[tuple[str, str]],
    ranked: tuple[Mapping[str, Any], ...],
    recall_sources: Mapping[tuple[str, str], set[str]],
    per_node_limit: int,
    config: AnalysisConfig,
) -> MetricResult:
    full_pair_count = table_graph.node_count * (table_graph.node_count - 1) // 2
    source_counts = Counter(
        source
        for sources in recall_sources.values()
        for source in sources
    )
    value = {
        "candidate_pair_count": len(candidate_pairs),
        "scored_pair_count": len(ranked),
        "full_pair_count": full_pair_count,
        "full_pair_scan_avoided": len(candidate_pairs) < full_pair_count
        if full_pair_count
        else True,
        "per_node_candidate_limit": per_node_limit,
        "recall_source_counts": dict(sorted(source_counts.items())),
        "resource_budget_similarity_candidates_per_node": (
            config.resource_budget.similarity_candidates_per_node
        ),
    }
    return MetricResult(
        name="similarity_candidate_recall",
        status=MetricStatus.SUCCESS,
        value=value,
        algorithm="similarity.indexed_candidate_recall",
        version=SIMILARITY_VERSION,
        parameters={
            "uses_layer_bucket": True,
            "uses_community_bucket": True,
            "uses_schema_signature": True,
            "uses_minhash_lsh": True,
            "uses_embedding_ann": bool(source_counts.get("ann")),
        },
    )


def _summary_metrics(
    table_graph: TableGraph,
    candidate_recall: MetricResult,
    ranked: tuple[Mapping[str, Any], ...],
    config: AnalysisConfig,
) -> Mapping[str, MetricResult]:
    top_limit = min(10, len(ranked))
    summary = {
        "similarity_table_count": table_graph.node_count,
        "similarity_edge_count": table_graph.edge_count,
        "similarity_candidate_pair_count": candidate_recall.value[
            "candidate_pair_count"
        ],
        "similarity_full_pair_scan_avoided": candidate_recall.value[
            "full_pair_scan_avoided"
        ],
        "top_similarity_candidates": tuple(
            {
                "left_table_id": item["left_table_id"],
                "right_table_id": item["right_table_id"],
                "similarity_score": item["similarity_score"],
            }
            for item in ranked[:top_limit]
        ),
    }
    return {
        name: MetricResult(
            name=name,
            status=MetricStatus.SUCCESS,
            value=value,
            algorithm="similarity.summary",
            version=SIMILARITY_VERSION,
            parameters={"float_precision": config.float_precision},
        )
        for name, value in sorted(summary.items())
    }


def _table_metrics(
    table_graph: TableGraph,
    ranked: tuple[Mapping[str, Any], ...],
) -> tuple[Mapping[str, Any], ...]:
    best: dict[str, Mapping[str, Any]] = {}
    counts = {node_id: 0 for node_id in table_graph.nodes}
    for item in ranked:
        left = str(item["left_table_id"])
        right = str(item["right_table_id"])
        counts[left] += 1
        counts[right] += 1
        for node_id, other_id in ((left, right), (right, left)):
            current = best.get(node_id)
            if current is None or float(item["similarity_score"] or 0.0) > float(
                current["similarity_score"] or 0.0
            ):
                best[node_id] = {
                    "other_table_id": other_id,
                    "similarity_score": item["similarity_score"],
                    "recall_sources": item["recall_sources"],
                }
    rows = []
    for table_id in table_graph.nodes:
        top = best.get(table_id)
        rows.append(
            {
                "table_id": table_id,
                "table_name": _table_full_name(
                    table_graph.nodes_by_id.get(table_id, {})
                ),
                "similar_candidate_count": counts[table_id],
                "top_similar_table_id": None if top is None else top["other_table_id"],
                "top_similarity_score": None if top is None else top["similarity_score"],
                "top_similarity_recall_sources": ()
                if top is None else top["recall_sources"],
            }
        )
    return tuple(rows)


def _minhash_lsh_keys(tokens: tuple[str, ...], *, band_count: int = 4) -> tuple[str, ...]:
    if not tokens:
        return ("empty",)
    signatures = []
    ordered = tuple(sorted(tokens))
    for band_index in range(band_count):
        minimum = min(
            hashlib.sha256(
                f"{band_index}:{token}".encode("utf-8")
            ).hexdigest()[:12]
            for token in ordered
        )
        signatures.append(f"{band_index}:{minimum}")
    return tuple(signatures)


def _schema_signature(tokens: tuple[str, ...]) -> str:
    if not tokens:
        return "empty"
    names = tuple(sorted(token for token in tokens if token.startswith("name:")))
    if not names:
        names = tuple(sorted(tokens))
    digest = hashlib.sha256("|".join(names).encode("utf-8")).hexdigest()[:16]
    return digest


def _declared_layer(snapshot: Mapping[str, Any], config: AnalysisConfig) -> str:
    text = ".".join(
        str(value).lower()
        for value in (
            snapshot.get("catalog", ""),
            snapshot.get("schema_name", ""),
            snapshot.get("name", ""),
        )
        if value
    )
    for layer, pattern in config.layer_patterns:
        if str(pattern).lower() in text:
            return str(layer)
    return "unknown"


def _weighted_score(
    submetrics: Mapping[str, float | None],
    precision: int,
) -> float | None:
    active_weight = 0.0
    total = 0.0
    for name, weight in SIMILARITY_WEIGHTS.items():
        value = submetrics.get(name)
        if value is None:
            continue
        active_weight += weight
        total += float(value) * weight
    if active_weight == 0.0:
        return None
    return round(total / active_weight, precision)


def _active_weights(submetrics: Mapping[str, float | None]) -> Mapping[str, float]:
    return {
        name: weight
        for name, weight in SIMILARITY_WEIGHTS.items()
        if submetrics.get(name) is not None
    }


def _intersection(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(set(left) & set(right)))


def _similarity_score_version(config: AnalysisConfig) -> str:
    versions = dict(config.algorithm_versions)
    return versions.get("similarity_score", SIMILARITY_VERSION)


def _table_full_name(node: Mapping[str, Any]) -> str:
    parts = [
        str(value)
        for value in (
            node.get("catalog"),
            node.get("schema_name"),
            node.get("name"),
        )
        if value
    ]
    return ".".join(parts) if parts else str(node.get("id", ""))
