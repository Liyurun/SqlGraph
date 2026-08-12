# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Community detection, coupling, and bridge metrics over TableGraph."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, Callable, Mapping

from sqlgraph.analyze.config import AnalysisConfig
from sqlgraph.analyze.contracts import MetricResult, MetricStatus, freeze, thaw
from sqlgraph.analyze.impact import ImpactAnalysisResult, analyze_impact
from sqlgraph.analyze.table_graph import TableGraph
from sqlgraph.analyze.topology import TopologyAnalysisResult, analyze_topology


COMMUNITY_VERSION = "1.0"
BRIDGE_SCORE_VERSION = "1.0"
BRIDGE_SCORE_WEIGHTS: Mapping[str, float] = {
    "betweenness": 0.60,
    "cross_community_contribution": 0.40,
}


@dataclass(frozen=True)
class CommunityAnalysisResult:
    """Task 7 result bundle for communities and bridge analysis."""

    summary: Mapping[str, MetricResult] = field(default_factory=dict)
    community_detection: MetricResult = field(
        default_factory=lambda: MetricResult(
            name="community_detection",
            status=MetricStatus.SUCCESS,
            value={
                "backend": "label_propagation",
                "requested_backend": "label_propagation",
                "community_count": 0,
                "communities_by_table": {},
            },
            algorithm="communities.empty_graph",
            version=COMMUNITY_VERSION,
        )
    )
    coupling: MetricResult = field(
        default_factory=lambda: MetricResult(
            name="community_coupling",
            status=MetricStatus.SUCCESS,
            value={
                "cross_community_edge_ratio": 0.0,
                "cross_community_edge_count": 0,
                "edge_count": 0,
            },
            algorithm="communities.empty_graph",
            version=COMMUNITY_VERSION,
        )
    )
    deletion_simulation: MetricResult = field(
        default_factory=lambda: MetricResult(
            name="node_removal_simulation",
            status=MetricStatus.SUCCESS,
            value=(),
            algorithm="communities.empty_graph",
            version=COMMUNITY_VERSION,
        )
    )
    communities: tuple[Mapping[str, Any], ...] = ()
    dependency_matrix: tuple[Mapping[str, Any], ...] = ()
    table_metrics: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", freeze(self.summary))
        object.__setattr__(
            self,
            "communities",
            tuple(freeze(item) for item in self.communities),
        )
        object.__setattr__(
            self,
            "dependency_matrix",
            tuple(freeze(item) for item in self.dependency_matrix),
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
            "community_detection": self.community_detection.to_dict(),
            "coupling": self.coupling.to_dict(),
            "deletion_simulation": self.deletion_simulation.to_dict(),
            "communities": [thaw(item) for item in self.communities],
            "dependency_matrix": [thaw(item) for item in self.dependency_matrix],
            "table_metrics": [thaw(item) for item in self.table_metrics],
        }


def analyze_communities(
    table_graph: TableGraph,
    topology: TopologyAnalysisResult | None = None,
    impact: ImpactAnalysisResult | None = None,
    config: AnalysisConfig | None = None,
    *,
    backend: str | None = None,
    top_k: int | None = None,
) -> CommunityAnalysisResult:
    """Compute Task 7 metrics without mutating the source graph."""
    config = config or AnalysisConfig()
    topology = topology or analyze_topology(table_graph, config=config)
    requested_backend = (backend or config.community_backend).strip().lower()
    detection, communities, communities_by_table = _detect_communities(
        table_graph,
        config,
        requested_backend,
    )
    impact = impact or analyze_impact(
        table_graph,
        topology=topology,
        config=config,
        communities_by_table=communities_by_table,
    )
    coupling, dependency_matrix, cross_by_table = _coupling_metrics(
        table_graph,
        communities_by_table,
        config,
    )
    table_metrics = _table_metrics(
        table_graph,
        communities,
        communities_by_table,
        cross_by_table,
        impact,
        config,
    )
    deletion_limit = (
        config.resource_budget.top_k_removal_simulation
        if top_k is None
        else max(0, int(top_k))
    )
    deletion_simulation = _deletion_simulation_metric(
        table_graph,
        table_metrics,
        deletion_limit,
    )
    return CommunityAnalysisResult(
        summary=_summary_metrics(
            table_graph,
            detection,
            coupling,
            deletion_simulation,
            table_metrics,
            config,
        ),
        community_detection=detection,
        coupling=coupling,
        deletion_simulation=deletion_simulation,
        communities=communities,
        dependency_matrix=dependency_matrix,
        table_metrics=table_metrics,
    )


