import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from sqlgraph.parser.base import SqlParser


def test_parse_simple_select():
    parser = SqlParser(dialect="spark")
    result = parser.parse("SELECT id, name FROM users", name="q1")
    assert len(result.source_tables) >= 1
    table_names = [t["name"] for t in result.source_tables]
    assert "users" in table_names


def test_parse_insert_overwrite():
    parser = SqlParser(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE dws_ad_daily
    SELECT ad_id, dt, COUNT(*) as imp_count
    FROM stg_impressions
    GROUP BY ad_id, dt
    """
    result = parser.parse(sql, name="daily_agg")
    assert len(result.target_tables) == 1
    assert result.target_tables[0]["name"] == "dws_ad_daily"
    assert any(t["name"] == "stg_impressions" for t in result.source_tables)


def test_parse_cte():
    parser = SqlParser(dialect="spark")
    sql = """
    WITH base AS (
        SELECT user_id, ad_id FROM imp
    )
    SELECT * FROM base
    """
    result = parser.parse(sql, name="cte_test")
    assert len(result.cte_tables) >= 1
    assert any(t["name"] == "base" and t["is_cte"] for t in result.cte_tables)


def test_parse_case_when():
    parser = SqlParser(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE result
    SELECT
        id,
        CASE WHEN age > 18 THEN 'adult' ELSE 'minor' END as age_group
    FROM users
    """
    result = parser.parse(sql, name="case_test")
    case_cols = [c for c in result.columns if c["transform_type"] == "case_when"]
    assert len(case_cols) >= 1


def test_parse_aggregation():
    parser = SqlParser(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE agg_table
    SELECT ad_id, SUM(imp) as imp_sum, MAX(price) as max_price, COUNT(*) as cnt
    FROM events
    GROUP BY ad_id
    """
    result = parser.parse(sql, name="agg_test")
    agg_cols = [c for c in result.columns if c["transform_type"] == "agg"]
    assert len(agg_cols) >= 2


def test_parse_coalesce():
    parser = SqlParser(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE cleaned
    SELECT id, COALESCE(name, 'unknown') as name
    FROM raw
    """
    result = parser.parse(sql, name="coalesce_test")
    coalesce_cols = [c for c in result.columns if c["transform_type"] == "coalesce"]
    assert len(coalesce_cols) >= 1


def test_parse_cast_and_arithmetic():
    parser = SqlParser(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE metrics
    SELECT
        ad_id,
        CAST(clicks AS DOUBLE) / NULLIF(imps, 0) as ctr,
        ROUND(clicks * 100.0 / imps, 4) as ctr_pct
    FROM daily
    """
    result = parser.parse(sql, name="arith_test")
    assert len(result.columns) >= 3


def test_parse_multiple_sources():
    parser = SqlParser(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE joined
    SELECT a.id, b.name
    FROM table_a a
    JOIN table_b b ON a.id = b.id
    """
    result = parser.parse(sql, name="join_test")
    names = [t["name"] for t in result.source_tables]
    assert "table_a" in names
    assert "table_b" in names
