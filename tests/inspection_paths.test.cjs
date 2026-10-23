const {test}=require('node:test');
const assert=require('node:assert/strict');
const P=require('../tracker/web/inspection-paths.js');
const L=require('../tracker/web/map-layout.js');
const n=(id,kind,i,extra={})=>({id:'event:'+id,kind:'event',trajectory_id:'main',event_index:i,properties:{id,kind,text:id},...extra});
const e=(id,source,target,type,extra={})=>({id,source,target,type,properties:{},...extra});
function fixture(){
 const nodes=[n('a','action',1),n('r','tool_result',2),n('think','message',3),n('b','action',4),n('rb','tool_result',5)];
 const check={id:'check:a',kind:'check',trajectory_id:'main',properties:{action_id:'a',result_event_id:'r',criterion_id:'parser-tests',result:'failed'}};
 return {nodes:[...nodes,check],edges:[e('r-a','event:r','event:a','response_to'),e('rb-b','event:rb','event:b','response_to'),e('use','event:think','event:r','assesses'),e('retry','event:b','event:a','revisits_after_error_report'),e('requested','check:a','event:a','requested_by'),e('result','check:a','event:r','result_recorded_at')]};
}
const groups=(g,ex=[])=>P.catalog(g,L.project(g,ex),ex),cases=(g,id,ex=[])=>groups(g,ex).find(x=>x.id===id).cases;
test('failed-check path includes its feedback, saved assessment, linked retry and bound result',()=>{
 const g=fixture(),before=JSON.stringify(g),c=cases(g,'failed-checks')[0];
 assert.deepEqual(new Set(c.node_ids),new Set(['event:a','event:r','event:think','event:b','event:rb']));
 assert.deepEqual(new Set(c.edge_ids),new Set(['r-a','rb-b','retry','use']));assert.equal(c.gaps.length,0);
 assert.equal(c.checks[0].properties.result,'failed');assert.equal(c.attempts[0].checks.length,1);
 assert.deepEqual(c.attempts.map(a=>a.responses.map(n=>n.id)),[['event:r'],['event:rb']]);
 assert.equal(JSON.stringify(g),before);assert.deepEqual(groups(g),groups(g));
});
test('error prose, identical actions and chronology do not invent failures or retries',()=>{
 const g=fixture();g.nodes=g.nodes.filter(n=>n.kind!=='check');g.edges=g.edges.filter(e=>!['retry','requested','result'].includes(e.id));
 g.nodes.find(n=>n.id==='event:r').properties.text='Error: failed tests. Retry now!';g.nodes.find(n=>n.id==='event:b').properties.text='a';
 g.edges.push(e('seq','event:a','event:b','source_order'));
 for(const group of groups(g))assert.equal(group.cases.length,0);
});
test('same-target comparison is available without misclassifying it as a retry',()=>{
 const g=fixture();g.edges.find(e=>e.id==='retry').type='same_action_target';
 assert.equal(cases(g,'retry-paths').length,0);assert.equal(cases(g,'attempt-pairs').length,1);
 assert.equal(cases(g,'failed-checks')[0].attempts.length,1);
 assert.match(cases(g,'failed-checks')[0].gaps.join(' '),/No linked retry/);
});
test('multiple saved pair types yield one attempt comparison with each witness retained',()=>{
 const g=fixture();g.edges.push(e('same','event:b','event:a','same_action_target'),e('completed','event:b','event:a','completed_after_failed_call'));
 const pairs=cases(g,'attempt-pairs');assert.equal(pairs.length,1);assert.ok(pairs[0].edge_ids.includes('same'));assert.ok(pairs[0].edge_ids.includes('completed'));
 assert.equal(cases(g,'retry-paths').length,1);
});
test('excluded links, dangling links and cross-trajectory evidence cannot enter a path',()=>{
 const g=fixture();g.nodes.find(n=>n.id==='event:think').trajectory_id='parallel';g.edges.push(e('dangling','missing','event:a','revisits_after_error_report'));
 const c=cases(g,'failed-checks',['retry'])[0];assert.ok(!c.node_ids.includes('event:think'));assert.ok(!c.node_ids.includes('event:b'));assert.ok(!c.edge_ids.includes('use'));
 assert.equal(cases(g,'retry-paths',['retry']).length,0);
 assert.equal(cases(g,'failed-checks',['requested','result']).length,0);
});
test('structured unknown is not a failed check; other trajectory check does not attach',()=>{
 const g=fixture(),q=g.nodes.find(n=>n.kind==='check');q.properties.result='unknown';assert.equal(cases(g,'failed-checks').length,0);
 q.properties.result='failed';q.trajectory_id='parallel';assert.equal(cases(g,'failed-checks').length,0);
});
test('parallel returned results and their assessments stay distinct',()=>{
 const g=fixture();g.nodes.push(n('r2','tool_result',6),n('use2','message',7));g.edges.push(e('r2','event:r2','event:a','response_to'),e('u2','event:use2','event:r2','uses_evidence'));
 const c=cases(g,'retry-paths')[0];assert.equal(c.attempts[0].responses.length,2);assert.ok(c.edge_ids.includes('u2'));assert.ok(c.edge_ids.includes('use'));
});
test('saved changes are included, but unrelated context and unconstrained graph traversal are excluded',()=>{
 const g=fixture();g.nodes.push(n('change','message',3),n('other','message',8));g.edges.push(e('change','event:change','event:a','changes_attempt_procedure'),e('other','event:other','event:change','in_work_context'));
 const c=cases(g,'retry-paths')[0];assert.ok(c.node_ids.includes('event:change'));assert.ok(!c.node_ids.includes('event:other'));
});
test('source check identity survives projection onto a semantic action without a phantom card',()=>{
 const g=fixture();g.nodes.push({id:'unit:a',kind:'unit',trajectory_id:'main',event_index:1,properties:{kind:'action',source:{event_id:'a',text:'a',start:0,end:1}}});g.edges.push(e('ground','unit:a','event:a','grounded_in'));
 const c=cases(g,'failed-checks')[0];assert.equal(c.attempts[0].node.id,'unit:a');assert.equal(c.attempts[0].checks[0].id,'check:a');assert.ok(!c.node_ids.includes('check:a'));
});
test('ambiguous source-to-unit check attachment is not assigned to both units',()=>{
 const g=fixture();for(const id of ['u1','u2']){g.nodes.push({id,kind:'unit',trajectory_id:'main',event_index:1,properties:{kind:'action',source:{event_id:'a',text:'a'}}});g.edges.push(e(id,id,'event:a','grounded_in'));}
 const c=cases(g,'failed-checks')[0];assert.equal(c.attempts.length,0);assert.deepEqual(c.node_ids,['event:r','event:think']);
});
test('recheck keeps recorded comparability and passing result separate from recovery',()=>{
 const g=fixture();g.edges=g.edges.filter(e=>e.id!=='retry');g.nodes.push({id:'check:b',kind:'check',trajectory_id:'main',properties:{action_id:'b',result_event_id:'rb',criterion_id:'parser-tests',result:'passed'}});
 g.edges.push(e('qb','check:b','event:b','requested_by'),e('qbr','check:b','event:rb','result_recorded_at'),e('recheck','check:b','check:a','recorded_recheck_of',{properties:{comparable:false,issues:['criterion_version_changed']}}));
 const c=cases(g,'failed-checks')[0];assert.equal(c.attempts.length,2);assert.equal(c.attempts[1].checks[0].properties.result,'passed');assert.equal(c.edges.find(e=>e.id==='recheck').properties.comparable,false);
 assert.equal(cases(g,'retry-paths').length,0);assert.equal(cases(g,'attempt-pairs').length,1);
});

