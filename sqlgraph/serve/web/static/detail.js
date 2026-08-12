// Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

// Shared detail panel with per-table read/write SQL groups (lazy full text).
(function(){
  function esc(s){ const d=document.createElement('div'); d.textContent=s==null?'':String(s); return d.innerHTML; }
  function fmt(v){
    if(v === null || v === undefined || v === '') return '';
    const num = Number(v);
    if(Number.isFinite(num)) return num.toLocaleString(undefined, {maximumFractionDigits: 4});
    return String(v);
  }

  function sqlGroup(title, items){
    if(!items || !items.length) return '';
    const rows = items.map(it => `
      <div class="sql-item">
        <button class="sql-head" type="button" data-sql-id="${esc(it.sqlId)}" aria-expanded="false">
          <strong title="${esc(it.name||it.sqlId)}">${esc(it.name||it.sqlId)}</strong>
          <span class="sql-src">${esc(it.sourceUri||'')}</span>
        </button>
        <div class="sql-preview">${esc(it.preview||'')}</div>
        <pre class="sql-full" id="full-${esc(it.sqlId)}" hidden></pre>
      </div>`).join('');
    return `<div class="sql-group"><h4>${esc(title)} <span>${items.length}</span></h4>${rows}</div>`;
  }

  function fieldList(columns){
    if(!columns || !columns.length) return '';
    const rows = columns.map(col => `
      <button class="field-link" type="button" data-node-id="${esc(col.id)}" title="${esc(col.tableName ? `${col.tableName}.${col.name}` : col.name)}">
        <span>${esc(col.name || col.id)}</span>
      </button>`).join('');
    return `<div class="field-section">
      <h4>字段列表 <span>${columns.length}</span></h4>
      <div class="field-list">${rows}</div>
    </div>`;
  }

  function lineageList(title, items){
    if(!items || !items.length) return '';
    const rows = items.map(item => `
      <div class="lineage-row">
        <strong title="${esc(item.tableName ? `${item.tableName}.${item.name}` : item.name)}">${esc(item.name || item.id)}</strong>
        <span>${esc(item.tableName || item.nodeType || '')}</span>
      </div>`).join('');
    return `<div class="field-section"><h4>${esc(title)} <span>${items.length}</span></h4>${rows}</div>`;
  }

  function transformList(items){
    if(!items || !items.length) return '';
    const rows = items.map(item => `
      <div class="lineage-row transform-row">
        <strong title="${esc(item.outputName || item.name || item.id)}">${esc(item.outputName || item.name || item.id)}</strong>
        <span title="${esc(item.expression || '')}">${esc(item.expression || item.name || '')}</span>
      </div>`).join('');
    return `<div class="field-section"><h4>计算表达式 <span>${items.length}</span></h4>${rows}</div>`;
  }

  function statsProfile(detail){
    const stats = detail && detail.stats;
    if(!stats || !stats.index) return '';
    const idx = stats.index;
    const analysis = (stats.analysis && stats.analysis.metrics) || {};
    const mode = stats.analysis && stats.analysis.mode;
    const analysisRows = [
      ['声明层级', analysis.declared_layer || analysis.layer],
      ['真实层级', analysis.graph_layer_max],
      ['层级漂移', analysis.layer_drift],
      ['PageRank', analysis.pagerank_reverse],
      ['Authority', analysis.hits_authority],
      ['K-Core', analysis.k_core],
      ['下游影响面', analysis.downstream_reachability_count],
      ['影响分', analysis.blast_score],
      ['社区', analysis.community_id],
      ['桥接分', analysis.bridge_score],
      ['异常分', analysis.rule_anomaly_score],
      ['产品分', analysis.product_score]
    ].filter(row => row[1] !== undefined && row[1] !== null && row[1] !== '');
    return `<div class="stats-profile">
      <h4>统计画像</h4>
      <div class="detail-stats">
        <span>${idx.upstreamCount||0} 上游表</span>
        <span>${idx.downstreamCount||0} 下游表</span>
        <span>${idx.degree||0} 表级度数</span>
      </div>
      ${analysisRows.length ? `<dl>${analysisRows.map(row => `<div><dt>${esc(row[0])}</dt><dd>${esc(fmt(row[1]))}</dd></div>`).join('')}</dl>` : `<p class="muted">${mode === 'index_only' ? '治理画像未加载。' : '该表暂无治理画像指标。'}</p>`}
    </div>`;
  }

  function detailTitle(node, detail){
    if(node.node_type === 'column' && detail.ownerTable){
      return `${detail.ownerTable.fullName || detail.ownerTable.name || detail.ownerTable.id}.${node.name || node.id}`;
    }
    return node.full_name || node.name || node.id;
  }

  function bindSqlToggles(box){
    box.querySelectorAll('.sql-head').forEach(head => {
      head.addEventListener('click', async () => {
        const id = head.getAttribute('data-sql-id');
        const pre = document.getElementById(`full-${id}`);
        if(!pre) return;
        if(pre.hidden && !pre.textContent){
          const sql = await (await fetch(`/api/sql/${encodeURIComponent(id)}`)).json();
          pre.textContent = (sql && sql.sql_content) || '(无原文)';
        }
        pre.hidden = !pre.hidden;
        head.setAttribute('aria-expanded', String(!pre.hidden));
      });
    });
  }

  function bindFieldLinks(box){
    box.querySelectorAll('.field-link').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-node-id');
        if(!id) return;
        const detail = await (await fetch(`/api/node/${encodeURIComponent(id)}`)).json();
        window.renderDetail(detail);
      });
    });
  }

  window.renderDetail = function(detail){
    const box = document.getElementById('detail');
    if(!box) return;
    if(!detail || !detail.node){ box.innerHTML = '<div class="empty">选择图中的节点查看详情。</div>'; return; }
    const n = detail.node;
    const title = detailTitle(n, detail);
    const relatedSqls = detail.sqls || [];
    box.innerHTML = `
      <div class="detail-title">
        <p class="eyebrow">节点详情</p>
        <h3 title="${esc(title)}">${esc(title)}</h3>
      </div>
      <div class="badge">${esc(n.node_type)}</div>
      ${n.node_type === 'table' ? `<div class="detail-stats">
        <span>${n.writeSqlCount||0} 写入 SQL</span>
        <span>${n.readSqlCount||0} 读取 SQL</span>
      </div>` : ''}
      ${n.node_type === 'column' && detail.ownerTable ? `<div class="owner-table">所属表：${esc(detail.ownerTable.fullName || detail.ownerTable.name || detail.ownerTable.id)}</div>` : ''}
      ${statsProfile(detail)}
      ${fieldList(detail.columns)}
      ${lineageList('上游字段', detail.upstream)}
      ${transformList(detail.transforms)}
      ${lineageList('下游字段', detail.downstream)}
      ${sqlGroup('写入 SQL', detail.writeSqls)}
      ${sqlGroup('读取 SQL', detail.readSqls)}
      ${sqlGroup('相关 SQL', relatedSqls)}`;
    bindSqlToggles(box);
    bindFieldLinks(box);
  };
})();
