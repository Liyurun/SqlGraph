# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Topology, centrality, and graph-layer analysis over TableGraph."""

from __future__ import annotations

from dataclasses import dataclass, field
from heapq import heappop, heappush
from typing import Any, Mapping

from sqlgraph.analyze.config import AnalysisConfig
from sqlgraph.analyze.contracts import MetricResult, MetricStatus, freeze, thaw
from sqlgraph.analyze.table_graph import TableGraph


TOPOLOGY_VERSION = "1.0"


@dataclass(frozen=True)
class TopologyAnalysisResult:
    """Task 5 result bundle for topology and graph-layer metrics."""

    summary: Mapping[str, MetricResult] = field(default_factory=dict)
    weak_components: tuple[Mapping[str, Any], ...] = ()
    strong_components: tuple[Mapping[str, Any], ...] = ()
    scc_dag_edges: tuple[Mapping[str, Any], ...] = ()
    graph_algorithms: Mapping[str, MetricResult] = field(default_factory=dict)
    table_metrics: tuple[Mapping[str, Any], ...] = ()
    layer_violations: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", freeze(self.summary))
        object.__setattr__(
            self,
            "weak_components",
            tuple(freeze(item) for item in self.weak_components),
        )
        object.__setattr__(
            self,
            "strong_components",
            tuple(freeze(item) for item in self.strong_components),
        )
        object.__setattr__(
            self,
            "scc_dag_edges",
            tuple(freeze(item) for item in self.scc_dag_edges),
        )
        object.__setattr__(self, "graph_algorithms", freeze(self.graph_algorithms))
        object.__setattr__(
            self,
            "table_metrics",
            tuple(freeze(item) for item in self.table_metrics),
        )
        object.__setattr__(
            self,
            "layer_violations",
            tuple(freeze(item) for item in self.layer_violations),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                name: result.to_dict() for name, result in self.summary.items()
            },
            "weak_components": [thaw(item) for item in self.weak_components],
            "strong_components": [thaw(item) for item in self.strong_components],
            "scc_dag_edges": [thaw(item) for item in self.scc_dag_edges],
            "graph_algorithms": {
                name: result.to_dict()
                for name, result in self.graph_algorithms.items()
            },
            "table_metrics": [thaw(item) for item in self.table_metrics],
            "layer_violations": [thaw(item) for item in self.layer_violations],
        }


