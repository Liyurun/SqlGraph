// Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
// SPDX-License-Identifier: Apache-2.0

// Shared detail panel with per-table read/write SQL groups (lazy full text).
(function(){
  function esc(s){ const d=document.createElement('div'); d.textContent=s==null?'':String(s); return d.innerHTML; }

  function sqlGroup(title, items){
    if(!items || !items.length) return '';
    const rows = items.map(it => `
      <div class="sql-item">
        <div class="sql-head" data-sql-id="${esc(it.sqlId)}">
          <strong>${esc(it.name||it.sqlId)}</strong>
          <span class="sql-src">${esc(it.sourceUri||'')}</span>
        </div>
        <div class="sql-preview">${esc(it.preview||'')}</div>
        <pre class="sql-full" id="full-${esc(it.sqlId)}" hidden></pre>
      </div>`).join('');
    return `<div class="sql-group"><h4>${esc(title)}</h4>${rows}</div>`;
  }

  window.renderDetail = function(detail){
    const box = document.getElementById('detail');
    if(!box) return;
    if(!detail || !detail.node){ box.innerHTML = '<div class="empty">无详情</div>'; return; }
    const n = detail.node;
    box.innerHTML = `
      <h3>${esc(n.full_name || n.name || n.id)}</h3>
      <div class="badge">${esc(n.node_type)}</div>
      ${sqlGroup('写入 SQL', detail.writeSqls)}
      ${sqlGroup('读取 SQL', detail.readSqls)}`;
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
      });
    });
  };
})();
