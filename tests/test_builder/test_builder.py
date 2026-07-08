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
