# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os

from sqlgraph.api import build_graph
from sqlgraph.serve.index_io import build_index, load_raw_index
from sqlgraph.serve.graph_index import GraphIndex


def _index(tmp_path, sql):
    graph = build_graph(sql, dialect="spark")
    index_dir = os.path.join(tmp_path, "idx")
    build_index(graph, index_dir, source_meta={"path": "inline", "size": 0, "mtime": 0, "sha1_16": ""})
    return GraphIndex.from_raw(load_raw_index(index_dir))


def _table_id(index, full_name):
    for nid, node in index.nodes.items():
        if node.get("node_type") == "table" and node.get("full_name") == full_name:
            return nid
    raise AssertionError(f"table {full_name} not found")


def _node_ids(payload):
    return {node["id"] for node in payload["nodes"]}


def _node_types(payload):
    return {node["node_type"] for node in payload["nodes"]}


def _column_id(index, table_full_name, column_name):
    table_id = _table_id(index, table_full_name)
    for nid, node in index.nodes.items():
        if (
            node.get("node_type") == "column"
            and node.get("table_id") == table_id
            and node.get("name") == column_name
        ):
            return nid
    raise AssertionError(f"column {table_full_name}.{column_name} not found")


def _single_sql_id(index):
    sql_nodes = [
        nid for nid, node in index.nodes.items()
        if node.get("node_type") == "sql"
    ]
    assert len(sql_nodes) == 1
    return sql_nodes[0]


def _manual_index(nodes, edges, sql=None):
    return GraphIndex.from_raw({
        "manifest": {"stats": {"nodes": len(nodes), "edges": len(edges), "sql": len(sql or [])}},
        "nodes": nodes,
        "edges": edges,
        "sql": sql or [],
    })


def _table_node(table_id, name):
    return {"id": table_id, "name": name, "node_type": "table"}


def _cte_table_node(table_id, name="subq_deadbeef", alias="cte_data"):
    return {
        "id": table_id,
        "name": name,
        "node_type": "table",
        "is_cte": True,
        "aliases": [alias],
    }


def _column_node(column_id, table_id, name):
    return {
        "id": column_id,
        "name": name,
        "node_type": "column",
        "table_id": table_id,
    }


def _sql_node(sql_id, name="job"):
    return {
        "id": sql_id,
        "name": name,
        "node_type": "sql",
        "sql_content": "INSERT OVERWRITE TABLE dst SELECT id FROM src",
    }


def _transform_node(transform_id, expression="SUM(src.id)", output_name="id_sum"):
    return {
        "id": transform_id,
        "name": expression,
        "node_type": "transform",
        "expression": expression,
        "output_name": output_name,
    }


def _edge(edge_id, source, target, edge_type):
    return {"id": edge_id, "source": source, "target": target, "type": edge_type}


def test_meta_reports_counts(tmp_path):
    index = _index(tmp_path, "INSERT OVERWRITE TABLE dst SELECT id FROM src")
    meta = index.meta()
    assert meta["stats"]["nodes"] > 0
    assert meta["stats"]["edges"] > 0


def test_adjacency_and_full_name(tmp_path):
    index = _index(tmp_path, "INSERT OVERWRITE TABLE dst SELECT id FROM src")
    src_id = _table_id(index, "src")
    adj = index.adjacency[src_id]
    assert set(adj.keys()) == {"in", "out"}
    assert all(isinstance(x, str) for x in adj["out"])
    # full_name is derived once and stored on the cached node dict
    assert index.nodes[src_id]["full_name"] == "src"


def test_search_matches_table_and_column(tmp_path):
    index = _index(tmp_path, "INSERT OVERWRITE TABLE dst SELECT id FROM src")
    tables = index.search("dst", entity_type="table", limit=10)
    assert any(hit["type"] == "table" and hit["name"] == "dst" for hit in tables)
    cols = index.search("id", entity_type="column", limit=10)
    assert any(hit["type"] == "column" and hit["name"] == "id" for hit in cols)
    # SQL raw text is NOT searchable in v1
    assert index.search("select", entity_type="all", limit=10) == [] or all(
        hit["type"] in ("table", "column") for hit in index.search("select", entity_type="all", limit=10)
    )


def test_search_filters_internal_cte_tables(tmp_path):
    del tmp_path
    index = _manual_index(
        nodes=[
            _table_node("src", "src"),
            _table_node("dst", "dst"),
            _cte_table_node("cte", "subq_200e72d319fd5a2b", "all_sales_and_details"),
            _column_node("cte_col", "cte", "metric"),
        ],
        edges=[_edge("cte_has_metric", "cte", "cte_col", "has_column")],
    )

    assert index.search("subq_200e72d319fd5a2b", entity_type="table", limit=10) == []
    assert index.search("metric", entity_type="column", limit=10)[0]["tableId"] == "cte"


