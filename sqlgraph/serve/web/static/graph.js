// Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

// Shared Cytoscape renderer for viewer and playground pages.
(function(){
  if (window.cytoscape && window.cytoscapeDagre) { cytoscape.use(cytoscapeDagre); }
  let cy = null;
  let selectedNodeId = null;
  const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function graphLabel(node){
    const raw = node.name || node.full_name || node.id || '';
    return raw.length > 38 ? `${raw.slice(0, 35)}…` : raw;
  }

  function toElements(data){
    if (data.elements) return data.elements;
    const nodes = (data.nodes||[]).map(n => ({ data: {
      id: n.id, label: graphLabel(n), nodeType: n.node_type,
      writeSqlCount: n.writeSqlCount||0, readSqlCount: n.readSqlCount||0
    }}));
    const edges = (data.edges||[]).map(e => ({ data: {
      id: e.id, source: e.source, target: e.target, edgeType: e.type
    }}));
    return nodes.concat(edges);
  }

  window.renderGraph = function(data){
    const container = document.getElementById('cy');
    if (!container) return;
    container.classList.toggle('has-graph', Boolean((data.nodes||data.elements||[]).length));
    selectedNodeId = null;
    cy = cytoscape({
      container,
      elements: toElements(data),
      minZoom: 0.08,
      maxZoom: 1.4,
      style: [
        {selector:'node',style:{'label':'data(label)','font-size':9,'background-color':'#60a5fa','border-width':1,'border-color':'#bfdbfe','color':'#e5e7eb','text-valign':'bottom','text-margin-y':7,'text-wrap':'ellipsis','text-max-width':120}},
        {selector:'node[nodeType="table"]',style:{'shape':'round-rectangle','width':40,'height':24,'background-color':'#2563eb','border-color':'#93c5fd'}},
        {selector:'node[nodeType="column"]',style:{'background-color':'#22c55e','border-color':'#86efac','width':12,'height':12}},
        {selector:'node[nodeType="sql"]',style:{'shape':'round-rectangle','background-color':'#7c3aed','border-color':'#c4b5fd','color':'#fff'}},
        {selector:'node[nodeType="transform"]',style:{'shape':'diamond','background-color':'#f59e0b','border-color':'#fde68a'}},
        {selector:'node:selected',style:{'border-width':3,'border-color':'#f8fafc','overlay-color':'#38bdf8','overlay-opacity':0.18,'overlay-padding':8}},
        {selector:'edge',style:{'curve-style':'bezier','target-arrow-shape':'triangle','line-color':'#64748b','target-arrow-color':'#64748b','width':1.2,'arrow-scale':.7}},
        {selector:'edge[edgeType="table_lineage"]',style:{'line-color':'#38bdf8','target-arrow-color':'#38bdf8','width':2}},
        {selector:'edge[edgeType="reads_from"]',style:{'line-style':'dashed','line-color':'#a78bfa','target-arrow-color':'#a78bfa'}},
        {selector:'edge[edgeType="writes_to"]',style:{'line-style':'dashed','line-color':'#fb7185','target-arrow-color':'#fb7185'}}
      ],
      layout:{name:'dagre', rankDir:'LR', nodeSep:44, rankSep:128, animate:!prefersReducedMotion}
    });
    cy.ready(() => {
      if (cy.zoom() > 1) {
        cy.zoom(1);
        cy.center();
      }
    });
    cy.on('tap','node', evt => {
      selectedNodeId = evt.target.id();
      if (window.onGraphNodeTap) window.onGraphNodeTap(selectedNodeId);
    });
  };

  window.selectedGraphNodeId = function(){
    return selectedNodeId;
  };

  window.mergeGraph = function(data){
    if (!cy) {
      window.renderGraph(data);
      const rendered = toElements(data);
      return {
        nodes: rendered.filter(ele => ele.data && !ele.data.source).length,
        edges: rendered.filter(ele => ele.data && ele.data.source).length
      };
    }
    const elements = toElements(data);
    const existing = new Set(cy.elements().map(ele => ele.id()));
    const additions = elements.filter(ele => ele.data && ele.data.id && !existing.has(ele.data.id));
    if (additions.length) {
      cy.add(additions);
      cy.layout({name:'dagre', rankDir:'LR', nodeSep:44, rankSep:128, animate:!prefersReducedMotion}).run();
    }
    return {
      nodes: additions.filter(ele => ele.data && !ele.data.source).length,
      edges: additions.filter(ele => ele.data && ele.data.source).length
    };
  };
})();
