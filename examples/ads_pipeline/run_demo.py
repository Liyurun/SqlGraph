#!/usr/bin/env python3
# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

"""一键运行 AdTech 示例：解析所有 SQL 并生成可视化 HTML"""
import os
import sys
import webbrowser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlgraph import build_graph
from sqlgraph.visualize import to_html

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(os.path.dirname(DEMO_DIR), '..', 'demo_output')


def main():
    print("=" * 60, flush=True)
    print("  SqlGraph AdTech Demo - Ad pipeline lineage", flush=True)
    print("=" * 60, flush=True)
    schema_path = os.path.join(DEMO_DIR, 'schema.csv')
    if not os.path.isfile(schema_path):
        schema_path = None
    print(f"\n[1/3] 解析 SQL 文件: {DEMO_DIR}/", flush=True)
    graph = build_graph(DEMO_DIR, dialect='spark', schema_path=schema_path)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html_path = os.path.join(OUTPUT_DIR, 'lineage.html')
    print(f"\n[2/3] 生成可视化: {html_path}", flush=True)
    to_html(
        graph,
        output_path=html_path,
        view='table',
        theme='light',
        title='SqlGraph',
        auto_open=False,
    )
    abs_path = os.path.abspath(html_path)
    print(f"\n[3/3] 完成！请在浏览器中打开:", flush=True)
    print(f"  file://{abs_path}", flush=True)
    print("=" * 60, flush=True)
    webbrowser.open('file://' + abs_path)


if __name__ == '__main__':
    main()