def _detect_communities(
    table_graph: TableGraph,
    config: AnalysisConfig,
    requested_backend: str,
) -> tuple[MetricResult, tuple[Mapping[str, Any], ...], dict[str, str]]:
    if table_graph.node_count == 0:
        value = {
            "backend": "label_propagation",
            "requested_backend": requested_backend,
            "community_count": 0,
            "communities_by_table": {},
            "communities": (),
        }
        return (
            MetricResult(
                name="community_detection",
                status=MetricStatus.SUCCESS,
                value=value,
                algorithm="communities.empty_graph",
                version=COMMUNITY_VERSION,
            ),
            (),
            {},
        )

    backend = "label_propagation" if requested_backend in {"lpa", "lp"} else requested_backend
    if backend in {"label_propagation", "auto"}:
        assignments = _label_propagation_assignments(table_graph, config)
        status = MetricStatus.SUCCESS
        reason = None
        algorithm = "communities.label_propagation"
        actual_backend = "label_propagation"
    elif backend == "louvain":
        detected = _louvain_assignments(table_graph, config)
        if detected is None:
            if not config.allow_degraded:
                return _skipped_detection(
                    requested_backend,
                    "louvain backend is not available",
                )
            assignments = _label_propagation_assignments(table_graph, config)
            status = MetricStatus.DEGRADED
            reason = "louvain backend is not available; fell back to label_propagation"
            algorithm = "communities.label_propagation"
            actual_backend = "label_propagation"
        else:
            assignments = detected
            status = MetricStatus.SUCCESS
            reason = None
            algorithm = "communities.louvain"
            actual_backend = "louvain"
    elif backend == "leiden":
        detected = _leiden_assignments(table_graph, config)
        if detected is None:
            if not config.allow_degraded:
                return _skipped_detection(
                    requested_backend,
                    "leiden backend is not available",
                )
            assignments = _label_propagation_assignments(table_graph, config)
            status = MetricStatus.DEGRADED
            reason = "leiden backend is not available; fell back to label_propagation"
            algorithm = "communities.label_propagation"
            actual_backend = "label_propagation"
        else:
            assignments = detected
            status = MetricStatus.SUCCESS
            reason = None
            algorithm = "communities.leiden"
            actual_backend = "leiden"
    else:
        if not config.allow_degraded:
            return _skipped_detection(
                requested_backend,
                f"unknown community backend {requested_backend!r}",
            )
        assignments = _label_propagation_assignments(table_graph, config)
        status = MetricStatus.DEGRADED
        reason = (
            f"unknown community backend {requested_backend!r}; "
            "fell back to label_propagation"
        )
        algorithm = "communities.label_propagation"
        actual_backend = "label_propagation"

    communities, communities_by_table = _stable_communities(assignments)
    value = {
        "backend": actual_backend,
        "requested_backend": requested_backend,
        "community_count": len(communities),
        "communities_by_table": communities_by_table,
        "communities": communities,
    }
    return (
        MetricResult(
            name="community_detection",
            status=status,
            value=value,
            reason=reason,
            algorithm=algorithm,
            version=COMMUNITY_VERSION,
            parameters={
                "random_seed": config.random_seed,
                "stable_relabeling": True,
            },
        ),
        communities,
        communities_by_table,
    )


def _skipped_detection(
    requested_backend: str,
    reason: str,
) -> tuple[MetricResult, tuple[Mapping[str, Any], ...], dict[str, str]]:
    return (
        MetricResult(
            name="community_detection",
            status=MetricStatus.SKIPPED,
            value={
                "backend": None,
                "requested_backend": requested_backend,
                "community_count": 0,
                "communities_by_table": {},
                "communities": (),
            },
            reason=reason,
            algorithm="communities.backend_selection",
            version=COMMUNITY_VERSION,
        ),
        (),
        {},
    )


