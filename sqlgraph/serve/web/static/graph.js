// Shared Cytoscape renderer for viewer and playground pages.
(function(){
  if (window.cytoscape && window.cytoscapeDagre) { cytoscape.use(cytoscapeDagre); }
  let cy = null;

  function toElements(data){
    if (data.elements) return data.elements;
    const nodes = (data.nodes||[]).map(n => ({ data: {
      id: n.id, label: n.full_name || n.name || n.id, nodeType: n.node_type,
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
    cy = cytoscape({
      container,
      elements: toElements(data),
      style: [
        {selector:'node',style:{'label':'data(label)','font-size':10,'background-color':'#64b5f6','color':'#e5e7eb','text-valign':'bottom'}},
        {selector:'node[nodeType="column"]',style:{'background-color':'#66bb6a','width':12,'height':12}},
        {selector:'node[nodeType="sql"]',style:{'shape':'round-rectangle','background-color':'#7c3aed','color':'#fff'}},
        {selector:'node[nodeType="transform"]',style:{'shape':'diamond','background-color':'#ffa726'}},
        {selector:'edge',style:{'curve-style':'bezier','target-arrow-shape':'triangle','line-color':'#94a3b8','target-arrow-color':'#94a3b8','width':1.2,'arrow-scale':.7}}
      ],
      layout:{name:'dagre', rankDir:'LR', nodeSep:36, rankSep:110}
    });
    cy.on('tap','node', evt => {
      if (window.onGraphNodeTap) window.onGraphNodeTap(evt.target.id());
    });
  };
})();
