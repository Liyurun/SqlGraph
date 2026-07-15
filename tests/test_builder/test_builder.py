import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from sqlgraph.builder import GraphBuilder
from sqlgraph.input import SqlSource, SqlSourceItem
from sqlgraph.model import EdgeType


def test_build_simple_insert():
    builder = GraphBuilder(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE target_tbl
    SELECT id, name FROM source_tbl
    """
    graph = builder.build_from_sql(sql, name="simple_insert")
    stats = graph.stats()
    assert stats["sql_count"] == 1
    assert stats["table_count"] >= 2
    assert stats["edge_count"] > 0


def test_build_multi_sql_lineage():
    builder = GraphBuilder(dialect="spark")
    sql1 = "INSERT OVERWRITE TABLE mid_tbl SELECT id, name FROM raw_tbl"
    sql2 = "INSERT OVERWRITE TABLE final_tbl SELECT id, name FROM mid_tbl"
    source = SqlSource.from_string(sql1, name="etl1")
    source.add_item(SqlSourceItem(name="etl2", content=sql2, source_type="string"))
    graph = builder.build_from_source(source)
    stats = graph.stats()
    assert stats["sql_count"] == 2
    assert stats["table_count"] >= 3
    lineage_edges = graph.get_edges_by_type(EdgeType.TABLE_LINEAGE)
    assert len(lineage_edges) >= 1


def test_build_with_aggregates():
    builder = GraphBuilder(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE daily_agg
    SELECT ad_id, dt, SUM(imp) as imp_sum, COUNT(*) as cnt, MAX(price) as max_p
    FROM events
    GROUP BY ad_id, dt
    """
    graph = builder.build_from_sql(sql, name="agg")
    stats = graph.stats()
    assert stats["transform_count"] >= 3


def test_build_with_case_when():
    builder = GraphBuilder(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE result
    SELECT id, CASE WHEN age > 18 THEN 'adult' ELSE 'minor' END as age_group
    FROM users
    """
    graph = builder.build_from_sql(sql, name="case_test")
    stats = graph.stats()
    assert stats["transform_count"] >= 1


def _expr_ids(graph):
    return [n.id for n in graph.nodes if n.node_type.value == "transform"]


def test_expr_dag_different_output_fields_not_merged():
    """相同表达式产出不同字段时，不应误合并 Transform 节点"""
    builder = GraphBuilder(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE agg
    SELECT
        ad_id,
        ROUND(SUM(is_click) * 100.0 / COUNT(*), 4) AS ctr,
        ROUND(SUM(is_click) * 100.0 / COUNT(*), 4) AS ctr2
    FROM dwd_ad_event
    GROUP BY ad_id
    """
    graph = builder.build_from_sql(sql, name="dedup")
    expr_nodes = [n for n in graph.nodes if n.node_type.value == "transform"]
    assert len(expr_nodes) == 2
    assert {n.output_name for n in expr_nodes} == {"ctr", "ctr2"}
    assert len({n.fingerprint for n in expr_nodes}) == 1


def test_expr_dag_same_logic_same_output_field_merged_across_sql():
    """相同表达式产出相同字段时，跨 SQL 自动合并 Transform 节点"""
    builder = GraphBuilder(dialect="spark")
    source = SqlSource.from_string(
        "INSERT OVERWRITE TABLE a SELECT SUM(is_click) AS c FROM dwd_ad_event",
        name="s1",
    )
    source.add_item(SqlSourceItem(
        name="s2",
        content="INSERT OVERWRITE TABLE b SELECT SUM(is_click) AS c FROM dwd_ad_event",
        source_type="string",
    ))
    graph = builder.build_from_source(source)
    expr_nodes = [n for n in graph.nodes if n.node_type.value == "transform" and n.op == "sum"]
    assert len(expr_nodes) == 1
    assert expr_nodes[0].output_name == "c"
    produces_edges = graph.get_edges_by_type(EdgeType.PRODUCES)
    assert sum(1 for e in produces_edges if e.source_id == expr_nodes[0].id) == 2


def test_composite_expression_single_node():
    """复合表达式整体作为一个节点，不再拆成子表达式"""
    builder = GraphBuilder(dialect="spark")
    graph = builder.build_from_sql(
        "INSERT OVERWRITE TABLE t SELECT ROUND(SUM(x) / COUNT(*), 4) AS r FROM e", name="single")
    expr_nodes = [n for n in graph.nodes if n.node_type.value == "transform"]
    assert len(expr_nodes) == 1
    # 不应再产生表达式内部的操作数边
    assert len(graph.get_edges_by_type(EdgeType.EXPR_OPERAND)) == 0
    # 表达式引用的物理列产生计算依赖边（x 一个来源列）
    assert len(graph.get_edges_by_type(EdgeType.COMPUTE_DEPENDENCY)) >= 1


def test_expr_dag_shared_across_sql():
    """跨 SQL 相同逻辑（SUM(dwd.is_click)）复用同一节点 id"""
    b1 = GraphBuilder(dialect="spark")
    g1 = b1.build_from_sql(
        "INSERT OVERWRITE TABLE a SELECT SUM(is_click) AS c FROM dwd_ad_event", name="s1")
    b2 = GraphBuilder(dialect="spark")
    g2 = b2.build_from_sql(
        "INSERT OVERWRITE TABLE b SELECT SUM(is_click) AS c FROM dwd_ad_event", name="s2")
    sum1 = [n.id for n in g1.nodes if n.node_type.value == "transform" and n.op == "sum"]
    sum2 = [n.id for n in g2.nodes if n.node_type.value == "transform" and n.op == "sum"]
    assert sum1 and sum1 == sum2


def test_expr_dag_distinct_physical_columns():
    """不同物理列来源的相同算子是不同节点"""
    builder = GraphBuilder(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE t
    SELECT
        TRY_CAST(impression.ad_id AS BIGINT) AS x,
        TRY_CAST(click.ad_id AS BIGINT) AS y
    FROM impression JOIN click ON impression.id = click.id
    """
    graph = builder.build_from_sql(sql, name="distinct")
    cast_nodes = [n for n in graph.nodes
                  if n.node_type.value == "transform" and n.op in ("trycast", "cast")]
    assert len(cast_nodes) == 2


def test_build_insert_union_all_lineage():
    """INSERT ... UNION ALL 应保留所有分支的源表和字段依赖"""
    builder = GraphBuilder(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE dst
    SELECT id FROM src_a
    UNION ALL
    SELECT user_id FROM src_b
    """
    graph = builder.build_from_sql(sql, name="union_test")
    table_names = {n.full_name for n in graph.nodes if n.node_type.value == "table"}
    assert {"src_a", "src_b", "dst"}.issubset(table_names)
    lineage_edges = graph.get_edges_by_type(EdgeType.TABLE_LINEAGE)
    lineage_pairs = {
        (graph.get_node(e.source_id).full_name, graph.get_node(e.target_id).full_name)
        for e in lineage_edges
    }
    assert ("src_a", "dst") in lineage_pairs
    assert ("src_b", "dst") in lineage_pairs
    deps = graph.get_edges_by_type(EdgeType.COMPUTE_DEPENDENCY)
    assert len(deps) == 2


def test_build_lateral_view_explode_lineage():
    """LATERAL VIEW explode 输出列应由 explode(items) Transform 产出"""
    builder = GraphBuilder(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE dst
    SELECT id, item
    FROM src
    LATERAL VIEW explode(items) t AS item
    """
    graph = builder.build_from_sql(sql, name="lateral_explode")
    transforms = [n for n in graph.nodes if n.node_type.value == "transform"]
    assert len(transforms) == 1
    assert transforms[0].expression == "EXPLODE(src.items)"
    assert transforms[0].output_name == "item"
    produces = graph.get_edges_by_type(EdgeType.PRODUCES)
    assert any(e.source_id == transforms[0].id for e in produces)


def test_build_lateral_view_output_inside_expression_uses_generator_source():
    """lateral 产出列进入表达式时，应依赖 generator 的真实源字段"""
    builder = GraphBuilder(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE dst
    SELECT concat(item, '_x') AS item_x
    FROM src
    LATERAL VIEW explode(items) t AS item
    """
    graph = builder.build_from_sql(sql, name="lateral_expr")
    columns = [n for n in graph.nodes if n.node_type.value == "column"]
    full_columns = {
        f"{graph.get_node(n.table_id).full_name}.{n.name}"
        for n in columns
    }
    assert "src.items" in full_columns
    assert "src.item" not in full_columns
    transforms = [n for n in graph.nodes if n.node_type.value == "transform"]
    assert len(transforms) == 1
    assert transforms[0].expression == "CONCAT(EXPLODE(src.items), '_x')"


def test_build_cte_columns_are_connected_across_subqueries():
    """CTE 输出字段应作为下游 CTE/最终查询的真实读取起点"""
    builder = GraphBuilder(dialect="spark")
    sql = """
    WITH base AS (
        SELECT id, payload, get_json_object(payload, '$.items') AS output_items_json
        FROM raw_log
    ), parsed AS (
        SELECT
            id,
            from_json(output_items_json, 'array<struct<Item:struct<id:string,type:struct<type:int>>>>') AS output_items
        FROM base
    )
    SELECT
        id,
        oi.Item.id AS item_id,
        oi.Item.type.type AS item_type
    FROM parsed
    LATERAL VIEW explode(output_items) e AS oi
    """
    graph = builder.build_from_sql(sql, name="cte_lateral")
    tables = [n for n in graph.nodes if n.node_type.value == "table"]
    table_names = {n.full_name for n in tables}
    table_by_alias = {
        alias: n
        for n in tables
        for alias in getattr(n, "aliases", [])
    }
    base_name = table_by_alias["base"].full_name
    parsed_name = table_by_alias["parsed"].full_name
    assert {"raw_log", "cte_lateral_result", base_name, parsed_name}.issubset(table_names)
    assert "UNKNOWN" not in table_names
    assert "Item" not in table_names
    assert "type" not in table_names

    columns = [n for n in graph.nodes if n.node_type.value == "column"]
    full_columns = {
        f"{graph.get_node(n.table_id).full_name}.{n.name}"
        for n in columns
    }
    assert {
        "raw_log.id",
        "raw_log.payload",
        f"{base_name}.id",
        f"{base_name}.output_items_json",
        f"{parsed_name}.id",
        f"{parsed_name}.output_items",
        "cte_lateral_result.id",
        "cte_lateral_result.item_id",
        "cte_lateral_result.item_type",
    }.issubset(full_columns)

    def col_id(full_name: str) -> str:
        table, column = full_name.rsplit(".", 1)
        return next(
            n.id for n in columns
            if n.name == column and graph.get_node(n.table_id).full_name == table
        )

    dep_pairs = {
        (e.source_id, e.target_id)
        for e in graph.get_edges_by_type(EdgeType.COMPUTE_DEPENDENCY)
    }
    assert (col_id("raw_log.id"), col_id(f"{base_name}.id")) in dep_pairs
    assert (col_id(f"{base_name}.id"), col_id(f"{parsed_name}.id")) in dep_pairs

    transforms = [n for n in graph.nodes if n.node_type.value == "transform"]
    item_id_transform = next(t for t in transforms if t.expression == f"EXPLODE({parsed_name}.output_items).Item.id")
    item_type_transform = next(t for t in transforms if t.expression == f"EXPLODE({parsed_name}.output_items).Item.type.type")
    produces_pairs = {
        (e.source_id, e.target_id)
        for e in graph.get_edges_by_type(EdgeType.PRODUCES)
    }
    assert (item_id_transform.id, col_id("cte_lateral_result.item_id")) in produces_pairs
    assert (item_type_transform.id, col_id("cte_lateral_result.item_type")) in produces_pairs


def test_build_duplicate_cte_logic_reuses_single_intermediate_table():
    builder = GraphBuilder(dialect="spark")
    sql = """
    WITH a AS (SELECT id, get_json_object(payload, '$.x') AS x FROM raw_log),
         b AS (SELECT id, get_json_object(payload, '$.x') AS x FROM raw_log)
    SELECT a.x AS ax, b.x AS bx
    FROM a JOIN b ON a.id = b.id
    """
    graph = builder.build_from_sql(sql, name="dup_cte")
    cte_tables = [n for n in graph.nodes if n.node_type.value == "table" and n.is_cte]
    assert len(cte_tables) == 1
    assert cte_tables[0].aliases == ["a", "b"]
    columns = [n for n in graph.nodes if n.node_type.value == "column"]
    cte_columns = {
        n.name for n in columns
        if n.table_id == cte_tables[0].id
    }
    assert cte_columns == {"id", "x"}