def _label_propagation_assignments(
    table_graph: TableGraph,
    config: AnalysisConfig,
    *,
    max_iter: int = 100,
    self_weight: float = 0.5,
) -> dict[str, str]:
    del config
    neighbors = _weighted_undirected_neighbors(table_graph)
    labels = {node_id: node_id for node_id in table_graph.nodes}
    seen_states: set[tuple[str, ...]] = set()

    for _ in range(max_iter):
        previous = dict(labels)
        next_labels: dict[str, str] = {}
        for node_id in table_graph.nodes:
            votes: dict[str, float] = {previous[node_id]: self_weight}
            for neighbor_id, weight in neighbors.get(node_id, {}).items():
                label = previous[neighbor_id]
                votes[label] = votes.get(label, 0.0) + float(weight)
            best_score = max(votes.values(), default=0.0)
            best_labels = sorted(
                label for label, score in votes.items() if score == best_score
            )
            current = previous[node_id]
            next_labels[node_id] = (
                current if current in best_labels else best_labels[0]
            )

        state = tuple(next_labels[node_id] for node_id in table_graph.nodes)
        previous_state = tuple(previous[node_id] for node_id in table_graph.nodes)
        if state == previous_state:
            labels = next_labels
            break
        if state in seen_states:
            labels = {
                node_id: min(previous[node_id], next_labels[node_id])
                for node_id in table_graph.nodes
            }
            break
        seen_states.add(previous_state)
        labels = next_labels

    return {node_id: labels[node_id] for node_id in table_graph.nodes}


def _louvain_assignments(
    table_graph: TableGraph,
    config: AnalysisConfig,
) -> dict[str, str] | None:
    louvain = _load_networkx_louvain()
    if louvain is None:
        return None
    nx = import_module("networkx")
    graph = nx.Graph()
    graph.add_nodes_from(table_graph.nodes)
    for edge in table_graph.edges:
        weight = max(edge.total_weight, 1)
        if graph.has_edge(edge.source_id, edge.target_id):
            graph[edge.source_id][edge.target_id]["weight"] += weight
        else:
            graph.add_edge(edge.source_id, edge.target_id, weight=weight)
    raw_communities = louvain(
        graph,
        weight="weight",
        seed=config.random_seed,
    )
    assignments: dict[str, str] = {}
    for index, members in enumerate(raw_communities):
        for node_id in sorted(str(item) for item in members):
            assignments[node_id] = f"louvain_{index:04d}"
    return {node_id: assignments[node_id] for node_id in table_graph.nodes}


def _load_networkx_louvain() -> Callable[..., Any] | None:
    try:
        nx = import_module("networkx")
    except ImportError:
        return None
    community = getattr(getattr(nx, "algorithms", None), "community", None)
    if community is None:
        return None
    return getattr(community, "louvain_communities", None)


def _leiden_assignments(
    table_graph: TableGraph,
    config: AnalysisConfig,
) -> dict[str, str] | None:
    backend = _load_leiden_backend()
    if backend is None:
        return None
    igraph, leidenalg = backend
    index_by_node = {node_id: index for index, node_id in enumerate(table_graph.nodes)}
    edges = [
        (index_by_node[edge.source_id], index_by_node[edge.target_id])
        for edge in table_graph.edges
    ]
    weights = [max(edge.total_weight, 1) for edge in table_graph.edges]
    graph = igraph.Graph(
        n=table_graph.node_count,
        edges=edges,
        directed=False,
    )
    graph.vs["name"] = list(table_graph.nodes)
    try:
        partition = leidenalg.find_partition(
            graph,
            leidenalg.ModularityVertexPartition,
            weights=weights,
            seed=config.random_seed,
        )
    except TypeError:
        partition = leidenalg.find_partition(
            graph,
            leidenalg.ModularityVertexPartition,
            weights=weights,
        )
    assignments: dict[str, str] = {}
    for index, members in enumerate(partition):
        for vertex_index in sorted(int(item) for item in members):
            assignments[table_graph.nodes[vertex_index]] = f"leiden_{index:04d}"
    return {node_id: assignments[node_id] for node_id in table_graph.nodes}


def _load_leiden_backend() -> tuple[Any, Any] | None:
    try:
        return import_module("igraph"), import_module("leidenalg")
    except ImportError:
        return None


