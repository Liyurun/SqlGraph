# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Synthetic-data tests for Task 2: inventory and table-graph projection."""

from __future__ import annotations

from pathlib import Path

import pytest

from sqlgraph.analyze import (
    AssetCoverage,
    ExternalSchemaInventory,
    LineageAssetInventory,
    TableGraph,
    TableGraphEdge,
    build_lineage_inventory,
    build_table_graph,
    compute_coverage,
    load_analysis_view,
    load_external_schema_csv,
)
from sqlgraph.model import (
    ColumnNode,
    Edge,
    EdgeType,
    PropertyGraph,
    SqlNode,
    TableNode,
    TransformNode,
)


# ============================================================================
# Helpers
# ============================================================================


def _graph_to_dict(graph: PropertyGraph) -> dict:
    return load_analysis_view(graph).to_dict()


# ============================================================================
# LineageAssetInventory
# ============================================================================


def _chain_graph() -> PropertyGraph:
    """A → B → C  (3 tables, 3 columns each, 2 SQLs)."""
    g = PropertyGraph()
    for tid, name in [("ta", "A"), ("tb", "B"), ("tc", "C")]:
        g.add_node(TableNode(id=tid, name=name, schema_name="s"))
        for i in range(3):
            g.add_node(ColumnNode(id=f"{tid}_{i}", name=f"col{i}", table_id=tid))
            g.add_edge(Edge(id=f"hc_{tid}_{i}", source_id=tid, target_id=f"{tid}_{i}",
                            edge_type=EdgeType.HAS_COLUMN))
    for sid in ("s1", "s2"):
        g.add_node(SqlNode(id=sid, name="q"))
    g.add_edge(Edge("r1", "s1", "ta", EdgeType.READS_FROM))
    g.add_edge(Edge("w1", "s1", "tb", EdgeType.WRITES_TO))
    g.add_edge(Edge("r2", "s2", "tb", EdgeType.READS_FROM))
    g.add_edge(Edge("w2", "s2", "tc", EdgeType.WRITES_TO))
    return g


def test_lineage_inventory_counts_tables_and_columns():
    g = _chain_graph()
    view = load_analysis_view(g)
    inv = build_lineage_inventory(view)
    assert inv.table_count == 3
    assert inv.column_count == 9
    assert len(inv.table_ids) == 3
    assert len(inv.column_ids) == 9
    assert set(inv.table_full_names) == {"s.A", "s.B", "s.C"}


def test_lineage_inventory_produces_stable_output():
    g = _chain_graph()
    a = build_lineage_inventory(load_analysis_view(g))
    b = build_lineage_inventory(load_analysis_view(g))
    assert a.to_dict() == b.to_dict()


def test_lineage_inventory_is_serializable():
    inv = build_lineage_inventory(load_analysis_view(_chain_graph()))
    d = inv.to_dict()
    assert isinstance(d["table_ids"], list)
    assert d["table_count"] == 3


# ============================================================================
# ExternalSchemaInventory
# ============================================================================


def _write_csv(path: Path, rows: list[list[str]]) -> Path:
    import csv
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["table_name", "column_name", "data_type"])
        for r in rows:
            w.writerow(r)
    return path


def test_external_schema_loads_csv(tmp_path):
    csv_path = _write_csv(tmp_path / "s.csv", [
        ["db.A", "id", "bigint"],
        ["db.A", "name", "string"],
        ["db.B", "id", "bigint"],
        ["db.B", "val", "double"],
    ])
    inv = load_external_schema_csv(csv_path)
    assert inv.table_count == 2
    assert inv.column_count == 4
    assert inv.get_columns("db.A") == ("id", "name")
    assert inv.get_columns("db.B") == ("id", "val")
    assert inv.get_columns("db.C") is None
    assert len(inv.tables) == 2


def test_external_schema_defaults_data_type(tmp_path):
    csv_path = _write_csv(tmp_path / "s.csv", [
        ["t1", "c1", ""],
        ["t1", "c2", ""],
    ])
    inv = load_external_schema_csv(csv_path)
    entry = inv.tables[0]
    assert entry.columns[0].data_type == "string"


