const test=require('node:test'),assert=require('node:assert/strict');
const {project,declarationInFocus}=require('../tracker/web/behavior-blueprint.js');
const make=(id,kind,event,actor='agent')=>({id,kind,actor,trajectory_id:'t',activity:kind==='semantic'?'orient':undefined,source:{event_id:event,start:0,end:1},content:{summary:{text:id}}});
test('work result links retain scope identity and are distinct from tool completion',()=>{
 const run={events:['1','2'].map((id,index)=>({id,index}))},units=[make('scope','semantic','1'),make('response','feedback','2')];
 const relations=[{from:'response',to:'scope',type:'records_result_for_declared_work',declared_work_id:'w',work_result:'not_established'},
  {from:'response',to:'scope',type:'records_result_for_plan_stage',plan_step_id:'s',work_result:'fulfilled'}];
 const g=project({units,relations},run,new Set(['scope','response']));
 assert.equal(g.edges.find(e=>e.family==='declaration').label,'Work result not established');
 assert.equal(g.edges.find(e=>e.family==='plan').label,'Work scope fulfilled');
 assert.equal(g.edges.find(e=>e.family==='plan').plan_step_id,'s');
 assert.equal(declarationInFocus(g.edges.find(e=>e.family==='declaration'),'declared:other','declaration'),false);
});
test('blueprint preserves unit identities and typed backward links',()=>{
 const run={events:['1','2','3','4'].map((id,index)=>({id,index}))};
 const units=[make('idea','semantic','1'),make('action','action','2'),make('feedback','feedback','3','environment'),make('again','action','4')];
 const relations=[{from:'feedback',to:'action',type:'feedback_for'},{from:'again',to:'action',type:'same_action_target'}];
 const doc={units,relations},before=JSON.stringify(doc),g=project(doc,run,new Set(units.map(u=>u.id)));
 assert.equal(g.nodes.length,4);assert.equal(new Set(g.nodes.map(n=>n.id)).size,4);assert.equal(g.nodes[1].row,g.nodes[2].row);
 assert.equal(g.edges.find(e=>e.family==='return').from,'again');assert.equal(g.edges.find(e=>e.family==='return').to,'action');assert.equal(JSON.stringify(doc),before);
 assert.ok(!g.edges.some(e=>['recovery','deviation','completed'].includes(e.type)));
});
test('filtered source order discloses gaps and never adds missing relation endpoints',()=>{
 const run={events:['1','2','3'].map((id,index)=>({id,index}))};const units=[make('a','semantic','1'),make('hidden','action','2'),make('b','semantic','3')];
 const g=project({units,relations:[{from:'b',to:'hidden',type:'assesses'}]},run,new Set(['a','b']));
 assert.equal(g.hidden,1);assert.equal(g.edges.length,1);assert.equal(g.edges[0].hidden,1);assert.equal(g.edges[0].family,'order');
});
test('stated-work identity remains distinct from action recurrence',()=>{
 const run={events:['1','2'].map((id,index)=>({id,index}))},units=[make('a','semantic','1'),make('b','semantic','2')];
 const relation={from:'b',to:'a',type:'declares_same_work_as',from_item_id:'w1',to_item_id:'w2'};
 const g=project({units,relations:[relation]},run,new Set(['a','b']));
 const edge=g.edges.find(e=>e.type==='declares_same_work_as');assert.equal(edge.family,'declaration');assert.equal(edge.from_item_id,'w1');
 assert.equal(g.edges.filter(e=>e.family==='return').length,0);
});
test('a focused history shows only its work identity even when another shares both units',()=>{
 const a={family:'declaration',declared_work_id:'a'},b={family:'declaration',declared_work_id:'b'};
 assert.equal(declarationInFocus(a,'declared:a','declaration'),true);
 assert.equal(declarationInFocus(b,'declared:a','declaration'),false);
 assert.equal(declarationInFocus(b,'declared:a','all'),true);
 assert.equal(declarationInFocus({family:'feedback'},'declared:a','declaration'),true);
});