def test_subgraph_depth_and_direction(tmp_path):
    index = _index(
        tmp_path,
        "INSERT OVERWRITE TABLE mid SELECT id FROM src;\n"
        "INSERT OVERWRITE TABLE dst SELECT id FROM mid",
    )
    mid_id = _table_id(index, "mid")
    both = index.subgraph(mid_id, depth=1, direction="both")
    node_ids = {n["id"] for n in both["nodes"]}
    assert mid_id in node_ids
    assert len(both["edges"]) >= 1
    # depth 1 from mid should not reach 2-hop-only nodes on a single side
    up_only = index.subgraph(mid_id, depth=1, direction="up")
    down_only = index.subgraph(mid_id, depth=1, direction="down")
    assert {n["id"] for n in up_only["nodes"]} != {n["id"] for n in down_only["nodes"]}


def test_table_subgraph_accepts_depth_beyond_three(tmp_path):
    del tmp_path
    index = _manual_index(
        nodes=[
            _table_node("a", "a"),
            _table_node("b", "b"),
            _table_node("c", "c"),
            _table_node("d", "d"),
            _table_node("e", "e"),
        ],
        edges=[
            _edge("ab", "a", "b", "table_lineage"),
            _edge("bc", "b", "c", "table_lineage"),
            _edge("cd", "c", "d", "table_lineage"),
            _edge("de", "d", "e", "table_lineage"),
        ],
    )

    depth_3 = index.table_subgraph("a", depth=3, direction="down")
    assert "e" not in _node_ids(depth_3)

    depth_4 = index.table_subgraph("a", depth=4, direction="down")
    assert "e" in _node_ids(depth_4)
    assert _node_types(depth_4) == {"table"}
    assert all(edge["type"] == "table_lineage" for edge in depth_4["edges"])


def test_table_subgraph_direction_uses_table_lineage(tmp_path):
    del tmp_path
    index = _manual_index(
        nodes=[
            _table_node("a", "a"),
            _table_node("b", "b"),
            _table_node("c", "c"),
        ],
        edges=[
            _edge("ab", "a", "b", "table_lineage"),
            _edge("bc", "b", "c", "table_lineage"),
        ],
    )

    up = index.table_subgraph("b", depth=1, direction="up")
    down = index.table_subgraph("b", depth=1, direction="down")

    assert "a" in _node_ids(up)
    assert "c" not in _node_ids(up)
    assert "c" in _node_ids(down)
    assert "a" not in _node_ids(down)


def test_table_subgraph_truncates_large_payload_with_user_message(tmp_path):
    del tmp_path
    index = _manual_index(
        nodes=[
            _table_node("a", "a"),
            _table_node("b", "b"),
            _table_node("c", "c"),
            _table_node("d", "d"),
            _table_node("e", "e"),
        ],
        edges=[
            _edge("ab", "a", "b", "table_lineage"),
            _edge("bc", "b", "c", "table_lineage"),
            _edge("cd", "c", "d", "table_lineage"),
            _edge("de", "d", "e", "table_lineage"),
        ],
    )
    index.max_graph_nodes = 3
    index.max_graph_edges = 2

    payload = index.table_subgraph("a", depth=4, direction="down")

    assert payload["truncated"] is True
    assert payload["totalNodes"] == 5
    assert payload["displayedNodes"] == 3
    assert payload["totalEdges"] == 4
    assert payload["displayedEdges"] == 2
    assert payload["limits"] == {"maxNodes": 3, "maxEdges": 2}
    assert "只展示一部分" in payload["message"]
    assert _node_ids(payload) == {"a", "b", "c"}
    assert [edge["id"] for edge in payload["edges"]] == ["ab", "bc"]


def test_table_subgraph_column_start_uses_parent_table(tmp_path):
    index = _index(tmp_path, "INSERT OVERWRITE TABLE dst SELECT id FROM src")
    dst = _table_id(index, "dst")
    dst_id_col = _column_id(index, "dst", "id")

    payload = index.table_subgraph(dst_id_col, depth=1, direction="up")

    assert dst in _node_ids(payload)
    assert _node_types(payload) == {"table"}


def test_table_subgraph_sql_start_uses_read_write_tables(tmp_path):
    index = _index(tmp_path, "INSERT OVERWRITE TABLE dst SELECT id FROM src")
    sql_id = _single_sql_id(index)
    src = _table_id(index, "src")
    dst = _table_id(index, "dst")

    payload = index.table_subgraph(sql_id, depth=1, direction="both")

    assert {src, dst}.issubset(_node_ids(payload))
    assert _node_types(payload) == {"table"}


def test_table_subgraph_filters_cte_and_resolves_cte_start_to_physical_tables(tmp_path):
    del tmp_path
    index = _manual_index(
        nodes=[
            _sql_node("sql"),
            _table_node("src", "src"),
            _table_node("dst", "dst"),
            _cte_table_node("cte", "subq_200e72d319fd5a2b", "all_sales_and_details"),
            _column_node("src_id", "src", "id"),
            _column_node("cte_id", "cte", "id"),
            _transform_node("expr", "SUM(src.id)", "id"),
        ],
        edges=[
            _edge("sql_reads_src", "sql", "src", "reads_from"),
            _edge("sql_writes_dst", "sql", "dst", "writes_to"),
            _edge("src_to_dst", "src", "dst", "table_lineage"),
            _edge("cte_has_id", "cte", "cte_id", "has_column"),
            _edge("src_has_id", "src", "src_id", "has_column"),
            _edge("sql_contains_expr", "sql", "expr", "contains"),
            _edge("src_to_cte", "src_id", "cte_id", "compute_dependency"),
            _edge("expr_to_cte", "expr", "cte_id", "produces"),
        ],
    )

    assert "cte" not in index.table_adjacency

    payload = index.table_subgraph("cte", depth=1, direction="both")
    assert _node_ids(payload) == {"src", "dst"}
    assert _node_types(payload) == {"table"}
    assert payload["edges"] == [_edge("src_to_dst", "src", "dst", "table_lineage")]


