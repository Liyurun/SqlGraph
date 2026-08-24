# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Impact radius and core-asset metrics over the physical TableGraph."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
import math
import random  # allow-random: deterministic analysis sampling uses an explicit seed
from typing import Any, Mapping

from sqlgraph.analyze.config import AnalysisConfig
from sqlgraph.analyze.contracts import MetricResult, MetricStatus, freeze, thaw
from sqlgraph.analyze.table_graph import TableGraph
from sqlgraph.analyze.topology import TopologyAnalysisResult, analyze_topology


IMPACT_VERSION = "1.0"
BLAST_SCORE_VERSION = "1.0"
BLAST_SCORE_WEIGHTS: Mapping[str, float] = {
    "direct_downstream": 0.20,
    "indirect_downstream": 0.30,
    "sql_dependency": 0.15,
    "field_dependency": 0.10,
    "impact_entropy": 0.15,
    "betweenness": 0.10,
}


@dataclass(frozen=True)
class ImpactAnalysisResult:
    """Task 6 result bundle for downstream impact and core-asset scoring."""

    summary: Mapping[str, MetricResult] = field(default_factory=dict)
    reachability: MetricResult = field(
        default_factory=lambda: MetricResult(
            name="batch_reachability",
            status=MetricStatus.SUCCESS,
            value={},
            algorithm="impact.empty_graph",
            version=IMPACT_VERSION,
        )
    )
    betweenness: MetricResult = field(
        default_factory=lambda: MetricResult(
            name="betweenness",
            status=MetricStatus.SUCCESS,
            value={},
            algorithm="impact.empty_graph",
            version=IMPACT_VERSION,
        )
    )
    table_metrics: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", freeze(self.summary))
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
            "reachability": self.reachability.to_dict(),
            "betweenness": self.betweenness.to_dict(),
            "table_metrics": [thaw(item) for item in self.table_metrics],
        }


@dataclass(frozen=True)
class _SccModel:
    component_ids: tuple[str, ...]
    component_members: Mapping[str, tuple[str, ...]]
    component_by_table: Mapping[str, str]
    dag_adjacency: Mapping[str, tuple[str, ...]]
    reverse_dag_adjacency: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class _ReachabilityData:
    mode: str
    status: MetricStatus
    reason: str | None
    downstream_counts: Mapping[str, int]
    upstream_counts: Mapping[str, int]
    downstream_masks: Mapping[str, int] | None
    upstream_masks: Mapping[str, int] | None
    component_index: Mapping[str, int]


def analyze_impact(
    table_graph: TableGraph,
    topology: TopologyAnalysisResult | None = None,
    config: AnalysisConfig | None = None,
    *,
    communities_by_table: Mapping[str, str] | None = None,
    layers_by_table: Mapping[str, str] | None = None,
    top_n: int = 10,
) -> ImpactAnalysisResult:
    """Compute Task 6 impact metrics without mutating the source graph.

    Batch reachability is computed on the SCC DAG. Exact mode uses integer
    bitsets; over the exact-node budget it falls back to a deterministic
    topological upper-bound estimate and records a degraded status.
    """
    config = config or AnalysisConfig()
    topology = topology or analyze_topology(table_graph, config=config)
    scc_model = _build_scc_model(topology)
    reachability_data = _batch_reachability(table_graph, scc_model, config)
    reachability_metric = _reachability_metric(table_graph, scc_model, reachability_data)
    betweenness_metric = _betweenness_metric(table_graph, config)
    layer_labels = _layer_labels(
        table_graph,
        topology,
        layers_by_table=layers_by_table,
    )
    table_metrics = _table_metrics(
        table_graph,
        scc_model,
        reachability_data,
        betweenness_metric,
        config,
        layer_labels=layer_labels,
        community_labels=communities_by_table,
    )
    table_metrics = _with_blast_scores(table_metrics, config)
    return ImpactAnalysisResult(
        summary=_summary_metrics(
            table_graph,
            reachability_metric,
            betweenness_metric,
            table_metrics,
            communities_by_table=communities_by_table,
            top_n=top_n,
        ),
        reachability=reachability_metric,
        betweenness=betweenness_metric,
        table_metrics=table_metrics,
    )


