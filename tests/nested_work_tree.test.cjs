const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {model}=require('../tracker/web/nested-work-tree.js');
const real=JSON.parse(fs.readFileSync(path.join(__dirname,'../research/nested-plan-map-2026-10-13/hierarchy.json'),'utf8'));
const graph=JSON.parse(fs.readFileSync(path.join(__dirname,'../research/nested-plan-map-2026-10-13/graph.json'),'utf8'));
const layout=require('../tracker/web/map-layout.js');
test('structural evidence never becomes extra semantic units or opaque map cards',()=>{
 const p=layout.project(graph);assert.equal(p.nodes.length,166);assert.ok(p.nodes.every(n=>n.kind==='event'));
 const context=layout.declaredWork(graph,'event:e71');assert.equal(context.length,1);
 assert.equal(context[0].goal.properties.label,'find and pick up the wine in kitchen 1');
 assert.equal(context[0].record.properties.kind,'reported_failed');
});
test('public goal effort is counted once without promoting branch reports into parent success',()=>{
 const before=JSON.stringify(real),m=model(real),root=real.roots[0],s=m.summary(root);
 assert.equal(s.operations,45);assert.equal(s.goals,10);assert.equal(s.failures,2);assert.equal(s.completions,4);
 assert.equal(m.byId.get(root).state,'Expanded into subgoals');assert.equal(JSON.stringify(real),before);
});
test('fallback declaration preserves exact sibling order and three distinct outcomes',()=>{
 const m=model(real),control=real.nodes.find(n=>n.control==='fallback'),ids=m.children.get(control.id),nodes=ids.map(id=>m.byId.get(id));
 assert.deepEqual(nodes.map(n=>n.label.split(' in ')[1]),['kitchen 1','living room 1','bedroom 1']);
 assert.deepEqual(nodes.map(n=>n.state),['Reported failed','Reported failed','Reported complete']);
 // Kitchen: room + table + four fridge requests + sixteen cabinet requests.
 assert.deepEqual(ids.map(id=>m.summary(id).operations),[22,7,5]);
 assert.equal(m.path(ids[0]).length,4);
});
test('branch comparison includes only its own descendants',()=>{
 const m=model(real),wine=real.nodes.find(n=>n.label==='move the wine on the coffee table'),juice=real.nodes.find(n=>n.label==='and move the juice on the coffee table');
 assert.equal(m.summary(wine.id).operations,38);assert.equal(m.summary(juice.id).operations,7);assert.equal(m.summary(juice.id).failures,0);
});
test('same wording never merges separately identified goals',()=>{
 const d={nodes:[{id:'root',kind:'native_goal'},{id:'a',label:'Same',kind:'native_goal',records:[]},{id:'b',label:'Same',kind:'native_goal',records:[]}],links:[{source:'root',target:'a',type:'contains',order:2},{source:'root',target:'b',type:'contains',order:1}]},m=model(d);
 assert.deepEqual(m.children.get('root'),['b','a']);assert.equal(m.summary('root').goals,3);
});
test('a shared reference does not double-count an operation',()=>{
 const record={id:'one',occurrence_id:'one-source-occurrence',kind:'operation'},d={nodes:[{id:'r',records:[record]},{id:'a',records:[{...record,id:'other-scope-link'}]}],links:[{source:'r',target:'a',type:'contains'}]};assert.equal(model(d).summary('r').operations,1);
});
test('unknown focus has no fabricated ancestry or measurements',()=>{
 const m=model(real);assert.deepEqual(m.path('missing'),[]);assert.equal(m.summary('missing').operations,0);
});
