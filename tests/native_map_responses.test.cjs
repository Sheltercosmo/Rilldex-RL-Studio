const {test}=require('node:test');
const assert=require('node:assert/strict');
const L=require('../tracker/web/map-layout.js');
const S=require('../tracker/web/rollout-story.js');
const R=require('../tracker/web/unit-reading.js');
const P=require('../tracker/web/inspection-paths.js');
const event=(id,kind,index,text)=>({id:'event:'+id,kind:'event',trajectory_id:'main',event_index:index,properties:{id,kind,text,context_id:'session-1'}});
const edge=(id,source,target,type)=>({id,source,target,type,properties:{basis:'source_action_result_identity'}});
function fixture(){
 const events=[event('a','action',0,'check("😀")'),event('r','observation',1,'ERROR: expected timezone'),event('b','action',2,'check("ISO")'),event('s','observation',3,'PASS')];
 const units=events.map(e=>({id:'unit:'+e.properties.id,kind:'unit',activity:e.properties.kind==='action'?'execute':'orient',trajectory_id:e.trajectory_id,event_index:e.event_index,properties:{kind:e.properties.kind==='action'?'action':'feedback',source:{event_id:e.properties.id,start:0,end:Array.from(e.properties.text).length,text:e.properties.text}}}));
 const graph={nodes:[...events,...units],edges:[...units.map(u=>edge('g:'+u.id,u.id,'event:'+u.properties.source.event_id,'grounded_in')),edge('native:r','event:r','event:a','response_to'),edge('native:s','event:s','event:b','response_to'),edge('same','unit:b','unit:a','same_action_target')]};
 return graph;
}
test('native call returns survive semantic cards in unit, story and paired-attempt views',()=>{
 const g=fixture(),before=JSON.stringify(g),v=L.project(g),returns=v.edges.filter(e=>e.type==='response_to');
 assert.deepEqual(returns.map(e=>[e.id,e.source,e.target]),[['native:r','unit:r','unit:a'],['native:s','unit:s','unit:b']]);
 assert.equal(returns[0].stored_source,'event:r');assert.equal(returns[0].stored_target,'event:a');
 assert.equal(v.byId.get('unit:r').row,v.byId.get('unit:a').row);
 assert.deepEqual(R.sections(v,'unit:a').find(s=>s.key==='result').rows.map(r=>r.node.id),['unit:r']);
 assert.deepEqual(S.project(g,{events:[]},v).moments.filter(m=>m.actions.length).map(m=>m.responses.map(r=>r.node.id)),[['unit:r'],['unit:s']]);
 const pairs=P.catalog(g,v).find(g=>g.id==='attempt-pairs').cases;
 assert.deepEqual(pairs[0].attempts.map(a=>a.responses.map(n=>n.id)),[['unit:r'],['unit:s']]);
 assert.equal(JSON.stringify(g),before);assert.deepEqual(L.project(g),v);
});
test('native and semantic witnesses do not duplicate a returned response',()=>{
 const g=fixture();g.edges.push(edge('semantic:r','unit:r','unit:a','feedback_for'));
 const v=L.project(g),links=v.edges.filter(e=>['feedback_for','response_to'].includes(e.type)&&e.source==='unit:r');
 assert.equal(links.length,1);assert.equal(links[0].id,'semantic:r');
 assert.equal(v.nativeResponses.find(r=>r.edge.id==='native:r').visible_edge_id,'semantic:r');
});
test('split action annotations keep call-level feedback without choosing a sub-action',()=>{
 const g=fixture(),a=g.nodes.find(n=>n.id==='unit:a');g.nodes.push({...a,id:'unit:a2'});g.edges.push(edge('g:a2','unit:a2','event:a','grounded_in'));
 const v=L.project(g);assert.equal(v.edges.some(e=>e.id==='native:r'),false);
 for(const id of ['unit:a','unit:a2']){const rows=L.capturedResponses(v,id);assert.equal(rows.length,1);assert.equal(rows[0].response.properties.text,'ERROR: expected timezone');assert.equal(rows[0].edge.target,'event:a');}
 const pairs=P.catalog(g,v).find(g=>g.id==='attempt-pairs').cases;
 assert.equal(pairs[0].attempts[0].responses.length,0);assert.equal(pairs[0].attempts[0].captured_responses.length,1);
 assert.doesNotMatch(R.sections(v,'unit:a').find(s=>s.key==='result').empty,/No response is bound/);
});
test('partial response excerpts do not acquire a whole-call arrow or hide the full result',()=>{
 const g=fixture(),u=g.nodes.find(n=>n.id==='unit:r');u.properties.source={event_id:'r',start:7,end:15,text:'expected'};
 const v=L.project(g);assert.equal(v.edges.some(e=>e.id==='native:r'),false);
 assert.equal(L.capturedResponses(v,'unit:a')[0].response.properties.text,'ERROR: expected timezone');
 assert.equal(L.capturedResponses(v,'unit:r')[0].action.id,'event:a');
 assert.equal(R.foot(v,v.byId.get('unit:a')),'Call feedback available');
 assert.match(R.foot(v,v.byId.get('unit:r')),/^Call linked/);
 const s=S.project(g,{},v),attempt=s.moments.find(m=>m.actions.some(n=>n.id==='unit:a'));
 assert.equal(S.matches(attempt,'missing'),false);assert.equal(S.matches(attempt,'output'),true);
 assert.equal(S.matches(attempt,'all','timezone'),true);assert.equal(attempt.hasSignal,true);
 assert.equal(s.counts.notableOutputs,1);
});