test('failed paths follow later explicit retries through multiple failures and a passing check',()=>{
 const g=fixture();
 for(const [id,i,result]of [['b',4,'failed'],['c',7,'passed']]){
  if(id==='c')g.nodes.push(n(id,'action',i),n('r'+id,'tool_result',i+1));
  g.nodes.push({id:'check:'+id,kind:'check',trajectory_id:'main',properties:{criterion_id:'parser-tests',result}});
  g.edges.push(e('q'+id,'check:'+id,'event:'+id,'requested_by'),e('qr'+id,'check:'+id,'event:r'+id,'result_recorded_at'));
 }
 g.edges.push(e('c-b','event:c','event:b','revisits_after_error_report'),e('rc-c','event:rc','event:c','response_to'));
 const path=cases(g,'failed-checks')[0];
 assert.deepEqual(path.attempts.map(a=>a.node.id),['event:a','event:b','event:c']);
 assert.equal(path.attempts.at(-1).checks[0].properties.result,'passed');
 assert.deepEqual(P.summary(path),{attempts:3,checks:3,failed:2,passed:1,unknown:0,feedbackUses:1,changes:0,truncated:false});
 assert.equal(cases(g,'retry-paths')[0].attempts.length,3);
 assert.ok(cases(g,'attempt-pairs').every(p=>p.attempts.length===2));
});

