const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.style={};this.isConnected=true;this._text='';}
 set textContent(v){this._text=String(v);this.children=[];}
 get textContent(){return this._text+this.children.map(c=>c.textContent).join(' ');}
 append(...nodes){this.children.push(...nodes);}
 prepend(...nodes){this.children.unshift(...nodes);}
 replaceChildren(...nodes){this._text='';this.children=nodes;}
 setAttribute(k,v){this.attrs[k]=String(v);}
 get options(){return this.children;}
}
const all=(root,p)=>[...(p(root)?[root]:[]),...root.children.flatMap(c=>all(c,p))];
const one=(root,tag,text)=>all(root,n=>n.tag===tag&&(text===undefined||n.textContent===text))[0];
function boot(){
 const context={window:{},location:{pathname:'/',search:'?view=strategies&experiment=control'},URLSearchParams,
  document:{createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t)}};
 vm.runInNewContext(fs.readFileSync('tracker/web/behavior-distributions.js','utf8'),context);
 return context.window.BehaviorDistributions.readiness;
}
function fixture(){
 const readiness={current:2,population:27,eligible:1,statuses:{available:1,no_opportunities:1,not_observed:25},
  coverage:2/27,delay:{median_seconds:null,max_seconds:null,available:0,current:2,definition:'Not model inference latency.'},
  boundary:'Coverage is not semantic accuracy.',selection:[{field:'task_id',groups:[{value:'A',observed:14,measured:1},{value:'B',observed:13,measured:0}]}]};
 return {lens:'work',observer:'review',cohort_id:'c1',observation_readiness:readiness,
  observation_statuses:{available:'Current input',no_opportunities:'No opportunities',not_observed:'No saved observation'},
  bins:[{step:0,population:27,eligible_rollouts:1,observation_readiness:readiness}],
  baseline:{start:0,end:0,observation_readiness:readiness},current:{start:0,end:0,observation_readiness:readiness},
  observation_checks:[{evidence:'Task proportions differ among eligible and imported rollouts.'}],
  observation_members:Array.from({length:27},(_,i)=>({run_id:'r'+i,task_id:'Task '+i,step:0,
   status:i===0?'available':i===1?'no_opportunities':'not_observed',graph_id:i<2?'g'+i:null}))};
}
test('separates current inputs, opportunities, missing inputs and unavailable timing',()=>{
 const root=boot()(fixture());assert.match(root.textContent,/2\/27 imported rollouts/);
 assert.match(root.textContent,/1 contribute category opportunities/);
 assert.match(root.textContent,/1 · No opportunities/);assert.match(root.textContent,/25 · No saved observation/);
 assert.match(root.textContent,/median unavailable; maximum unavailable/);
 assert.match(root.textContent,/Task proportions differ/);assert.match(root.textContent,/Coverage is not semantic accuracy/);
 assert.equal(one(root,'circle').children[0].textContent,'Step 0 · 2/27 current inputs · 1 with opportunities');
});
test('all missing rollouts remain reachable through pagination and refresh',()=>{
 const render=boot(),d=fixture();let root=render(d);
 const first=all(root,n=>n.tag==='a').map(n=>n.href);assert.equal(first.length,20);
 const details=one(root,'details');details.open=true;details.ontoggle();
 one(root,'button','Next rollouts').onclick();
 const last=all(root,n=>n.tag==='a').map(n=>n.href);assert.equal(last.length,5);
 assert.equal(new Set([...first,...last]).size,25);
 root=render(d);assert.equal(one(root,'details').open,true);
 assert.equal(all(root,n=>n.tag==='a').length,5);assert.match(root.textContent,/21–25 \/ 25/);
 d.observation_members=d.observation_members.slice(0,4);root=render(d);
 assert.equal(all(root,n=>n.tag==='a').length,2); // Catch-up shrinks the page safely.
});
test('current evidence is pinned; missing rows open source and preserve return context',()=>{
 const render=boot(),d=fixture(),root=render(d),select=one(root,'select');
 select.value='all';select.onchange();
 const links=all(root,n=>n.tag==='a'),known=new URL(links[0].href,'http://local'),missing=new URL(links[2].href,'http://local');
 assert.equal(known.searchParams.get('graph'),'g0');assert.equal(known.searchParams.get('observer'),'review');
 assert.equal(missing.searchParams.get('observer'),'source');assert.equal(missing.searchParams.get('graph'),null);
 assert.equal(missing.searchParams.get('return_to'),'/?view=strategies&experiment=control');
 select.value='no_opportunities';select.onchange();assert.equal(all(root,n=>n.tag==='a').length,1);
 assert.equal(one(render(d),'select').value,'no_opportunities');
 assert.equal(one(render({...d,cohort_id:'c2'}),'select').value,'missing');
});
test('partial current annotations are directly retrievable, not hidden by current status',()=>{
 const d=fixture();d.observation_readiness.record_coverage={inputs:2,covered:11,records:20,fraction:.55};
 Object.assign(d.observation_members[0],{agent_records:10,records_with_units:1});
 Object.assign(d.observation_members[1],{agent_records:10,records_with_units:10});
 const root=boot()(d);assert.match(root.textContent,/26 matching rollouts/);
 const select=one(root,'select');select.value='partial_records';select.onchange();
 assert.equal(all(root,n=>n.tag==='a').length,1);
 assert.equal(new URL(one(root,'a').href,'http://local').searchParams.get('run'),'r0');
 assert.match(root.textContent,/1\/10/);
});
