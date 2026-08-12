# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Bounded governance motif and path-diversity analysis over TableGraph."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
import random
from typing import Any, Mapping, Sequence

from sqlgraph.analyze.config import AnalysisConfig
from sqlgraph.analyze.contracts import MetricResult, MetricStatus, freeze, thaw
from sqlgraph.analyze.table_graph import TableGraph
from sqlgraph.analyze.topology import TopologyAnalysisResult, analyze_topology


MOTIF_VERSION = "1.0"
DEFAULT_FAN_THRESHOLD = 2
DEFAULT_PATH_DEPTH = 3


@dataclass(frozen=True)
class MotifAnalysisResult:
    """Task 10 result bundle for motifs and bounded path diversity."""

    summary: Mapping[str, MetricResult] = field(default_factory=dict)
    motifs: MetricResult = field(
        default_factory=lambda: MetricResult(
            name="motifs",
            status=MetricStatus.SUCCESS,
            value={"motif_count": 0, "motif_type_counts": {}},
            algorithm="motifs.empty_graph",
            version=MOTIF_VERSION,
        )
    )
    path_diversity: MetricResult = field(
        default_factory=lambda: MetricResult(
            name="path_diversity",
            status=MetricStatus.SUCCESS,
            value={"start_count": 0, "records": ()},
            algorithm="motifs.empty_graph",
            version=MOTIF_VERSION,
        )
    )
    motif_records: tuple[Mapping[str, Any], ...] = ()
    table_metrics: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", freeze(self.summary))
        object.__setattr__(
            self,
            "motif_records",
            tuple(freeze(item) for item in self.motif_records),
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
            "motifs": self.motifs.to_dict(),
            "path_diversity": self.path_diversity.to_dict(),
            "motif_records": [thaw(item) for item in self.motif_records],
            "table_metrics": [thaw(item) for item in self.table_metrics],
        }


def analyze_motifs(
    table_graph: TableGraph,
    topology: TopologyAnalysisResult | None = None,
    config: AnalysisConfig | None = None,
    *,
    communities_by_table: Mapping[str, str] | None = None,
    layers_by_table: Mapping[str, str] | None = None,
    start_tables: Sequence[str] | None = None,
    max_path_depth: int = DEFAULT_PATH_DEPTH,
) -> MotifAnalysisResult:
    """Compute bounded motif and path-diversity metrics.

    Motif mining deliberately avoids whole-subgraph enumeration. Cheap local
    motifs always run in O(V + E); two-hop diamonds and small cycles are capped
    by the exact-node budget and record a degraded status when skipped.
    """
    if max_path_depth <= 0:
        raise ValueError("max_path_depth must be greater than zero")
    config = config or AnalysisConfig()
    topology = topology or analyze_topology(table_graph, config=config)
    adjacency, reverse_adjacency = _adjacency_maps(table_graph)
    layer_labels = _layer_labels(table_graph, topology, layers_by_table)

    motif_records, motif_status, motif_reason, skipped_types = _motif_records(
        table_graph,
        topology,
        config,
        adjacency,
        reverse_adjacency,
    )
    motifs_metric = _motifs_metric(
        motif_records,
        motif_status,
        motif_reason,
        skipped_types,
        config,
    )
    path_metric = path_diversity(
        table_graph,
        config=config,
        start_tables=start_tables,
        communities_by_table=communities_by_table,
        layers_by_table=layer_labels,
        max_depth=max_path_depth,
    )
    table_metrics = _table_metrics(table_graph, motif_records, path_metric)
    return MotifAnalysisResult(
        summary=_summary_metrics(
            table_graph,
            motifs_metric,
            path_metric,
            table_metrics,
        ),
        motifs=motifs_metric,
        path_diversity=path_metric,
        motif_records=motif_records,
        table_metrics=table_metrics,
    )


