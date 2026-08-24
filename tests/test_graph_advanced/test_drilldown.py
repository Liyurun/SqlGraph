from __future__ import annotations

from sqlgraph.analyze.loader import load_analysis_view
from sqlgraph.analyze.table_graph import build_table_graph
from sqlgraph.api import build_graph
from sqlgraph.lineage import drilldown


def test_table_edge_drills_to_statement_columns_and_transforms():
    graph = build_graph(
        "INSERT INTO dst "
        "SELECT CASE WHEN status='A' THEN amount ELSE 0 END AS value "
        "FROM src",
        dialect="spark",
    )

    result = drilldown(graph, "src", "dst")

    assert result["found"]
    assert result["statements"]
    path = next(
        item for item in result["column_paths"]
        if item["target_column"] == "dst.value"
    )
    assert set(path["source_columns"]) == {"src.amount", "src.status"}
    assert path["transform"]


def test_table_projection_keeps_rebuild_references():
    graph = build_graph(
        "INSERT INTO dst SELECT amount * 2 AS value FROM src",
        dialect="spark",
    )

    table_graph = build_table_graph(load_analysis_view(graph))
    edge = table_graph.edges[0]

    assert edge.statement_refs
    assert edge.column_dependency_ids
    assert edge.transform_ids