def analyze_topology(
    table_graph: TableGraph,
    config: AnalysisConfig | None = None,
) -> TopologyAnalysisResult:
    """Compute Task 5 metrics without mutating the source graph."""
    config = config or AnalysisConfig()
    adjacency, reverse_adjacency = _adjacency_maps(table_graph)
    weak_components, weak_by_node = _weak_components(
        table_graph.nodes, adjacency, reverse_adjacency
    )
    strong_components, scc_by_node = _strong_components(table_graph.nodes, adjacency)
    scc_dag = _scc_dag(table_graph, strong_components, scc_by_node)
    graph_layers = _graph_layers(scc_dag)
    graph_algorithms = _networkx_metrics(table_graph, config)
    table_metrics = _table_metrics(
        table_graph,
        config,
        weak_by_node,
        scc_by_node,
        strong_components,
        graph_layers,
        graph_algorithms,
    )
    layer_violations = _layer_violations(table_graph, table_metrics, config)
    summary = {
        "weak_component_count": len(weak_components),
        "strong_component_count": len(strong_components),
        "cycle_member_count": sum(
            1 for item in table_metrics if item["is_cycle_member"]
        ),
        "scc_dag_node_count": len(scc_dag["nodes"]),
        "scc_dag_edge_count": len(scc_dag["edges"]),
        "graph_layer_max_depth": max(
            (int(item["graph_layer_max"]) for item in table_metrics),
            default=0,
        ),
        "layer_violation_count": len(layer_violations),
    }
    return TopologyAnalysisResult(
        summary={
            name: _success_metric(name, value)
            for name, value in sorted(summary.items())
        },
        weak_components=tuple(weak_components),
        strong_components=tuple(strong_components),
        scc_dag_edges=tuple(scc_dag["edge_records"]),
        graph_algorithms=graph_algorithms,
        table_metrics=table_metrics,
        layer_violations=tuple(layer_violations),
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


def _weak_components(
    nodes: tuple[str, ...],
    adjacency: Mapping[str, tuple[str, ...]],
    reverse_adjacency: Mapping[str, tuple[str, ...]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    visited: set[str] = set()
    components: list[dict[str, Any]] = []
    by_node: dict[str, str] = {}
    for start in sorted(nodes):
        if start in visited:
            continue
        visited.add(start)
        stack = [start]
        members: set[str] = set()
        while stack:
            node_id = stack.pop()
            members.add(node_id)
            neighbors = sorted(
                set(adjacency.get(node_id, ()))
                | set(reverse_adjacency.get(node_id, ()))
            )
            for neighbor in neighbors:
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        ordered_members = tuple(sorted(members))
        component_id = f"wcc_{len(components):04d}"
        for node_id in ordered_members:
            by_node[node_id] = component_id
        components.append(
            {
                "component_id": component_id,
                "size": len(ordered_members),
                "members": list(ordered_members),
            }
        )
    return components, by_node


def _strong_components(
    nodes: tuple[str, ...],
    adjacency: Mapping[str, tuple[str, ...]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    raw_components: list[tuple[str, ...]] = []

    def visit(node_id: str) -> None:
        nonlocal index
        indices[node_id] = index
        lowlinks[node_id] = index
        index += 1
        stack.append(node_id)
        on_stack.add(node_id)
        for successor in adjacency.get(node_id, ()):
            if successor not in indices:
                visit(successor)
                lowlinks[node_id] = min(lowlinks[node_id], lowlinks[successor])
            elif successor in on_stack:
                lowlinks[node_id] = min(lowlinks[node_id], indices[successor])
        if lowlinks[node_id] == indices[node_id]:
            members: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                members.append(member)
                if member == node_id:
                    break
            raw_components.append(tuple(sorted(members)))

    for node_id in sorted(nodes):
        if node_id not in indices:
            visit(node_id)

    by_node: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    for offset, members in enumerate(
        sorted(raw_components, key=lambda item: (item[0], len(item), item))
    ):
        component_id = f"scc_{offset:04d}"
        for node_id in members:
            by_node[node_id] = component_id
        records.append(
            {
                "component_id": component_id,
                "size": len(members),
                "members": list(members),
                "has_cycle": len(members) > 1,
            }
        )
    return records, by_node


def _scc_dag(
    table_graph: TableGraph,
    strong_components: list[dict[str, Any]],
    scc_by_node: Mapping[str, str],
) -> dict[str, Any]:
    nodes = tuple(str(record["component_id"]) for record in strong_components)
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    indegree = {node_id: 0 for node_id in nodes}
    edges: set[tuple[str, str]] = set()
    for edge in table_graph.edges:
        source_scc = scc_by_node[edge.source_id]
        target_scc = scc_by_node[edge.target_id]
        if source_scc == target_scc or (source_scc, target_scc) in edges:
            continue
        edges.add((source_scc, target_scc))
        adjacency[source_scc].add(target_scc)
        indegree[target_scc] += 1
    return {
        "nodes": nodes,
        "edges": tuple(sorted(edges)),
        "edge_records": [
            {"source_component_id": source, "target_component_id": target}
            for source, target in sorted(edges)
        ],
        "adjacency": {
            node_id: tuple(sorted(targets))
            for node_id, targets in adjacency.items()
        },
        "indegree": indegree,
    }


def _graph_layers(scc_dag: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    nodes = tuple(scc_dag["nodes"])
    adjacency: Mapping[str, tuple[str, ...]] = scc_dag["adjacency"]
    indegree = {str(key): int(value) for key, value in scc_dag["indegree"].items()}
    heap: list[str] = []
    shortest: dict[str, int] = {}
    longest: dict[str, int] = {}
    for node_id in nodes:
        if indegree.get(node_id, 0) == 0:
            heappush(heap, node_id)
            shortest[node_id] = 0
            longest[node_id] = 0
    while heap:
        node_id = heappop(heap)
        for target in adjacency.get(node_id, ()):
            candidate_min = shortest[node_id] + 1
            candidate_max = longest[node_id] + 1
            shortest[target] = min(shortest.get(target, candidate_min), candidate_min)
            longest[target] = max(longest.get(target, 0), candidate_max)
            indegree[target] -= 1
            if indegree[target] == 0:
                heappush(heap, target)
    return {
        node_id: {
            "min": shortest.get(node_id, 0),
            "max": longest.get(node_id, 0),
        }
        for node_id in nodes
    }


def _networkx_metrics(
    table_graph: TableGraph,
    config: AnalysisConfig,
) -> dict[str, MetricResult]:
    if table_graph.node_count == 0:
        return _empty_algorithm_metrics()
    names = ("pagerank", "hits", "k_core")
    if table_graph.node_count > config.resource_budget.exact_algorithm_max_nodes:
        reason = (
            "table graph exceeds exact algorithm node budget "
            f"({table_graph.node_count} > "
            f"{config.resource_budget.exact_algorithm_max_nodes})"
        )
        return {name: _skipped_metric(name, reason) for name in names}
    nx = _load_networkx()
    if nx is None:
        return {
            name: _skipped_metric(name, "networkx is not installed")
            for name in names
        }
    graph = nx.DiGraph()
    graph.add_nodes_from(table_graph.nodes)
    for edge in table_graph.edges:
        graph.add_edge(edge.source_id, edge.target_id, weight=max(edge.total_weight, 1))
    return {
        "pagerank": _run_pagerank(nx, graph, config),
        "hits": _run_hits(nx, graph, config),
        "k_core": _run_k_core(nx, graph),
    }


def _empty_algorithm_metrics() -> dict[str, MetricResult]:
    return {
        "pagerank": MetricResult(
            name="pagerank",
            status=MetricStatus.SUCCESS,
            value={"forward": {}, "reverse": {}},
            algorithm="topology.empty_graph",
            version=TOPOLOGY_VERSION,
        ),
        "hits": MetricResult(
            name="hits",
            status=MetricStatus.SUCCESS,
            value={"hub": {}, "authority": {}},
            algorithm="topology.empty_graph",
            version=TOPOLOGY_VERSION,
        ),
        "k_core": MetricResult(
            name="k_core",
            status=MetricStatus.SUCCESS,
            value={},
            algorithm="topology.empty_graph",
            version=TOPOLOGY_VERSION,
        ),
    }


def _run_pagerank(nx: Any, graph: Any, config: AnalysisConfig) -> MetricResult:
    del nx
    forward = _pagerank_power_iteration(graph, reverse=False)
    reverse = _pagerank_power_iteration(graph, reverse=True)
    return MetricResult(
        name="pagerank",
        status=MetricStatus.SUCCESS,
        value={
            "forward": _round_float_mapping(forward, config.float_precision),
            "reverse": _round_float_mapping(reverse, config.float_precision),
        },
        algorithm="deterministic.pagerank_power_iteration",
        version=TOPOLOGY_VERSION,
        parameters={"alpha": 0.85, "max_iter": 100, "tol": 1.0e-12},
    )


def _run_hits(nx: Any, graph: Any, config: AnalysisConfig) -> MetricResult:
    del nx
    hubs, authorities = _hits_power_iteration(graph)
    return MetricResult(
        name="hits",
        status=MetricStatus.SUCCESS,
        value={
            "hub": _round_float_mapping(hubs, config.float_precision),
            "authority": _round_float_mapping(authorities, config.float_precision),
        },
        algorithm="deterministic.hits_power_iteration",
        version=TOPOLOGY_VERSION,
        parameters={"max_iter": 1000, "tol": 1.0e-12},
    )


def _pagerank_power_iteration(
    graph: Any,
    *,
    reverse: bool,
    alpha: float = 0.85,
    max_iter: int = 100,
    tol: float = 1.0e-12,
) -> dict[str, float]:
    nodes = sorted(str(node_id) for node_id in graph.nodes)
    if not nodes:
        return {}
    n = len(nodes)
    rank = {node_id: 1.0 / n for node_id in nodes}

    outgoing: dict[str, tuple[str, ...]] = {}
    for node_id in nodes:
        successors = graph.predecessors(node_id) if reverse else graph.successors(node_id)
        outgoing[node_id] = tuple(sorted(str(item) for item in successors))

    for _iteration in range(max_iter):
        dangling_rank = sum(rank[node_id] for node_id in nodes if not outgoing[node_id])
        next_rank = {node_id: (1.0 - alpha) / n for node_id in nodes}
        dangling_share = alpha * dangling_rank / n
        for node_id in nodes:
            next_rank[node_id] += dangling_share
        for source in nodes:
            targets = outgoing[source]
            if not targets:
                continue
            share = alpha * rank[source] / len(targets)
            for target in targets:
                next_rank[target] += share
        delta = sum(abs(next_rank[node_id] - rank[node_id]) for node_id in nodes)
        rank = next_rank
        if delta < n * tol:
            break
    return rank


def _hits_power_iteration(
    graph: Any,
    *,
    max_iter: int = 1000,
    tol: float = 1.0e-12,
) -> tuple[dict[str, float], dict[str, float]]:
    nodes = sorted(str(node_id) for node_id in graph.nodes)
    if not nodes:
        return {}, {}
    hubs = {node_id: 1.0 for node_id in nodes}
    authorities = {node_id: 1.0 for node_id in nodes}
    predecessors = {
        node_id: tuple(sorted(str(item) for item in graph.predecessors(node_id)))
        for node_id in nodes
    }
    successors = {
        node_id: tuple(sorted(str(item) for item in graph.successors(node_id)))
        for node_id in nodes
    }

    for _iteration in range(max_iter):
        next_authorities = {
            node_id: sum(hubs[source] for source in predecessors[node_id])
            for node_id in nodes
        }
        next_hubs = {
            node_id: sum(next_authorities[target] for target in successors[node_id])
            for node_id in nodes
        }
        next_authorities = _normalize_l1(next_authorities)
        next_hubs = _normalize_l1(next_hubs)
        delta = sum(
            abs(next_hubs[node_id] - hubs[node_id])
            + abs(next_authorities[node_id] - authorities[node_id])
            for node_id in nodes
        )
        hubs = next_hubs
        authorities = next_authorities
        if delta < tol:
            break
    return hubs, authorities


def _normalize_l1(values: Mapping[str, float]) -> dict[str, float]:
    total = sum(abs(value) for value in values.values())
    if total == 0:
        if not values:
            return {}
        fallback = 1.0 / len(values)
        return {str(key): fallback for key in sorted(values)}
    return {str(key): float(values[key]) / total for key in sorted(values)}


def _run_k_core(nx: Any, graph: Any) -> MetricResult:
    try:
        values = nx.core_number(graph.to_undirected())
    except Exception as exc:  # pragma: no cover - backend-specific failure path
        return MetricResult(
            name="k_core",
            status=MetricStatus.FAILED,
            reason=f"networkx k-core failed: {exc}",
            algorithm="networkx.core_number",
            version=TOPOLOGY_VERSION,
        )
    return MetricResult(
        name="k_core",
        status=MetricStatus.SUCCESS,
        value={str(node_id): int(values[node_id]) for node_id in sorted(values)},
        algorithm="networkx.core_number",
        version=TOPOLOGY_VERSION,
        parameters={"orientation": "undirected"},
    )


def _table_metrics(
    table_graph: TableGraph,
    config: AnalysisConfig,
    weak_by_node: Mapping[str, str],
    scc_by_node: Mapping[str, str],
    strong_components: list[dict[str, Any]],
    graph_layers: Mapping[str, Mapping[str, int]],
    graph_algorithms: Mapping[str, MetricResult],
) -> tuple[Mapping[str, Any], ...]:
    scc_has_cycle = {
        str(record["component_id"]): bool(record["has_cycle"])
        for record in strong_components
    }
    pagerank = _metric_value(graph_algorithms["pagerank"])
    hits = _metric_value(graph_algorithms["hits"])
    k_core = _metric_value(graph_algorithms["k_core"])
    layer_names = _declared_layer_names(config)
    max_graph_layer = max(
        (int(layer_info["max"]) for layer_info in graph_layers.values()),
        default=0,
    )
    records: list[dict[str, Any]] = []
    for table_id in table_graph.nodes:
        table = table_graph.nodes_by_id.get(table_id, {})
        scc_id = scc_by_node[table_id]
        layer_info = graph_layers[scc_id]
        declared_layer = _match_layer(table, config)
        declared_index = _declared_layer_index(declared_layer, layer_names)
        mapped_graph_layer = _map_graph_layer(
            graph_layer=int(layer_info["max"]),
            max_graph_layer=max_graph_layer,
            layer_count=len(layer_names),
        )
        drift = (
            None
            if declared_index is None or mapped_graph_layer is None
            else mapped_graph_layer - declared_index
        )
        records.append(
            {
                "table_id": table_id,
                "table_name": _table_full_name(table),
                "weak_component_id": weak_by_node[table_id],
                "strong_component_id": scc_id,
                "is_cycle_member": scc_has_cycle.get(scc_id, False),
                "graph_layer_min": int(layer_info["min"]),
                "graph_layer_max": int(layer_info["max"]),
                "declared_layer": declared_layer,
                "declared_layer_index": declared_index,
                "mapped_graph_layer": mapped_graph_layer,
                "layer_drift": drift,
                "layer_drift_abs": None if drift is None else abs(drift),
                "pagerank_forward": _nested_get(pagerank, ("forward", table_id)),
                "pagerank_reverse": _nested_get(pagerank, ("reverse", table_id)),
                "hits_hub": _nested_get(hits, ("hub", table_id)),
                "hits_authority": _nested_get(hits, ("authority", table_id)),
                "k_core": k_core.get(table_id),
            }
        )
    return tuple(records)


def _layer_violations(
    table_graph: TableGraph,
    table_metrics: tuple[Mapping[str, Any], ...],
    config: AnalysisConfig,
) -> list[dict[str, Any]]:
    by_table = {str(item["table_id"]): item for item in table_metrics}
    violations: list[dict[str, Any]] = []
    for edge in table_graph.edges:
        source = by_table[edge.source_id]
        target = by_table[edge.target_id]
        source_layer = str(source["declared_layer"])
        target_layer = str(target["declared_layer"])
        for source_rule, target_rule, rule_id, severity in config.layer_violation_rules:
            if not _layer_rule_matches(source_layer, str(source_rule)):
                continue
            if not _layer_rule_matches(target_layer, str(target_rule)):
                continue
            violations.append(
                {
                    "rule_id": str(rule_id),
                    "severity": str(severity),
                    "source_table_id": edge.source_id,
                    "source_table_name": str(source["table_name"]),
                    "source_layer": source_layer,
                    "target_table_id": edge.target_id,
                    "target_table_name": str(target["table_name"]),
                    "target_layer": target_layer,
                }
            )
    return sorted(
        violations,
        key=lambda item: (
            item["rule_id"],
            item["source_table_id"],
            item["target_table_id"],
            item["severity"],
        ),
    )


def _declared_layer_names(config: AnalysisConfig) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for layer, _pattern in config.layer_patterns:
        layer_name = str(layer)
        if layer_name not in seen:
            names.append(layer_name)
            seen.add(layer_name)
    return tuple(names)


def _declared_layer_index(layer: str, layer_names: tuple[str, ...]) -> int | None:
    if layer == "unknown":
        return None
    try:
        return layer_names.index(layer)
    except ValueError:
        return None


def _map_graph_layer(graph_layer: int, max_graph_layer: int, layer_count: int) -> int | None:
    if layer_count <= 0:
        return None
    if max_graph_layer <= 0:
        return 0
    mapped = round((graph_layer / max_graph_layer) * (layer_count - 1))
    return min(layer_count - 1, max(0, int(mapped)))


def _match_layer(table: Mapping[str, Any], config: AnalysisConfig) -> str:
    full_name = _table_full_name(table).lower()
    for layer, pattern in config.layer_patterns:
        normalized_pattern = str(pattern).lower()
        if normalized_pattern and normalized_pattern in full_name:
            return str(layer)
    return "unknown"


def _table_full_name(table: Mapping[str, Any]) -> str:
    parts = [
        str(value)
        for value in (table.get("catalog"), table.get("schema_name"), table.get("name"))
        if value
    ]
    return ".".join(parts) if parts else str(table.get("name", ""))


def _layer_rule_matches(layer: str, rule_layer: str) -> bool:
    return rule_layer == "*" or layer == rule_layer


def _metric_value(metric: MetricResult) -> dict[str, Any]:
    if metric.status != MetricStatus.SUCCESS:
        return {}
    value = thaw(metric.value)
    return value if isinstance(value, dict) else {}


def _nested_get(mapping: Mapping[str, Any], path: tuple[str, str]) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _round_float_mapping(values: Mapping[str, float], precision: int) -> dict[str, float]:
    return {
        str(node_id): round(float(values[node_id]), precision)
        for node_id in sorted(values)
    }


def _load_networkx() -> Any | None:
    try:
        import networkx as nx  # type: ignore
    except ImportError:
        return None
    return nx


def _success_metric(name: str, value: Any) -> MetricResult:
    return MetricResult(
        name=name,
        status=MetricStatus.SUCCESS,
        value=value,
        algorithm="topology",
        version=TOPOLOGY_VERSION,
    )


def _skipped_metric(name: str, reason: str) -> MetricResult:
    return MetricResult(
        name=name,
        status=MetricStatus.SKIPPED,
        reason=reason,
        algorithm="topology",
        version=TOPOLOGY_VERSION,
    )