def _stable_communities(
    assignments: Mapping[str, str],
) -> tuple[tuple[Mapping[str, Any], ...], dict[str, str]]:
    grouped: dict[str, list[str]] = {}
    for node_id, raw_label in assignments.items():
        grouped.setdefault(str(raw_label), []).append(str(node_id))

    ordered_members = [
        tuple(sorted(members))
        for members in grouped.values()
    ]
    ordered_members.sort(key=lambda members: (-len(members), members[0], members))

    communities: list[Mapping[str, Any]] = []
    communities_by_table: dict[str, str] = {}
    for index, members in enumerate(ordered_members):
        community_id = f"community_{index:04d}"
        for table_id in members:
            communities_by_table[table_id] = community_id
        communities.append(
            {
                "community_id": community_id,
                "size": len(members),
                "members": list(members),
            }
        )
    return tuple(communities), communities_by_table


def _coupling_metrics(
    table_graph: TableGraph,
    communities_by_table: Mapping[str, str],
    config: AnalysisConfig,
) -> tuple[MetricResult, tuple[Mapping[str, Any], ...], dict[str, dict[str, int]]]:
    matrix: dict[tuple[str, str], dict[str, int]] = {}
    cross_by_table = {
        node_id: {
            "incoming_cross_edge_count": 0,
            "outgoing_cross_edge_count": 0,
            "incident_cross_edge_count": 0,
            "cross_total_weight": 0,
        }
        for node_id in table_graph.nodes
    }
    cross_edges = 0
    for edge in table_graph.edges:
        source_community = communities_by_table.get(edge.source_id)
        target_community = communities_by_table.get(edge.target_id)
        if source_community is None or target_community is None:
            continue
        key = (source_community, target_community)
        bucket = matrix.setdefault(
            key,
            {
                "edge_count": 0,
                "field_weight": 0,
                "sql_weight": 0,
                "total_weight": 0,
            },
        )
        weight = max(edge.total_weight, 1)
        bucket["edge_count"] += 1
        bucket["field_weight"] += int(edge.field_weight)
        bucket["sql_weight"] += int(edge.sql_weight)
        bucket["total_weight"] += weight
        if source_community != target_community:
            cross_edges += 1
            cross_by_table[edge.source_id]["outgoing_cross_edge_count"] += 1
            cross_by_table[edge.target_id]["incoming_cross_edge_count"] += 1
            cross_by_table[edge.source_id]["incident_cross_edge_count"] += 1
            cross_by_table[edge.target_id]["incident_cross_edge_count"] += 1
            cross_by_table[edge.source_id]["cross_total_weight"] += weight
            cross_by_table[edge.target_id]["cross_total_weight"] += weight

    dependency_matrix = tuple(
        {
            "source_community_id": source,
            "target_community_id": target,
            "edge_count": values["edge_count"],
            "field_weight": values["field_weight"],
            "sql_weight": values["sql_weight"],
            "total_weight": values["total_weight"],
        }
        for (source, target), values in sorted(matrix.items())
    )
    ratio = (
        round(cross_edges / table_graph.edge_count, config.float_precision)
        if table_graph.edge_count
        else 0.0
    )
    value = {
        "cross_community_edge_ratio": ratio,
        "cross_community_edge_count": cross_edges,
        "intra_community_edge_count": table_graph.edge_count - cross_edges,
        "edge_count": table_graph.edge_count,
        "matrix_edge_count": len(dependency_matrix),
    }
    return (
        MetricResult(
            name="community_coupling",
            status=MetricStatus.SUCCESS,
            value=value,
            algorithm="communities.cross_community_matrix",
            version=COMMUNITY_VERSION,
        ),
        dependency_matrix,
        cross_by_table,
    )


