# sqlGraph

一个面向 SQL 血缘和数据资产关系的轻量级图构建与召回框架。

## 安装

```bash
pip install sqlgraph-lineage
```

## 快速开始

```python
from sqlgraph import build_graph, visualize

graph = build_graph("examples/ads_pipeline/", dialect="spark")
visualize.to_html(graph, "lineage.html")
```

## CLI

```bash
sqlgraph demo  # 运行示例并打开浏览器
sqlgraph build sql/ --format html,csv -o ./output
```