def n_hop_impact(
    table_graph: TableGraph,
    table_id: str,
    depth: int,
    *,
    direction: str = "downstream",
) -> MetricResult:
    """Return a deterministic N-hop upstream or downstream BFS result."""
    if depth < 0:
        raise ValueError("depth must be greater than or equal to zero")
    if direction not in {"downstream", "upstream"}:
        raise ValueError("direction must be 'downstream' or 'upstream'")
    if not table_graph.has_node(table_id):
        return MetricResult(
            name="n_hop_impact",
            status=MetricStatus.UNAVAILABLE,
            reason=f"table_id {table_id!r} is not present in the TableGraph",
            algorithm="impact.n_hop_bfs",
            version=IMPACT_VERSION,
            parameters={"depth": depth, "direction": direction},
        )

    adjacency, reverse_adjacency = _adjacency_maps(table_graph)
    selected = adjacency if direction == "downstream" else reverse_adjacency
    levels = _bfs_levels(selected, table_id, depth)
    nodes = tuple(sorted(node_id for level in levels for node_id in level))
    value = {
        "table_id": table_id,
        "direction": direction,
        "depth": depth,
        "count": len(nodes),
        "nodes": list(nodes),
        "hop_counts": [
            {"hop": hop, "count": len(level)}
            for hop, level in enumerate(levels, start=1)
        ],
        "levels": [
            {"hop": hop, "nodes": list(level)}
            for hop, level in enumerate(levels, start=1)
        ],
    }
    return MetricResult(
        name="n_hop_impact",
        status=MetricStatus.SUCCESS,
        value=value,
        algorithm="impact.n_hop_bfs",
        version=IMPACT_VERSION,
        parameters={"depth": depth, "direction": direction},
    )


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


def _bfs_levels(
    adjacency: Mapping[str, tuple[str, ...]],
    start: str,
    depth: int,
) -> list[tuple[str, ...]]:
    visited = {start}
    frontier = {start}
    levels: list[tuple[str, ...]] = []
    for _ in range(depth):
        next_frontier: set[str] = set()
        for node_id in sorted(frontier):
            for neighbor in adjacency.get(node_id, ()):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                next_frontier.add(neighbor)
        if not next_frontier:
            break
        level = tuple(sorted(next_frontier))
        levels.append(level)
        frontier = set(level)
    return levels


def _build_scc_model(topology: TopologyAnalysisResult) -> _SccModel:
    component_members: dict[str, tuple[str, ...]] = {}
    component_by_table: dict[str, str] = {}
    for record in topology.strong_components:
        component_id = str(record["component_id"])
        members = tuple(sorted(str(item) for item in record.get("members", ())))
        component_members[component_id] = members
        for table_id in members:
            component_by_table[table_id] = component_id

    component_ids = tuple(sorted(component_members))
    adjacency: dict[str, set[str]] = {component_id: set() for component_id in component_ids}
    reverse_adjacency: dict[str, set[str]] = {
        component_id: set() for component_id in component_ids
    }
    for edge in topology.scc_dag_edges:
        source = str(edge["source_component_id"])
        target = str(edge["target_component_id"])
        if source == target:
            continue
        adjacency.setdefault(source, set()).add(target)
        reverse_adjacency.setdefault(target, set()).add(source)

    return _SccModel(
        component_ids=component_ids,
        component_members=component_members,
        component_by_table=component_by_table,
        dag_adjacency={
            component_id: tuple(sorted(targets))
            for component_id, targets in adjacency.items()
        },
        reverse_dag_adjacency={
            component_id: tuple(sorted(sources))
            for component_id, sources in reverse_adjacency.items()
        },
    )


