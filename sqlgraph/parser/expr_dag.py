# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

# sqlgraph/parser/expr_dag.py
"""
表达式指纹与依赖提取模块。

把一个 SQL SELECT 输出表达式整体作为**一个**逻辑节点，并计算内容指纹
（fingerprint）：

- 整条复合表达式（如 ROUND(SUM(clk)/COUNT(*),4)）是一个节点，不再拆成
  sum/div/round 等子节点；
- 相同逻辑（叶子绑定到相同物理列）跨 SQL 收敛为同一节点；
- 不同物理列来源的相同逻辑（如 SUM(a.x) vs SUM(b.x)）是不同节点；
- 交换律算子（+ * AND OR）的操作数排序后再算指纹，a+b 与 b+a 收敛；
- CAST 的目标类型、函数名、字面量等都纳入指纹，保证可无损区分。

指纹算法：对整棵表达式做一份拷贝，把其中所有列引用替换成"物理列串"（由
resolve_column 解析），对交换律算子的操作数排序，再用 sqlglot 的
normalize 序列化成规范字符串，最后 sha1 取指纹。表达式引用到的所有物理
列作为该节点的依赖来源（source_columns）。
"""
from __future__ import annotations
import hashlib
from sqlglot import exp


# 交换律算子的 sqlglot key，操作数排序后再算指纹
COMMUTATIVE_OPS = {"add", "mul", "and", "or"}
# 透明包裹节点：不单独成节点，直接下钻到内部表达式
_TRANSPARENT = (exp.Paren, exp.Ordered, exp.Alias)


def _fp(canonical: str) -> str:
    """由规范字符串计算内容指纹作为节点 id

    指纹长度取 32 个十六进制字符（128 bit）。在 160 万级字段/表达式规模下，
    64 bit 的碰撞概率已非绝对安全，128 bit 可将碰撞概率压到天文级别可忽略。
    """
    return "expr_" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:32]


def _depth(node) -> int:
    """节点在 AST 中的深度（用于自底向上处理交换律排序）"""
    d = 0
    p = node.parent
    while p is not None:
        d += 1
        p = p.parent
    return d


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


def _sort_commutative(root) -> None:
    """对交换律算子的两个操作数按序列化结果排序，实现 a+b == b+a 归一"""
    targets = [n for n in root.find_all(exp.Expression)
               if getattr(n, "key", None) in COMMUTATIVE_OPS
               and n.args.get("this") is not None
               and n.args.get("expression") is not None]
    if getattr(root, "key", None) in COMMUTATIVE_OPS and root not in targets \
            and root.args.get("this") is not None and root.args.get("expression") is not None:
        targets.append(root)
    # 深的先处理，保证外层比较时内层已归一
    targets.sort(key=_depth, reverse=True)
    for b in targets:
        left = b.args.get("this")
        right = b.args.get("expression")
        if left is None or right is None:
            continue
        if left.sql() > right.sql():
            lc, rc = left.copy(), right.copy()
            b.set("this", rc)
            b.set("expression", lc)


def _canonical(node, resolve_column, dialect) -> str:
    """规范字符串：物理列替换 + 交换律排序 + normalize 序列化"""
    copied = _prepare_copy(node, resolve_column)
    _sort_commutative(copied)
    return copied.sql(dialect=dialect, normalize=True, comments=False)


def _display(node, resolve_column, dialect) -> str:
    """展示字符串：物理列替换后的可读 SQL（不做交换律排序）"""
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
