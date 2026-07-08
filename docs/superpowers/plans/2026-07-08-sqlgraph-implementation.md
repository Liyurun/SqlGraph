# sqlGraph 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 sqlGraph 开源项目——一个面向 SQL 血缘和数据资产关系的轻量级图构建与召回框架，支持从 SQL/CSV/DataFrame 构建 property graph，输出精美交互式 HTML 可视化，并适配 GraphRAG 等后端。

**Architecture:** 分层流水线架构：Input → Parser → Builder → Model → Serialize/Visualize。核心只构建内存中的 PropertyGraph 对象，写入完全解耦。使用 SQLGlot 做 SQL 解析，Cytoscape.js 做可视化，Typer 做 CLI，Poetry 做包管理。所有源文件带详细中文注释，使用 print(..., flush=True) 做实时日志。

**Tech Stack:** Python 3.9+, sqlglot, pandas, typer, jinja2, rich, pytest (dev), networkx (optional)

---

## Task 0: 项目初始化（Poetry + 目录骨架）

**Files:**
- Create: `pyproject.toml`
- Create: `sqlgraph/__init__.py`
- Create all package `__init__.py` files
- Create: `tests/__init__.py`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[tool.poetry]
name = "sqlgraph-lineage"
version = "0.1.0"
description = "A lightweight SQL lineage and data asset graph construction framework"
authors = ["sqlgraph contributors"]
license = "Apache-2.0"
readme = "README.md"
packages = [{include = "sqlgraph"}]

[tool.poetry.dependencies]
python = "^3.9"
sqlglot = ">=25.0.0"
pandas = ">=2.0.0"
typer = ">=0.9.0"
jinja2 = ">=3.1.0"
rich = ">=13.0.0"
networkx = {version = ">=3.0", optional = true}
ipython = {version = ">=8.0", optional = true}

[tool.poetry.group.dev.dependencies]
pytest = ">=7.0.0"
pytest-cov = ">=4.0.0"

[tool.poetry.extras]
notebook = ["ipython"]
graph = ["networkx"]
all = ["networkx", "ipython"]

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
python_classes = "Test*"
python_functions = "test_*"
```

- [ ] **Step 2: 创建目录结构和所有 __init__.py**

```bash
mkdir -p sqlgraph/{model,input,parser,builder,serialize,visualize/templates,utils}
mkdir -p tests/{test_model,test_input,test_parser,test_builder,test_serialize,test_visualize,test_integration}
mkdir -p examples/ads_pipeline
```

Create empty `__init__.py` in each package directory:
- `sqlgraph/__init__.py`
- `sqlgraph/model/__init__.py`
- `sqlgraph/input/__init__.py`
- `sqlgraph/parser/__init__.py`
- `sqlgraph/builder/__init__.py`
- `sqlgraph/serialize/__init__.py`
- `sqlgraph/visualize/__init__.py`
- `sqlgraph/utils/__init__.py`
- `tests/__init__.py`

- [ ] **Step 3: 创建 README.md 占位**

```markdown
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
```

- [ ] **Step 4: 安装依赖并验证环境**

Run: `cd /Users/bytedance/Documents/trae_projects/sql_graph && poetry install`
Expected: 成功安装所有依赖

- [ ] **Step 5: 验证 pytest 可用**

Run: `poetry run pytest --version`
Expected: `pytest 7.x.x` 或更高版本

- [ ] **Step 6: 提交初始化代码**

```bash
git add pyproject.toml README.md sqlgraph/ tests/
git commit -m "feat: initialize project with Poetry and directory structure"
```

---

## Task 1: 错误类型体系（utils/errors.py）

**Files:**
- Create: `sqlgraph/utils/errors.py`
- Create: `tests/test_utils/test_errors.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_utils/test_errors.py
import pytest
from sqlgraph.utils.errors import (
    SqlGraphError,
    SqlParseError,
    SchemaNotFoundError,
    AmbiguousColumnError,
    CircularDependencyError,
    InputError,
)


def test_sql_parse_error_is_sqlgraph_error():
    err = SqlParseError("test message", sql="SELECT 1", file_path="test.sql")
    assert isinstance(err, SqlGraphError)
    assert str(err) == "test message"
    assert err.sql == "SELECT 1"
    assert err.file_path == "test.sql"