def _batch_reachability(
    table_graph: TableGraph,
    scc_model: _SccModel,
    config: AnalysisConfig,
) -> _ReachabilityData:
    component_index = {
        component_id: index
        for index, component_id in enumerate(scc_model.component_ids)
    }
    if table_graph.node_count == 0:
        return _ReachabilityData(
            mode="exact_bitset",
            status=MetricStatus.SUCCESS,
            reason=None,
            downstream_counts={},
            upstream_counts={},
            downstream_masks={},
            upstream_masks={},
            component_index=component_index,
        )

    component_count = len(scc_model.component_ids)
    budget = config.resource_budget.exact_algorithm_max_nodes
    if component_count <= budget:
        downstream_masks = _component_reachability_masks(
            scc_model.component_ids,
            scc_model.dag_adjacency,
            component_index,
        )
        upstream_masks = _component_reachability_masks(
            scc_model.component_ids,
            scc_model.reverse_dag_adjacency,
            component_index,
        )
        return _ReachabilityData(
            mode="exact_bitset",
            status=MetricStatus.SUCCESS,
            reason=None,
            downstream_counts=_table_counts_from_masks(
                table_graph,
                scc_model,
                downstream_masks,
                component_index,
            ),
            upstream_counts=_table_counts_from_masks(
                table_graph,
                scc_model,
                upstream_masks,
                component_index,
            ),
            downstream_masks=downstream_masks,
            upstream_masks=upstream_masks,
            component_index=component_index,
        )

    reason = (
        "SCC component count exceeds exact reachability node budget "
        f"({component_count} > {budget})"
    )
    if not config.allow_degraded:
        return _ReachabilityData(
            mode="skipped_over_budget",
            status=MetricStatus.UNAVAILABLE,
            reason=reason,
            downstream_counts={},
            upstream_counts={},
            downstream_masks=None,
            upstream_masks=None,
            component_index=component_index,
        )

    return _ReachabilityData(
        mode="approx_topological_upper_bound",
        status=MetricStatus.DEGRADED,
        reason=reason,
        downstream_counts=_table_counts_from_estimates(
            table_graph,
            scc_model,
            _estimated_component_reachability_counts(
                scc_model.component_ids,
                scc_model.component_members,
                scc_model.dag_adjacency,
            ),
        ),
        upstream_counts=_table_counts_from_estimates(
            table_graph,
            scc_model,
            _estimated_component_reachability_counts(
                scc_model.component_ids,
                scc_model.component_members,
                scc_model.reverse_dag_adjacency,
            ),
        ),
        downstream_masks=None,
        upstream_masks=None,
        component_index=component_index,
    )


def _component_reachability_masks(
    component_ids: tuple[str, ...],
    adjacency: Mapping[str, tuple[str, ...]],
    component_index: Mapping[str, int],
) -> dict[str, int]:
    masks = {component_id: 0 for component_id in component_ids}
    for component_id in reversed(_topological_order(component_ids, adjacency)):
        mask = 0
        for target in adjacency.get(component_id, ()):
            mask |= 1 << int(component_index[target])
            mask |= masks[target]
        masks[component_id] = mask
    return masks