test('retry branching stays connected, cycles terminate, same-target neighbors do not extend a chain',()=>{
 const g=fixture();g.nodes.push(n('c','action',6),n('other','action',8));
 g.edges.push(e('c-a','event:c','event:a','revisits_after_error_report'),e('cycle','event:a','event:c','revisits_after_error_report'),e('target','event:other','event:c','same_action_target'));
 const path=cases(g,'failed-checks')[0];
 assert.deepEqual(new Set(path.attempts.map(a=>a.node.id)),new Set(['event:a','event:b','event:c']));
 assert.ok(path.edge_ids.includes('c-a'));assert.ok(!path.node_ids.includes('event:other'));
 assert.equal(path.truncated,false);
});

test('long follow-up paths disclose the display bound without inventing an endpoint result',()=>{
 const g=fixture();let previous='b';
 for(let i=0;i<80;i++){const id='long-'+i;g.nodes.push(n(id,'action',10+i));g.edges.push(e('retry-'+id,'event:'+id,'event:'+previous,'revisits_after_error_report'));previous=id;}
 const path=cases(g,'failed-checks')[0];
 assert.equal(path.attempts.length,64);assert.equal(path.truncated,true);
 assert.match(path.gaps.join(' '),/Additional follow-ups remain/);
 assert.equal(P.summary(path).passed,0);
});

test('recheck arrows cannot choose the first of several semantic actions in one source event',()=>{
 const g=fixture();g.edges=g.edges.filter(e=>e.id!=='retry');
 g.nodes.push({id:'check:b',kind:'check',trajectory_id:'main',properties:{action_id:'b',result:'passed'}});
 for(const id of ['u1','u2']){g.nodes.push({id,kind:'unit',trajectory_id:'main',event_index:1,properties:{kind:'action',source:{event_id:'a',text:'a'}}});g.edges.push(e(id,id,'event:a','grounded_in'));}
 g.edges.push(e('recheck','check:b','check:a','recorded_recheck_of',{properties:{comparable:true}}));
 const projected=L.project(g);
 assert.equal(projected.edges.some(e=>e.id==='recheck'),false);
 const path=P.catalog(g,projected).find(g=>g.id==='failed-checks').cases[0];
 assert.equal(path.attempts.length,0);
});

test('a check in another trajectory cannot project its recheck onto an unrelated action',()=>{
 const g=fixture();g.nodes.push({id:'check:b',kind:'check',trajectory_id:'parallel',properties:{action_id:'b',result:'passed'}});
 g.edges.push(e('recheck','check:b','check:a','recorded_recheck_of'));
 assert.equal(L.project(g).edges.some(e=>e.id==='recheck'),false);
});
