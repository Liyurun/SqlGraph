# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Trace a projected table edge back to statement and column evidence."""

from __future__ import annotations

from sqlgraph.model import ColumnNode, EdgeType, TransformNode


def _column_ids(graph, table_id: str) -> set[str]:
    return {
        edge.target_id
        for edge in graph.edges
        if edge.edge_type == EdgeType.HAS_COLUMN
        and edge.source_id == table_id
    }


def _column_name(graph, column_id: str) -> str:
    column = graph.get_node(column_id)
    if not isinstance(column, ColumnNode):
        return column_id
    table = graph.get_node(column.table_id) if column.table_id else None
    table_name = getattr(table, "full_name", None)
    return f"{table_name}.{column.name}" if table_name else column.name


def drilldown(graph, source_table: str, target_table: str) -> dict:
    """Return the evidence that produced one direct table-lineage edge."""
    source = graph.get_node_by_name(source_table)
    target = graph.get_node_by_name(target_table)
    if source is None or target is None:
        return {"found": False, "reason": "table not found"}

    lineage_edge = next(
        (
            edge for edge in graph.edges
            if edge.edge_type == EdgeType.TABLE_LINEAGE
            and edge.source_id == source.id
            and edge.target_id == target.id
        ),
        None,
    )
    if lineage_edge is None:
        return {"found": False, "reason": "no table_lineage edge"}

    provenance = tuple(lineage_edge.properties.get("provenance", ()))
    target_columns = _column_ids(graph, target.id)
    column_paths = []
    transform_ids: set[str] = set()

    for target_column_id in sorted(target_columns):
        producers = [
            edge.source_id
            for edge in graph.edges
            if edge.edge_type == EdgeType.PRODUCES
            and edge.target_id == target_column_id
        ]
        for transform_id in producers:
            transform = graph.get_node(transform_id)
            if not isinstance(transform, TransformNode):
                continue
            dependencies = [
                edge.source_id
                for edge in graph.edges
                if edge.edge_type == EdgeType.COMPUTE_DEPENDENCY
                and edge.target_id == transform_id
            ]
            matching = [
                dependency
                for dependency in dependencies
                if getattr(graph.get_node(dependency), "table_id", None) == source.id
            ]
            if not matching:
                continue
            transform_ids.add(transform_id)
            column_paths.append({
                "target_column": _column_name(graph, target_column_id),
                "transform": transform_id,
                "source_columns": tuple(
                    sorted(_column_name(graph, item) for item in matching)
                ),
            })

        passthrough = [
            edge.source_id
            for edge in graph.edges
            if edge.edge_type == EdgeType.COMPUTE_DEPENDENCY
            and edge.target_id == target_column_id
            and getattr(graph.get_node(edge.source_id), "table_id", None) == source.id
        ]
        if passthrough:
            column_paths.append({
                "target_column": _column_name(graph, target_column_id),
                "transform": None,
                "source_columns": tuple(
                    sorted(_column_name(graph, item) for item in passthrough)
                ),
            })

    return {
        "found": True,
        "edge": (source.id, target.id),
        "edge_id": lineage_edge.id,
        "provenance": list(provenance),
        "statements": sorted({
            ref["sql_id"] for ref in provenance if ref.get("sql_id")
        }),
        "transforms": sorted(transform_ids),
        "column_paths": column_paths,
    }
