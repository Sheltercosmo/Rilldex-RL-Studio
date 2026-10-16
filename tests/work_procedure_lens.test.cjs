const {test}=require('node:test');
const assert=require('node:assert/strict');
const {project,comparisonFor,dispatchDiff}=require('../tracker/web/work-timeline.js');
function setup(){
 const visit=(id,g,positions)=>({id,group_id:g,target:g,order_known:true,positions,occurrences:positions.map(i=>({unit_id:'u'+i,order_known:true}))});
 const visits=[visit('first','x',[1]),visit('other','y',[2]),visit('later','x',[3,4,5])];
 const episodes=[{id:'a',previous_unit_id:'u1',current_unit_id:'u3',category:'returned'},{id:'b',previous_unit_id:'u3',current_unit_id:'u4',category:'continued'},{id:'c',previous_unit_id:'u4',current_unit_id:'u5',category:'continued'}];
 const data={graph_id:'g',run_id:'r',source_hash:'s',visits,episodes,paths:[{visit_ids:visits.map(v=>v.id)}],links:episodes.map(e=>({id:'l'+e.id,episode_id:e.id,type:'same_work_return',source:'later',target:e.id==='a'?'first':'later',category:e.category}))};
 const observations={graph_id:'g',run_id:'r',source_hash:'s',records:episodes.slice(0,2).map((e,i)=>({episode_id:e.id,previous_unit_id:e.previous_unit_id,current_unit_id:e.current_unit_id,procedure:i?'same_procedure':'reconfigured_procedure',episode:{...e},procedure_reason:'Saved review'}))};
 return {data,observations};
}
test('procedure lens counts exact recurrence pairs, preserving unknown opportunities and all context marks',()=>{
 const {data,observations}=setup(),before=JSON.stringify([data,observations]),p=project(data,{procedureObservations:observations});
 assert.deepEqual(p.procedures,{counts:{same_procedure:1,reconfigured_procedure:1,alternative_procedure:0,unresolved:1},opportunities:3,compared:2,unknown:1});
 assert.equal(p.count,5);assert.equal(p.paths[0].points.find(p=>p.position===2).pairs.length,0);
 assert.equal(JSON.stringify([data,observations]),before);
});
test('no observations produces unknown comparisons, never a zero-change finding',()=>{
 const {data}=setup(),p=project(data);
 assert.equal(p.procedures.compared,0);assert.equal(p.procedures.unknown,3);assert.equal(p.procedures.opportunities,3);
});
test('graph, source and rollout identity must all match',()=>{
 for(const k of ['graph_id','run_id','source_hash'])for(const missing of [false,true]){
  const {data,observations}=setup();if(missing)delete observations[k];else observations[k]='different';
  assert.equal(project(data,{procedureObservations:observations}).procedures.compared,0);
 }
});
test('wrong or duplicate pair evidence and unknown category are not promoted to known',()=>{
 for(const change of [o=>o.records.push({...o.records[0]}),o=>o.records[0].current_unit_id='u4',o=>o.records[0].episode.previous_unit_id='u2',o=>o.records[0].procedure='exploration',o=>o.records[0].procedure='__proto__']){
  const {data,observations}=setup();change(observations);
  assert.equal(comparisonFor(data,observations,data.episodes[0]).key,'unresolved');
 }
});
test('disputed identity, interrupted recurrence and contribution scope withhold procedure claims',()=>{
 const {data,observations}=setup();
 assert.equal(comparisonFor(data,observations,data.episodes[0],{affected_subject_ids:['x']}).key,'unresolved');
 assert.equal(project(data,{procedureObservations:observations,scopeAudit:{affected_subject_ids:['x']}}).procedures.opportunities,0);
 data.episodes[0].category='interrupted';assert.equal(comparisonFor(data,observations,data.episodes[0]).key,'unresolved');
 data.axis='contributions';assert.equal(comparisonFor(data,observations,data.episodes[1]).key,'unresolved');
 assert.equal(project(data,{procedureObservations:observations}).procedures,null);
});
test('window counts only pairs with both endpoints and retains between-work context',()=>{
 const {data,observations}=setup(),p=project(data,{procedureObservations:observations,visitIds:['other','later']});
 assert.deepEqual([p.count,p.procedures.opportunities,p.procedures.compared,p.procedures.unknown],[4,2,1,1]);
 assert.equal(p.paths[0].points.find(p=>p.position===3).pairs.length,0);
});
test('unordered endpoint is retained as a comparison opportunity with unknown procedure',()=>{
 const {data,observations}=setup();data.visits[0].occurrences[0].order_known=false;
 const p=project(data,{procedureObservations:observations});
 assert.equal(p.procedures.opportunities,3);assert.equal(p.procedures.compared,1);assert.equal(p.procedures.unknown,2);
 assert.match(p.paths[0].pairs[0].comparison.reason,/order is not established/);
});
test('explicit alternative and unresolved records retain their different evidence states',()=>{
 const {data,observations}=setup();observations.records[0].procedure='alternative_procedure';observations.records[1].procedure='unresolved';
 const p=project(data,{procedureObservations:observations});assert.equal(p.procedures.counts.alternative_procedure,1);assert.equal(p.procedures.unknown,2);
 assert.ok(comparisonFor(data,observations,data.episodes[1]).record);assert.equal(comparisonFor(data,observations,data.episodes[2]).record,null);
});
test('text diff highlights the explicit setting and reconstructs both exact sources',()=>{
 const a='pandoc input.md -o result.pdf',b=a+' --pdf-engine=pdflatex',d=dispatchDiff(a,b);
 assert.equal(d.equal,false);assert.equal(d.before.changed,'');assert.equal(d.after.changed,' --pdf-engine=pdflatex');
 for(const [key,text]of [['before',a],['after',b]])assert.equal(d[key].prefix+d[key].changed+d[key].suffix,text);
});
test('diff preserves Unicode, whitespace, deletions, repeated text and literal markup',()=>{
 for(const [a,b]of [['\r\n X ','\n X '],['α😀AB','α😺AB'],['x repeated repeated z','x repeated z'],['<script>x</script>','<script>y</script>'],['abc',''],['','abc'],['',''],['same','same']]){
  const d=dispatchDiff(a,b);assert.equal(d.equal,a===b);
  for(const [key,text]of [['before',a],['after',b]])assert.equal(d[key].prefix+d[key].changed+d[key].suffix,text);
 }
 assert.equal(dispatchDiff(null,'a'),null);assert.equal(dispatchDiff('a',undefined),null);
});
