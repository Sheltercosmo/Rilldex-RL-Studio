const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

// Minimal DOM for the existing transition renderer; no layout or browser claims.
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.dataset={};this.style={setProperty:(k,v)=>this.style[k]=v};this.value='';}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;}
 setAttribute(k,v){this.attributes[k]=v;}
 addEventListener(){}
 add(option){if(!this.children.length)this.value=option.value;this.append(option);}
}
function render(modes){
 const context={window:{},document:{createElement:tag=>new Element(tag),querySelector:()=>new Element('control')},Option:class{constructor(text,value){this.textContent=text;this.value=value;}},URLSearchParams};
 vm.runInNewContext(fs.readFileSync(require.resolve('../tracker/web/comparison.js'),'utf8'),context);
 const before={},after={},metrics={};
 for(const from of modes)for(const to of modes){const key=from+'.'+to;before[key]=after[key]=0;metrics['transition.'+key]={delta:0,task_count:1};}
 const coverage={observed_pairs:1,possible_pairs:1,excluded_order_pairs:0,excluded_batch_pairs:0,unresolved_pairs:0,eligible_rollouts:1,total_rollouts:1};
 const host=new Element('div');
 context.window.trackerComparison.flow(host,{}, {reference:'before',checkpoint:'after',metrics,
   sequence:{task_ids:['task'],excluded_task_ids:[],before,after,definition:'Recorded sequence',coverage:{before:coverage,after:coverage}}});
 return host.children[0].children.find(e=>e.className==='transition-matrix');
}
const prior=['explore','apply','verify','coordinate','report','unresolved'];
test('legacy comparison retains its six observed purpose categories',()=>{
 const matrix=render(prior);assert.equal(matrix.style['--purpose-count'],6);
 assert.equal(matrix.children.filter(e=>e.tag==='button').length,36);
 assert.ok(matrix.children.every(e=>!String(e.textContent).includes('NaN')));
 assert.ok(matrix.children.every(e=>!e.dataset.transition?.includes('mixed')));
});
test('combined-purpose comparisons render all 49 transitions in an eight-column matrix',()=>{
 const matrix=render([...prior.slice(0,-1),'mixed','unresolved']);
 assert.equal(matrix.style['--purpose-count'],7);assert.equal(matrix.children.length,64);
 assert.equal(matrix.children.filter(e=>e.tag==='button').length,49);
 assert.ok(matrix.children.some(e=>e.dataset.transition==='mixed.verify'));
});
