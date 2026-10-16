const {test}=require('node:test'),assert=require('node:assert/strict');
const layout=require('../tracker/web/map-layout.js'),history={project:layout.requestedHistory};
function graph(selection={support:{value:'supported'},scope:{value:'same_undertaking'},terms:{value:'equivalent'}}){
 const nodes=[{id:'u1',kind:'unit',event_index:1,trajectory_id:'main',activity:'orient',properties:{actor:'user',kind:'semantic',source:{text:'Before'}}},
 {id:'u2',kind:'unit',event_index:2,trajectory_id:'main',activity:'orient',properties:{actor:'user',kind:'semantic',source:{text:'After'}}},
 ...[1,2].map(i=>({id:'v'+i,kind:'requested_work_version',event_index:i,trajectory_id:'main',properties:{id:'work',kind:'work',text:'Requested wording '+i,status:'requested',source_unit_id:'u'+i}}))];
 return {nodes,edges:[{id:'r',source:'v2',target:'v1',type:'updates_requested_version',properties:{operation:'revise',status:'selected',selections:selection}}],semantic_context:{requested_changes:{counts:{revisions:1}}}};
}
test('versions preserve explicit before/after edge and source unit identity',()=>{
 const g=graph(),original=JSON.stringify(g),p=history.project(g);
 assert.equal(p.groups.length,1);assert.deepEqual(p.groups[0].versions.map(v=>v.label),['Introduced request','Same requested terms']);
 assert.equal(p.groups[0].versions[1].before.id,'v1');assert.equal(p.groups[0].versions[1].source_unit_id,'u2');assert.equal(JSON.stringify(g),original);
});
test('unsupported interpretation never becomes changed terms or a goal-drift label',()=>{
 const p=history.project(graph({support:{value:'unsupported'}})),v=p.groups[0].versions[1];
 assert.equal(v.label,'Record interpretation disputed');assert.equal(v.review,true);
 for(const selection of [{},{support:{value:'supported'}},{support:{value:'supported'},scope:{value:'same_undertaking'}}])assert.equal(history.project(graph(selection)).groups[0].versions[1].review,true);
});
test('same record ID in different trajectories does not merge histories',()=>{
 const g=graph();g.nodes.push({...g.nodes[2],id:'other',trajectory_id:'other'});
 assert.equal(history.project(g).groups.length,2);
});
test('requested versions cannot become extra unit cards or temporal transitions',()=>{
 const g=graph(),p=layout.project(g);
 assert.deepEqual(p.nodes.map(n=>n.id),['u1','u2']);
 assert.deepEqual(p.edges.map(e=>[e.source,e.target,e.type]),[['u1','u2','source_order']]);
});
test('no requested-change observation is not an empty measured history',()=>{
 assert.equal(history.project({semantic_context:{}}),null);
});
test('dispatch context retains work choices and keeps conditions distinct from satisfaction',()=>{
 const g=graph();g.nodes.push({id:'state',kind:'requested_state',trajectory_id:'main',properties:{version_ids:['v1','condition']}});
 g.nodes.push({id:'requested-version:condition',kind:'requested_work_version',trajectory_id:'main',properties:{kind:'condition',version_id:'condition',text:'Use draft address.'}});
 const first=g.nodes.find(n=>n.id==='v1');first.properties.version_id='v1';first.id='requested-version:v1';
 g.edges.push({id:'context',source:'u2',target:'state',type:'request_context_at_dispatch',properties:{choices:{v1:'none'}}},
  {id:'member2',source:'state',target:'requested-version:condition',type:'contains_requested_version'},
  {id:'member1',source:'state',target:'requested-version:v1',type:'contains_requested_version'});
 const context=layout.requestContext(g,'u2');
 assert.equal(context.versions[0].label,'No specific work correspondence selected');
 assert.equal(context.versions[1].label,'Condition in context · satisfaction not inspected');
 assert.equal(layout.requestContext(g,'u1'),null);
 assert.deepEqual(layout.project(g).nodes.map(n=>n.id),['u1','u2']);
});

test('recorded clauses remain typed, ordered historical objects outside activity layout',()=>{
 const g=graph();delete g.semantic_context.requested_changes;g.semantic_context.requested_history={counts:{revisions:1}};
 const record=g.nodes.find(n=>n.id==='v2');record.properties.kind='condition';record.properties.clauses=[{id:'check'},{id:'claim'}];
 g.edges[0].properties={operation:'revise',status:'not_inspected'};
 for(const [i,kind]of ['requested_check','attributed_claim'].entries()){
  g.nodes.push({id:'clause'+i,kind:'requested_clause_version',event_index:2,trajectory_id:'main',properties:{kind,text:kind}});
  g.edges.unshift({id:'member'+i,source:'v2',target:'clause'+i,type:'contains_requested_clause',properties:{position:i}});
 }
 g.edges.push({id:'retired',source:'v2',target:'clause1',type:'retires_requested_clause',properties:{reason:'Changed subject'}});
 const value=layout.requestedClauses(g,'v2');assert.equal(value.status,'structured');
 assert.deepEqual(value.clauses.map(c=>c.node.properties.kind),['requested_check','attributed_claim']);
 assert.equal(value.retired[0].edge.properties.reason,'Changed subject');
 assert.equal(layout.requestedHistory(g).groups[0].versions[1].label,'Recorded revision · terms not compared');
 assert.deepEqual(layout.project(g).nodes.map(n=>n.id),['u1','u2']);
 delete record.properties.clauses;assert.equal(layout.requestedClauses(g,'v2').status,'unstructured');
 delete g.semantic_context.requested_history;assert.equal(layout.requestedClauses(g,'v2').status,'not_projected');
 assert.equal(layout.requestedClauses(g,'v1'),null);
});
