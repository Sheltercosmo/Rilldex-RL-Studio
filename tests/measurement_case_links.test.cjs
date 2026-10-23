const {test}=require('node:test'),assert=require('node:assert/strict');
const M=require('../tracker/web/measurement-case-links.js');
test('measurement-local keys distinguish case kinds and survive reordering',()=>{
 const a={id:'same'},b={anchor:'same',matches:[]},x={analysis_cases:[a],cases:[b]};
 assert.equal(M.find(x,'analysis:same').item,a);assert.equal(M.find(x,'anchor:same').item,b);
 assert.equal(M.find({analysis_cases:[{id:'other'},a]},'analysis:same').item,a);
});
test('missing or ambiguous identities do not choose an arbitrary case',()=>{
 assert.equal(M.find({analysis_cases:[{id:'a'},{id:'a'}]},'analysis:a'),null);
 assert.equal(M.find({analysis_cases:[{}]},null),null);assert.equal(M.find({},'analysis:missing'),null);
});
test('map links bind exact source, graph, receipt and case without mutating evidence',()=>{
 const r={run:{id:'old-source'},graph:{id:'old-graph',run_id:'old-source',observer:'review'},measurement:{id:'old-value'},explanation:{analysis_cases:[{id:'recovery'}]}},before=JSON.stringify(r);
 const url=new URL(M.mapUrl(r,M.entries(r.explanation)[0],'/investigate?saved=original'),'http://localhost');
 assert.equal(url.searchParams.get('graph'),'old-graph');assert.equal(url.searchParams.get('value'),'old-value');assert.equal(url.searchParams.get('measure_case'),'analysis:recovery');assert.equal(JSON.stringify(r),before);
 assert.equal(M.mapUrl({...r,graph:{...r.graph,run_id:'different'}},M.entries(r.explanation)[0],'/'),null);
});
test('return links preserve population mode and exact selected receipt',()=>{
 const url=M.returnUrl('http://localhost/investigate?saved=old&case_measure_view=matched#case-behavior',{monitor:'m',side:'baseline',value:'v',caseKey:'analysis:c'});
 assert.match(url,/case_measure_view=matched/);assert.match(url,/evidence_value=v/);assert.match(url,/#case-behavior$/);
 assert.equal(new URL(url,'http://localhost').searchParams.get('evidence_case'),'analysis:c');
});
test('retry and revision chains use recorded endpoints rather than list positions',()=>{
 const e={failed_event_id:'a',retry_event_id:'b',failed_unit_id:'u1',retry_unit_id:'u2'},x={retry_observation:{episodes:[e]},revision_observation:{episodes:[e]}};
 const rows=M.entries(x);assert.equal(rows.length,2);assert.notEqual(rows[0].key,rows[1].key);assert.deepEqual(M.nodes(rows[0]),['u1','u2']);
});
test('unresolved order windows and feedback groups remain directly inspectable',()=>{
 const x={unavailable_windows:[{anchor:'a',status:'order_unavailable',matches:[]}],feedback_assessment:{observations:[{request_hash:'h',action_event_id:'a',response_event_ids:['r']}]}},rows=M.entries(x);
 assert.equal(rows[0].status,'order_unavailable');assert.equal(M.find(x,'anchor:a').item.anchor,'a');assert.deepEqual(M.nodes(rows[1]),['event:a','event:r']);
});
test('restoration preserves the measured task population instead of widening it',()=>{
 const task={context:{task_id:'a',environment:'terminal'},measured_on_both:true,points:{baseline:[{value_id:'a'}],current:[{value_id:'b'}]}},gap={context:{task_id:'c',environment:'terminal'},measured_on_both:false,points:{baseline:[{value_id:'c'}],current:[]}};
 const p={points:{baseline:[...task.points.baseline,...gap.points.baseline],current:task.points.current},same_tasks:{tasks:[task,gap]}};
 assert.equal(M.cohorts(p,{scope:'all'})[0].points.baseline.length,2);
 assert.deepEqual(M.cohorts(p,{scope:'matched'})[0].points.baseline,[{value_id:'a'}]);
 assert.deepEqual(M.cohorts(p,{scope:'task',task:{environment:'terminal',task_id:'a'}}),[task]);
 assert.deepEqual(M.cohorts(p,{scope:'task',task:{task_id:'a',environment:'other'}}),[]);
 assert.deepEqual(M.cohorts(p,{scope:'invalid'}),[]);
 const u=new URL(M.returnUrl('/investigate?saved=old',{monitor:'m',side:'baseline',value:'a',scope:'task',task:task.context}),'http://localhost');
 assert.equal(u.searchParams.get('evidence_scope'),'task');assert.deepEqual(JSON.parse(u.searchParams.get('evidence_task')),task.context);
 const cleared=new URL(M.returnUrl(u.href,{monitor:'m',side:'baseline',value:'a',scope:'all'}),'http://localhost');assert.equal(cleared.searchParams.has('evidence_task'),false);
});