def _topological_order(
    component_ids: tuple[str, ...],
    adjacency: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    indegree = {component_id: 0 for component_id in component_ids}
    for source in component_ids:
        for target in adjacency.get(source, ()):
            indegree[target] = indegree.get(target, 0) + 1
    queue = deque(sorted(component_id for component_id, degree in indegree.items() if degree == 0))
    ordered: list[str] = []
    while queue:
        component_id = queue.popleft()
        ordered.append(component_id)
        for target in adjacency.get(component_id, ()):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
        queue = deque(sorted(queue))
    if len(ordered) != len(component_ids):
        ordered.extend(component_id for component_id in component_ids if component_id not in ordered)
    return tuple(ordered)


def _table_counts_from_masks(
    table_graph: TableGraph,
    scc_model: _SccModel,
    masks: Mapping[str, int],
    component_index: Mapping[str, int],
) -> dict[str, int]:
    sizes_by_index = {
        int(index): len(scc_model.component_members[component_id])
        for component_id, index in component_index.items()
    }
    counts: dict[str, int] = {}
    for table_id in table_graph.nodes:
        component_id = scc_model.component_by_table[table_id]
        same_component_peers = len(scc_model.component_members[component_id]) - 1
        reachable_count = _mask_weighted_count(
            int(masks.get(component_id, 0)),
            sizes_by_index,
        )
        counts[table_id] = min(
            table_graph.node_count - 1,
            same_component_peers + reachable_count,
        )
    return counts


def _mask_weighted_count(mask: int, sizes_by_index: Mapping[int, int]) -> int:
    count = 0
    current = mask
    while current:
        bit = current & -current
        index = bit.bit_length() - 1
        count += int(sizes_by_index.get(index, 0))
        current ^= bit
    return count


def _estimated_component_reachability_counts(
    component_ids: tuple[str, ...],
    component_members: Mapping[str, tuple[str, ...]],
    adjacency: Mapping[str, tuple[str, ...]],
) -> dict[str, int]:
    counts = {component_id: 0 for component_id in component_ids}
    for component_id in reversed(_topological_order(component_ids, adjacency)):
        counts[component_id] = sum(
            len(component_members.get(target, ())) + counts.get(target, 0)
            for target in adjacency.get(component_id, ())
        )
    return counts


def _table_counts_from_estimates(
    table_graph: TableGraph,
    scc_model: _SccModel,
    component_counts: Mapping[str, int],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_id in table_graph.nodes:
        component_id = scc_model.component_by_table[table_id]
        same_component_peers = len(scc_model.component_members[component_id]) - 1
        counts[table_id] = min(
            table_graph.node_count - 1,
            same_component_peers + int(component_counts.get(component_id, 0)),
        )
    return counts


def _reachability_metric(
    table_graph: TableGraph,
    scc_model: _SccModel,
    data: _ReachabilityData,
) -> MetricResult:
    value = {
        "mode": data.mode,
        "table_count": table_graph.node_count,
        "component_count": len(scc_model.component_ids),
        "downstream_counts": {
            table_id: int(data.downstream_counts[table_id])
            for table_id in sorted(data.downstream_counts)
        },
        "upstream_counts": {
            table_id: int(data.upstream_counts[table_id])
            for table_id in sorted(data.upstream_counts)
        },
        "exact_masks_available": data.downstream_masks is not None,
    }
    return MetricResult(
        name="batch_reachability",
        status=data.status,
        value=value,
        reason=data.reason if data.status != MetricStatus.SUCCESS else None,
        algorithm=f"impact.{data.mode}",
        version=IMPACT_VERSION,
        parameters={"component_granularity": "scc_dag"},
    )


def _betweenness_metric(
    table_graph: TableGraph,
    config: AnalysisConfig,
) -> MetricResult:
    adjacency, _ = _adjacency_maps(table_graph)
    nodes = tuple(sorted(table_graph.nodes))
    if not nodes:
        return MetricResult(
            name="betweenness",
            status=MetricStatus.SUCCESS,
            value={},
            algorithm="impact.empty_graph",
            version=IMPACT_VERSION,
        )

    if len(nodes) > config.resource_budget.exact_algorithm_max_nodes:
        sample_size = min(config.resource_budget.betweenness_samples, len(nodes))
        rng = random.Random(config.random_seed)
        sources = tuple(sorted(rng.sample(list(nodes), sample_size)))
        mode = "approximate_sampled"
        algorithm = "impact.betweenness_brandes_sampled"
    else:
        sources = nodes
        mode = "exact"
        algorithm = "impact.betweenness_brandes_exact"

    values = _brandes_betweenness(nodes, adjacency, sources)
    if len(sources) < len(nodes):
        factor = len(nodes) / len(sources)
        values = {node_id: value * factor for node_id, value in values.items()}
    values = _normalize_betweenness(values, len(nodes), config.float_precision)
    return MetricResult(
        name="betweenness",
        status=MetricStatus.SUCCESS,
        value=values,
        algorithm=algorithm,
        version=IMPACT_VERSION,
        parameters={
            "mode": mode,
            "sample_size": len(sources),
            "node_count": len(nodes),
            "random_seed": config.random_seed,
            "normalized": True,
        },
    )


def _brandes_betweenness(
    nodes: tuple[str, ...],
    adjacency: Mapping[str, tuple[str, ...]],
    sources: tuple[str, ...],
) -> dict[str, float]:
    centrality = {node_id: 0.0 for node_id in nodes}
    for source in sources:
        stack: list[str] = []
        predecessors = {node_id: [] for node_id in nodes}
        sigma = {node_id: 0.0 for node_id in nodes}
        distance = {node_id: -1 for node_id in nodes}
        sigma[source] = 1.0
        distance[source] = 0
        queue: deque[str] = deque([source])
        while queue:
            node_id = queue.popleft()
            stack.append(node_id)
            for successor in adjacency.get(node_id, ()):
                if distance[successor] < 0:
                    queue.append(successor)
                    distance[successor] = distance[node_id] + 1
                if distance[successor] == distance[node_id] + 1:
                    sigma[successor] += sigma[node_id]
                    predecessors[successor].append(node_id)

        dependency = {node_id: 0.0 for node_id in nodes}
        while stack:
            target = stack.pop()
            if sigma[target] == 0:
                continue
            for predecessor in predecessors[target]:
                dependency[predecessor] += (
                    sigma[predecessor] / sigma[target]
                ) * (1.0 + dependency[target])
            if target != source:
                centrality[target] += dependency[target]
    return centrality


def _normalize_betweenness(
    values: Mapping[str, float],
    node_count: int,
    precision: int,
) -> dict[str, float]:
    if node_count <= 2:
        return {node_id: 0.0 for node_id in sorted(values)}
    scale = 1.0 / ((node_count - 1) * (node_count - 2))
    return {
        node_id: round(float(values[node_id]) * scale, precision)
        for node_id in sorted(values)
    }


def _layer_labels(
    table_graph: TableGraph,
    topology: TopologyAnalysisResult,
    *,
    layers_by_table: Mapping[str, str] | None,
) -> dict[str, str]:
    if layers_by_table is not None:
        return {
            table_id: str(layers_by_table.get(table_id, "unknown"))
            for table_id in table_graph.nodes
        }
    labels: dict[str, str] = {}
    for item in topology.table_metrics:
        table_id = str(item["table_id"])
        declared = str(item.get("declared_layer", "unknown"))
        if declared != "unknown":
            labels[table_id] = declared
        else:
            labels[table_id] = f"graph_layer_{int(item.get('graph_layer_max', 0))}"
    return {table_id: labels.get(table_id, "unknown") for table_id in table_graph.nodes}


def _table_metrics(
    table_graph: TableGraph,
    scc_model: _SccModel,
    reachability: _ReachabilityData,
    betweenness: MetricResult,
    config: AnalysisConfig,
    *,
    layer_labels: Mapping[str, str],
    community_labels: Mapping[str, str] | None,
) -> tuple[Mapping[str, Any], ...]:
    betweenness_values = (
        thaw(betweenness.value)
        if betweenness.status == MetricStatus.SUCCESS and isinstance(thaw(betweenness.value), dict)
        else {}
    )
    edge_weights = _edge_weight_totals(table_graph)
    records: list[dict[str, Any]] = []
    for table_id in table_graph.nodes:
        downstream_nodes = _reachable_tables(
            table_id,
            table_graph,
            scc_model,
            reachability.downstream_masks,
            reachability.component_index,
        )
        layer_distribution = _label_distribution(downstream_nodes, layer_labels)
        community_distribution = (
            _label_distribution(downstream_nodes, community_labels)
            if community_labels is not None
            else {}
        )
        layer_entropy = _shannon_entropy(layer_distribution, config.float_precision)
        community_entropy = (
            _shannon_entropy(community_distribution, config.float_precision)
            if community_labels is not None
            else None
        )
        downstream_count = reachability.downstream_counts.get(table_id)
        upstream_count = reachability.upstream_counts.get(table_id)
        direct_downstream = int(table_graph.out_degree.get(table_id, 0))
        indirect_downstream = (
            None
            if downstream_count is None
            else max(0, int(downstream_count) - direct_downstream)
        )
        table = table_graph.nodes_by_id.get(table_id, {})
        records.append(
            {
                "table_id": table_id,
                "table_name": _table_full_name(table),
                "direct_downstream_count": direct_downstream,
                "direct_upstream_count": int(table_graph.in_degree.get(table_id, 0)),
                "downstream_reachability_count": downstream_count,
                "upstream_reachability_count": upstream_count,
                "indirect_downstream_count": indirect_downstream,
                "reachability_mode": reachability.mode,
                "reachability_status": reachability.status.value,
                "out_field_weight": edge_weights["out_field"].get(table_id, 0),
                "in_field_weight": edge_weights["in_field"].get(table_id, 0),
                "out_sql_weight": edge_weights["out_sql"].get(table_id, 0),
                "in_sql_weight": edge_weights["in_sql"].get(table_id, 0),
                "betweenness": betweenness_values.get(table_id),
                "downstream_layer_distribution": layer_distribution,
                "downstream_community_distribution": community_distribution,
                "impact_layer_entropy": layer_entropy,
                "impact_community_entropy": community_entropy,
                "impact_entropy": (
                    community_entropy
                    if community_entropy is not None
                    else layer_entropy
                ),
            }
        )
    return tuple(records)


def _edge_weight_totals(table_graph: TableGraph) -> dict[str, dict[str, int]]:
    totals = {
        "out_field": {node_id: 0 for node_id in table_graph.nodes},
        "in_field": {node_id: 0 for node_id in table_graph.nodes},
        "out_sql": {node_id: 0 for node_id in table_graph.nodes},
        "in_sql": {node_id: 0 for node_id in table_graph.nodes},
    }
    for edge in table_graph.edges:
        totals["out_field"][edge.source_id] += int(edge.field_weight)
        totals["in_field"][edge.target_id] += int(edge.field_weight)
        totals["out_sql"][edge.source_id] += int(edge.sql_weight)
        totals["in_sql"][edge.target_id] += int(edge.sql_weight)
    return totals


def _reachable_tables(
    table_id: str,
    table_graph: TableGraph,
    scc_model: _SccModel,
    masks: Mapping[str, int] | None,
    component_index: Mapping[str, int],
) -> tuple[str, ...]:
    component_id = scc_model.component_by_table[table_id]
    members = set(scc_model.component_members[component_id])
    if masks is not None:
        index_component = {index: component_id for component_id, index in component_index.items()}
        current = int(masks.get(component_id, 0))
        while current:
            bit = current & -current
            index = bit.bit_length() - 1
            members.update(scc_model.component_members.get(index_component[index], ()))
            current ^= bit
    members.discard(table_id)
    return tuple(sorted(node_id for node_id in members if node_id in table_graph.node_index))


def _label_distribution(
    table_ids: tuple[str, ...],
    labels: Mapping[str, str] | None,
) -> dict[str, int]:
    if labels is None:
        return {}
    counts: Counter[str] = Counter()
    for table_id in table_ids:
        counts[str(labels.get(table_id, "unknown"))] += 1
    return {label: counts[label] for label in sorted(counts)}


def _shannon_entropy(distribution: Mapping[str, int], precision: int) -> float:
    total = sum(int(value) for value in distribution.values())
    if total <= 0:
        return 0.0
    entropy = 0.0
    for count in distribution.values():
        probability = int(count) / total
        entropy -= probability * math.log2(probability)
    return round(entropy, precision)


def _with_blast_scores(
    table_metrics: tuple[Mapping[str, Any], ...],
    config: AnalysisConfig,
) -> tuple[Mapping[str, Any], ...]:
    maxima = {
        "direct_downstream": _max_numeric(table_metrics, "direct_downstream_count"),
        "indirect_downstream": _max_numeric(table_metrics, "indirect_downstream_count"),
        "sql_dependency": _max_numeric(table_metrics, "out_sql_weight"),
        "field_dependency": _max_numeric(table_metrics, "out_field_weight"),
        "impact_entropy": _max_numeric(table_metrics, "impact_entropy"),
        "betweenness": _max_numeric(table_metrics, "betweenness"),
    }
    records: list[Mapping[str, Any]] = []
    for item in table_metrics:
        plain = dict(item)
        submetrics = {
            "direct_downstream": _normalize_feature(
                plain.get("direct_downstream_count"),
                maxima["direct_downstream"],
                config.float_precision,
            ),
            "indirect_downstream": _normalize_feature(
                plain.get("indirect_downstream_count"),
                maxima["indirect_downstream"],
                config.float_precision,
            ),
            "sql_dependency": _normalize_feature(
                plain.get("out_sql_weight"),
                maxima["sql_dependency"],
                config.float_precision,
            ),
            "field_dependency": _normalize_feature(
                plain.get("out_field_weight"),
                maxima["field_dependency"],
                config.float_precision,
            ),
            "impact_entropy": _normalize_feature(
                plain.get("impact_entropy"),
                maxima["impact_entropy"],
                config.float_precision,
            ),
            "betweenness": _normalize_feature(
                plain.get("betweenness"),
                maxima["betweenness"],
                config.float_precision,
            ),
        }
        missing = sorted(name for name, value in submetrics.items() if value is None)
        plain["blast_score"] = _weighted_score(submetrics, config.float_precision)
        plain["blast_score_status"] = "success" if not missing else "degraded"
        plain["blast_score_version"] = _blast_score_version(config)
        plain["blast_score_submetrics"] = submetrics
        plain["blast_score_weights"] = {
            name: BLAST_SCORE_WEIGHTS[name]
            for name, value in submetrics.items()
            if value is not None
        }
        plain["blast_score_missing_submetrics"] = missing
        records.append(plain)
    return tuple(
        sorted(
            records,
            key=lambda item: (
                item["blast_score"] is None,
                -float(item["blast_score"] or 0.0),
                str(item["table_id"]),
            ),
        )
    )


def _max_numeric(records: tuple[Mapping[str, Any], ...], key: str) -> float:
    values = [
        float(item[key])
        for item in records
        if item.get(key) is not None
    ]
    return max(values, default=0.0)


def _normalize_feature(value: Any, maximum: float, precision: int) -> float | None:
    if value is None:
        return None
    if maximum <= 0:
        return 0.0
    return round(float(value) / maximum, precision)


def _weighted_score(
    submetrics: Mapping[str, float | None],
    precision: int,
) -> float | None:
    used = [
        (BLAST_SCORE_WEIGHTS[name], float(value))
        for name, value in submetrics.items()
        if value is not None
    ]
    if not used:
        return None
    weight_sum = sum(weight for weight, _ in used)
    raw = sum(weight * value for weight, value in used) / weight_sum
    return round(raw * 100.0, precision)


def _summary_metrics(
    table_graph: TableGraph,
    reachability: MetricResult,
    betweenness: MetricResult,
    table_metrics: tuple[Mapping[str, Any], ...],
    *,
    communities_by_table: Mapping[str, str] | None,
    top_n: int,
) -> dict[str, MetricResult]:
    downstream_counts = [
        int(item["downstream_reachability_count"])
        for item in table_metrics
        if item.get("downstream_reachability_count") is not None
    ]
    upstream_counts = [
        int(item["upstream_reachability_count"])
        for item in table_metrics
        if item.get("upstream_reachability_count") is not None
    ]
    blast_scores = [
        float(item["blast_score"])
        for item in table_metrics
        if item.get("blast_score") is not None
    ]
    values: dict[str, Any] = {
        "table_count": table_graph.node_count,
        "reachability_mode": thaw(reachability.value).get("mode")
        if isinstance(thaw(reachability.value), dict)
        else None,
        "betweenness_mode": thaw(betweenness.parameters).get("mode"),
        "max_downstream_reachability_count": max(downstream_counts, default=None),
        "max_upstream_reachability_count": max(upstream_counts, default=None),
        "average_downstream_reachability_count": _average(downstream_counts),
        "max_blast_score": max(blast_scores, default=None),
        "average_blast_score": _average(blast_scores),
        "community_label_count": (
            len({str(value) for value in communities_by_table.values()})
            if communities_by_table is not None
            else 0
        ),
        "top_blast_score_tables": _top_metric_tables(table_metrics, "blast_score", top_n),
        "top_downstream_reachability_tables": _top_metric_tables(
            table_metrics,
            "downstream_reachability_count",
            top_n,
        ),
    }
    summary = {
        name: MetricResult(
            name=name,
            status=MetricStatus.SUCCESS,
            value=value,
            algorithm="impact.summary",
            version=IMPACT_VERSION,
        )
        for name, value in sorted(values.items())
    }
    summary["batch_reachability"] = reachability
    summary["betweenness"] = betweenness
    return summary


def _average(values: list[int] | list[float]) -> float | None:
    if not values:
        return None
    return sum(float(value) for value in values) / len(values)


def _top_metric_tables(
    table_metrics: tuple[Mapping[str, Any], ...],
    key: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = [item for item in table_metrics if item.get(key) is not None]
    rows.sort(key=lambda item: (-float(item[key]), str(item["table_id"])))
    return [
        {
            "table_id": str(item["table_id"]),
            "table_name": str(item["table_name"]),
            key: item[key],
        }
        for item in rows[:limit]
    ]


def _blast_score_version(config: AnalysisConfig) -> str:
    return dict(config.algorithm_versions).get("blast_score", BLAST_SCORE_VERSION)


def _table_full_name(table: Mapping[str, Any]) -> str:
    parts = [
        str(value)
        for value in (table.get("catalog"), table.get("schema_name"), table.get("name"))
        if value
    ]
    return ".".join(parts) if parts else str(table.get("name", ""))
