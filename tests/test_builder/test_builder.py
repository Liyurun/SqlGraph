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
