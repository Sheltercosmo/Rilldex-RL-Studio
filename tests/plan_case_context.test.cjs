const {test}=require('node:test');
const assert=require('node:assert/strict');
const C=require('../tracker/web/plan-case-context.js');
function fixture(){
 const items=[{id:'i1',text:'Fix',status:'completed'},{id:'i2',text:'Fix',status:'pending'},{id:'i3',text:'Fix',status:'completed'}];
 const snapshots=items.map((item,i)=>({id:'s'+(i+1),event_id:'e'+(i+1),items:[item],actor:'agent',context_id:'a',profile:'native'}));
 const nodes=snapshots.flatMap((s,i)=>[{id:'event:'+s.event_id,kind:'event',event_index:i,trajectory_id:'t',properties:{id:s.event_id}},
  {id:s.id,kind:'declared_plan_snapshot',event_index:i,trajectory_id:'t',properties:s},
  {id:items[i].id,kind:'declared_plan_item',event_index:i,trajectory_id:'t',properties:items[i]}]);
 return {graph:{id:'g',nodes},snapshots,items};
}
function reopened(f){return {id:'case',label:'Fix',status:'reopened_report',taken:true,declared_plan_change:{previous_id:'s1',current_id:'s2',event_ids:['e1','e2'],before:f.items[0],after:f.items[1],candidates:[f.items[1]]}};}
test('initial item is scoped to its captured declaration, not latest completion',()=>{
 const f=fixture(),r={id:'initial',label:'Fix',status:'initially_reported_complete',taken:true,plan_declaration:f.snapshots[0],initial_item:f.items[0]};
 const c=C.resolve(f.graph,r);assert.equal(c.cutoff_event_id,'e1');assert.deepEqual(c.item_ids,['i1']);assert.equal(c.scope,'initial captured item');
});
test('reopening focuses both exact witnesses and ends at the next declaration',()=>{
 const f=fixture(),c=C.resolve(f.graph,reopened(f));assert.equal(c.cutoff_event_id,'e2');assert.deepEqual(c.item_ids,['i1','i2']);assert.equal(c.summary,'reported complete → reported pending');
 assert(C.matches({source_node_ids:['i1','i2','i3']},c));assert(!C.matches({source_node_ids:['unrelated']},c));
});
test('unknown item correspondence highlights candidates without establishing identity',()=>{
 const f=fixture(),r=reopened(f);r.taken=null;r.status='unknown';r.declared_plan_change.after=null;r.declared_plan_change.reason='renamed_item';
 const c=C.resolve(f.graph,r);assert.equal(c.taken,null);assert.match(c.summary,/unresolved/);assert.equal(c.reason,'renamed_item');assert.deepEqual(c.item_ids,['i1','i2']);
});
test('empty declarations remain a list case, with no fabricated item',()=>{
 const f=fixture();f.snapshots[0].items=[];const c=C.resolve(f.graph,{id:'empty',label:'Empty',status:'issued_declaration',taken:true,plan_declaration:f.snapshots[0]});
 assert.deepEqual(c.item_ids,[]);assert.equal(c.summary,'0 recorded list entries');assert(C.matches({source_node_ids:['s1']},c));
});
test('missing item, declaration, source cutoff and inconsistent membership fail closed',()=>{
 for(const kind of ['item','snapshot','event','membership']){const f=fixture(),r=reopened(f);
  if(kind==='item')f.graph.nodes=f.graph.nodes.filter(n=>n.id!=='i2');
  if(kind==='snapshot')f.graph.nodes=f.graph.nodes.filter(n=>n.id!=='s2');
  if(kind==='event')f.graph.nodes=f.graph.nodes.filter(n=>n.id!=='event:e2');
  if(kind==='membership')f.snapshots[1].items=[];
  assert.throws(()=>C.resolve(f.graph,r));
 }
});
test('a case crossing declared profiles keeps both roots visible',()=>{
 const f=fixture();f.snapshots[1].profile='other';const c=C.resolve(f.graph,reopened(f));assert.equal(c.comparable_lanes,false);
 const data={roots:['r1','r2'],nodes:[{id:'x',source_node_ids:['i1']},{id:'y',source_node_ids:['i2']}],links:[{source:'r1',target:'x',type:'contains'},{source:'r2',target:'y',type:'contains'}]};
 assert.equal(C.rootFor(data,c),'all');
});
test('a later existing event cannot silently replace the measured cutoff',()=>{
 const f=fixture(),r=reopened(f);r.declared_plan_change.event_ids=['e1','e3'];assert.throws(()=>C.resolve(f.graph,r),/cutoff differs/);
});
test('root selection uses source identity rather than repeated task text',()=>{
 const f=fixture(),c=C.resolve(f.graph,reopened(f));const data={roots:['wrong','right'],nodes:[{id:'x',label:'Fix',source_node_ids:['other']},{id:'y',label:'Fix',source_node_ids:['i1']}],links:[{source:'wrong',target:'x',type:'contains'},{source:'right',target:'y',type:'contains'}]};
 assert.equal(C.rootFor(data,c),'right');assert.equal(C.rootFor(data,null),null);
});
test('unrelated measured cases do not receive a plan interpretation',()=>assert.equal(C.resolve(fixture().graph,{id:'other',next_check:true}),null));
test('context construction never changes the saved graph or case',()=>{
 const f=fixture(),r=reopened(f),before=JSON.stringify([f.graph,r]);C.resolve(f.graph,r);assert.equal(JSON.stringify([f.graph,r]),before);
});
test('monitor links carry the source population instead of inheriting an unrelated session filter',()=>{
 const receipt={monitor:{id:'m'},run:{metadata:{environment:'tool-world'}}};
 let q=new URL(C.monitorUrl(receipt),'http://localhost').searchParams;assert.equal(q.get('experiment'),'__unassigned__');assert.equal(q.get('environment'),'tool-world');
 receipt.run.metadata.experiment='RL & tool';q=new URL(C.monitorUrl(receipt),'http://localhost').searchParams;assert.equal(q.get('experiment'),'RL & tool');assert.equal(q.get('monitor'),'m');assert.equal(C.monitorUrl(null),null);
});
