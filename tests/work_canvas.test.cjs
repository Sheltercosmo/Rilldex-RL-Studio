const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../tracker/web/work-canvas.js');
const item=(id,state='No decision recorded',decisions=[])=>({id,label:id,work_kind:id==='root'?'objective':'subgoal',state,decisions,source_node_ids:[]});
const part=(source,target)=>({source,target,type:'part_of'});
function fixture(){return {items:['root','a','b','c','a1','a2','deep','shared'].map(id=>item(id)),links:[part('a','root'),part('b','root'),part('c','root'),part('a1','a'),part('a2','a'),part('deep','a1'),part('shared','b'),part('shared','c'),{source:'b',target:'a',type:'alternative_to'}]};}
function noOverlap(nodes){for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){const a=nodes[i],b=nodes[j];assert.ok(a.x+a.width<=b.x||b.x+b.width<=a.x||a.y+a.height<=b.y||b.y+b.height<=a.y,`${a.id} overlaps ${b.id}`);}}
test('mind-map geometry fits a nested DAG without overlap or invented relationships',()=>{
 const data=fixture(),before=JSON.stringify(data),result=api.layout(data,'root');
 noOverlap(result.nodes);assert.equal(result.nodes.length,9);assert.equal(result.nodes.filter(n=>n.shared).length,1);assert.equal(result.edges.length,8);assert.equal(result.crosslinks.length,1);
 assert.deepEqual(new Set(result.nodes.filter(n=>n.depth===1).map(n=>n.side)),new Set([-1,1]));
 assert.ok(result.nodes.every(n=>n.x>=result.bounds.x&&n.y>=result.bounds.y&&n.x+n.width<=result.bounds.x+result.bounds.width&&n.y+n.height<=result.bounds.y+result.bounds.height));
 assert.equal(JSON.stringify(data),before);
});
test('collapse retains hidden descendant counts and stable branch sides; focus uses a local root',()=>{
 const data=fixture(),full=api.layout(data,'root'),collapsed=api.layout(data,'root',{collapsed:new Set(['a'])});
 noOverlap(collapsed.nodes);assert.equal(collapsed.nodes.find(n=>n.id==='a').hiddenCount,3);
 assert.equal(collapsed.nodes.find(n=>n.id==='a').side,full.nodes.find(n=>n.id==='a').side);
 assert.equal(collapsed.nodes.some(n=>n.id==='deep'),false);
 const scoped=api.layout(data,'a');assert.equal(scoped.nodes.find(n=>n.id==='a').depth,0);assert.equal(scoped.nodes.length,4);assert.equal(scoped.crosslinks[0].from,undefined);assert.ok(scoped.crosslinks[0].to);
});
test('wide and deep hierarchies preserve every node with bounded nonoverlapping rectangles',()=>{
 for(const shape of ['wide','deep']){const data={items:[item('root')],links:[]};for(let i=0;i<150;i++){data.items.push(item('n'+i));data.links.push(part('n'+i,shape==='wide'||!i?'root':'n'+(i-1)));}const r=api.layout(data,'root');assert.equal(r.nodes.length,151);noOverlap(r.nodes);assert.ok(Number.isFinite(r.bounds.height+r.bounds.width));}
});
test('gray is an explicit inactive state; absence, failure and conflicting reports stay distinct',()=>{
 assert.equal(api.state(item('missing')).tone,'unknown');assert.equal(api.state(item('failure','Reported failed')).tone,'failed');
 assert.equal(api.state(item('complete','Reported complete')).tone,'complete');
 for(const state of ['Explicitly deferred','Explicitly stopped'])assert.equal(api.state(item('inactive',state)).tone,'inactive');
 assert.equal(api.state(item('return','Explicitly resumed')).tone,'chosen');assert.equal(api.state(item('conflict','Conflicting decisions')).tone,'conflict');
});
const decision=(id,type,index)=>({id,type,event_index:index,evidence:{end:10,text:id}});
test('signals count scoped statements, retain stop depth and never infer parent success or an exploration ratio',()=>{
 const data=fixture();data.items.find(n=>n.id==='deep').decisions=[decision('choose','pursue',1),decision('stop','stop',3),decision('return','resume',5)];data.items.find(n=>n.id==='deep').state='Explicitly resumed';
 data.items.find(n=>n.id==='b').state='Reported complete';
 const s=api.summary(data,'root');assert.equal(s.items,8);assert.equal(s.branches,3);assert.equal(s.depth,3);assert.equal(s.chosen,1);assert.equal(s.stopped,1);assert.equal(s.resumed,1);assert.deepEqual(s.stopDepths,[3]);assert.equal(s.reportedComplete,1);assert.equal(data.items[0].state,'No decision recorded');assert.equal(s.explorationRatio,undefined);
 assert.equal(api.summary(data,'b').stopped,0);assert.deepEqual(api.summary(fixture(),'root').stopDepths,[]);
});
test('shared work has one statement count and its shortest-root-path depth',()=>{
 const data=fixture();data.links.push(part('shared','deep'));data.items.find(n=>n.id==='shared').decisions=[decision('stop','stop',3)];const s=api.summary(data,'root');assert.equal(s.stopped,1);assert.deepEqual(s.stopDepths,[2]);
});
test('fit contains the full drawing and anchored zoom preserves the pointed world position',()=>{
 const b={x:-400,y:-300,width:1200,height:800},t=api.fitTransform(b,1000,700);assert.ok(b.x*t.scale+t.x>=0);assert.ok((b.x+b.width)*t.scale+t.x<=1000);assert.ok((b.y+b.height)*t.scale+t.y<=700);
 const z=api.zoomAt(t,t.scale*1.3,170,240);assert.ok(Math.abs((170-t.x)/t.scale-(170-z.x)/z.scale)<1e-8);assert.ok(Math.abs((240-t.y)/t.scale-(240-z.y)/z.scale)<1e-8);
 assert.equal(api.zoomAt(t,200,0,0).scale,2);assert.equal(api.zoomAt(t,0,0,0).scale,.12);
});
test('highlight categories do not promote past failures or ancestor outcomes to current completion',()=>{
 const returned=item('returned','Explicitly resumed',[decision('f','reported_failed',1),decision('r','resume',2)]);
 assert.equal(api.matching(returned,'returns'),true);assert.equal(api.matching(returned,'failed'),false);assert.equal(api.matching(returned,'complete'),false);assert.equal(api.matching(item('empty'),'inactive'),false);
});
test('retry highlighting requires saved counts, not a failed or resumed branch label',()=>{
 assert.equal(Boolean(api.matching(item('f','Reported failed'),'retries')),false);
 const r={...item('a'),retry_summary:{repeated_attempts:3,after_reported_error:1}};
 assert.equal(api.matching(r,'retries'),true);assert.equal(api.matching(r,'repeated'),true);
 assert.equal(Boolean(api.matching({...r,retry_summary:{repeated_attempts:2,after_reported_error:0}},'retries')),false);
});
test('execution card distinguishes missing mapping from a bound plan with zero observed attempts',()=>{
 const missing=api.execution(item('missing','Reported complete'));
 assert.equal(missing.available,false);assert.equal(missing.label,'Execution not mapped');
 const bound={...item('bound'),execution_summary:{scope:'direct',counts:{actions:0,attempts:0,checks:0,preparations:0,with_feedback:0,with_assessment:0}}};
 assert.equal(api.execution(bound).available,true);assert.equal(api.execution(bound).label,'0 attempts · 0 checks');
 assert.equal(Boolean(api.matching(bound,'unmapped')),false);assert.equal(Boolean(api.matching(bound,'attempted')),false);
 assert.equal(api.matching(item('missing'),'unmapped'),true);
});
test('execution counts keep inherited scope and retries visible without claiming successful checks',()=>{
 const n={...item('a','Reported complete'),execution_summary:{scope:'descendants',counts:{actions:12,attempts:5,checks:1,preparations:6,with_feedback:12,with_assessment:9}},retry_summary:{repeated_attempts:3}};
 const before=JSON.stringify(n),e=api.execution(n);
 assert.equal(e.scope,'In subplans');assert.equal(e.label,'5 attempts · 1 check · 3 repeats');
 assert.match(e.note,/12 unique actions/);assert.match(e.note,/9 with assessed feedback/);
 assert.equal(api.matching(n,'attempted'),true);assert.equal(JSON.stringify(n),before);
 assert.equal(api.execution({...n,execution_summary:{...n.execution_summary,scope:'mixed'}}).scope,'Here + subplans');
});