def test_table_subgraph_filters_cte_aliases_inferred_from_sql_text(tmp_path):
    del tmp_path
    index = _manual_index(
        nodes=[
            _sql_node("sql"),
            _table_node("src", "src"),
            _table_node("dst", "dst"),
            _table_node("base", "base"),
        ],
        edges=[
            _edge("sql_reads_src", "sql", "src", "reads_from"),
            _edge("sql_reads_base", "sql", "base", "reads_from"),
            _edge("sql_writes_dst", "sql", "dst", "writes_to"),
            _edge("src_to_dst", "src", "dst", "table_lineage"),
            _edge("base_to_dst", "base", "dst", "table_lineage"),
        ],
        sql=[{
            "id": "sql",
            "name": "job",
            "sql_content": "WITH base AS (SELECT id FROM src) INSERT OVERWRITE TABLE dst SELECT id FROM base",
        }],
    )

    assert "base" not in index.table_adjacency

    payload = index.table_subgraph("dst", depth=1, direction="up")
    assert _node_ids(payload) == {"src", "dst"}
    assert payload["edges"] == [_edge("src_to_dst", "src", "dst", "table_lineage")]


def test_table_expansion_returns_incremental_one_hop(tmp_path):
    del tmp_path
    index = _manual_index(
        nodes=[
            _table_node("a", "a"),
            _table_node("b", "b"),
            _table_node("c", "c"),
            _table_node("d", "d"),
        ],
        edges=[
            _edge("ab", "a", "b", "table_lineage"),
            _edge("bc", "b", "c", "table_lineage"),
            _edge("cd", "c", "d", "table_lineage"),
        ],
    )

    up = index.table_expansion("b", direction="up", depth=1)
    assert {"a", "b"}.issubset(_node_ids(up))
    assert "c" not in _node_ids(up)

    down = index.table_expansion("b", direction="down", depth=1)
    assert {"b", "c"}.issubset(_node_ids(down))
    assert "d" not in _node_ids(down)
    assert _node_types(down) == {"table"}


def test_node_detail_has_read_write_sql_groups(tmp_path):
    index = _index(tmp_path, "INSERT OVERWRITE TABLE dst SELECT id FROM src")
    dst_id = _table_id(index, "dst")
    detail = index.node_detail(dst_id)
    assert detail["node"]["id"] == dst_id
    assert any(item["sqlId"] for item in detail["writeSqls"])
    assert isinstance(detail["readSqls"], list)


def test_node_detail_for_table_includes_clickable_columns(tmp_path):
    index = _index(tmp_path, "INSERT OVERWRITE TABLE dst SELECT id FROM src")
    dst_id = _table_id(index, "dst")

    detail = index.node_detail(dst_id)

    assert any(col["name"] == "id" and col["tableId"] == dst_id for col in detail["columns"])


def test_node_detail_for_column_reports_owner_and_lineage(tmp_path):
    del tmp_path
    index = _manual_index(
        nodes=[
            _sql_node("sql"),
            _table_node("src", "src"),
            _table_node("dst", "dst"),
            _column_node("src_id", "src", "id"),
            _column_node("dst_id", "dst", "id"),
            _transform_node("expr", "SUM(src.id)", "id"),
        ],
        edges=[
            _edge("src_has_id", "src", "src_id", "has_column"),
            _edge("dst_has_id", "dst", "dst_id", "has_column"),
            _edge("sql_contains_expr", "sql", "expr", "contains"),
            _edge("src_to_dst_col", "src_id", "dst_id", "compute_dependency"),
            _edge("expr_to_dst", "expr", "dst_id", "produces"),
        ],
        sql=[{"id": "sql", "name": "job", "sql_content": "INSERT OVERWRITE TABLE dst SELECT id FROM src"}],
    )

    detail = index.node_detail("dst_id")

    assert detail["node"]["id"] == "dst_id"
    assert detail["ownerTable"]["id"] == "dst"
    assert detail["ownerTable"]["fullName"] == "dst"
    assert detail["upstream"][0]["id"] == "src_id"
    assert detail["upstream"][0]["tableName"] == "src"
    assert detail["transforms"][0]["id"] == "expr"
    assert detail["sqls"][0]["sqlId"] == "sql"


def test_node_detail_missing_returns_none(tmp_path):
    index = _index(tmp_path, "INSERT OVERWRITE TABLE dst SELECT id FROM src")
    assert index.node_detail("no_such_id") is None