def _table_metrics(
    table_graph: TableGraph,
    communities: tuple[Mapping[str, Any], ...],
    communities_by_table: Mapping[str, str],
    cross_by_table: Mapping[str, Mapping[str, int]],
    impact: ImpactAnalysisResult,
    config: AnalysisConfig,
) -> tuple[Mapping[str, Any], ...]:
    community_sizes = {
        str(community["community_id"]): int(community["size"])
        for community in communities
    }
    betweenness_values = _betweenness_values(impact)
    max_betweenness = max(
        (float(value) for value in betweenness_values.values()),
        default=0.0,
    )
    max_cross_weight = max(
        (
            int(values["cross_total_weight"])
            for values in cross_by_table.values()
        ),
        default=0,
    )
    records: list[Mapping[str, Any]] = []
    for table_id in table_graph.nodes:
        community_id = communities_by_table.get(table_id)
        cross = cross_by_table.get(table_id, {})
        betweenness = betweenness_values.get(table_id)
        cross_contribution = _normalize_feature(
            cross.get("cross_total_weight", 0),
            max_cross_weight,
            config.float_precision,
        )
        betweenness_contribution = _normalize_feature(
            betweenness,
            max_betweenness,
            config.float_precision,
        )
        submetrics = {
            "betweenness": betweenness_contribution,
            "cross_community_contribution": cross_contribution,
        }
        missing = sorted(name for name, value in submetrics.items() if value is None)
        score = _weighted_bridge_score(submetrics, config.float_precision)
        records.append(
            {
                "table_id": table_id,
                "table_name": _table_full_name(
                    table_graph.nodes_by_id.get(table_id, {})
                ),
                "community_id": community_id,
                "community_size": community_sizes.get(str(community_id), 0),
                "incoming_cross_edge_count": int(
                    cross.get("incoming_cross_edge_count", 0)
                ),
                "outgoing_cross_edge_count": int(
                    cross.get("outgoing_cross_edge_count", 0)
                ),
                "incident_cross_edge_count": int(
                    cross.get("incident_cross_edge_count", 0)
                ),
                "cross_total_weight": int(cross.get("cross_total_weight", 0)),
                "betweenness": betweenness,
                "betweenness_mode": thaw(impact.betweenness.parameters).get("mode"),
                "bridge_score": score,
                "bridge_score_status": "success" if not missing else "degraded",
                "bridge_score_version": _bridge_score_version(config),
                "bridge_score_submetrics": submetrics,
                "bridge_score_weights": {
                    name: BRIDGE_SCORE_WEIGHTS[name]
                    for name, value in submetrics.items()
                    if value is not None
                },
                "bridge_score_missing_submetrics": missing,
            }
        )
    return tuple(
        sorted(
            records,
            key=lambda item: (
                item["bridge_score"] is None,
                -float(item["bridge_score"] or 0.0),
                str(item["table_id"]),
            ),
        )
    )


def _deletion_simulation_metric(
    table_graph: TableGraph,
    table_metrics: tuple[Mapping[str, Any], ...],
    top_k: int,
) -> MetricResult:
    candidates = [
        str(item["table_id"])
        for item in table_metrics
        if item.get("bridge_score") is not None
    ][:top_k]
    baseline = _weak_component_stats(
        set(table_graph.nodes),
        _unweighted_undirected_adjacency(table_graph),
    )
    rows = []
    for table_id in candidates:
        remaining_nodes = set(table_graph.nodes)
        remaining_nodes.discard(table_id)
        adjacency = _unweighted_undirected_adjacency(table_graph)
        adjacency.pop(table_id, None)
        for neighbors in adjacency.values():
            neighbors.discard(table_id)
        after = _weak_component_stats(remaining_nodes, adjacency)
        rows.append(
            {
                "removed_table_id": table_id,
                "before_component_count": baseline["component_count"],
                "after_component_count": after["component_count"],
                "component_count_delta": (
                    after["component_count"] - baseline["component_count"]
                ),
                "before_largest_component_size": baseline[
                    "largest_component_size"
                ],
                "after_largest_component_size": after["largest_component_size"],
                "largest_component_size_delta": (
                    baseline["largest_component_size"]
                    - after["largest_component_size"]
                ),
                "remaining_node_count": len(remaining_nodes),
            }
        )
    return MetricResult(
        name="node_removal_simulation",
        status=MetricStatus.SUCCESS,
        value=rows,
        algorithm="communities.top_k_node_removal_copy",
        version=COMMUNITY_VERSION,
        parameters={"top_k": top_k, "candidate_count": len(candidates)},
    )


def _weighted_undirected_neighbors(
    table_graph: TableGraph,
) -> dict[str, dict[str, float]]:
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
        node_id: {
            neighbor_id: neighbor_weights[neighbor_id]
            for neighbor_id in sorted(neighbor_weights)
        }
        for node_id, neighbor_weights in neighbors.items()
    }


def _unweighted_undirected_adjacency(
    table_graph: TableGraph,
) -> dict[str, set[str]]:
    adjacency = {node_id: set() for node_id in table_graph.nodes}
    for edge in table_graph.edges:
        adjacency[edge.source_id].add(edge.target_id)
        adjacency[edge.target_id].add(edge.source_id)
    return adjacency


