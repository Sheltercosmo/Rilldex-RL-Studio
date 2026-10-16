const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
class Node{
 constructor(tag,text,cls){this.tag=tag;this.textContent=text??'';this.className=cls||'';this.children=[];}
 append(...items){this.children.push(...items);} replaceChildren(...items){this.children=items;} setAttribute(){}
}
const text=n=>[n.textContent,...n.children.map(text)].join(' ');
const all=n=>[n,...n.children.flatMap(all)];
const script=fs.readFileSync(require.resolve('../tracker/web/rollout-map.js'),'utf8');
const method=script.slice(script.indexOf('function renderMapAvailability('),script.indexOf('function render(){'));
function setup(graph,graphs,params=''){
 const host=new Node('section'),calls=[];
 const c=vm.createContext({$:()=>host,el:(...args)=>new Node(...args),URLSearchParams,
  params:new URLSearchParams(params),payload:{run:{id:'run-a',metadata:{experiment:'test / alpha'}},graph,graphs},
  layout:{nodes:[{},{}],edges:[{family:'sequence'},{family:'feedback'}]},
  clearReceipt:()=>calls.push('clear'),load:(...args)=>calls.push(args)});
 vm.runInContext(method,c);c.renderMapAvailability();return{host,calls};
}
test('source-only map explains missing semantic layers and retains experiment in overview link',()=>{
 const source={observer:'source',coverage:{semantic_relations:'unavailable'}};
 const {host}=setup(source,[source]);
 assert.match(text(host),/No semantic observations are saved/);
 assert.equal(all(host).filter(n=>n.tag==='button').length,0);
 const link=all(host).find(n=>n.textContent==='Behavior measures →');
 assert.equal(new URL(link.href,'http://localhost').searchParams.get('experiment'),'test / alpha');
});
test('source map offers an explicit saved-observer switch without invoking any new inference',()=>{
 const source={observer:'source',coverage:{semantic_relations:'unavailable'}};
 const semantic={observer:'review-v2',observer_label:'Reviewed map',coverage:{semantic_relations:'available'}};
 const {host,calls}=setup(source,[source,semantic]);
 assert.match(text(host),/Semantic observations are also saved/);
 assert.equal(calls.length,0);
 all(host).find(n=>n.tag==='button').onclick();
 assert.deepEqual(calls,['clear',['run-a','review-v2']]);
});
test('semantic inventory excludes sequential adjacency from relationship count',()=>{
 const graph={observer:'review-v2',observer_label:'Reviewed map',coverage:{semantic_relations:'available'}};
 const {host}=setup(graph,[graph]);
 assert.match(text(host),/2 visible units · 1 saved relationships/);
 assert.equal(all(host).filter(n=>n.tag==='button').length,0);
});
test('pinned source view does not claim the rollout has no other saved observations',()=>{
 const source={observer:'source',coverage:{semantic_relations:'unavailable'}};
 const {host,calls}=setup(source,[source],'graph=pinned-source');
 assert.doesNotMatch(text(host),/No semantic observations are saved/);
 all(host).find(n=>n.textContent==='Browse saved observations').onclick();
 assert.deepEqual(calls,['clear',['run-a','source']]);
});
test('partial observer is not mislabeled as a source-only rollout',()=>{
 const partial={observer:'activities-only',coverage:{semantic_relations:'unavailable'}};
 const {host}=setup(partial,[partial]);
 assert.match(text(host),/Partial observation view/);
 assert.doesNotMatch(text(host),/No semantic observations are saved/);
});