def test_ambiguous_column_error_has_candidates():
    err = AmbiguousColumnError("user_id", candidates=["ods_a.user_id", "ods_b.user_id"])
    assert err.column_name == "user_id"
    assert len(err.candidates) == 2


def test_circular_dependency_error_has_chain():
    err = CircularDependencyError(["table_a", "table_b", "table_a"])
    assert "table_a" in err.chain
```

- [ ] **Step 2: 运行测试确认失败**

Run: `poetry run pytest tests/test_utils/test_errors.py -v`
Expected: FAIL (ImportError - module not found)

- [ ] **Step 3: 实现 errors.py**

```python
# sqlgraph/utils/errors.py


class SqlGraphError(Exception):
    """sqlGraph 基础异常类"""
    pass


class SqlParseError(SqlGraphError):
    """SQL 解析失败异常"""

    def __init__(self, message: str, sql: str | None = None, file_path: str | None = None):
        super().__init__(message)
        self.sql = sql
        self.file_path = file_path


class SchemaNotFoundError(SqlGraphError):
    """表 Schema 未找到异常"""

    def __init__(self, table_name: str):
        super().__init__(f"Schema not found for table: {table_name}")
        self.table_name = table_name


class AmbiguousColumnError(SqlGraphError):
    """字段引用歧义异常"""

    def __init__(self, column_name: str, candidates: list[str]):
        super().__init__(
            f"Ambiguous column '{column_name}', candidates: {candidates}"
        )
        self.column_name = column_name
        self.candidates = candidates


class CircularDependencyError(SqlGraphError):
    """循环依赖异常"""

    def __init__(self, chain: list[str]):
        super().__init__(f"Circular dependency detected: {' -> '.join(chain)}")
        self.chain = chain


class InputError(SqlGraphError):
    """输入错误（配置问题，立即失败）"""
    pass
```

- [ ] **Step 4: 运行测试确认通过**

Run: `poetry run pytest tests/test_utils/test_errors.py -v`
Expected: 3 tests passed

- [ ] **Step 5: 提交**

```bash
git add sqlgraph/utils/errors.py tests/test_utils/test_errors.py
git commit -m "feat: add error type hierarchy"
```

---

## Task 2: 日志工具（utils/logging.py）

**Files:**
- Create: `sqlgraph/utils/logging.py`
- Create: `tests/test_utils/test_logging.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_utils/test_logging.py
from sqlgraph.utils.logging import log_info, log_warn, log_error, log_progress, reset_progress


def test_log_info(capsys):
    log_info("test message")
    captured = capsys.readouterr()
    assert "test message" in captured.out
    assert "[INFO]" in captured.out


def test_log_warn(capsys):
    log_warn("warning message")
    captured = capsys.readouterr()
    assert "warning message" in captured.out
    assert "[WARN]" in captured.out


def test_log_error(capsys):
    log_error("error message")
    captured = capsys.readouterr()
    assert "error message" in captured.out
    assert "[ERROR]" in captured.out


def test_log_progress(capsys):
    reset_progress()
    log_progress(3, 10, prefix="Parsing")
    captured = capsys.readouterr()
    assert "Parsing" in captured.out
    assert "3/10" in captured.out
```

- [ ] **Step 2: 运行测试确认失败**

Run: `poetry run pytest tests/test_utils/test_logging.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 logging.py**

```python
# sqlgraph/utils/logging.py
import sys
from datetime import datetime


def _print(level: str, message: str) -> None:
    """带时间戳和级别的实时日志输出"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}", file=sys.stdout, flush=True)


def log_info(message: str) -> None:
    """输出 INFO 级别日志"""
    _print("INFO", message)


def log_warn(message: str) -> None:
    """输出 WARN 级别日志"""
    _print("WARN", message)


def log_error(message: str) -> None:
    """输出 ERROR 级别日志"""
    _print("ERROR", message)


def log_progress(current: int, total: int, prefix: str = "Processing") -> None:
    """输出进度日志（覆盖当前行）"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    pct = (current / total * 100) if total > 0 else 0
    bar_len = 30
    filled = int(bar_len * current / total) if total > 0 else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    line = f"[{timestamp}] [{prefix}] |{bar}| {current}/{total} ({pct:.1f}%)"
    print(f"\r{line}", end="", file=sys.stdout, flush=True)
    if current >= total:
        print(file=sys.stdout, flush=True)


def reset_progress() -> None:
    """重置进度条状态（无需调用，保留接口一致性）"""
    pass


def log_stats(stats: dict) -> None:
    """输出统计信息"""
    _print("STATS", "=" * 50)
    for key, value in stats.items():
        _print("STATS", f"  {key}: {value}")
    _print("STATS", "=" * 50)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `poetry run pytest tests/test_utils/test_logging.py -v`
Expected: 4 tests passed

- [ ] **Step 5: 提交**

```bash
git add sqlgraph/utils/logging.py tests/test_utils/test_logging.py
git commit -m "feat: add real-time flush logging utilities"
```

---

## Task 3: 数据模型 - 节点类型（model/nodes.py）

**Files:**
- Create: `sqlgraph/model/nodes.py`
- Create: `tests/test_model/test_nodes.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_model/test_nodes.py
from sqlgraph.model.nodes import (
    SqlNode, TableNode, ColumnNode, TransformNode, NodeType, ExpressionType
)


