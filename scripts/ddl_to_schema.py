# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

# scripts/ddl_to_schema.py
"""离线预处理：把原始 DDL 供给（table_name,ddl）转换为轻量 schema CSV。

线上数仓导出的 schema 供给往往是整段原始 Hive 建表语句，体积大（几十 MB）、
不适合直接进版本库，也不能被 SchemaRegistry.from_csv 直接消费。本脚本一次性
把它解析成逐列展开的 `table_name,column_name,data_type`（几 MB，可提交、可人工
复核），后续 `sqlgraph build --schema` 直接吃这个产物即可。

用法：
    python3 scripts/ddl_to_schema.py examples/table_ddl.csv examples/schema_from_ddl.csv

解析逻辑复用 sqlgraph.input.ddl_schema（库内、可测试），本脚本只做 IO 与统计。
"""
from __future__ import annotations

import os
import sys
import csv
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlgraph.input.ddl_schema import parse_ddl_columns  # noqa: E402

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def convert(ddl_csv: str, out_csv: str) -> dict:
    """把 DDL 供给 CSV 转成轻量 schema CSV，返回统计信息。"""
    total = ok = failed = col_count = 0
    with open(ddl_csv, "r", encoding="utf-8") as fin, \
            open(out_csv, "w", encoding="utf-8", newline="") as fout:
        reader = csv.DictReader(fin)
        writer = csv.writer(fout)
        writer.writerow(["table_name", "column_name", "data_type"])
        for row in reader:
            total += 1
            ddl = (row.get("ddl") or "").strip()
            table, cols = parse_ddl_columns(ddl)
            if not table:
                table = (row.get("table_name") or "").strip().split(".")[-1]
            if not table or not cols:
                failed += 1
                continue
            ok += 1
            for cname, ctype in cols:
                writer.writerow([table, cname, ctype])
                col_count += 1
    return {
        "total_tables": total,
        "resolved_tables": ok,
        "failed_tables": failed,
        "coverage": (ok / total * 100) if total else 0.0,
        "total_columns": col_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert raw DDL CSV (table_name,ddl) into a lightweight "
                    "schema CSV (table_name,column_name,data_type)."
    )
    parser.add_argument("ddl_csv", help="输入：原始 DDL 供给 CSV，表头 table_name,ddl")
    parser.add_argument("out_csv", help="输出：轻量 schema CSV")
    args = parser.parse_args()

    if not os.path.isfile(args.ddl_csv):
        print(f"[error] input not found: {args.ddl_csv}", file=sys.stderr)
        return 1

    stats = convert(args.ddl_csv, args.out_csv)
    in_mb = os.path.getsize(args.ddl_csv) / 1024 / 1024
    out_mb = os.path.getsize(args.out_csv) / 1024 / 1024
    print("==== DDL -> schema 转换完成 ====")
    print(f"  输入表数     : {stats['total_tables']}")
    print(f"  成功解析     : {stats['resolved_tables']} ({stats['coverage']:.2f}%)")
    print(f"  未解析       : {stats['failed_tables']}")
    print(f"  展开列数     : {stats['total_columns']}")
    print(f"  体积         : {in_mb:.1f} MB -> {out_mb:.1f} MB")
    print(f"  产物         : {args.out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