def path_diversity(
    table_graph: TableGraph,
    config: AnalysisConfig | None = None,
    *,
    start_tables: Sequence[str] | None = None,
    communities_by_table: Mapping[str, str] | None = None,
    layers_by_table: Mapping[str, str] | None = None,
    max_depth: int = DEFAULT_PATH_DEPTH,
    max_paths_per_start: int | None = None,
) -> MetricResult:
    """Return bounded path diversity records for selected start tables."""
    if max_depth <= 0:
        raise ValueError("max_depth must be greater than zero")
    config = config or AnalysisConfig()
    adjacency, _reverse_adjacency = _adjacency_maps(table_graph)
    selected_starts = _select_start_tables(
        table_graph,
        config,
        start_tables,
    )
    path_limit = (
        max_paths_per_start
        if max_paths_per_start is not None
        else max(1, config.resource_budget.betweenness_samples)
    )
    if path_limit <= 0:
        raise ValueError("max_paths_per_start must be greater than zero")

    records = tuple(
        _path_record(
            adjacency,
            table_id,
            max_depth,
            path_limit,
            communities_by_table or {},
            layers_by_table or {},
            config,
        )
        for table_id in selected_starts
    )
    sampled_starts = (
        start_tables is None
        and table_graph.node_count > config.resource_budget.exact_algorithm_max_nodes
    )
    status = MetricStatus.DEGRADED if sampled_starts else MetricStatus.SUCCESS
    reason = (
        "table graph exceeds exact path-diversity start-node budget; "
        "sampled deterministic start tables"
        if sampled_starts
        else None
    )
    return MetricResult(
        name="path_diversity",
        status=status,
        value={
            "start_count": len(records),
            "records": records,
            "max_depth": max_depth,
            "max_paths_per_start": path_limit,
            "sampled_starts": sampled_starts,
        },
        reason=reason,
        algorithm="motifs.bounded_path_bfs",
        version=MOTIF_VERSION,
        parameters={
            "max_depth": max_depth,
            "max_paths_per_start": path_limit,
            "random_seed": config.random_seed,
        },
    )


def _motif_records(
    table_graph: TableGraph,
    topology: TopologyAnalysisResult,
    config: AnalysisConfig,
    adjacency: Mapping[str, tuple[str, ...]],
    reverse_adjacency: Mapping[str, tuple[str, ...]],
) -> tuple[tuple[Mapping[str, Any], ...], MetricStatus, str | None, tuple[str, ...]]:
    records: list[dict[str, Any]] = []
    records.extend(_fan_motifs(table_graph))
    records.extend(_parallel_link_motifs(table_graph))
    skipped_types: tuple[str, ...] = ()
    status = MetricStatus.SUCCESS
    reason = None

    budget = config.resource_budget.exact_algorithm_max_nodes
    if table_graph.node_count <= budget:
        records.extend(_diamond_motifs(adjacency, reverse_adjacency))
        records.extend(_cycle_motifs(adjacency, topology))
    else:
        status = MetricStatus.DEGRADED
        reason = (
            "table graph exceeds exact motif node budget "
            f"({table_graph.node_count} > {budget}); skipped bounded "
            "diamond and cycle enumeration"
        )
        skipped_types = ("diamond", "small_cycle")

    ordered = tuple(
        sorted(
            records,
            key=lambda item: (
                str(item["motif_type"]),
                str(item.get("source_table_id", "")),
                str(item.get("target_table_id", "")),
                str(item.get("table_id", "")),
                tuple(str(value) for value in item.get("member_table_ids", ())),
            ),
        )
    )
    return ordered, status, reason, skipped_types


def _fan_motifs(table_graph: TableGraph) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for table_id in table_graph.nodes:
        in_degree = int(table_graph.in_degree.get(table_id, 0))
        out_degree = int(table_graph.out_degree.get(table_id, 0))
        if in_degree >= DEFAULT_FAN_THRESHOLD:
            records.append(
                {
                    "motif_type": "fan_in",
                    "table_id": table_id,
                    "degree": in_degree,
                    "upstream_table_ids": [
                        edge.source_id
                        for edge in table_graph.edges
                        if edge.target_id == table_id
                    ],
                }
            )
        if out_degree >= DEFAULT_FAN_THRESHOLD:
            records.append(
                {
                    "motif_type": "fan_out",
                    "table_id": table_id,
                    "degree": out_degree,
                    "downstream_table_ids": [
                        edge.target_id for edge in table_graph.successors(table_id)
                    ],
                }
            )
    return records