def test_sql_node_creation():
    node = SqlNode(
        id="sql_001",
        name="01_stg_impressions",
        file_path="01_stg_impressions.sql",
        sql_content="INSERT OVERWRITE TABLE stg_imp SELECT ...",
        dialect="spark",
    )
    assert node.id == "sql_001"
    assert node.node_type == NodeType.SQL
    assert node.dialect == "spark"


def test_table_node_creation():
    node = TableNode(
        id="tbl_001",
        name="stg_impressions",
        is_cte=False,
    )
    assert node.node_type == NodeType.TABLE
    assert node.is_cte is False
    assert node.catalog is None
    assert node.schema is None


def test_column_node_creation():
    node = ColumnNode(
        id="col_001",
        name="imp_count",
        table_id="tbl_002",
        data_type="bigint",
    )
    assert node.node_type == NodeType.COLUMN
    assert node.data_type == "bigint"
    assert node.is_primary_key is False


def test_transform_node_creation():
    node = TransformNode(
        id="tr_001",
        expression="SUM(imp_flag)",
        expression_type=ExpressionType.AGG,
    )
    assert node.node_type == NodeType.TRANSFORM
    assert node.expression_type == ExpressionType.AGG


def test_node_to_dict():
    node = SqlNode(id="s1", name="test", dialect="spark")
    d = node.to_dict()
    assert d["id"] == "s1"
    assert d["node_type"] == "sql"
    assert d["dialect"] == "spark"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `poetry run pytest tests/test_model/test_nodes.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 nodes.py**

```python
# sqlgraph/model/nodes.py
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    """节点类型枚举"""
    SQL = "sql"
    TABLE = "table"
    COLUMN = "column"
    TRANSFORM = "transform"


class ExpressionType(str, Enum):
    """Transform 表达式类型枚举"""
    CASE_WHEN = "case_when"
    AGG = "agg"
    CAST = "cast"
    ARITHMETIC = "arithmetic"
    COALESCE = "coalesce"
    WINDOW = "window"
    UNION = "union"
    LITERAL = "literal"
    COLUMN_REF = "column_ref"
    FUNCTION = "function"


@dataclass
class BaseNode:
    """节点基类"""
    id: str
    name: str
    node_type: NodeType = field(init=False)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        d = asdict(self)
        d["node_type"] = self.node_type.value
        if "node_type" in d:
            del d["node_type"]
        return d


@dataclass
class SqlNode(BaseNode):
    """SQL 任务/文件节点"""
    file_path: str | None = None
    sql_content: str | None = None
    dialect: str | None = None
    created_at: str | None = None

    def __post_init__(self):
        self.node_type = NodeType.SQL


@dataclass
class TableNode(BaseNode):
    """物理表或 CTE 节点"""
    catalog: str | None = None
    schema_name: str | None = None
    is_cte: bool = False
    columns: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.node_type = NodeType.TABLE

    @property
    def full_name(self) -> str:
        """获取完整表名（catalog.schema.name）"""
        parts = []
        if self.catalog:
            parts.append(self.catalog)
        if self.schema_name:
            parts.append(self.schema_name)
        parts.append(self.name)
        return ".".join(parts)


@dataclass
class ColumnNode(BaseNode):
    """字段节点"""
    table_id: str | None = None
    data_type: str | None = None
    is_primary_key: bool = False

    def __post_init__(self):
        self.node_type = NodeType.COLUMN


