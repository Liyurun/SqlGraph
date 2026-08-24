# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

# sqlgraph/parser/expr_dag.py
"""
表达式指纹与依赖提取模块。

把一个 SQL SELECT 输出表达式整体作为**一个**逻辑节点，并计算内容指纹
（fingerprint）：

- 整条复合表达式（如 ROUND(SUM(clk)/COUNT(*),4)）是一个节点，不再拆成
  sum/div/round 等子节点；
- 相同物理列表达式结构跨 SQL 收敛为同一节点；
- 不同物理列来源的相同逻辑（如 SUM(a.x) vs SUM(b.x)）是不同节点；
- CAST 的目标类型、函数名、字面量等都纳入指纹，保证可无损区分。

指纹算法：对整棵表达式做一份拷贝，把其中所有列引用替换成"物理列串"（由
resolve_column 解析），再用 sqlglot 的 normalize 序列化成规范字符串，
最后 sha1 取指纹。表达式引用到的所有物理列作为该节点的依赖来源
（source_columns）。这是保守指纹：只承诺物理列绑定后的同构表达式一致，
不做交换律、结合律、常量折叠等代数等价推理。
"""
from __future__ import annotations
import hashlib
from sqlglot import exp


def _fp(canonical: str) -> str:
    """由规范字符串计算内容指纹作为节点 id

    指纹长度取 32 个十六进制字符（128 bit）。在 160 万级字段/表达式规模下，
    64 bit 的碰撞概率已非绝对安全，128 bit 可将碰撞概率压到天文级别可忽略。
    """
    return "expr_" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:32]


def _prepare_copy(node, resolve_column):
    """拷贝子树并把其中所有列引用替换为物理列串（用 Var 承载，序列化稳定）"""
    copied = node.copy()
    for col in list(copied.find_all(exp.Column)):
        copied_is_root = col is copied
        replacement = exp.var(resolve_column(col))
        if copied_is_root:
            copied = replacement
        else:
            col.replace(replacement)
    return copied


def _canonical(node, resolve_column, dialect) -> str:
    """规范字符串：物理列替换 + SQLGlot normalize 序列化"""
    copied = _prepare_copy(node, resolve_column)
    return copied.sql(dialect=dialect, normalize=True, comments=False)


def _display(node, resolve_column, dialect) -> str:
    """展示字符串：物理列替换后的可读 SQL"""
    copied = _prepare_copy(node, resolve_column)
    return copied.sql(dialect=dialect)


def classify_expr_type(node) -> str:
    """把 sqlglot 节点分类到 ExpressionType 的字符串值"""
    if isinstance(node, exp.Column):
        return "column_ref"
    if isinstance(node, (exp.Literal, exp.Boolean, exp.Null)):
        return "literal"
    if isinstance(node, exp.Case):
        return "case_when"
    if isinstance(node, exp.Window):
        return "window"
    if isinstance(node, exp.AggFunc):
        return "agg"
    if isinstance(node, exp.Cast):
        return "cast"
    if isinstance(node, exp.Coalesce):
        return "coalesce"
    if isinstance(node, (exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.Nullif, exp.Round)):
        return "arithmetic"
    if isinstance(node, exp.Anonymous):
        return "function"
    if node.find(exp.AggFunc):
        return "agg"
    return "function"


def is_passthrough(unaliased_expr) -> bool:
    """是否为纯透传列（SELECT col / col AS alias），透传列不建表达式节点"""
    return isinstance(unaliased_expr, exp.Column)


def decompose(expr, resolve_column, dialect=None):
    """把一个表达式整体转成单个逻辑节点。

    整条复合表达式作为一个节点（不再拆成子表达式），指纹由归一化后的
    物理列表达式字符串计算，表达式引用的所有物理列作为依赖来源。

    Args:
        expr: sqlglot 表达式节点（应已 unalias）
        resolve_column: 可调用对象，输入 exp.Column，返回物理列串 "db.tbl.col"
        dialect: SQL 方言，用于稳定序列化

    Returns:
        (root_fp, nodes)
        - root_fp: 表达式节点指纹
        - nodes: {fp: {fingerprint, op, expr_type, expression, canonical, source_columns}}
          （固定只含一个节点，保持与调用方一致的返回结构）
    """
    canonical = _canonical(expr, resolve_column, dialect)
    fp = _fp(canonical)
    # 收集表达式引用到的所有物理列，作为该节点的计算依赖来源
    source_columns = []
    seen = set()
    if isinstance(expr, exp.Column):
        cols = [expr]
    else:
        cols = list(expr.find_all(exp.Column))
    for col in cols:
        phys = resolve_column(col)
        if phys not in seen:
            seen.add(phys)
            source_columns.append(phys)
    nodes = {
        fp: {
            "fingerprint": fp,
            "op": getattr(expr, "key", "expr"),
            "expr_type": classify_expr_type(expr),
            "expression": _display(expr, resolve_column, dialect),
            "canonical": canonical,
            "source_columns": source_columns,
        }
    }
    return fp, nodes


_TRANSPARENT = (exp.Paren, exp.Ordered, exp.Alias)
_DECOMPOSABLE = (
    exp.Add,
    exp.Sub,
    exp.Mul,
    exp.Div,
    exp.Mod,
    exp.Case,
    exp.Coalesce,
    exp.Cast,
    exp.Round,
    exp.And,
    exp.Or,
    exp.AggFunc,
    exp.Anonymous,
    exp.Func,
)


def decompose_operands(expr, resolve_column, dialect=None):
    """Describe nested expression nodes as child-to-parent operand edges.

    The root fingerprint remains the conservative fingerprint produced by
    :func:`decompose`. No algebraic equivalence rules are introduced.
    """
    root_fp, _ = decompose(expr, resolve_column, dialect)
    nodes: dict[str, dict] = {}
    edges: list[tuple[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()

    def register(node) -> str:
        canonical = _canonical(node, resolve_column, dialect)
        fingerprint = _fp(canonical)
        if fingerprint not in nodes:
            columns = (
                [node]
                if isinstance(node, exp.Column)
                else list(node.find_all(exp.Column))
            )
            source_columns = []
            seen_columns = set()
            for column in columns:
                physical = resolve_column(column)
                if physical not in seen_columns:
                    seen_columns.add(physical)
                    source_columns.append(physical)
            nodes[fingerprint] = {
                "fingerprint": fingerprint,
                "op": getattr(node, "key", "expr"),
                "expr_type": classify_expr_type(node),
                "expression": _display(node, resolve_column, dialect),
                "canonical": canonical,
                "source_columns": source_columns,
            }
        return fingerprint

    def walk(node, parent_fingerprint: str) -> None:
        while isinstance(node, _TRANSPARENT):
            inner = node.args.get("this")
            if inner is None:
                return
            node = inner
        if not isinstance(node, _DECOMPOSABLE):
            return
        fingerprint = register(node)
        edge = (fingerprint, parent_fingerprint)
        if fingerprint != parent_fingerprint and edge not in seen_edges:
            seen_edges.add(edge)
            edges.append(edge)
        for child in node.iter_expressions():
            walk(child, fingerprint)

    register(expr)
    for child in expr.iter_expressions():
        walk(child, root_fp)
    return root_fp, nodes, edges
