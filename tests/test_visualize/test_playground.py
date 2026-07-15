"""Playground 展示语义回归测试。"""

from sqlgraph.playground import PLAYGROUND_HTML, graph_to_playground_payload


def _nodes_and_edges(sql: str):
    payload = graph_to_playground_payload(sql, dialect="spark", name="playground_test")
    elements = payload["elements"]
    nodes = [e["data"] for e in elements if "source" not in e.get("data", {})]
    edges = [e["data"] for e in elements if "source" in e.get("data", {})]
    return nodes, edges


def _table_id(nodes: list[dict], label: str) -> str:
    return next(n["id"] for n in nodes if n.get("nodeType") == "table" and n.get("label") == label)


def _column_id(nodes: list[dict], table_id: str, label: str) -> str:
    return next(
        n["id"]
        for n in nodes
        if n.get("nodeType") == "column"
        and n.get("tableId") == table_id
        and n.get("label") == label
    )


def test_playground_html_contains_color_legend():
    assert 'aria-label="图例：节点与边颜色含义"' in PLAYGROUND_HTML
    assert "字段对齐/重命名" in PLAYGROUND_HTML
    assert "SQL 路径" in PLAYGROUND_HTML


def test_playground_collapses_same_name_passthrough_to_table():
    nodes, edges = _nodes_and_edges(
        """
        INSERT OVERWRITE TABLE dst
        SELECT id FROM src
        """
    )
    src_id = _table_id(nodes, "src")
    dst_id = _table_id(nodes, "dst")
    src_col = _column_id(nodes, src_id, "id")

    assert any(
        e.get("edgeType") == "direct_to_table"
        and e.get("source") == src_col
        and e.get("target") == dst_id
        for e in edges
    )
    assert not any(
        n.get("nodeType") == "column"
        and n.get("tableId") == dst_id
        and n.get("label") == "id"
        for n in nodes
    )


def test_playground_union_mixed_sources_preserve_target_field():
    nodes, edges = _nodes_and_edges(
        """
        INSERT OVERWRITE TABLE dst
        SELECT id FROM src_a
        UNION ALL
        SELECT user_id FROM src_b
        """
    )
    src_a_id = _table_id(nodes, "src_a")
    src_b_id = _table_id(nodes, "src_b")
    dst_id = _table_id(nodes, "dst")
    src_a_col = _column_id(nodes, src_a_id, "id")
    src_b_col = _column_id(nodes, src_b_id, "user_id")
    dst_col = _column_id(nodes, dst_id, "id")

    assert any(
        e.get("edgeType") == "direct_column"
        and e.get("source") == src_a_col
        and e.get("target") == dst_col
        for e in edges
    )
    assert any(
        e.get("edgeType") == "rename_column"
        and e.get("source") == src_b_col
        and e.get("target") == dst_col
        for e in edges
    )
    assert any(
        e.get("edgeType") == "column_to_table"
        and e.get("source") == dst_col
        and e.get("target") == dst_id
        for e in edges
    )
    assert not any(
        e.get("edgeType") == "direct_to_table"
        and e.get("source") == src_b_col
        and e.get("target") == dst_id
        for e in edges
    )


def test_playground_collapses_cte_table_nodes_by_default():
    payload = graph_to_playground_payload(
        """
        WITH a AS (SELECT id FROM raw_log),
             b AS (SELECT id FROM raw_log)
        SELECT a.id AS ax, b.id AS bx
        FROM a JOIN b ON a.id = b.id
        """,
        dialect="spark",
        name="dup_cte",
    )
    nodes = [e["data"] for e in payload["elements"] if "source" not in e.get("data", {})]
    cte_tables = [
        n for n in nodes
        if n.get("nodeType") == "table" and n.get("isCte")
    ]
    table_labels = {
        n.get("label") for n in nodes
        if n.get("nodeType") == "table"
    }
    assert cte_tables == []
    assert "a / b" not in table_labels
    assert "raw_log" in table_labels
    assert "dup_cte_result" in table_labels