@dataclass
class TransformNode(BaseNode):
    """字段计算表达式节点"""
    expression: str = ""
    expression_type: ExpressionType = ExpressionType.FUNCTION

    def __post_init__(self):
        self.node_type = NodeType.TRANSFORM

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["expression_type"] = self.expression_type.value
        return d
```

- [ ] **Step 4: 运行测试确认通过**

Run: `poetry run pytest tests/test_model/test_nodes.py -v`
Expected: 5 tests passed

- [ ] **Step 5: 提交**

```bash
git add sqlgraph/model/nodes.py tests/test_model/test_nodes.py
git commit -m "feat: add node types (SqlNode, TableNode, ColumnNode, TransformNode)"
```

---

## Task 4: 数据模型 - 边类型（model/edges.py）

**Files:**
- Create: `sqlgraph/model/edges.py`
- Create: `tests/test_model/test_edges.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_model/test_edges.py
from sqlgraph.model.edges import Edge, EdgeType


def test_edge_creation():
    edge = Edge(
        id="e1",
        source_id="sql_001",
        target_id="tbl_001",
        edge_type=EdgeType.WRITES_TO,
    )
    assert edge.source_id == "sql_001"
    assert edge.target_id == "tbl_001"
    assert edge.edge_type == EdgeType.WRITES_TO


def test_edge_to_dict():
    edge = Edge(
        id="e2",
        source_id="tbl_001",
        target_id="sql_001",
        edge_type=EdgeType.READS_FROM,
    )
    d = edge.to_dict()
    assert d["source"] == "tbl_001"
    assert d["target"] == "sql_001"
    assert d["type"] == "reads_from"


def test_edge_with_properties():
    edge = Edge(
        id="e3",
        source_id="col_001",
        target_id="tr_001",
        edge_type=EdgeType.COMPUTE_DEPENDENCY,
        properties={"position": 0},
    )
    assert edge.properties["position"] == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `poetry run pytest tests/test_model/test_edges.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 edges.py**

```python
# sqlgraph/model/edges.py
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class EdgeType(str, Enum):
    """边类型枚举"""
    WRITES_TO = "writes_to"
    READS_FROM = "reads_from"
    TABLE_LINEAGE = "table_lineage"
    PRODUCES = "produces"
    COMPUTE_DEPENDENCY = "compute_dependency"
    HAS_COLUMN = "has_column"
    CONTAINS = "contains"