test('split response cards preserve a single whole-call result without an arbitrary arrow',()=>{
 const g=fixture(),r=g.nodes.find(n=>n.id==='unit:r');g.nodes.push({...r,id:'unit:r2'});g.edges.push(edge('g:r2','unit:r2','event:r','grounded_in'));
 const v=L.project(g);assert.equal(v.edges.some(e=>e.id==='native:r'),false);
 assert.equal(L.capturedResponses(v,'unit:a').length,1);assert.equal(L.capturedResponses(v,'unit:r2').length,1);
 assert.equal(S.project(g,{},v).counts.notableOutputs,1);
});

test('whole-event projection requires matching spans and exact captured text',()=>{
 for(const patch of [{start:1},{end:100},{text:'different output'},{end:undefined}]){
  const g=fixture(),r=g.nodes.find(n=>n.id==='unit:r');Object.assign(r.properties.source,patch);
  const v=L.project(g);assert.equal(v.edges.some(e=>e.id==='native:r'),false);assert.equal(L.capturedResponses(v,'unit:a').length,1);
 }
});

test('source-only return witnesses are preserved without semantic remapping',()=>{
 const g=fixture();g.nodes=g.nodes.filter(n=>n.kind==='event');g.edges=g.edges.filter(e=>e.type==='response_to');
 g.edges.push({...g.edges[0],id:'native:r2'});
 const v=L.project(g);assert.deepEqual(v.edges.map(e=>[e.id,e.source,e.target]),g.edges.map(e=>[e.id,e.source,e.target]));
 assert.equal(L.capturedResponses(v,'event:a').length,0);
});
test('cross-session, cross-trajectory, copied or excluded source links are not restored',()=>{
 for(const mutate of [g=>g.nodes[1].properties.context_id='session-2',g=>g.nodes[1].trajectory_id='other',g=>g.nodes[1].properties.copied_context=true]){
  const g=fixture();mutate(g);const v=L.project(g);assert.equal(v.edges.some(e=>e.id==='native:r'),false);assert.equal(L.capturedResponses(v,'unit:a').length,0);
 }
 const v=L.project(fixture(),['native:r']);assert.equal(v.edges.some(e=>e.id==='native:r'),false);assert.equal(L.capturedResponses(v,'unit:a').length,0);
});

test('foundation source order does not override captured session or visibility boundaries',()=>{
 for(const mutate of [g=>g.nodes[1].properties.context_id='session-2',g=>g.nodes[1].properties.agent_visible=false,g=>g.nodes[1].properties.agent_visibility='not_established']){
  const g=fixture();mutate(g);const order={nodes:Object.fromEntries(g.nodes.map(n=>[n.id,{scope:['main'],index:n.event_index}]))};
  const v=L.project(g,[],[],order);assert.equal(v.edges.some(e=>e.id==='native:r'),false);assert.equal(L.capturedResponses(v,'unit:a').length,0);
 }
 const g=fixture(),order={nodes:Object.fromEntries(g.nodes.map(n=>[n.id,{scope:['main'],index:n.event_index,reason:'parallel_dispatch'}]))};
 assert.equal(L.project(g,[],[],order).edges.filter(e=>e.type==='response_to').length,2);
 order.nodes['event:r'].hidden=true;assert.equal(L.project(g,[],[],order).edges.some(e=>e.id==='native:r'),false);
});
test('source fallback after rejected annotations retains the same original call identity',()=>{
 const g=fixture(),v=L.project(g,[],['unit:a']);const e=v.edges.find(e=>e.id==='native:r');
 assert.equal(e.target,'event:a');assert.equal(e.source,'unit:r');assert.equal(e.id,'native:r');
});
test('parallel results bind by saved identities despite arrival order; missing links stay missing',()=>{
 const g=fixture();g.nodes[1].event_index=8;g.nodes[3].event_index=5;
 const v=L.project(g);assert.deepEqual(v.edges.filter(e=>e.type==='response_to').map(e=>[e.source,e.target]),[['unit:r','unit:a'],['unit:s','unit:b']]);
 g.edges=g.edges.filter(e=>e.type!=='response_to');assert.equal(L.project(g).edges.some(e=>e.type==='response_to'),false);
});