def test_external_schema_rejects_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("col_a,col_b\nv1,v2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        load_external_schema_csv(path)


def test_external_schema_rejects_empty_cell(tmp_path):
    csv_path = _write_csv(tmp_path / "s.csv", [
        ["t1", "c1", "string"],
        ["", "c2", "string"],
    ])
    with pytest.raises(ValueError, match="table_name is empty"):
        load_external_schema_csv(csv_path)


def test_external_schema_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_external_schema_csv(tmp_path / "no_such.csv")


def test_external_schema_stable_sort(tmp_path):
    csv_path = _write_csv(tmp_path / "s.csv", [
        ["z.z", "a", "int"],
        ["a.a", "b", "string"],
    ])
    inv = load_external_schema_csv(csv_path)
    names = [t.table_name for t in inv.tables]
    assert names == sorted(names)


def test_external_schema_to_dict(tmp_path):
    csv_path = _write_csv(tmp_path / "s.csv", [
        ["t1", "c1", "string"],
    ])
    inv = load_external_schema_csv(csv_path)
    d = inv.to_dict()
    assert d["table_count"] == 1
    assert d["tables"][0]["table_name"] == "t1"
    assert d["tables"][0]["columns"][0]["data_type"] == "string"


# ============================================================================
# AssetCoverage
# ============================================================================


def test_coverage_without_external_returns_none_for_external():
    g = _chain_graph()
    view = load_analysis_view(g)
    cov = compute_coverage(view, None)
    assert cov.lineage_table_count == 3
    assert cov.external_table_count is None
    assert cov.external_column_count is None
    assert cov.table_coverage_ratio is None


def test_coverage_with_external(tmp_path):
    g = _chain_graph()
    csv_path = _write_csv(tmp_path / "s.csv", [
        ["s.A", "col0", "int"],
        ["s.A", "col1", "int"],
        ["s.A", "col2", "int"],
        ["s.B", "col0", "int"],
        ["s.B", "col1", "int"],
        ["s.B", "colX", "int"],  # not in lineage
        ["s.C", "col0", "int"],
        ["s.D", "x", "int"],     # table not in lineage
    ])
    ext = load_external_schema_csv(csv_path)
    view = load_analysis_view(g)
    cov = compute_coverage(view, ext)

    assert cov.external_table_count == 4
    assert cov.external_column_count == 8
    assert cov.lineage_table_count == 3
    assert cov.covered_table_count == 3       # A, B, C
    assert cov.table_coverage_ratio == 0.75   # 3 / 4
    # Columns: A=3 covered, B=2, C=1, D=0 → 6 covered
    assert cov.covered_column_count == 6
    assert cov.column_coverage_ratio == 0.75  # 6 / 8


# ============================================================================
# TableGraph — chain
# ============================================================================


def test_table_graph_chain():
    """A → B → C with TABLE_LINEAGE edges and passthrough columns."""
    g = PropertyGraph()
    tables = {}
    for tid, name in [("ta", "A"), ("tb", "B"), ("tc", "C")]:
        tables[tid] = TableNode(id=tid, name=name, schema_name="s")
        g.add_node(tables[tid])
    for tn, tid in [("ta", "c0"), ("ta", "c1"), ("tb", "c2"), ("tb", "c3"),
                    ("tc", "c4"), ("tc", "c5")]:
        g.add_node(ColumnNode(id=f"{tn}_{tid}", name=tid, table_id=tn))
    # Passthrough: A.c0 → B.c2, B.c3 → C.c5
    g.add_edge(Edge("cd0", "ta_c0", "tb_c2", EdgeType.COMPUTE_DEPENDENCY))
    g.add_edge(Edge("cd1", "tb_c3", "tc_c5", EdgeType.COMPUTE_DEPENDENCY))
    # TABLE_LINEAGE
    g.add_edge(Edge("tl_a_b", "ta", "tb", EdgeType.TABLE_LINEAGE))
    g.add_edge(Edge("tl_b_c", "tb", "tc", EdgeType.TABLE_LINEAGE))

    view = load_analysis_view(g)
    tg = build_table_graph(view)

    assert tg.node_count == 3
    assert tg.edge_count == 2
    assert set(tg.nodes) == {"ta", "tb", "tc"}

    e_ab = tg.adjacency["ta"][0]
    assert e_ab.source_id == "ta"
    assert e_ab.target_id == "tb"
    assert e_ab.field_weight == 1  # A.c0 → B.c2

    e_bc = tg.adjacency["tb"][0]
    assert e_bc.source_id == "tb"
    assert e_bc.target_id == "tc"
    assert e_bc.field_weight == 1  # B.c3 → C.c5


# ============================================================================
# TableGraph — fan-in (many-to-one)
# ============================================================================


def test_table_graph_fan_in():
    """A → C, B → C (two source tables writing to one target)."""
    g = PropertyGraph()
    for tid, name in [("ta", "A"), ("tb", "B"), ("tc", "C")]:
        g.add_node(TableNode(id=tid, name=name, schema_name="s"))
    for cid in ("a_c0", "b_c0", "c_c0", "c_c1"):
        tid = "ta" if cid.startswith("a") else "tb" if cid.startswith("b") else "tc"
        g.add_node(ColumnNode(id=cid, name=cid.split("_", 1)[1], table_id=tid))
    g.add_edge(Edge("cd_ac", "a_c0", "c_c0", EdgeType.COMPUTE_DEPENDENCY))
    g.add_edge(Edge("cd_bc", "b_c0", "c_c1", EdgeType.COMPUTE_DEPENDENCY))
    g.add_edge(Edge("tl_ac", "ta", "tc", EdgeType.TABLE_LINEAGE))
    g.add_edge(Edge("tl_bc", "tb", "tc", EdgeType.TABLE_LINEAGE))

    view = load_analysis_view(g)
    tg = build_table_graph(view)

    assert tg.node_count == 3
    assert tg.edge_count == 2
    assert tg.in_degree["tc"] == 2
    assert tg.out_degree["ta"] == 1
    assert tg.out_degree["tb"] == 1
    assert tg.out_degree["tc"] == 0


# ============================================================================
# TableGraph — fan-out (one-to-many)
# ============================================================================


def test_table_graph_fan_out():
    """A → B, A → C (one source feeding two targets)."""
    g = PropertyGraph()
    for tid, name in [("ta", "A"), ("tb", "B"), ("tc", "C")]:
        g.add_node(TableNode(id=tid, name=name, schema_name="s"))
    for cid, pt in [("a0", "ta"), ("b0", "tb"), ("c0", "tc")]:
        g.add_node(ColumnNode(id=pt + "_" + cid, name="col", table_id=pt))
    g.add_edge(Edge("cd_ab", "ta_a0", "tb_b0", EdgeType.COMPUTE_DEPENDENCY))
    g.add_edge(Edge("cd_ac", "ta_a0", "tc_c0", EdgeType.COMPUTE_DEPENDENCY))
    g.add_edge(Edge("tl_ab", "ta", "tb", EdgeType.TABLE_LINEAGE))
    g.add_edge(Edge("tl_ac", "ta", "tc", EdgeType.TABLE_LINEAGE))

    view = load_analysis_view(g)
    tg = build_table_graph(view)

    assert tg.node_count == 3
    assert tg.edge_count == 2
    assert tg.out_degree["ta"] == 2


# ============================================================================
# TableGraph — cycle / self-loop exclusion
# ============================================================================


def test_table_graph_excludes_self_loop():
    """A → A self-loop in TABLE_LINEAGE is excluded."""
    g = PropertyGraph()
    g.add_node(TableNode(id="ta", name="A", schema_name="s"))
    g.add_node(ColumnNode(id="c0", name="c0", table_id="ta"))
    g.add_edge(Edge("self", "ta", "ta", EdgeType.TABLE_LINEAGE))

    view = load_analysis_view(g)
    tg = build_table_graph(view)
    assert tg.edge_count == 0


def test_table_graph_cycle_is_preserved():
    """A → B → A (mutual reference): graph preserves the cycle edges."""
    g = PropertyGraph()
    for tid, name in [("ta", "A"), ("tb", "B")]:
        g.add_node(TableNode(id=tid, name=name, schema_name="s"))
    g.add_edge(Edge("tl_ab", "ta", "tb", EdgeType.TABLE_LINEAGE))
    g.add_edge(Edge("tl_ba", "tb", "ta", EdgeType.TABLE_LINEAGE))

    view = load_analysis_view(g)
    tg = build_table_graph(view)
    assert tg.edge_count == 2
    # Graph has a 2-cycle
    assert tg.out_degree["ta"] == 1
    assert tg.out_degree["tb"] == 1
    assert tg.in_degree["ta"] == 1
    assert tg.in_degree["tb"] == 1


# ============================================================================
# TableGraph — CTE exclusion
# ============================================================================


def test_table_graph_excludes_cte_tables():
    """CTE tables (is_cte=True) are excluded from the projection."""
    g = PropertyGraph()
    g.add_node(TableNode(id="t_src", name="src", schema_name="s"))
    g.add_node(TableNode(id="t_cte", name="cte_tmp", schema_name="s", is_cte=True))
    g.add_node(TableNode(id="t_dst", name="dst", schema_name="s"))
    g.add_edge(Edge("tl_sc", "t_src", "t_cte", EdgeType.TABLE_LINEAGE))
    g.add_edge(Edge("tl_cd", "t_cte", "t_dst", EdgeType.TABLE_LINEAGE))

    view = load_analysis_view(g)
    tg = build_table_graph(view)

    assert tg.node_count == 2  # src, dst
    assert "t_cte" not in tg.nodes
    assert tg.edge_count == 0  # no edge directly between src→dst


# ============================================================================
# TableGraph — duplicate edges de-duplicated
# ============================================================================


def test_table_graph_deduplicates_table_lineage():
    """Two identical TABLE_LINEAGE edges → one row with field_weight=2."""
    g = PropertyGraph()
    for tid, name in [("ta", "A"), ("tb", "B")]:
        g.add_node(TableNode(id=tid, name=name, schema_name="s"))
    g.add_node(ColumnNode(id="ca", name="a", table_id="ta"))
    g.add_node(ColumnNode(id="cb", name="b", table_id="tb"))
    # Two passthrough edges between same tables
    g.add_edge(Edge("cd1", "ca", "cb", EdgeType.COMPUTE_DEPENDENCY))
    g.add_edge(Edge("cd2", "ca", "cb", EdgeType.COMPUTE_DEPENDENCY))
    # TABLE_LINEAGE (once)
    g.add_edge(Edge("tl", "ta", "tb", EdgeType.TABLE_LINEAGE))

    view = load_analysis_view(g)
    tg = build_table_graph(view)

    assert tg.edge_count == 1
    e = tg.edges[0]
    assert e.field_weight == 2  # two passthrough edges counted


# ============================================================================
# TableGraph — passthrough vs transform
# ============================================================================


def test_table_graph_passthrough_and_transform():
    """Both passthrough (col→col) and transform (col→tr→col) contribute."""
    g = PropertyGraph()
    for tid, name in [("ta", "A"), ("tb", "B")]:
        g.add_node(TableNode(id=tid, name=name, schema_name="s"))
    g.add_node(ColumnNode(id="ca_p", name="p", table_id="ta"))
    g.add_node(ColumnNode(id="cb_p", name="p", table_id="tb"))
    g.add_node(ColumnNode(id="ca_t", name="t_src", table_id="ta"))
    g.add_node(ColumnNode(id="cb_t", name="t_dst", table_id="tb"))
    g.add_node(TransformNode(id="tr1", expression="upper(t_src)", fingerprint="fp1"))
    # Passthrough
    g.add_edge(Edge("cd_p", "ca_p", "cb_p", EdgeType.COMPUTE_DEPENDENCY))
    # Transform
    g.add_edge(Edge("cd_in", "ca_t", "tr1", EdgeType.COMPUTE_DEPENDENCY))
    g.add_edge(Edge("prod_out", "tr1", "cb_t", EdgeType.PRODUCES))
    # TABLE_LINEAGE
    g.add_edge(Edge("tl", "ta", "tb", EdgeType.TABLE_LINEAGE))

    view = load_analysis_view(g)
    tg = build_table_graph(view)

    assert tg.edge_count == 1
    e = tg.edges[0]
    assert e.field_weight == 2  # 1 passthrough + 1 transform path


# ============================================================================
# TableGraph — SQL weight
# ============================================================================


def test_table_graph_sql_weight_from_reads_writes():
    """SQL weight counts independent SQLs, not TABLE_LINEAGE entries."""
    g = PropertyGraph()
    for tid, name in [("ta", "A"), ("tb", "B"), ("tc", "C")]:
        g.add_node(TableNode(id=tid, name=name, schema_name="s"))
    for sid in ("s1", "s2", "s3"):
        g.add_node(SqlNode(id=sid, name=sid))
    # s1: reads A, writes B
    # s2: reads A, writes B (same pair → weight=2)
    # s3: reads A, writes C
    g.add_edge(Edge("s1_r", "s1", "ta", EdgeType.READS_FROM))
    g.add_edge(Edge("s1_w", "s1", "tb", EdgeType.WRITES_TO))
    g.add_edge(Edge("s2_r", "s2", "ta", EdgeType.READS_FROM))
    g.add_edge(Edge("s2_w", "s2", "tb", EdgeType.WRITES_TO))
    g.add_edge(Edge("s3_r", "s3", "ta", EdgeType.READS_FROM))
    g.add_edge(Edge("s3_w", "s3", "tc", EdgeType.WRITES_TO))
    # TABLE_LINEAGE (one per pair)
    g.add_edge(Edge("tl_ab", "ta", "tb", EdgeType.TABLE_LINEAGE))
    g.add_edge(Edge("tl_ac", "ta", "tc", EdgeType.TABLE_LINEAGE))

    view = load_analysis_view(g)
    tg = build_table_graph(view)

    assert tg.edge_count == 2
    edges_by_key = {(e.source_id, e.target_id): e for e in tg.edges}

    ab = edges_by_key[("ta", "tb")]
    assert ab.sql_weight == 2  # s1 + s2

    ac = edges_by_key[("ta", "tc")]
    assert ac.sql_weight == 1  # s3


def test_table_graph_sql_weight_skips_cte():
    """READS_FROM/WRITES_TO targeting CTE tables are excluded from SQL weight."""
    g = PropertyGraph()
    g.add_node(TableNode(id="ta", name="A", schema_name="s"))
    g.add_node(TableNode(id="tb", name="B", schema_name="s"))
    g.add_node(TableNode(id="cte", name="CteTmp", schema_name="s", is_cte=True))
    for sid in ("s1", "s2"):
        g.add_node(SqlNode(id=sid, name=sid))
    g.add_edge(Edge("s1_r", "s1", "ta", EdgeType.READS_FROM))
    g.add_edge(Edge("s1_w", "s1", "cte", EdgeType.WRITES_TO, properties={}))
    g.add_edge(Edge("s2_r", "s2", "cte", EdgeType.READS_FROM))
    g.add_edge(Edge("s2_w", "s2", "tb", EdgeType.WRITES_TO, properties={}))
    g.add_edge(Edge("tl_ab", "ta", "tb", EdgeType.TABLE_LINEAGE))

    view = load_analysis_view(g)
    tg = build_table_graph(view)

    assert tg.edge_count == 1
    # sql_weight should NOT count s1 or s2 because CTE is excluded
    e = tg.edges[0]
    assert e.sql_weight == 0


# ============================================================================
# TableGraph — STRUCT/nested fields do not leak
# ============================================================================


def test_table_graph_struct_fields_not_leaked():
    """STRUCT sub-fields are not ColumnNode entities → cannot leak as top-level."""
    g = PropertyGraph()
    for tid, name in [("ta", "A"), ("tb", "B")]:
        g.add_node(TableNode(id=tid, name=name, schema_name="s"))
    # Only top-level columns — no struct sub-fields as ColumnNodes
    g.add_node(ColumnNode(id="ca", name="price_info", table_id="ta"))
    g.add_node(ColumnNode(id="cb", name="price_info", table_id="tb"))
    g.add_node(TransformNode(id="tr1", expression="price_info.amount", fingerprint="fp1"))
    g.add_edge(Edge("cd", "ca", "tr1", EdgeType.COMPUTE_DEPENDENCY))
    g.add_edge(Edge("prod", "tr1", "cb", EdgeType.PRODUCES))
    g.add_edge(Edge("tl", "ta", "tb", EdgeType.TABLE_LINEAGE))

    view = load_analysis_view(g)
    tg = build_table_graph(view)

    assert tg.edge_count == 1
    e = tg.edges[0]
    # We see 1 field_weight from the single top-level column dependency
    assert e.field_weight == 1


# ============================================================================
# TableGraph — stability / determinism
# ============================================================================


def test_table_graph_deterministic():
    g = _chain_graph()
    view = load_analysis_view(g)
    tg1 = build_table_graph(view)
    tg2 = build_table_graph(view)
    assert tg1.to_dict() == tg2.to_dict()
    assert tg1.nodes == tg2.nodes
    assert [e.source_id for e in tg1.edges] == [e.source_id for e in tg2.edges]


def test_table_graph_stable_sort():
    """Edges are sorted by (source_id, target_id)."""
    g = PropertyGraph()
    for tid in ("tz", "ta", "tm"):
        g.add_node(TableNode(id=tid, name=tid, schema_name="s"))
    g.add_edge(Edge("t2", "tz", "tm", EdgeType.TABLE_LINEAGE))
    g.add_edge(Edge("t1", "ta", "tm", EdgeType.TABLE_LINEAGE))
    g.add_edge(Edge("t3", "tz", "ta", EdgeType.TABLE_LINEAGE))

    view = load_analysis_view(g)
    tg = build_table_graph(view)

    keys = [(e.source_id, e.target_id) for e in tg.edges]
    assert keys == sorted(keys)


# ============================================================================
# TableGraph — original graph is never mutated
# ============================================================================


def test_table_graph_does_not_mutate_original():
    import copy
    g = _chain_graph()
    before = copy.deepcopy(g.to_dict())
    build_table_graph(load_analysis_view(g))
    after = g.to_dict()
    assert before == after


# ============================================================================
# TableGraph — edge cases: empty graph, no table_lineage
# ============================================================================


def test_table_graph_empty():
    g = PropertyGraph()
    g.add_node(SqlNode(id="s1", name="q"))
    view = load_analysis_view(g)
    tg = build_table_graph(view)
    assert tg.node_count == 0
    assert tg.edge_count == 0


def test_table_graph_no_lineage_edge_but_has_field_weight():
    """Field weight from compute_dependency can create edge even without TABLE_LINEAGE."""
    g = PropertyGraph()
    for tid, name in [("ta", "A"), ("tb", "B")]:
        g.add_node(TableNode(id=tid, name=name, schema_name="s"))
    g.add_node(ColumnNode(id="ca", name="a", table_id="ta"))
    g.add_node(ColumnNode(id="cb", name="b", table_id="tb"))
    g.add_edge(Edge("cd", "ca", "cb", EdgeType.COMPUTE_DEPENDENCY))
    # No TABLE_LINEAGE edge

    view = load_analysis_view(g)
    tg = build_table_graph(view)
    assert tg.edge_count == 1
    assert tg.edges[0].field_weight == 1


# ============================================================================
# TableGraph — multi-step passthrough (A→B, B→C in one graph)
# ============================================================================


def test_table_graph_multi_step():
    """A→B, B→C, A→C (direct + indirect)."""
    g = PropertyGraph()
    for tid, name in [("ta", "A"), ("tb", "B"), ("tc", "C")]:
        g.add_node(TableNode(id=tid, name=name, schema_name="s"))
    for tn, pt in [("a0", "ta"), ("b0", "tb"), ("b1", "tb"), ("c0", "tc")]:
        g.add_node(ColumnNode(id=pt + "_" + tn, name="col", table_id=pt))
    g.add_edge(Edge("cd_ab", "ta_a0", "tb_b0", EdgeType.COMPUTE_DEPENDENCY))
    g.add_edge(Edge("cd_bc", "tb_b1", "tc_c0", EdgeType.COMPUTE_DEPENDENCY))
    g.add_edge(Edge("cd_ac", "ta_a0", "tc_c0", EdgeType.COMPUTE_DEPENDENCY))
    g.add_edge(Edge("tl_ab", "ta", "tb", EdgeType.TABLE_LINEAGE))
    g.add_edge(Edge("tl_bc", "tb", "tc", EdgeType.TABLE_LINEAGE))
    g.add_edge(Edge("tl_ac", "ta", "tc", EdgeType.TABLE_LINEAGE))

    view = load_analysis_view(g)
    tg = build_table_graph(view)

    assert tg.edge_count == 3
    e_ab = tg.adjacency["ta"][0]
    assert e_ab.target_id == "tb"
    assert e_ab.field_weight == 1
    e_ac = tg.adjacency["ta"][1]
    assert e_ac.target_id == "tc"
    assert e_ac.field_weight == 1
    e_bc = tg.adjacency["tb"][0]
    assert e_bc.target_id == "tc"
    assert e_bc.field_weight == 1


# ============================================================================
# TableGraph — SQL dedup with reads + multiple writes
# ============================================================================


def test_table_graph_sql_multi_reads_multi_writes():
    """One SQL reads {A,B} and writes {C,D} → generates 4 edges."""
    g = PropertyGraph()
    for tid in ("ta", "tb", "tc", "td"):
        g.add_node(TableNode(id=tid, name=tid, schema_name="s"))
    g.add_node(SqlNode(id="s1", name="s1"))
    g.add_edge(Edge("r_a", "s1", "ta", EdgeType.READS_FROM))
    g.add_edge(Edge("r_b", "s1", "tb", EdgeType.READS_FROM))
    g.add_edge(Edge("w_c", "s1", "tc", EdgeType.WRITES_TO))
    g.add_edge(Edge("w_d", "s1", "td", EdgeType.WRITES_TO))

    view = load_analysis_view(g)
    tg = build_table_graph(view)

    # A→C, A→D, B→C, B→D = 4 edges, each sql_weight=1
    assert tg.edge_count == 4
    for e in tg.edges:
        assert e.sql_weight == 1


# ============================================================================
# Integration: inventory, table_graph, coverage
# ============================================================================


def test_integration_full_flow(tmp_path):
    """Synthetic 3-table graph: inventory → table_graph → coverage."""
    import csv

    g = PropertyGraph()
    for tid, name in [("t1", "ods_log"), ("t2", "dwd_order"), ("t3", "ads_report")]:
        g.add_node(TableNode(id=tid, name=name, schema_name="dw"))
    for tid in ("t1", "t2"):
        for i in range(2):
            cid = f"{tid}_c{i}"
            g.add_node(ColumnNode(id=cid, name=f"col{i}", table_id=tid))
    for i in range(4):
        cid = f"t3_c{i}"
        g.add_node(ColumnNode(id=cid, name=f"col{i}", table_id="t3"))

    g.add_node(SqlNode(id="s1", name="s1"))
    g.add_node(SqlNode(id="s2", name="s2"))
    g.add_edge(Edge("r1", "s1", "t1", EdgeType.READS_FROM))
    g.add_edge(Edge("w1", "s1", "t2", EdgeType.WRITES_TO))
    g.add_edge(Edge("r2", "s2", "t2", EdgeType.READS_FROM))
    g.add_edge(Edge("w2", "s2", "t3", EdgeType.WRITES_TO))
    g.add_edge(Edge("tl_12", "t1", "t2", EdgeType.TABLE_LINEAGE))
    g.add_edge(Edge("tl_23", "t2", "t3", EdgeType.TABLE_LINEAGE))

    view = load_analysis_view(g)

    # Inventory
    inv = build_lineage_inventory(view)
    assert inv.table_count == 3
    assert inv.column_count == 8      # 2+2+4

    # TableGraph
    tg = build_table_graph(view)
    assert tg.node_count == 3
    assert tg.edge_count == 2
    assert tg.edges[0].sql_weight == 1
    assert tg.edges[1].sql_weight == 1

    # External schema
    csv_path = tmp_path / "schema.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["table_name", "column_name", "data_type"])
        for r in [
            ["dw.ods_log", "col0", "string"],
            ["dw.ods_log", "col1", "string"],
            ["dw.ods_log", "col_extra", "int"],
            ["dw.dwd_order", "col0", "string"],
            ["dw.dwd_order", "col1", "string"],
            ["dw.ads_report", "col0", "string"],
            ["dw.ads_report", "col1", "string"],
            ["dw.ads_report", "col2", "string"],
            ["dw.ads_report", "col3", "string"],
            ["dw.unknown", "x", "string"],
        ]:
            w.writerow(r)

    ext = load_external_schema_csv(csv_path)
    cov = compute_coverage(view, ext)
    assert cov.external_table_count == 4
    assert cov.covered_table_count == 3
    assert cov.external_column_count == 10
    # covered: ods_log 2, dwd_order 2, ads_report 4 → 8
    assert cov.covered_column_count == 8
    assert cov.table_coverage_ratio == 0.75