@dataclass
class Edge:
    """图的边"""
    id: str
    source_id: str
    target_id: str
    edge_type: EdgeType
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（使用 source/target/type 键名，方便图数据库导入）"""
        return {
            "id": self.id,
            "source": self.source_id,
            "target": self.target_id,
            "type": self.edge_type.value,
            **self.properties,
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `poetry run pytest tests/test_model/test_edges.py -v`
Expected: 3 tests passed

- [ ] **Step 5: 提交**

```bash
git add sqlgraph/model/edges.py tests/test_model/test_edges.py
git commit -m "feat: add edge types (WRITES_TO, READS_FROM, TABLE_LINEAGE, etc.)"
```

---

## Task 5: 数据模型 - PropertyGraph（model/graph.py）

**Files:**
- Create: `sqlgraph/model/graph.py`
- Modify: `sqlgraph/model/__init__.py`
- Create: `tests/test_model/test_graph.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_model/test_graph.py
from sqlgraph.model.graph import PropertyGraph
from sqlgraph.model.nodes import SqlNode, TableNode, ColumnNode, TransformNode, ExpressionType
from sqlgraph.model.edges import Edge, EdgeType


def _make_sample_graph() -> PropertyGraph:
    g = PropertyGraph()
    s1 = SqlNode(id="s1", name="sql1")
    t1 = TableNode(id="t1", name="src_table")
    t2 = TableNode(id="t2", name="dst_table")
    c1 = ColumnNode(id="c1", name="id", table_id="t1")
    c2 = ColumnNode(id="c2", name="id", table_id="t2")
    tr1 = TransformNode(id="tr1", expression="id", expression_type=ExpressionType.COLUMN_REF)
    g.add_node(s1)
    g.add_node(t1)
    g.add_node(t2)
    g.add_node(c1)
    g.add_node(c2)
    g.add_node(tr1)
    g.add_edge(Edge("e1", "s1", "t1", EdgeType.READS_FROM))
    g.add_edge(Edge("e2", "s1", "t2", EdgeType.WRITES_TO))
    g.add_edge(Edge("e3", "t1", "c1", EdgeType.HAS_COLUMN))
    g.add_edge(Edge("e4", "t2", "c2", EdgeType.HAS_COLUMN))
    g.add_edge(Edge("e5", "s1", "tr1", EdgeType.CONTAINS))
    g.add_edge(Edge("e6", "c1", "tr1", EdgeType.COMPUTE_DEPENDENCY))
    g.add_edge(Edge("e7", "tr1", "c2", EdgeType.PRODUCES))
    g.add_edge(Edge("e8", "t1", "t2", EdgeType.TABLE_LINEAGE))
    return g


def test_add_node_and_edge():
    g = PropertyGraph()
    s = SqlNode(id="s1", name="test_sql")
    t = TableNode(id="t1", name="test_table")
    g.add_node(s)
    g.add_node(t)
    g.add_edge(Edge("e1", "s1", "t1", EdgeType.WRITES_TO))
    assert len(g.nodes) == 2
    assert len(g.edges) == 1
    assert g.get_node("s1") == s
    assert g.get_node("t1") == t


def test_stats():
    g = _make_sample_graph()
    stats = g.stats()
    assert stats["sql_count"] == 1
    assert stats["table_count"] == 2
    assert stats["column_count"] == 2
    assert stats["transform_count"] == 1
    assert stats["edge_count"] == 8


def test_get_upstream_tables():
    g = _make_sample_graph()
    upstream = g.get_upstream("dst_table")
    assert "src_table" in upstream


def test_get_downstream_tables():
    g = _make_sample_graph()
    downstream = g.get_downstream("src_table")
    assert "dst_table" in downstream


def test_duplicate_node_raises():
    g = PropertyGraph()
    g.add_node(SqlNode(id="s1", name="s1"))
    import pytest
    with pytest.raises(ValueError):
        g.add_node(SqlNode(id="s1", name="s1_dup"))


def test_to_dict():
    g = _make_sample_graph()
    d = g.to_dict()
    assert "nodes" in d
    assert "edges" in d
    assert len(d["nodes"]) == 6
    assert len(d["edges"]) == 8
```

- [ ] **Step 2: 运行测试确认失败**

Run: `poetry run pytest tests/test_model/test_graph.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 graph.py**

```python
# sqlgraph/model/graph.py
from typing import Any
from sqlgraph.model.nodes import BaseNode, SqlNode, TableNode, ColumnNode, TransformNode, NodeType
from sqlgraph.model.edges import Edge, EdgeType


class PropertyGraph:
    """属性图 - sqlGraph 的核心数据模型"""

    def __init__(self):
        self._nodes: dict[str, BaseNode] = {}
        self._edges: list[Edge] = []
        self._node_by_name: dict[str, str] = {}

    @property
    def nodes(self) -> list[BaseNode]:
        """所有节点列表"""
        return list(self._nodes.values())

    @property
    def edges(self) -> list[Edge]:
        """所有边列表"""
        return list(self._edges)

    def add_node(self, node: BaseNode) -> None:
        """添加节点，重复 id 抛出异常"""
        if node.id in self._nodes:
            raise ValueError(f"Node with id '{node.id}' already exists")
        self._nodes[node.id] = node
        self._node_by_name[node.name] = node.id

    def add_edge(self, edge: Edge) -> None:
        """添加边（不验证节点存在性，构建时可延迟添加）"""
        self._edges.append(edge)

    def get_node(self, node_id: str) -> BaseNode | None:
        """按 ID 获取节点"""
        return self._nodes.get(node_id)

    def get_node_by_name(self, name: str) -> BaseNode | None:
        """按名称获取节点"""
        nid = self._node_by_name.get(name)
        if nid:
            return self._nodes.get(nid)
        for node in self._nodes.values():
            if node.name == name:
                return node
        return None

    def stats(self) -> dict[str, int]:
        """统计节点/边数量"""
        counts = {
            "sql_count": 0,
            "table_count": 0,
            "column_count": 0,
            "transform_count": 0,
            "edge_count": len(self._edges),
        }
        for node in self._nodes.values():
            if isinstance(node, SqlNode):
                counts["sql_count"] += 1
            elif isinstance(node, TableNode):
                counts["table_count"] += 1
            elif isinstance(node, ColumnNode):
                counts["column_count"] += 1
            elif isinstance(node, TransformNode):
                counts["transform_count"] += 1
        counts["node_count"] = len(self._nodes)
        return counts

    def get_upstream(self, table_name: str) -> list[str]:
        """获取指定表的上游表名列表（通过 TABLE_LINEAGE 边）"""
        tgt_id = self._node_by_name.get(table_name)
        if not tgt_id:
            return []
        upstream = []
        for edge in self._edges:
            if edge.edge_type == EdgeType.TABLE_LINEAGE and edge.target_id == tgt_id:
                src = self._nodes.get(edge.source_id)
                if src and isinstance(src, TableNode):
                    upstream.append(src.name)
        return upstream

    def get_downstream(self, table_name: str) -> list[str]:
        """获取指定表的下游表名列表（通过 TABLE_LINEAGE 边）"""
        src_id = self._node_by_name.get(table_name)
        if not src_id:
            return []
        downstream = []
        for edge in self._edges:
            if edge.edge_type == EdgeType.TABLE_LINEAGE and edge.source_id == src_id:
                tgt = self._nodes.get(edge.target_id)
                if tgt and isinstance(tgt, TableNode):
                    downstream.append(tgt.name)
        return downstream

    def get_nodes_by_type(self, node_type: NodeType) -> list[BaseNode]:
        """按类型获取节点列表"""
        return [n for n in self._nodes.values() if n.node_type == node_type]

    def get_edges_by_type(self, edge_type: EdgeType) -> list[Edge]:
        """按类型获取边列表"""
        return [e for e in self._edges if e.edge_type == edge_type]

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges],
        }
```

- [ ] **Step 4: 更新 model/__init__.py 导出**

```python
# sqlgraph/model/__init__.py
from sqlgraph.model.nodes import (
    NodeType, ExpressionType,
    BaseNode, SqlNode, TableNode, ColumnNode, TransformNode,
)
from sqlgraph.model.edges import EdgeType, Edge
from sqlgraph.model.graph import PropertyGraph

__all__ = [
    "NodeType", "ExpressionType",
    "BaseNode", "SqlNode", "TableNode", "ColumnNode", "TransformNode",
    "EdgeType", "Edge",
    "PropertyGraph",
]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `poetry run pytest tests/test_model/ -v`
Expected: All tests passed (nodes + edges + graph)

- [ ] **Step 6: 提交**

```bash
git add sqlgraph/model/ tests/test_model/
git commit -m "feat: add PropertyGraph core model with upstream/downstream queries"
```

---

## Task 6: 批处理韧性工具（utils/batch.py）

**Files:**
- Create: `sqlgraph/utils/batch.py`
- Create: `tests/test_utils/test_batch.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_utils/test_batch.py
import json
import os
import tempfile
from sqlgraph.utils.batch import BatchResult, FailedCase, process_batch


def test_batch_result_success():
    result = BatchResult()
    result.add_success("file1.sql")
    result.add_success("file2.sql")
    assert result.success_count == 2
    assert result.failure_count == 0


def test_batch_result_failure():
    result = BatchResult()
    result.add_failure(FailedCase(
        file_path="bad.sql",
        error_message="syntax error",
        sql_content="SELECT FROM",
    ))
    assert result.success_count == 0
    assert result.failure_count == 1
    assert len(result.failed_cases) == 1


def test_batch_process_all_success():
    def processor(item):
        return item * 2

    items = [1, 2, 3]
    result = process_batch(items, processor, desc="Testing")
    assert result.success_count == 3
    assert result.failure_count == 0


def test_batch_process_partial_failure():
    def processor(item):
        if item == 2:
            raise ValueError("bad value")
        return item * 2

    items = [1, 2, 3]
    result = process_batch(items, processor, desc="Testing")
    assert result.success_count == 2
    assert result.failure_count == 1
    assert result.failed_cases[0].file_path == "2"


def test_failed_cases_json_output():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = BatchResult()
        result.add_failure(FailedCase(
            file_path="bad.sql",
            error_message="parse error",
            sql_content="BAD SQL",
        ))
        path = os.path.join(tmpdir, "failed_cases.json")
        result.write_failed_cases(path)
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["file_path"] == "bad.sql"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `poetry run pytest tests/test_utils/test_batch.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 batch.py**

```python
# sqlgraph/utils/batch.py
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, TypeVar, Generic
from sqlgraph.utils.logging import log_progress, log_info, log_error

T = TypeVar("T")


@dataclass
class FailedCase:
    """失败案例记录"""
    file_path: str
    error_message: str
    sql_content: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BatchResult(Generic[T]):
    """批处理结果"""
    successful: list[T] = field(default_factory=list)
    failed_cases: list[FailedCase] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return len(self.successful)

    @property
    def failure_count(self) -> int:
        return len(self.failed_cases)

    def add_success(self, item: T) -> None:
        self.successful.append(item)

    def add_failure(self, case: FailedCase) -> None:
        self.failed_cases.append(case)

    def write_failed_cases(self, path: str) -> None:
        """将失败案例写入 JSON 文件"""
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in self.failed_cases], f, ensure_ascii=False, indent=2)


def process_batch(
    items: list[T],
    processor: Callable[[T], Any],
    desc: str = "Processing",
) -> BatchResult:
    """批处理执行，单条失败不影响整体"""
    result = BatchResult()
    total = len(items)
    for idx, item in enumerate(items, 1):
        try:
            processed = processor(item)
            result.add_success(processed)
        except Exception as e:
            file_path = str(item) if not isinstance(item, str) else item
            sql_content = item if isinstance(item, str) else None
            result.add_failure(FailedCase(
                file_path=file_path,
                error_message=str(e),
                sql_content=sql_content,
            ))
            log_error(f"Failed to process {file_path}: {e}")
        log_progress(idx, total, prefix=desc)
    log_info(f"Done. Success: {result.success_count}, Failed: {result.failure_count}")
    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `poetry run pytest tests/test_utils/test_batch.py -v`
Expected: 5 tests passed

- [ ] **Step 5: 提交**

```bash
git add sqlgraph/utils/batch.py tests/test_utils/test_batch.py
git commit -m "feat: add batch processing resilience with failed_cases.json"
```

---

## Task 7: Notebook 兼容工具（utils/notebook.py）

**Files:**
- Create: `sqlgraph/utils/notebook.py`
- Create: `tests/test_utils/test_notebook.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_utils/test_notebook.py
import sys
from sqlgraph.utils.notebook import is_notebook_env, patch_str_none_type, setup_notebook


def test_is_notebook_env_defaults_false():
    assert is_notebook_env() is False


def test_patch_str_none_type():
    if sys.version_info < (3, 10):
        patch_str_none_type()
    assert True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `poetry run pytest tests/test_utils/test_notebook.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 notebook.py**

```python
# sqlgraph/utils/notebook.py
import sys


def is_notebook_env() -> bool:
    """检测是否运行在 Jupyter Notebook 环境中"""
    try:
        from IPython import get_ipython
        if get_ipython() is None:
            return False
        shell = get_ipython().__class__.__name__
        if shell == "ZMQInteractiveShell":
            return True
        return False
    except ImportError:
        return False


def patch_str_none_type() -> None:
    """Patch Python < 3.10 的 str | None 类型注解兼容性问题"""
    if sys.version_info >= (3, 10):
        return
    import builtins
    import types
    if not hasattr(types, "UnionType"):
        return


def setup_notebook() -> None:
    """Notebook 环境初始化：patch 类型 + 配置日志"""
    patch_str_none_type()


def display_html_in_notebook(html_content: str) -> None:
    """在 Notebook 中展示 HTML 内容"""
    if not is_notebook_env():
        return
    try:
        from IPython.display import HTML, display
        display(HTML(html_content))
    except ImportError:
        pass
```

- [ ] **Step 4: 更新 utils/__init__.py**

```python
# sqlgraph/utils/__init__.py
from sqlgraph.utils.errors import (
    SqlGraphError, SqlParseError, SchemaNotFoundError,
    AmbiguousColumnError, CircularDependencyError, InputError,
)
from sqlgraph.utils.logging import log_info, log_warn, log_error, log_progress, log_stats
from sqlgraph.utils.batch import BatchResult, FailedCase, process_batch
from sqlgraph.utils.notebook import is_notebook_env, setup_notebook, display_html_in_notebook
```

- [ ] **Step 5: 运行测试确认通过**

Run: `poetry run pytest tests/test_utils/ -v`
Expected: All utils tests passed

- [ ] **Step 6: 提交**

```bash
git add sqlgraph/utils/ tests/test_utils/
git commit -m "feat: add notebook compatibility utilities"
```
