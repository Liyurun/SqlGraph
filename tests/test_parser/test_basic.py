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
    assert any(t["alias"] == "base" and t["is_cte"] for t in result.cte_tables)


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


def test_parse_insert_union_all_sources_and_columns():
    parser = SqlParser(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE dst
    SELECT id FROM src_a
    UNION ALL
    SELECT user_id FROM src_b
    """
    result = parser.parse(sql, name="union_test")
    names = {t["name"] for t in result.source_tables}
    assert {"src_a", "src_b"}.issubset(names)
    assert result.target_tables[0]["name"] == "dst"
    # UNION 的输出字段名来自左侧查询，第二个分支也应落到 dst.id
    assert [c["name"] for c in result.columns] == ["id", "id"]
    assert {c["physical_column"] for c in result.columns} == {"src_a.id", "src_b.user_id"}


def test_parse_lateral_view_explode_as_transform():
    parser = SqlParser(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE dst
    SELECT id, item
    FROM src
    LATERAL VIEW explode(items) t AS item
    """
    result = parser.parse(sql, name="lateral_explode")
    item_cols = [c for c in result.columns if c["name"] == "item"]
    assert len(item_cols) == 1
    assert item_cols[0]["passthrough"] is False
    root = item_cols[0]["expr_root"]
    assert root
    assert item_cols[0]["expr_nodes"][root]["expression"] == "EXPLODE(src.items)"


def test_parse_lateral_view_posexplode_outputs():
    parser = SqlParser(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE dst
    SELECT id, pos, item
    FROM src
    LATERAL VIEW posexplode(items) t AS pos, item
    """
    result = parser.parse(sql, name="lateral_posexplode")
    generated = [c for c in result.columns if c["name"] in {"pos", "item"}]
    assert len(generated) == 2
    assert all(not c["passthrough"] for c in generated)
    expressions = {
        c["expr_nodes"][c["expr_root"]]["expression"]
        for c in generated
    }
    assert expressions == {"POSEXPLODE(src.items)"}


def test_parse_lateral_view_output_inside_expression():
    """引用 lateral 产出列的表达式不应误解析成源表物理字段 src.item"""
    parser = SqlParser(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE dst
    SELECT concat(item, '_x') AS item_x
    FROM src
    LATERAL VIEW explode(items) t AS item
    """
    result = parser.parse(sql, name="lateral_expr")
    item_x = next(c for c in result.columns if c["name"] == "item_x")
    root = item_x["expr_root"]
    assert item_x["source_columns"] == ["src.items"]
    assert item_x["expr_nodes"][root]["source_columns"] == ["src.items"]
    assert item_x["expr_nodes"][root]["expression"] == "CONCAT(EXPLODE(src.items), '_x')"


def test_parse_chained_lateral_view_uses_previous_generator_source():
    """串联 lateral view 时，后一个 generator 应展开前一个 lateral 产出列"""
    parser = SqlParser(dialect="spark")
    sql = """
    INSERT OVERWRITE TABLE dst
    SELECT item
    FROM src
    LATERAL VIEW explode(arrays) a AS arr
    LATERAL VIEW explode(arr) b AS item
    """
    result = parser.parse(sql, name="chained_lateral")
    item = next(c for c in result.columns if c["name"] == "item")
    root = item["expr_root"]
    assert item["source_columns"] == ["src.arrays"]
    assert item["expr_nodes"][root]["source_columns"] == ["src.arrays"]
    assert item["expr_nodes"][root]["expression"] == "EXPLODE(EXPLODE(src.arrays))"


def test_parse_cte_scope_and_lateral_struct_access():
    """CTE 下游读取应绑定到 CTE 字段，lateral struct 访问不应生成假表"""
    parser = SqlParser(dialect="spark")
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
    result = parser.parse(sql, name="cte_lateral")
    cte_by_alias = {t["alias"]: t["name"] for t in result.cte_tables}
    base_name = cte_by_alias["base"]
    parsed_name = cte_by_alias["parsed"]
    assert set(cte_by_alias) == {"base", "parsed"}
    assert {"raw_log", base_name, parsed_name} == {t["name"] for t in result.source_tables}

    final_id = next(c for c in result.columns if c["table"] is None and c["name"] == "id")
    assert final_id["physical_column"] == f"{parsed_name}.id"

    item_id = next(c for c in result.columns if c["name"] == "item_id")
    item_type = next(c for c in result.columns if c["name"] == "item_type")
    assert item_id["source_columns"] == [f"{parsed_name}.output_items"]
    assert item_type["source_columns"] == [f"{parsed_name}.output_items"]
    assert item_id["expr_nodes"][item_id["expr_root"]]["expression"] == f"EXPLODE({parsed_name}.output_items).Item.id"
    assert item_type["expr_nodes"][item_type["expr_root"]]["expression"] == f"EXPLODE({parsed_name}.output_items).Item.type.type"


def test_parse_duplicate_cte_logic_merges_by_fingerprint():
    parser = SqlParser(dialect="spark")
    sql = """
    WITH a AS (SELECT id, get_json_object(payload, '$.x') AS x FROM raw_log),
         b AS (SELECT id, get_json_object(payload, '$.x') AS x FROM raw_log)
    SELECT a.x AS ax, b.x AS bx
    FROM a JOIN b ON a.id = b.id
    """
    result = parser.parse(sql, name="dup_cte")
    cte_names = {t["name"] for t in result.cte_tables}
    assert len(cte_names) == 1
    assert {t["alias"] for t in result.cte_tables} == {"a", "b"}
    logical_name = next(iter(cte_names))
    assert {
        c["physical_column"]
        for c in result.columns
        if c["name"] in {"ax", "bx"}
    } == {f"{logical_name}.x"}
