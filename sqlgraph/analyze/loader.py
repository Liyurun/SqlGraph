# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Load graph inputs into deeply immutable analysis views."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from sqlgraph.analyze.contracts import AnalysisView, freeze, thaw
from sqlgraph.model import PropertyGraph


def load_analysis_view(
    source: PropertyGraph | str | Path | Mapping[str, Any],
) -> AnalysisView:
    """Load a graph without retaining mutable references to the input.

    Args:
        source: An in-memory PropertyGraph, graph.json path, or compatible
            ``{"nodes": [...], "edges": [...]}`` mapping.

    Returns:
        A deeply immutable, deterministically ordered AnalysisView.

    Raises:
        FileNotFoundError: The JSON path does not exist.
        ValueError: The input does not satisfy the graph serialization contract.
        TypeError: The input type is unsupported.
    """
    source_path = None
    if isinstance(source, PropertyGraph):
        raw = source.to_dict()
        input_kind = "property_graph"
    elif isinstance(source, (str, Path)):
        path = Path(source)
        source_path = str(path.resolve())
        try:
            with path.open("r", encoding="utf-8") as stream:
                raw = json.load(stream)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid graph JSON: {exc}") from exc
        input_kind = "graph_json"
    elif isinstance(source, Mapping):
        raw = thaw(source)
        input_kind = "mapping"
    else:
        raise TypeError(
            "source must be PropertyGraph, graph.json path, or graph mapping"
        )

    nodes, edges = _validate_and_normalize(raw)
    fingerprint = _graph_fingerprint(nodes, edges)
    frozen_nodes = tuple(freeze(node) for node in nodes)
    frozen_edges = tuple(freeze(edge) for edge in edges)
    node_by_id = MappingProxyType(
        {str(node["id"]): node for node in frozen_nodes}
    )
    return AnalysisView(
        nodes=frozen_nodes,
        edges=frozen_edges,
        node_by_id=node_by_id,
        graph_fingerprint=fingerprint,
        input_kind=input_kind,
        source_path=source_path,
    )


def _validate_and_normalize(
    raw: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(raw, Mapping):
        raise ValueError("graph input must be a JSON object")
    raw_nodes = raw.get("nodes")
    raw_edges = raw.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ValueError("graph input must contain list fields: nodes and edges")

    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for index, item in enumerate(raw_nodes):
        if not isinstance(item, Mapping):
            raise ValueError(f"node at index {index} must be an object")
        node = thaw(item)
        node_id = node.get("id")
        node_type = node.get("node_type")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError(f"node at index {index} has invalid id")
        if not isinstance(node_type, str) or not node_type:
            raise ValueError(f"node {node_id!r} has invalid node_type")
        if node_id in node_ids:
            raise ValueError(f"Duplicate node id: {node_id}")
        node_ids.add(node_id)
        nodes.append(node)

    edges: list[dict[str, Any]] = []
    edge_ids: set[str] = set()
    for index, item in enumerate(raw_edges):
        if not isinstance(item, Mapping):
            raise ValueError(f"edge at index {index} must be an object")
        edge = thaw(item)
        edge_id = edge.get("id")
        source = edge.get("source")
        target = edge.get("target")
        edge_type = edge.get("type")
        if not isinstance(edge_id, str) or not edge_id:
            raise ValueError(f"edge at index {index} has invalid id")
        if edge_id in edge_ids:
            original_id = edge_id
            edge_id = f"{original_id}__dup_{index}"
            while edge_id in edge_ids:
                edge_id = f"{original_id}__dup_{index}_{len(edge_ids)}"
            edge["id"] = edge_id
            edge.setdefault("original_id", original_id)
        if source not in node_ids or target not in node_ids:
            raise ValueError(
                f"edge {edge_id!r} references missing node; "
                "node is missing from the input"
            )
        if not isinstance(edge_type, str) or not edge_type:
            raise ValueError(f"edge {edge_id!r} has invalid type")
        edge_ids.add(edge_id)
        edges.append(edge)

    nodes.sort(key=lambda node: str(node["id"]))
    edges.sort(
        key=lambda edge: (
            str(edge["source"]),
            str(edge["target"]),
            str(edge["type"]),
            str(edge["id"]),
        )
    )
    return nodes, edges


def _graph_fingerprint(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> str:
    payload = json.dumps(
        {"nodes": nodes, "edges": edges},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
