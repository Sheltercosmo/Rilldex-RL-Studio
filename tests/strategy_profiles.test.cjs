const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const code=fs.readFileSync(require.resolve('../tracker/web/strategy-profiles.js'),'utf8');
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.options=[];this.style={};this.attributes={};this.classList={add:()=>{}};this.textContent='';}
 append(...items){this.children.push(...items);if(this.tag==='select')this.options.push(...items);}
 prepend(...items){this.children.unshift(...items);}
 replaceChildren(...items){this.children=items;}
 setAttribute(k,v){this.attributes[k]=v;}
}
const flatten=n=>[n,...n.children.flatMap(flatten)];
function fixture(){
 const result={family:'failure',comparison:'training',observer:'review',cohort_id:'cohort',
  families:{failure:{label:'Response after failure'}},observers:[{id:'review',label:'Review',rollouts:2}],
  cohorts:[{id:'cohort',metadata:{task_id:'task'},rollouts:2,population:3}],population:3,measured_rollouts:2,
  coverage:{available:2,awaiting_observation:1},counts:{total:2,known:2,unknown:0,adjustment_observed:0,completed:1,terminal:2,outcome_unknown:0,categories:{changed:1,unchanged:1,unknown:0}},
  definition:{question:'Retry?',categories:{changed:'Changed dispatch',unchanged:'Same dispatch',unknown:'Unresolved'},primary_label:'Changed dispatch',limit:'Not whole-task recovery.'},
  measures:{dispatch_change:'Changed dispatch'},missing_training_coordinates:0,pending_dimensions:[],accuracy:'Controlled test',
  cases:[],points:[],bins:[]};
 for(let step=0;step<3;step++){
  const available=step!==1,value=available?(step===0?1:0):null;
  result.points.push({run_id:'rollout-'+step,step,policy_version:'p'+step,checkpoint:'c'+step,status:available?'available':'awaiting_observation',reason:available?null:'No matching observation is saved.',numerator:value??0,denominator:available?1:0,value,measure_unknown:0,completed:available?1:0,terminal:available?1:0});
  result.bins.push({step,value,coverage:available?1:0,measured_rollouts:available?1:0,rollouts:1,policies:[{policy_version:'p'+step}]});
 }
 return result;
}
async function render(search='?detail=episodes'){
 const requests=[],urls=[],host=new Element('div'),data=fixture(),context=vm.createContext({window:{},URLSearchParams,
  document:{createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t)},
  location:{search},history:{replaceState:(_,__,url)=>urls.push(url)},fetch:async url=>{requests.push(url);return {ok:true,json:async()=>data};}});
 vm.runInContext(code,context);await context.window.StrategyProfiles.load(host,{});
 return {host,requests,urls,data,nodes:flatten(host)};
}
test('profile default compares training while retaining an explicit fixed-policy option',async()=>{
 const {nodes,requests}=await render();assert.match(requests[0],/comparison=training/);
 const control=nodes.find(n=>n.tag==='select'&&n.options.some(o=>o.value==='fixed_policy'));
 assert.ok(control);control.value='fixed_policy';control.onchange();
 assert.match(requests.at(-1),/comparison=fixed_policy/);
 assert.doesNotMatch(requests.at(-1),/cohort_id=/);
});
test('unobserved steps break the metric line and retain a visible coverage bar',async()=>{
 const {nodes}=await render();
 const paths=nodes.filter(n=>n.tag==='path');assert.equal(paths.length,2);
 assert.ok(paths.every(p=>!p.attributes.d.includes('L')),'no line should bridge the missing middle step');
 const bars=nodes.filter(n=>n.tag==='rect'&&n.attributes['aria-label']);assert.equal(bars.length,3);
 assert.equal(bars[1].attributes['aria-label'],'Step 1: 0 of 1 rollouts observed');
 assert.ok(nodes.some(n=>String(n.textContent).includes('Missing observations are gaps')));
 assert.ok(nodes.some(n=>n.textContent==='No matching observation is saved.'));
 assert.ok(nodes.some(n=>n.textContent==='1 · p1'));
});
test('existing pinned cohort links retain fixed-policy meaning',async()=>{
 const {requests}=await render('?detail=episodes&cohort_id=earlier-cohort');
 assert.match(requests[0],/comparison=fixed_policy/);assert.match(requests[0],/cohort_id=earlier-cohort/);
});
test('profile comparison links do not collide with saved monitor comparison routing',async()=>{
 const {urls,requests}=await render('?detail=episodes&profile_comparison=training&cohort_id=training-cohort');
 const query=new URLSearchParams(urls.at(-1).split('?')[1]);
 assert.equal(query.get('profile_comparison'),'training');assert.equal(query.has('comparison'),false);
 assert.match(requests[0],/comparison=training/);
});
