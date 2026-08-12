# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Compact physical-table directed graph for governance analysis.

The :class:`TableGraph` is a self-contained projection that consumes only
an :class:`AnalysisView` and does **not** depend on NetworkX.

Edge direction is always *source_table → target_table* (upstream feeds
downstream).  CTE tables and self-loops are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from sqlgraph.analyze.contracts import AnalysisView


@dataclass(frozen=True)
class TableGraphEdge:
    """A weighted directed edge between two physical tables.

    Attributes:
        source_id: Node id of the source (upstream) table.
        target_id: Node id of the target (downstream) table.
        field_weight: Number of cross-table column-level dependency paths
            (both passthrough ``column→column`` and
            ``column→transform→column``).
        sql_weight: Number of independent SQL statements that create this
            table-level dependency, derived from ``reads_from`` and
            ``writes_to`` edges.
    """

    source_id: str
    target_id: str
    field_weight: int = 0
    sql_weight: int = 0

    @property
    def total_weight(self) -> int:
        """Combined weight for convenience; callers should prefer individual
        weights for semantic interpretation."""
        return self.field_weight + self.sql_weight


@dataclass(frozen=True)
class TableGraph:
    """Compact directed graph of physical (non-CTE) tables.

    Built once from an :class:`AnalysisView` and reused by downstream
    metrics.  All containers are immutable and deterministically ordered.
    """

    nodes: tuple[str, ...]
    """Stable-sorted physical table node ids."""

    edges: tuple[TableGraphEdge, ...]
    """All weighted edges (no CTE, no self-loops)."""

    node_index: Mapping[str, int]
    """O(1) lookup: node id → positional index."""

    adjacency: Mapping[str, tuple[TableGraphEdge, ...]]
    """Source node id → outgoing edges (stable order)."""

    in_degree: Mapping[str, int]
    """Node id → incoming edge count."""

    out_degree: Mapping[str, int]
    """Node id → outgoing edge count."""

    nodes_by_id: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    """Node id → immutable node snapshot (for name/layer lookups)."""

    def __post_init__(self) -> None:
        for field_name in (
            "node_index",
            "adjacency",
            "in_degree",
            "out_degree",
            "nodes_by_id",
        ):
            value = getattr(self, field_name)
            if isinstance(value, dict):
                object.__setattr__(self, field_name, MappingProxyType(value))

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def has_node(self, node_id: str) -> bool:
        return node_id in self.node_index

    def successors(self, node_id: str) -> tuple[TableGraphEdge, ...]:
        """Return outgoing edges for *node_id* (empty tuple if none)."""
        return self.adjacency.get(node_id, ())

    def iter_edges(self):
        """Iterate over all edges in stable order."""
        return iter(self.edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "nodes": list(self.nodes),
            "edges": [
                {
                    "source_id": e.source_id,
                    "target_id": e.target_id,
                    "field_weight": e.field_weight,
                    "sql_weight": e.sql_weight,
                }
                for e in self.edges
            ],
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_table_graph(view: AnalysisView) -> TableGraph:
    """Construct a compact physical-table directed graph.

    Steps (in order, all O(V+E)):

    1. Enumerate physical tables (``node_type == "table"``, ``is_cte`` falsy).
    2. Build a ``column_id → table_id`` index from ``ColumnNode.table_id``.
    3. Aggregate *field_weight* from:
       - Passthrough: ``COMPUTE_DEPENDENCY`` edge from source column to
         target column (different parent tables).
       - Transform: ``COMPUTE_DEPENDENCY`` from source column to
         ``TransformNode``, then ``PRODUCES`` to output column (different
         parent tables).
    4. Aggregate *sql_weight* per SQL node from ``READS_FROM`` and
       ``WRITES_TO`` edges, counting independent SQLs per (source, target)
       table pair.
    5. Seed the edge set from ``TABLE_LINEAGE`` edges (filtering CTE and
       self-loops), then overlay the aggregated weights.
    6. Build adjacency lists with stable ordering.

    STRUCT/nested sub-fields are never represented as ``ColumnNode``
    entities in the current model, so they cannot leak as top-level
    columns.
    """
    # ── 1. Identify physical tables ──────────────────────────────────────
    physical: set[str] = set()
    table_is_cte: dict[str, bool] = {}
    table_snapshots: dict[str, dict[str, Any]] = {}

    for node in view.iter_nodes("table"):
        tid = str(node["id"])
        is_cte = bool(node.get("is_cte", False))
        table_is_cte[tid] = is_cte
        table_snapshots[tid] = dict(node)
        if not is_cte:
            physical.add(tid)

    # ── 2. Column → table index ─────────────────────────────────────────
    column_table: dict[str, str] = {}
    for node in view.iter_nodes("column"):
        cid = str(node["id"])
        tid = node.get("table_id")
        if tid is not None:
            tid_str = str(tid)
            if tid_str in physical:
                column_table[cid] = tid_str

    # ── 3. Field weight ─────────────────────────────────────────────────
    field_weight: dict[tuple[str, str], int] = {}

    # Index: transform_id → output column_id
    transform_output: dict[str, str] = {}
    for edge in view.iter_edges("produces"):
        transform_output[str(edge["source"])] = str(edge["target"])

    for edge in view.iter_edges("compute_dependency"):
        src_id = str(edge["source"])
        tgt_id = str(edge["target"])

        src_table = column_table.get(src_id)
        if src_table is None:
            continue

        tgt_node = view.get_node(tgt_id)
        if tgt_node is None:
            continue

        tgt_type = tgt_node.get("node_type")

        if tgt_type == "column":
            # Passthrough: source_column → output_column
            tgt_table = column_table.get(tgt_id)
            if tgt_table is not None and tgt_table != src_table:
                key = (src_table, tgt_table)
                field_weight[key] = field_weight.get(key, 0) + 1

        elif tgt_type == "transform":
            # Transform: source_column → transform → output_column
            out_col = transform_output.get(tgt_id)
            if out_col:
                tgt_table = column_table.get(out_col)
                if tgt_table is not None and tgt_table != src_table:
                    key = (src_table, tgt_table)
                    field_weight[key] = field_weight.get(key, 0) + 1

    # ── 4. SQL weight ───────────────────────────────────────────────────
    sql_weight: dict[tuple[str, str], int] = {}
    sql_reads: dict[str, set[str]] = {}
    sql_writes: dict[str, set[str]] = {}

    for edge in view.iter_edges("reads_from"):
        sql_id = str(edge["source"])
        table_id = str(edge["target"])
        if table_id in physical:
            sql_reads.setdefault(sql_id, set()).add(table_id)

    for edge in view.iter_edges("writes_to"):
        sql_id = str(edge["source"])
        table_id = str(edge["target"])
        if table_id in physical:
            sql_writes.setdefault(sql_id, set()).add(table_id)

    for sql_id, reads in sql_reads.items():
        writes = sql_writes.get(sql_id, set())
        for src_tbl in reads:
            for tgt_tbl in writes:
                if src_tbl != tgt_tbl:
                    key = (src_tbl, tgt_tbl)
                    sql_weight[key] = sql_weight.get(key, 0) + 1

    # ── 5. Seed edge set from TABLE_LINEAGE and overlay weights ─────────
    edge_registry: dict[tuple[str, str], dict[str, int]] = {}

    for edge in view.iter_edges("table_lineage"):
        src_id = str(edge["source"])
        tgt_id = str(edge["target"])
        if src_id in physical and tgt_id in physical and src_id != tgt_id:
            edge_registry.setdefault(
                (src_id, tgt_id), {"field_weight": 0, "sql_weight": 0}
            )

    # Overlay field weights (may introduce edges not in TABLE_LINEAGE)
    for (src, tgt), fw in field_weight.items():
        edge_registry.setdefault(
            (src, tgt), {"field_weight": 0, "sql_weight": 0}
        )
        edge_registry[(src, tgt)]["field_weight"] += fw

    # Overlay SQL weights
    for (src, tgt), sw in sql_weight.items():
        edge_registry.setdefault(
            (src, tgt), {"field_weight": 0, "sql_weight": 0}
        )
        edge_registry[(src, tgt)]["sql_weight"] += sw

    # ── 6. Build graph structure ───────────────────────────────────────
    sorted_nodes = tuple(sorted(physical))
    node_index: dict[str, int] = {nid: i for i, nid in enumerate(sorted_nodes)}

    adjacency_builder: dict[str, list[TableGraphEdge]] = {nid: [] for nid in sorted_nodes}
    in_degree: dict[str, int] = {nid: 0 for nid in sorted_nodes}
    out_degree: dict[str, int] = {nid: 0 for nid in sorted_nodes}

    edge_list: list[TableGraphEdge] = []
    for (src, tgt) in sorted(edge_registry):
        weights = edge_registry[(src, tgt)]
        e = TableGraphEdge(
            source_id=src,
            target_id=tgt,
            field_weight=weights["field_weight"],
            sql_weight=weights["sql_weight"],
        )
        edge_list.append(e)
        adjacency_builder.setdefault(src, []).append(e)
        out_degree[src] += 1
        in_degree[tgt] += 1

    nodes_by_id: dict[str, dict[str, Any]] = {
        nid: table_snapshots.get(nid, {}) for nid in sorted_nodes
    }

    return TableGraph(
        nodes=sorted_nodes,
        edges=tuple(edge_list),
        node_index=node_index,
        adjacency={k: tuple(v) for k, v in adjacency_builder.items()},
        in_degree=in_degree,
        out_degree=out_degree,
        nodes_by_id=nodes_by_id,
    )
