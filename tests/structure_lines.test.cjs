const {layout,nodeType}=require('../tracker/web/structure-lines.js');
const assert=require('node:assert/strict');
const data={roots:['root'],nodes:['root','a','b','shared'].map(id=>({id,label:id,kind:'outline_item'})),links:[],work_outline:{links:[
 {source:'a',target:'root',type:'part_of'}, {source:'b',target:'root',type:'part_of'},
 {source:'shared',target:'a',type:'part_of'}, {source:'shared',target:'b',type:'part_of'},
 {source:'b',target:'a',type:'alternative_to'}]}};
const all=layout(data);assert.equal(all.nodes.length,4);assert.equal(all.edges.length,4);assert.equal(all.relations.length,1);
assert.equal(new Set(all.nodes.map(n=>n.id)).size,4);
const partial=layout(data,'root',new Set(['a']));assert.equal(partial.nodes.length,4);assert.equal(partial.edges.length,3);
const folded=layout(data,'root',new Set(['a','b']));assert.equal(folded.nodes.length,3);
assert.equal(layout(data,'a').nodes.length,2);
assert.ok(all.nodes.find(n=>n.id==='shared').x>all.nodes.find(n=>n.id==='a').x);
assert.throws(()=>layout({...data,work_outline:{links:[...data.work_outline.links,{source:'root',target:'shared',type:'part_of'}]}}),/cyclic/);
console.log('Structure lines: shared nodes, folding, cross-links and cycles verified');
const typeNames=['objective','subgoal','approach'];
const types=typeNames.map(work_kind=>nodeType({kind:'outline_item',work_kind}));
assert.equal(new Set(types.map(t=>t.color)).size,3,'Outline roles need distinct colors');
assert.deepEqual(types.map(t=>t.label),['Objective','Subgoal','Approach']);
assert.equal(nodeType({kind:'outline_item'}).label,'Work item','Missing role must not be presented as a goal');
assert.notEqual(nodeType({kind:'plan_step'}).color,nodeType({kind:'plan'}).color);
const deep=require('../scripts/promo/deep-structure-data.json');
const expanded=layout(deep);
assert.equal(expanded.nodes.length,43);
assert.equal(Math.max(...expanded.nodes.map(n=>n.depth)),7);
assert.ok(expanded.width<1600,'Eight levels should fit a wide desktop without card-width columns');
for(const edge of expanded.edges){const a=expanded.nodes.find(n=>n.id===edge.source),b=expanded.nodes.find(n=>n.id===edge.target);assert.equal(b.x-a.x-a.width,32,'Parentage connectors should use the short inter-column gap');}
const {geometry}=require('../scripts/promo/structure-scene.cjs');
const film=geometry();assert.equal(film.levels,8);assert.equal(film.nodes.size,43);
for(const n of film.nodes.values())assert.equal(n.depth,expanded.nodes.find(x=>x.id===n.id).depth,'Film and app must agree on depth');
assert.equal(film.relations.length,1,'Return remains a relationship, not added parentage');
console.log('Structure types, compact eight-level layout and film depth verified');