def _weak_component_stats(
    nodes: set[str],
    adjacency: Mapping[str, set[str]],
) -> dict[str, int]:
    visited: set[str] = set()
    component_count = 0
    largest = 0
    for start in sorted(nodes):
        if start in visited:
            continue
        component_count += 1
        visited.add(start)
        queue: deque[str] = deque([start])
        size = 0
        while queue:
            node_id = queue.popleft()
            size += 1
            for neighbor in sorted(adjacency.get(node_id, set())):
                if neighbor in nodes and neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        largest = max(largest, size)
    return {
        "component_count": component_count,
        "largest_component_size": largest,
    }


def _betweenness_values(impact: ImpactAnalysisResult) -> dict[str, float]:
    value = thaw(impact.betweenness.value)
    if impact.betweenness.status != MetricStatus.SUCCESS or not isinstance(value, dict):
        return {}
    return {
        str(table_id): float(score)
        for table_id, score in value.items()
        if score is not None
    }


def _normalize_feature(
    value: Any,
    maximum: float,
    precision: int,
) -> float | None:
    if value is None:
        return None
    if maximum <= 0:
        return 0.0
    return round(float(value) / maximum, precision)


def _weighted_bridge_score(
    submetrics: Mapping[str, float | None],
    precision: int,
) -> float | None:
    used = [
        (BRIDGE_SCORE_WEIGHTS[name], float(value))
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
    detection: MetricResult,
    coupling: MetricResult,
    deletion_simulation: MetricResult,
    table_metrics: tuple[Mapping[str, Any], ...],
    config: AnalysisConfig,
) -> dict[str, MetricResult]:
    detection_value = thaw(detection.value)
    coupling_value = thaw(coupling.value)
    bridge_scores = [
        float(item["bridge_score"])
        for item in table_metrics
        if item.get("bridge_score") is not None
    ]
    values: dict[str, Any] = {
        "table_count": table_graph.node_count,
        "community_count": detection_value.get("community_count", 0)
        if isinstance(detection_value, dict)
        else 0,
        "community_backend": detection_value.get("backend")
        if isinstance(detection_value, dict)
        else None,
        "community_detection_status": detection.status.value,
        "cross_community_edge_ratio": coupling_value.get(
            "cross_community_edge_ratio", 0.0
        )
        if isinstance(coupling_value, dict)
        else 0.0,
        "max_bridge_score": max(bridge_scores, default=None),
        "average_bridge_score": _average(bridge_scores),
        "top_bridge_tables": _top_bridge_tables(table_metrics, 10),
        "node_removal_simulation_count": len(thaw(deletion_simulation.value)),
    }
    summary = {
        name: MetricResult(
            name=name,
            status=MetricStatus.SUCCESS,
            value=value,
            algorithm="communities.summary",
            version=COMMUNITY_VERSION,
        )
        for name, value in sorted(values.items())
    }
    summary["community_detection"] = detection
    summary["community_coupling"] = coupling
    summary["node_removal_simulation"] = deletion_simulation
    summary["bridge_score"] = MetricResult(
        name="bridge_score",
        status=MetricStatus.SUCCESS,
        value={
            "version": _bridge_score_version(config),
            "weights": dict(BRIDGE_SCORE_WEIGHTS),
        },
        algorithm="communities.bridge_score_v1",
        version=BRIDGE_SCORE_VERSION,
    )
    return summary


def _top_bridge_tables(
    table_metrics: tuple[Mapping[str, Any], ...],
    limit: int,
) -> list[dict[str, Any]]:
    rows = [item for item in table_metrics if item.get("bridge_score") is not None]
    rows.sort(key=lambda item: (-float(item["bridge_score"]), str(item["table_id"])))
    return [
        {
            "table_id": str(item["table_id"]),
            "table_name": str(item["table_name"]),
            "bridge_score": item["bridge_score"],
            "community_id": item["community_id"],
        }
        for item in rows[:limit]
    ]


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _bridge_score_version(config: AnalysisConfig) -> str:
    return dict(config.algorithm_versions).get("bridge_score", BRIDGE_SCORE_VERSION)


def _table_full_name(table: Mapping[str, Any]) -> str:
    parts = [
        str(value)
        for value in (table.get("catalog"), table.get("schema_name"), table.get("name"))
        if value
    ]
    return ".".join(parts) if parts else str(table.get("name", ""))
