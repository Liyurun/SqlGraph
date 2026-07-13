from __future__ import annotations

import json
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
from typing import Any

from sqlgraph import build_graph
from sqlgraph.input.sql_source import SqlSource, SqlSourceItem, clean_df_sql, _split_sql_statements
from sqlgraph.visualize.html import _prepare_elements


PLAYGROUND_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SqlGraph Playground</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body,#app{width:100%;height:100%;overflow:hidden}
body{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:#f8f6f1;color:#243042}
#app{display:grid;grid-template-columns:420px 1fr}
.panel{height:100%;padding:18px;background:rgba(255,255,255,.92);border-right:1px solid rgba(0,0,0,.08);box-shadow:6px 0 24px rgba(0,0,0,.06);display:flex;flex-direction:column;gap:14px;z-index:2}
.brand{font-size:18px;font-weight:800;letter-spacing:-.4px;background:linear-gradient(135deg,#667eea,#764ba2);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sub{font-size:12px;color:#667085;line-height:1.6}
.row{display:flex;gap:8px;align-items:center}
select,input,textarea,button{font:inherit}
select,input{height:34px;border:1px solid rgba(0,0,0,.12);border-radius:9px;padding:0 10px;background:#fff;color:#243042}
select{width:120px}
input{flex:1}
textarea{flex:1;min-height:360px;width:100%;resize:none;border:1px solid rgba(0,0,0,.12);border-radius:12px;padding:12px;background:#fbfaf7;color:#1f2937;font-family:"SF Mono","JetBrains Mono","Fira Code",monospace;font-size:12px;line-height:1.55;outline:none}
textarea:focus,input:focus,select:focus{border-color:#667eea;box-shadow:0 0 0 3px rgba(102,126,234,.14)}
button{height:36px;border:none;border-radius:10px;padding:0 14px;background:#eef0ff;color:#4752c4;font-weight:700;cursor:pointer}
button.primary{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;box-shadow:0 8px 18px rgba(102,126,234,.25)}
button:disabled{opacity:.55;cursor:not-allowed}
.option-row{display:flex;align-items:center;gap:8px;font-size:12px;color:#475467;user-select:none}
.option-row input{width:16px;height:16px;accent-color:#667eea;flex:none}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.stat{border:1px solid rgba(0,0,0,.08);border-radius:10px;padding:8px;background:#fff}
.stat .k{font-size:10px;color:#667085}
.stat .v{font-size:16px;font-weight:800;margin-top:2px}
.msg{font-size:12px;line-height:1.6;border-radius:10px;padding:10px;background:#f3f4f6;color:#374151;white-space:pre-wrap;max-height:140px;overflow:auto}
.msg.err{background:#fff1f2;color:#be123c}.msg.ok{background:#ecfdf3;color:#027a48}
.canvas-wrap{position:relative;width:100%;height:100%}
#cy{position:absolute;inset:0;background:#faf8f5}
.topbar{position:absolute;top:14px;left:14px;right:14px;display:flex;align-items:center;gap:8px;z-index:3;pointer-events:none}
.pill{pointer-events:auto;border:1px solid rgba(0,0,0,.08);background:rgba(255,255,255,.9);backdrop-filter:blur(18px);border-radius:999px;padding:8px 12px;font-size:12px;color:#475467;box-shadow:0 4px 16px rgba(0,0,0,.06)}
.toolbar{margin-left:auto;display:flex;gap:8px;pointer-events:auto}
.detail{position:absolute;top:62px;right:14px;width:320px;max-height:calc(100vh - 82px);overflow:auto;background:rgba(255,255,255,.94);backdrop-filter:blur(18px);border:1px solid rgba(0,0,0,.08);box-shadow:0 12px 34px rgba(0,0,0,.1);border-radius:14px;padding:14px;z-index:4;display:none}
.detail.show{display:block}.detail h3{font-size:14px;margin-bottom:8px;word-break:break-all}.badge{display:inline-block;border-radius:6px;padding:2px 7px;background:#667eea;color:#fff;font-size:10px;font-weight:800;margin-bottom:8px}
.prop{display:flex;gap:8px;border-top:1px solid rgba(0,0,0,.07);padding:7px 0;font-size:12px}.prop .k{width:70px;flex:none;color:#667085}.prop .v{flex:1;word-break:break-all;font-family:"SF Mono","JetBrains Mono",monospace;font-size:11px}
pre.code{background:#1e1e2e;color:#cdd6f4;border-radius:10px;padding:10px;max-height:260px;overflow:auto;white-space:pre;font-size:11px;line-height:1.5}
</style>
</head>
<body>
<div id="app">
  <aside class="panel">
    <div>
      <div class="brand">SqlGraph Playground</div>
      <div class="sub">输入一段或多段 SQL，点击解析后会调用本地 SqlGraph 后端生成知识图谱。</div>
    </div>
    <div class="row">
      <select id="dialect">
        <option value="spark" selected>spark</option>
        <option value="hive">hive</option>
        <option value="">auto</option>
        <option value="presto">presto</option>
        <option value="mysql">mysql</option>
      </select>
      <input id="name" value="playground_sql" placeholder="SQL名称">
    </div>
    <textarea id="sqlInput"></textarea>
    <div class="row">
      <button class="primary" id="parseBtn">解析并生成图谱</button>
      <button id="sampleBtn">填入示例</button>
      <button id="clearBtn">清空</button>
    </div>
    <label class="option-row">
      <input type="checkbox" id="showSqlBridge" checked>
      选中表时高亮 SQL 虚线路径
    </label>
    <div class="stats">
      <div class="stat"><div class="k">SQL</div><div class="v" id="sqlCount">0</div></div>
      <div class="stat"><div class="k">节点</div><div class="v" id="nodeCount">0</div></div>
      <div class="stat"><div class="k">边</div><div class="v" id="edgeCount">0</div></div>
    </div>
    <div id="msg" class="msg">准备就绪。</div>
  </aside>
  <main class="canvas-wrap">
    <div id="cy"></div>
    <div class="topbar">
      <div class="pill">SQL -> Table / Column / Transform Graph</div>
      <div class="toolbar">
        <button id="fitBtn">适配视图</button>
        <button id="layoutBtn">重新布局</button>
      </div>
    </div>
    <div class="detail" id="detail"></div>
  </main>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.min.js"></script>
<script>
cytoscape.use(cytoscapeDagre);
const sampleSql = `INSERT OVERWRITE TABLE dws_creative_daily
SELECT
  creative_id,
  advertiser_id,
  SUM(impression_cnt) AS impression_cnt,
  SUM(click_cnt) AS click_cnt
FROM dwd_ad_event
WHERE p_date = '\${date}'
GROUP BY creative_id, advertiser_id;

INSERT OVERWRITE TABLE ads_creative_report
SELECT
  creative_id,
  advertiser_id,
  SUM(impression_cnt) AS impressions,
  SUM(click_cnt) AS clicks,
  CASE WHEN SUM(impression_cnt) > 0 THEN SUM(click_cnt) / SUM(impression_cnt) ELSE 0 END AS ctr
FROM dws_creative_daily
WHERE p_date = '\${date}'
GROUP BY creative_id, advertiser_id;

INSERT OVERWRITE TABLE rpt_creative_dashboard
SELECT
  advertiser_id,
  SUM(impressions) AS total_impressions,
  SUM(clicks) AS total_clicks,
  AVG(ctr) AS avg_ctr
FROM ads_creative_report
GROUP BY advertiser_id`;
const input = document.getElementById('sqlInput');
input.value = sampleSql;
const msg = document.getElementById('msg');
let cy = cytoscape({
  container: document.getElementById('cy'),
  elements: [],
  wheelSensitivity: .25,
  style: [
    {selector:'node',style:{'background-color':'data(bg)','border-color':'data(border)','border-width':2,'label':'data(label)','font-size':'data(fontSize)','width':'data(size)','height':'data(size)','text-valign':'bottom','text-halign':'center','text-margin-y':5,'font-family':'Inter, sans-serif','color':'#1f2937','text-background-color':'rgba(255,255,255,.9)','text-background-opacity':1,'text-background-padding':'2px 5px','text-background-shape':'roundrectangle','text-wrap':'wrap','text-max-width':'180px'}},
    {selector:'node[nodeType="sql"]',style:{'shape':'round-rectangle','width':118,'height':40,'label':'data(label)','background-color':'#7c3aed','border-color':'#4c1d95','border-width':3,'color':'#fff','font-size':10,'font-weight':'800','text-valign':'center','text-margin-y':0,'text-wrap':'wrap','text-max-width':'104px','text-background-opacity':0,'text-outline-width':1.5,'text-outline-color':'#4c1d95'}},
    {selector:'node[nodeType="transform"]',style:{'shape':'diamond','label':'data(label)','background-color':'#ffa726','border-color':'#ef6c00','color':'#1f2937','text-valign':'bottom','text-margin-y':6,'font-weight':'700','text-background-color':'rgba(255,255,255,.92)','text-background-opacity':1,'text-background-padding':'2px 5px','text-background-shape':'roundrectangle','text-max-width':'150px','text-wrap':'ellipsis'}},
    {selector:'node[nodeType="column"]',style:{'background-color':'#66bb6a','border-color':'#2e7d32','width':12,'height':12,'font-size':8}},
    {selector:'node[columnRole="read_anchor"]',style:{'background-color':'#86efac','border-color':'#059669','border-width':3}},
    {selector:'edge',style:{'curve-style':'bezier','target-arrow-shape':'triangle','line-color':'data(color)','target-arrow-color':'data(color)','width':'data(width)','opacity':'data(opacity)','arrow-scale':.65}},
    {selector:'edge[edgeType="contains"]',style:{'display':'none'}},
    {selector:'edge[edgeType="table_to_column"]',style:{'width':1.8,'opacity':.78,'line-color':'#10b981','target-arrow-color':'#10b981'}},
    {selector:'edge[edgeType="column_to_table"]',style:{'width':1.8,'opacity':.78,'line-color':'#f97316','target-arrow-color':'#f97316'}},
    {selector:'edge[edgeType="direct_to_table"]',style:{'width':2.1,'opacity':.82,'line-color':'#14b8a6','target-arrow-color':'#14b8a6'}},
    {selector:'edge[edgeType="rename_column"]',style:{'width':1.8,'opacity':.78,'line-color':'#a855f7','target-arrow-color':'#a855f7'}},
    {selector:'edge[edgeType="reads_from"]',style:{'display':'element','width':1.3,'opacity':.42,'line-color':'#8b5cf6','target-arrow-color':'#8b5cf6','line-style':'dashed'}},
    {selector:'edge[edgeType="writes_to"]',style:{'display':'element','width':1.5,'opacity':.48,'line-color':'#8b5cf6','target-arrow-color':'#8b5cf6','line-style':'dashed'}},
    {selector:'edge.sql-bridge-context',style:{'display':'element','width':2.1,'opacity':.72,'line-color':'#6d28d9','target-arrow-color':'#6d28d9','line-style':'dashed'}},
    {selector:'.highlighted',style:{'border-width':4,'border-color':'#f59e0b','z-index':99}},
    {selector:'node.table-selected',style:{'border-width':6,'border-color':'#f59e0b','z-index':120}},
    {selector:'.faded',style:{'opacity':.08}}
  ],
  layout:{name:'preset'}
});
function setMsg(text, type=''){ msg.textContent=text; msg.className='msg '+type; }
function applyLayout(){
  const layout = {name:'dagre',rankDir:'LR',nodeSep:38,rankSep:120,edgeSep:14,ranker:'network-simplex',animate:false,padding:70};
  cy.layout(layout).run();
  setTimeout(()=>cy.fit(undefined, 50), 200);
}
function updateStats(stats, elementCount){
  document.getElementById('sqlCount').textContent = stats.sql_count || 0;
  document.getElementById('nodeCount').textContent = elementCount.nodes || 0;
  document.getElementById('edgeCount').textContent = elementCount.edges || 0;
}
function esc(s){ const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML; }
function showDetail(d){
  const typeName = {sql:'SQL任务',table:'数据表',column:'字段',transform:'加工逻辑'}[d.nodeType] || d.nodeType;
  let html = `<h3>${esc(d.fullName || d.label || d.id)}</h3><span class="badge">${typeName}</span>`;
  const props = [
    ['ID', d.id],
    ['类型', d.nodeType],
    ['字段角色', ({read_anchor:'下游读取起点'}[d.columnRole] || '')],
    ['度数', d.degree],
    ['输出字段', d.outputName],
    ['表达式', d.expression],
    ['算子', d.op],
    ['方言', d.dialect],
  ].filter(x => x[1]);
  for (const [k,v] of props) html += `<div class="prop"><div class="k">${k}</div><div class="v">${esc(String(v))}</div></div>`;
  if (d.sqlContent) html += `<div class="prop"><div class="k">SQL源码</div><div class="v"><pre class="code">${esc(d.sqlContent)}</pre></div></div>`;
  const detail = document.getElementById('detail');
  detail.innerHTML = html;
  detail.classList.add('show');
}
function clearSqlBridgeContext(){
  cy.edges('.sql-bridge-context').removeClass('sql-bridge-context');
  cy.nodes('.table-selected').removeClass('table-selected');
}
function showSqlBridgeForTable(node){
  clearSqlBridgeContext();
  if(!document.getElementById('showSqlBridge').checked) return;
  node.addClass('table-selected');
  const id = node.id();
  cy.edges().forEach(edge => {
    const t = edge.data('edgeType');
    if((t === 'reads_from' || t === 'writes_to') &&
       (edge.data('source') === id || edge.data('target') === id)){
      edge.addClass('sql-bridge-context');
    }
  });
}
document.getElementById('showSqlBridge').addEventListener('change', () => {
  const selectedTable = cy.nodes('.table-selected[nodeType="table"]').first();
  if(selectedTable.length) showSqlBridgeForTable(selectedTable);
  else clearSqlBridgeContext();
});
cy.on('tap','node', evt => {
  const node = evt.target;
  showDetail(node.data());
  if(node.data('nodeType') === 'table') showSqlBridgeForTable(node);
  else clearSqlBridgeContext();
});
cy.on('tap', evt => { if(evt.target === cy){ clearSqlBridgeContext(); document.getElementById('detail').classList.remove('show'); } });
cy.on('mouseover','node', evt => {
  cy.elements().addClass('faded');
  evt.target.closedNeighborhood().removeClass('faded').addClass('highlighted');
  evt.target.removeClass('faded').addClass('highlighted');
});
cy.on('mouseout','node', () => cy.elements().removeClass('faded highlighted'));
document.getElementById('fitBtn').onclick = () => cy.fit(undefined, 50);
document.getElementById('layoutBtn').onclick = applyLayout;
document.getElementById('sampleBtn').onclick = () => input.value = sampleSql;
document.getElementById('clearBtn').onclick = () => input.value = '';
document.getElementById('parseBtn').onclick = async () => {
  const sql = input.value.trim();
  if(!sql){ setMsg('请输入 SQL。','err'); return; }
  const btn = document.getElementById('parseBtn');
  btn.disabled = true; setMsg('正在解析 SQL 并构建图谱...');
  try{
    const res = await fetch('/api/parse', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({sql, dialect: document.getElementById('dialect').value, name: document.getElementById('name').value || 'playground_sql'})
    });
    const data = await res.json();
    if(!res.ok || !data.ok) throw new Error(data.error || '解析失败');
    cy.elements().remove();
    cy.add(data.elements);
    updateStats(data.stats, data.elementCount);
    applyLayout();
    setMsg(`解析成功：${data.elementCount.nodes} 个节点，${data.elementCount.edges} 条边。`, 'ok');
  }catch(e){
    setMsg(e.message || String(e), 'err');
  }finally{
    btn.disabled = false;
  }
};
</script>
</body>
</html>
"""


def graph_to_playground_payload(sql: str, dialect: str | None = "spark", name: str = "playground_sql") -> dict[str, Any]:
    """解析 SQL 并转换为 Playground 前端可消费的数据"""
    source = _source_from_sql_text(sql, name=name)
    graph = build_graph(source, dialect=dialect or None)
    elements = _prepare_elements(graph, view="column")
    _normalize_elements_for_data_flow(elements)
    return {
        "ok": True,
        "stats": graph.stats(),
        "elements": elements,
        "elementCount": {
            "nodes": sum(1 for e in elements if "source" not in e.get("data", {})),
            "edges": sum(1 for e in elements if "source" in e.get("data", {})),
        },
    }


def _source_from_sql_text(sql: str, name: str = "playground_sql") -> SqlSource:
    """把页面输入的一段/多段 SQL 拆成多个 SqlSourceItem"""
    cleaned = clean_df_sql(sql)
    statements = [s.strip() for s in _split_sql_statements(cleaned) if s.strip()]
    if not statements:
        raise ValueError("没有找到可解析的 SQL 语句")
    source = SqlSource()
    width = max(2, len(str(len(statements))))
    for idx, stmt in enumerate(statements, start=1):
        item_name = name if len(statements) == 1 else f"{name}_{idx:0{width}d}"
        source.add_item(SqlSourceItem(
            name=item_name,
            content=stmt,
            source_type="playground",
            metadata={"raw_content": stmt},
        ))
    return source


def _normalize_elements_for_data_flow(elements: list[dict[str, Any]]) -> None:
    """把图谱展示方向规范成 数据源 -> SQL/Transform -> 下游"""
    node_by_id = {
        el.get("data", {}).get("id"): el.get("data", {})
        for el in elements
        if "source" not in el.get("data", {})
    }
    for node in node_by_id.values():
        if node.get("nodeType") == "sql":
            preview = _sql_logic_preview(node.get("sqlContent") or node.get("label") or node.get("fullName") or "")
            node["sqlPreview"] = preview
            node["label"] = preview
            node["size"] = 118
            node["fontSize"] = 10
        if node.get("nodeType") == "transform":
            expr = node.get("expression") or node.get("label") or node.get("op") or ""
            node["logicPreview"] = _short_logic(expr)
            node["label"] = node["logicPreview"]

    lineage_sources: set[str] = set()
    lineage_targets: set[str] = set()
    input_columns: set[str] = set()
    output_columns: set[str] = set()
    direct_output_columns: set[str] = set()
    direct_same_outputs: set[str] = set()
    col_to_table: dict[str, str] = {}

    for el in elements:
        data = el.get("data", {})
        if "source" in data:
            if data.get("edgeType") == "has_column":
                col_to_table[data.get("target")] = data.get("source")
            if data.get("edgeType") == "compute_dependency":
                src_type = node_by_id.get(data.get("source"), {}).get("nodeType")
                tgt_type = node_by_id.get(data.get("target"), {}).get("nodeType")
                if src_type == "column" and tgt_type == "column":
                    input_columns.add(data.get("source"))
                    direct_output_columns.add(data.get("target"))
                    if _same_column_name(node_by_id.get(data.get("source"), {}), node_by_id.get(data.get("target"), {})):
                        direct_same_outputs.add(data.get("target"))
                else:
                    input_columns.add(data.get("source"))
            elif data.get("edgeType") == "produces":
                output_columns.add(data.get("target"))
            if data.get("edgeType") == "reads_from":
                data["source"], data["target"] = data["target"], data["source"]
            if data.get("edgeType") == "table_lineage":
                lineage_sources.add(data.get("source"))
                lineage_targets.add(data.get("target"))
            continue
    _fill_column_table_map_from_nodes(col_to_table, node_by_id)
    for el in elements:
        data = el.get("data", {})
        if "source" in data:
            continue
        if data.get("nodeType") != "table":
            continue
        node_id = data.get("id")
        if node_id in lineage_sources and node_id in lineage_targets:
            data["flowRole"] = "middle"
        elif node_id in lineage_sources or data.get("isSource"):
            data["flowRole"] = "source"
        elif node_id in lineage_targets or data.get("isLeaf"):
            data["flowRole"] = "downstream"
    output_columns.update(direct_output_columns)

    # table_lineage 是从 SQL 读写关系推导出的摘要边。Playground 默认展示 SQL 节点，
    # 若继续显示该边，会形成“表直接产出表”的误导性捷径。
    elements[:] = [
        el for el in elements
        if el.get("data", {}).get("edgeType") != "table_lineage"
    ]
    read_anchor_by_column = _build_read_anchors(
        input_columns=input_columns,
        output_columns=output_columns,
        col_to_table=col_to_table,
        node_by_id=node_by_id,
    )
    normalized: list[dict[str, Any]] = []
    for anchor in read_anchor_by_column.values():
        normalized.extend(anchor)
    for el in elements:
        data = el.get("data", {})
        if data.get("edgeType") != "has_column":
            if data.get("edgeType") == "compute_dependency":
                src_type = node_by_id.get(data.get("source"), {}).get("nodeType")
                tgt_type = node_by_id.get(data.get("target"), {}).get("nodeType")
                if src_type == "column" and tgt_type == "column":
                    target_table = col_to_table.get(data.get("target"))
                    source_id = _read_anchor_id(read_anchor_by_column, data.get("source"))
                    if data.get("target") in direct_same_outputs:
                        if target_table:
                            normalized.append(_edge_like(
                                el,
                                source=source_id,
                                target=target_table,
                                edge_type="direct_to_table",
                                color="#14b8a6",
                                opacity=0.82,
                                width=2.1,
                            ))
                    else:
                        normalized.append(_edge_like(
                            el,
                            source=source_id,
                            target=data.get("target"),
                            edge_type="rename_column",
                            color="#a855f7",
                            opacity=0.78,
                            width=1.8,
                        ))
                    continue
                source_id = _read_anchor_id(read_anchor_by_column, data.get("source"))
                if source_id != data.get("source"):
                    normalized.append(_edge_with_endpoints(
                        el,
                        source=source_id,
                        target=data.get("target"),
                        suffix="from_read_anchor",
                    ))
                    continue
            normalized.append(el)
            continue
        table_id = data.get("source")
        column_id = data.get("target")
        if column_id in output_columns and column_id not in direct_same_outputs:
            down = {
                **el,
                "data": {
                    **data,
                    "id": f"{data.get('id')}_column_to_table",
                    "source": column_id,
                    "target": table_id,
                    "edgeType": "column_to_table",
                    "color": "#f97316",
                    "opacity": 0.78,
                    "width": 1.8,
                },
            }
            normalized.append(down)
        if column_id not in output_columns:
            up = {
                **el,
                "data": {
                    **data,
                    "id": f"{data.get('id')}_table_to_column",
                    "source": table_id,
                    "target": column_id,
                    "edgeType": "table_to_column",
                    "color": "#10b981",
                    "opacity": 0.78,
                    "width": 1.8,
                },
            }
            normalized.append(up)
    _ensure_input_columns_have_table_edges(
        normalized=normalized,
        input_columns=input_columns,
        col_to_table=col_to_table,
        read_anchor_by_column=read_anchor_by_column,
    )
    connected_ids = set()
    for el in normalized:
        data = el.get("data", {})
        if "source" in data:
            connected_ids.add(data.get("source"))
            connected_ids.add(data.get("target"))
    elements[:] = [
        el for el in normalized
        if "source" in el.get("data", {})
        or el.get("data", {}).get("nodeType") in ("table", "sql")
        or el.get("data", {}).get("id") in connected_ids
    ]


def _fill_column_table_map_from_nodes(
    col_to_table: dict[str, str],
    node_by_id: dict[str, dict[str, Any]],
) -> None:
    """用字段节点自带的 tableId 兜底补全字段所属表"""
    for node_id, node in node_by_id.items():
        if node.get("nodeType") != "column":
            continue
        table_id = node.get("tableId") or node.get("table_id")
        if table_id:
            col_to_table.setdefault(node_id, table_id)


def _ensure_input_columns_have_table_edges(
    normalized: list[dict[str, Any]],
    input_columns: set[str],
    col_to_table: dict[str, str],
    read_anchor_by_column: dict[str, list[dict[str, Any]]],
) -> None:
    """保证所有作为上游起点的字段都先挂在所属表下面"""
    existing = {
        (data.get("source"), data.get("target"))
        for data in (el.get("data", {}) for el in normalized)
        if data.get("edgeType") == "table_to_column"
    }
    for column_id in sorted(input_columns - {None}):
        table_id = col_to_table.get(column_id)
        if not table_id:
            continue
        visible_column_id = _read_anchor_id(read_anchor_by_column, column_id)
        if not visible_column_id or (table_id, visible_column_id) in existing:
            continue
        normalized.append({
            "data": {
                "id": f"{table_id}__to__{visible_column_id}_input_start",
                "source": table_id,
                "target": visible_column_id,
                "edgeType": "table_to_column",
                "color": "#10b981",
                "opacity": 0.78,
                "width": 1.8,
            }
        })
        existing.add((table_id, visible_column_id))


def _build_read_anchors(
    input_columns: set[str],
    output_columns: set[str],
    col_to_table: dict[str, str],
    node_by_id: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """为中间表字段生成展示用读取锚点，避免复用同一字段节点造成双向箭头"""
    anchors: dict[str, list[dict[str, Any]]] = {}
    for column_id in sorted((input_columns & output_columns) - {None}):
        table_id = col_to_table.get(column_id)
        column = node_by_id.get(column_id)
        if not table_id or not column or column.get("nodeType") != "column":
            continue
        table = node_by_id.get(table_id, {})
        anchor_id = f"{column_id}__read_anchor"
        label = column.get("label") or column.get("name") or column.get("fullName") or column_id
        table_label = table.get("fullName") or table.get("label") or table_id
        full_name = column.get("fullName") or f"{table_label}.{label}"
        anchor_node = {
            "data": {
                **column,
                "id": anchor_id,
                "label": label,
                "fullName": full_name,
                "columnRole": "read_anchor",
                "sourceColumnId": column_id,
                "tableId": table_id,
                "degree": "",
            }
        }
        anchor_edge = {
            "data": {
                "id": f"{table_id}__to__{anchor_id}",
                "source": table_id,
                "target": anchor_id,
                "edgeType": "table_to_column",
                "color": "#10b981",
                "opacity": 0.78,
                "width": 1.8,
            }
        }
        anchors[column_id] = [anchor_node, anchor_edge]
    return anchors


def _read_anchor_id(read_anchor_by_column: dict[str, list[dict[str, Any]]], column_id: str | None) -> str | None:
    """若字段有读取锚点，则返回锚点节点 ID"""
    anchor = read_anchor_by_column.get(column_id or "")
    if not anchor:
        return column_id
    return anchor[0].get("data", {}).get("id") or column_id


def _edge_with_endpoints(base: dict[str, Any], source: str | None, target: str | None, suffix: str) -> dict[str, Any]:
    """复制边并替换端点，用于把下游依赖边接到读取锚点"""
    data = dict(base.get("data", {}))
    data.update({
        "id": f"{data.get('id')}_{suffix}",
        "source": source,
        "target": target,
    })
    return {**base, "data": data}


def _sql_logic_preview(sql: str, max_table_len: int = 28, max_len: int = 46) -> str:
    """生成 SQL 节点卡片上的短逻辑摘要"""
    compact = " ".join((sql or "").replace("\n", " ").split())
    if not compact:
        return "SQL"

    patterns = (
        r"\binsert\s+(?:overwrite|into)\s+(?:table\s+)?([`\"\w.\-]+)",
        r"\bcreate\s+(?:or\s+replace\s+)?table\s+([`\"\w.\-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            table = match.group(1).strip("`\"")
            short_table = _short_logic(table, max_table_len)
            return f"SQL -> {short_table}"

    return "SQL: " + _short_logic(compact, max_len)


def _short_logic(text: str, max_len: int = 34) -> str:
    """生成 Transform 节点可读的短逻辑标签"""
    compact = " ".join((text or "").replace("\n", " ").split())
    if not compact:
        return "expr"
    return compact if len(compact) <= max_len else compact[: max_len - 1] + "…"


def _same_column_name(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """判断透传字段是否没有重命名"""
    return (left.get("label") or left.get("fullName")) == (right.get("label") or right.get("fullName"))


def _edge_like(base: dict[str, Any], source: str, target: str, edge_type: str,
               color: str, opacity: float, width: float) -> dict[str, Any]:
    """基于已有边创建一条展示语义边"""
    data = dict(base.get("data", {}))
    data.update({
        "id": f"{data.get('id')}_{edge_type}",
        "source": source,
        "target": target,
        "edgeType": edge_type,
        "color": color,
        "opacity": opacity,
        "width": width,
    })
    return {**base, "data": data}


class PlaygroundHandler(BaseHTTPRequestHandler):
    """SqlGraph Playground HTTP 处理器"""

    server_version = "SqlGraphPlayground/0.1"

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send_html(PLAYGROUND_HTML)
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/api/parse":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw or "{}")
            sql = (payload.get("sql") or "").strip()
            if not sql:
                raise ValueError("SQL 不能为空")
            data = graph_to_playground_payload(
                sql=sql,
                dialect=payload.get("dialect") or None,
                name=payload.get("name") or "playground_sql",
            )
            self._send_json(data)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)

    def log_message(self, fmt, *args):
        return

    def _send_html(self, html: str):
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, Any], status: int = 200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def find_free_port(host: str = "127.0.0.1", start: int = 8765) -> int:
    """寻找可用端口"""
    port = start
    while port < start + 100:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                port += 1
    raise RuntimeError("No free port found for SqlGraph playground")


def serve_playground(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> str:
    """启动本地 SQL Playground 服务"""
    if port <= 0:
        port = find_free_port(host)
    try:
        server = ThreadingHTTPServer((host, port), PlaygroundHandler)
    except OSError:
        fallback_port = find_free_port(host, port + 1)
        print(f"Port {port} is in use, using {fallback_port} instead.", flush=True)
        port = fallback_port
        server = ThreadingHTTPServer((host, port), PlaygroundHandler)
    url = f"http://{host}:{port}/"
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"SqlGraph Playground: {url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return url