def _parallel_link_motifs(table_graph: TableGraph) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for edge in table_graph.edges:
        dependency_count = int(edge.field_weight) + int(edge.sql_weight)
        if dependency_count <= 1:
            continue
        records.append(
            {
                "motif_type": "parallel_link",
                "source_table_id": edge.source_id,
                "target_table_id": edge.target_id,
                "dependency_count": dependency_count,
                "field_weight": int(edge.field_weight),
                "sql_weight": int(edge.sql_weight),
            }
        )
    return records


def _diamond_motifs(
    adjacency: Mapping[str, tuple[str, ...]],
    reverse_adjacency: Mapping[str, tuple[str, ...]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source in sorted(adjacency):
        branches = adjacency.get(source, ())
        if len(branches) < 2:
            continue
        candidate_targets = sorted(
            {
                target
                for branch in branches
                for target in adjacency.get(branch, ())
                if target != source
            }
        )
        for target in candidate_targets:
            via = tuple(
                branch
                for branch in branches
                if target in adjacency.get(branch, ())
            )
            if len(via) < 2:
                continue
            # The reverse adjacency check keeps this a true two-hop convergence.
            if len(set(via) & set(reverse_adjacency.get(target, ()))) < 2:
                continue
            records.append(
                {
                    "motif_type": "diamond",
                    "source_table_id": source,
                    "target_table_id": target,
                    "branch_table_ids": list(via),
                    "branch_count": len(via),
                    "orientation": "diverge_converge",
                }
            )
    return records


def _cycle_motifs(
    adjacency: Mapping[str, tuple[str, ...]],
    topology: TopologyAnalysisResult,
    *,
    max_cycle_length: int = 5,
) -> list[dict[str, Any]]:
    candidate_nodes = {
        str(member)
        for component in topology.strong_components
        if bool(component.get("has_cycle")) and int(component.get("size", 0)) <= max_cycle_length
        for member in component.get("members", ())
    }
    cycles: set[tuple[str, ...]] = set()
    for start in sorted(candidate_nodes):
        stack: list[tuple[str, tuple[str, ...]]] = [(start, (start,))]
        while stack:
            node_id, path = stack.pop()
            if len(path) > max_cycle_length:
                continue
            for successor in adjacency.get(node_id, ()):
                if successor == start and len(path) > 1:
                    cycles.add(_canonical_cycle(path))
                elif successor in candidate_nodes and successor not in path:
                    stack.append((successor, path + (successor,)))
    return [
        {
            "motif_type": "small_cycle",
            "member_table_ids": list(cycle),
            "cycle_length": len(cycle),
        }
        for cycle in sorted(cycles)
    ]


def _canonical_cycle(path: tuple[str, ...]) -> tuple[str, ...]:
    rotations = [path[index:] + path[:index] for index in range(len(path))]
    reversed_path = tuple(reversed(path))
    rotations.extend(
        reversed_path[index:] + reversed_path[:index]
        for index in range(len(reversed_path))
    )
    return min(rotations)


def _path_record(
    adjacency: Mapping[str, tuple[str, ...]],
    start: str,
    max_depth: int,
    max_paths: int,
    communities_by_table: Mapping[str, str],
    layers_by_table: Mapping[str, str],
    config: AnalysisConfig,
) -> dict[str, Any]:
    queue: deque[tuple[str, tuple[str, ...]]] = deque([(start, (start,))])
    path_count = 0
    truncated = False
    targets: set[str] = set()
    terminal_targets: set[str] = set()
    depth_counts: Counter[int] = Counter()
    community_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()

    while queue:
        node_id, path = queue.popleft()
        depth = len(path) - 1
        if depth == max_depth or not adjacency.get(node_id):
            if depth > 0:
                terminal = path[-1]
                terminal_targets.add(terminal)
                depth_counts[depth] += 1
            continue
        for successor in adjacency.get(node_id, ()):
            if successor in path:
                continue
            next_path = path + (successor,)
            path_count += 1
            targets.add(successor)
            community = str(communities_by_table.get(successor, "unknown"))
            layer = str(layers_by_table.get(successor, "unknown"))
            community_counts[community] += 1
            layer_counts[layer] += 1
            if path_count >= max_paths:
                truncated = True
                queue.clear()
                break
            queue.append((successor, next_path))
        if truncated:
            break

    return {
        "table_id": start,
        "bounded_path_count": path_count,
        "unique_target_count": len(targets),
        "terminal_target_count": len(terminal_targets),
        "max_depth": max_depth,
        "max_depth_reached": max(depth_counts.keys(), default=0),
        "truncated": truncated,
        "depth_distribution": [
            {"depth": depth, "path_count": count}
            for depth, count in sorted(depth_counts.items())
        ],
        "layer_distribution": dict(sorted(layer_counts.items())),
        "community_distribution": dict(sorted(community_counts.items())),
        "path_entropy": _entropy(community_counts, config.float_precision),
    }


def _select_start_tables(
    table_graph: TableGraph,
    config: AnalysisConfig,
    start_tables: Sequence[str] | None,
) -> tuple[str, ...]:
    if start_tables is not None:
        return tuple(
            sorted(
                {
                    str(table_id)
                    for table_id in start_tables
                    if table_graph.has_node(str(table_id))
                }
            )
        )
    if table_graph.node_count <= config.resource_budget.exact_algorithm_max_nodes:
        return tuple(table_graph.nodes)

    sample_size = min(
        config.resource_budget.betweenness_samples,
        table_graph.node_count,
    )
    rng = random.Random(config.random_seed)
    return tuple(sorted(rng.sample(list(table_graph.nodes), sample_size)))


def _table_metrics(
    table_graph: TableGraph,
    motif_records: tuple[Mapping[str, Any], ...],
    path_metric: MetricResult,
) -> tuple[Mapping[str, Any], ...]:
    motif_counts: dict[str, Counter[str]] = {
        table_id: Counter() for table_id in table_graph.nodes
    }
    for record in motif_records:
        motif_type = str(record["motif_type"])
        for table_id in _motif_member_ids(record):
            if table_id in motif_counts:
                motif_counts[table_id][motif_type] += 1

    path_records = {
        str(item["table_id"]): item
        for item in thaw(path_metric.value).get("records", ())
    }
    return tuple(
        {
            "table_id": table_id,
            "table_name": _table_full_name(table_graph.nodes_by_id.get(table_id, {})),
            "motif_count": sum(motif_counts[table_id].values()),
            "motif_type_counts": dict(sorted(motif_counts[table_id].items())),
            "bounded_path_count": int(
                path_records.get(table_id, {}).get("bounded_path_count", 0)
            ),
            "path_unique_target_count": int(
                path_records.get(table_id, {}).get("unique_target_count", 0)
            ),
            "path_entropy": path_records.get(table_id, {}).get("path_entropy"),
        }
        for table_id in table_graph.nodes
    )


def _motif_member_ids(record: Mapping[str, Any]) -> tuple[str, ...]:
    motif_type = str(record["motif_type"])
    if motif_type in {"fan_in", "fan_out"}:
        return (str(record["table_id"]),)
    if motif_type == "parallel_link":
        return (
            str(record["source_table_id"]),
            str(record["target_table_id"]),
        )
    if motif_type == "diamond":
        return tuple(
            sorted(
                {
                    str(record["source_table_id"]),
                    str(record["target_table_id"]),
                    *(str(item) for item in record.get("branch_table_ids", ())),
                }
            )
        )
    if motif_type == "small_cycle":
        return tuple(str(item) for item in record.get("member_table_ids", ()))
    return ()


def _motifs_metric(
    records: tuple[Mapping[str, Any], ...],
    status: MetricStatus,
    reason: str | None,
    skipped_types: tuple[str, ...],
    config: AnalysisConfig,
) -> MetricResult:
    type_counts = Counter(str(record["motif_type"]) for record in records)
    return MetricResult(
        name="motifs",
        status=status,
        value={
            "motif_count": len(records),
            "motif_type_counts": dict(sorted(type_counts.items())),
            "records": records,
            "skipped_motif_types": skipped_types,
        },
        reason=reason,
        algorithm="motifs.bounded_local_patterns",
        version=MOTIF_VERSION,
        parameters={
            "fan_threshold": DEFAULT_FAN_THRESHOLD,
            "exact_algorithm_max_nodes": (
                config.resource_budget.exact_algorithm_max_nodes
            ),
            "small_cycle_max_length": 5,
        },
    )


def _summary_metrics(
    table_graph: TableGraph,
    motifs_metric: MetricResult,
    path_metric: MetricResult,
    table_metrics: tuple[Mapping[str, Any], ...],
) -> dict[str, MetricResult]:
    motif_value = thaw(motifs_metric.value)
    path_value = thaw(path_metric.value)
    top_motif_tables = _top_tables(table_metrics, "motif_count")
    return {
        "motif_count": _success_metric(
            "motif_count",
            int(motif_value.get("motif_count", 0)),
        ),
        "motif_type_counts": _success_metric(
            "motif_type_counts",
            motif_value.get("motif_type_counts", {}),
        ),
        "path_diversity_start_count": _success_metric(
            "path_diversity_start_count",
            int(path_value.get("start_count", 0)),
        ),
        "path_diversity_truncated_table_count": _success_metric(
            "path_diversity_truncated_table_count",
            sum(
                1
                for item in path_value.get("records", ())
                if bool(item.get("truncated"))
            ),
        ),
        "top_motif_tables": _success_metric("top_motif_tables", top_motif_tables),
        "table_count": _success_metric("table_count", table_graph.node_count),
    }


def _top_tables(
    table_metrics: tuple[Mapping[str, Any], ...],
    key: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    rows = [item for item in table_metrics if int(item.get(key, 0)) > 0]
    rows.sort(key=lambda item: (-int(item[key]), str(item["table_id"])))
    return [
        {
            "table_id": str(item["table_id"]),
            "table_name": str(item["table_name"]),
            key: int(item[key]),
        }
        for item in rows[:limit]
    ]


def _adjacency_maps(
    table_graph: TableGraph,
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    outgoing: dict[str, set[str]] = {node_id: set() for node_id in table_graph.nodes}
    incoming: dict[str, set[str]] = {node_id: set() for node_id in table_graph.nodes}
    for edge in table_graph.edges:
        outgoing.setdefault(edge.source_id, set()).add(edge.target_id)
        incoming.setdefault(edge.target_id, set()).add(edge.source_id)
    return (
        {node_id: tuple(sorted(items)) for node_id, items in outgoing.items()},
        {node_id: tuple(sorted(items)) for node_id, items in incoming.items()},
    )


def _layer_labels(
    table_graph: TableGraph,
    topology: TopologyAnalysisResult,
    layers_by_table: Mapping[str, str] | None,
) -> dict[str, str]:
    if layers_by_table is not None:
        return {
            table_id: str(layers_by_table.get(table_id, "unknown"))
            for table_id in table_graph.nodes
        }
    labels = {table_id: "unknown" for table_id in table_graph.nodes}
    for item in topology.table_metrics:
        table_id = str(item["table_id"])
        if table_id in labels:
            labels[table_id] = str(item.get("declared_layer", "unknown"))
    return labels


def _entropy(counts: Mapping[str, int], precision: int) -> float:
    total = sum(int(value) for value in counts.values())
    if total <= 0:
        return 0.0
    import math

    entropy = 0.0
    for count in counts.values():
        if count <= 0:
            continue
        probability = count / total
        entropy -= probability * math.log2(probability)
    return round(entropy, precision)


def _success_metric(name: str, value: Any) -> MetricResult:
    return MetricResult(
        name=name,
        status=MetricStatus.SUCCESS,
        value=value,
        algorithm="motifs.summary",
        version=MOTIF_VERSION,
    )


def _table_full_name(table: Mapping[str, Any]) -> str:
    parts = [
        str(value)
        for value in (table.get("catalog"), table.get("schema_name"), table.get("name"))
        if value
    ]
    return ".".join(parts) if parts else str(table.get("name", ""))
