const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const Evidence=require('../tracker/web/distribution-evidence.js');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.style={};this.dataset={};this.isConnected=true;this._text='';this.className='';this.classList={add:()=>{}};}
 set textContent(v){this._text=String(v);this.children=[];}
 get textContent(){return this._text+this.children.map(c=>c.textContent).join(' ');}
 append(...nodes){this.children.push(...nodes);}
 prepend(...nodes){this.children.unshift(...nodes);}
 replaceChildren(...nodes){this._text='';this.children=nodes;}
 setAttribute(k,v){this.attrs[k]=String(v);}
 get options(){return this.children;}
 querySelectorAll(selector){return all(this,e=>selector.startsWith('.')?e.className.split(' ').includes(selector.slice(1)):e.tag===selector).filter(e=>e!==this);}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 scrollIntoView(){}
}
const all=(root,p)=>[...(p(root)?[root]:[]),...root.children.flatMap(c=>all(c,p))];
const find=(root,tag,text)=>all(root,e=>e.tag===tag&&e.textContent===text)[0];
function fixture({current=2,total=2}={}){
 const r={current,population:4,eligible:total?2:0,statuses:{available:total?2:0,no_opportunities:total?0:current,not_observed:4-current},coverage:current/4,
  delay:{available:0,current,median_seconds:null,max_seconds:null,definition:'Saved input delay'},selection:[],boundary:'Coverage is not semantic accuracy.'};
 const aggregate={total,eligible_rollouts:total?2:0,rollouts:current,population:4,shares:{continued:total?1: null,unknown:total?0:null},counts:{continued:total,unknown:0}};
 const d={lens:'recurrence',lenses:{recurrence:{label:'Repeated actions'}},definition:{grain:'recorded actions',limit:'No causal inference'},
  groupings:[],grouping:'work-default',population_mode:'task',weighting:'rollout',observer:'review',observers:[{id:'review',label:'Reviewed',rollouts:current}],
  cohort_id:'task-a',cohorts:[{id:'task-a',metadata:{task_id:'A'},rollouts:current,population:4}],metadata:{task_id:'A'},population:4,scope_population:4,observed_rollouts:current,
  categories:[{id:'continued',label:'Continued',color:'#5696aa'},{id:'unknown',label:'Unknown',color:'#888888'}],distribution:aggregate,
  points:[],cases:[],bins:[{step:0,...aggregate,observation_readiness:r},{step:1,...aggregate,observation_readiness:r}],
  baseline:{start:0,end:0,...aggregate,observation_readiness:r},current:{start:1,end:1,...aggregate,observation_readiness:r},
  deltas:[{id:'continued',before:total?1:null,after:total?1:null,pp:total?0:null},{id:'unknown',before:total?0:null,after:total?0:null,pp:total?0:null}],comparable:!!total,
  comparison_reason:'Missing observations',denominator:'Equal rollout weights',observation_readiness:r,observation_statuses:{available:'Available',no_opportunities:'No opportunities',not_observed:'No saved observation'},
  observation_checks:[],observation_members:[],unplaced_rollouts:0,review_note_count:0,snapshot_id:'snapshot'};
 if(total){d.points=[{run_id:'r',step:1,total,counts:{continued:total,unknown:0},input_id:'i',graph_id:'g'}];d.cases=Array.from({length:total},(_,i)=>({id:'c'+i,category:'continued',run_id:'r',step:1,input_id:'i',graph_id:'g',text:'Recorded attempt '+i,map_url:'/semantic-map?run=r&graph=g'}));}
 return d;
}
function boot(d,{search='?view=strategies&lens=recurrence&experiment=control',fetcher}={}){
 const requests=[],root=new Element('div'),context={window:{},location:{pathname:'/',search},history:{replaceState(_a,_b,url){context.location.search='?'+url.split('?')[1];}},URLSearchParams,DistributionEvidence:Evidence,
 document:{createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t)},fetch:async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>fetcher?fetcher(url,options):d};}};
 vm.runInNewContext(fs.readFileSync('tracker/web/behavior-distributions.js','utf8'),context);
 return {root,context,requests,load:selection=>context.window.BehaviorDistributions.load(root,selection||{experiment:'control'})};
}

test('saved views never refresh live evidence and keep source links inspectable',async()=>{
 const d=fixture(),record={id:'saved-one',captured_at:'2026-10-23T12:00:00Z',controls:{experiment:'control',lens:'recurrence',observer:'review',cohort_id:'task-a',a_start:0,a_end:0,b_start:1,b_end:1},snapshot:d};
 const {root,context,requests,load}=boot(d,{search:'?view=strategies&distribution=saved-one',fetcher:()=>record});
 await load();await load();
 assert.deepEqual(requests.map(r=>r.url),['/api/behavior-comparisons/saved-one']);
 assert.ok(find(root,'strong','Saved comparison'));assert.equal(root.querySelector('.bd-windows'),null);
 assert.equal(root.querySelector('.bd-settings').querySelectorAll('select').length,0);
 assert.equal(root.querySelector('.bd-view-selector').hidden,true);
 all(root,e=>e.attrs['aria-label']==='Inspect Continued')[0].onclick();
 assert.match(context.location.search,/distribution=saved-one/);
 assert.ok(all(root,e=>e.tag==='a'&&e.href?.startsWith('/semantic-map?run=r&graph=g')).length);
 assert.match(find(root,'a','Open live comparison').href,/a_start=0/);
 assert.doesNotMatch(find(root,'a','Open live comparison').href,/distribution=/);
 await find(root,'button','Capture latest evidence').onclick();
 assert.deepEqual(JSON.parse(requests.at(-1).options.body),{parent_id:'saved-one'});
});

test('saving fixes applied windows and leaves unfinished window drafts unapplied',async()=>{
 const d=fixture(),{root,requests,context,load}=boot(d,{fetcher:(url,options)=>options?{id:'capture',controls:{experiment:'control'}}:d});await load();
 const form=root.querySelector('.bd-windows');form.open=true;form.querySelectorAll('input')[0].value='99';
 await find(root,'button','Save latest comparison').onclick();
 const payload=JSON.parse(requests.at(-1).options.body);
 assert.equal(payload.controls.a_start,0);assert.equal(payload.controls.b_end,1);
 assert.equal(payload.controls.observer,'review');assert.equal(payload.controls.cohort_id,'task-a');
 assert.match(context.location.href,/distribution=capture/);
 assert.match(context.location.href,/category=continued/);
});

test('saved comparison list is fetched only when expanded',async()=>{
 const d=fixture(),{root,requests,load}=boot(d,{fetcher:url=>url.startsWith('/api/behavior-comparisons')?{comparisons:[]}:d});await load();
 assert.equal(requests.length,1);
 const list=root.querySelector('.bd-saved-list');list.open=true;await list.ontoggle();
 assert.match(requests.at(-1).url,/experiment=control/);assert.match(list.textContent,/No saved comparisons/);
});
test('missing inputs never render measured zeros or empty evidence categories',async()=>{
 const {root,load}=boot(fixture({current:0,total:0}));await load();
 assert.ok(find(root,'h2','No saved observations'));assert.equal(root.querySelector('.bd-result'),null);
 assert.equal(root.querySelector('.bd-stats'),null);assert.equal(root.querySelector('.bd-evidence'),null);
 assert.match(root.querySelector('.bd-coverage-flags').textContent,/4 · No saved observation/);
 const setup=find(root,'a','Observation setup');assert.equal(setup.href,'/connections?experiment=control#model-section');
});
test('current inputs with no opportunities remain distinct from absent observations',async()=>{
 const {root,load}=boot(fixture({current:2,total:0}));await load();
 assert.ok(find(root,'h2','No recorded opportunities'));
 assert.match(root.querySelector('.bd-no-observations').textContent,/2 rollouts have current inputs/);
 assert.match(root.querySelector('.bd-coverage-flags').textContent,/2 · No opportunities/);
 assert.match(root.querySelector('.bd-coverage-flags').textContent,/2 · No saved observation/);
});
test('settings remain folded and a measured zero stays inspectable',async()=>{
 const {root,load}=boot(fixture());await load();
 const settings=root.querySelector('.bd-settings');assert.equal(settings.open,false);
 assert.equal(settings.querySelectorAll('select').length,4);
 assert.equal(root.querySelector('.bd-coverage-summary').open,false);
 assert.match(all(root,e=>e.attrs['aria-label']==='Inspect Unknown')[0].textContent,/Unknown 0\.0% 0\.0% 0\.0 pp/);
 assert.equal(all(root,e=>e.tag==='select'&&['Trend category','Behavior to compare'].includes(e.attrs['aria-label'])).length,0);
 assert.equal(root.querySelectorAll('.bd-windows').length,1);
});

test('changing the behavior view retains training scope and clears incompatible comparison filters',async()=>{
 const d=fixture();d.lenses.work_visits={label:'Work focus'};
 const {root,requests,load}=boot(d,{search:'?view=strategies&lens=recurrence&observer=old&cohort_id=old-task&a_start=1&a_end=2&b_start=3&b_end=4'});
 await load({experiment:'control',environment:'swe-agent'});
 const view=root.querySelector('.bd-view-selector').querySelector('select');
 assert.deepEqual(view.options.map(o=>o.value),['work_visits','recurrence']);
 view.value='work_visits';view.onchange();
 const query=new URL(requests.at(-1).url,'http://local').searchParams;
 assert.equal(query.get('experiment'),'control');assert.equal(query.get('environment'),'swe-agent');
 assert.equal(query.get('lens'),'work_visits');assert.equal(query.get('recurrence_order'),'bracketed-parallel/1');
 for(const key of ['observer','cohort_id','a_start','a_end','b_start','b_end'])assert.equal(query.has(key),false,key);
});
test('category selection synchronizes evidence and trend without losing disclosure state',async()=>{
 const {root,load}=boot(fixture());await load();
 const settings=root.querySelector('.bd-settings');settings.open=true;settings.ontoggle();
 const coverage=root.querySelector('.bd-coverage-summary');coverage.open=true;coverage.ontoggle();
 all(root,e=>e.attrs['aria-label']==='Inspect Unknown')[0].onclick();
 assert.ok(find(root,'h2','Unknown over recorded progress'));
 assert.equal(root.querySelector('.bd-evidence').open,true);assert.match(root.querySelector('.bd-evidence').textContent,/Unknown · 0 cases/);
 assert.equal(root.querySelector('.bd-settings').open,true);assert.equal(root.querySelector('.bd-coverage-summary').open,true);
});
test('live refresh retains unfinished comparison-window edits only in the same scope',async()=>{
 const {root,load}=boot(fixture());await load();
 const windows=root.querySelector('.bd-windows');windows.open=true;windows.querySelectorAll('input')[0].value='17';
 await load();assert.equal(root.querySelector('.bd-windows').open,true);assert.equal(root.querySelector('.bd-windows').querySelectorAll('input')[0].value,'17');
 await load({experiment:'another'});assert.equal(root.querySelector('.bd-windows').open,false);assert.equal(root.querySelector('.bd-windows').querySelectorAll('input')[0].value,0);
});
test('error follow-up prioritizes the selected approach and retains other approaches on expansion',async()=>{
 const d=fixture();
 const rows=d.categories.map(c=>({id:c.id,total:1,eligible_rollouts:1,no_prior_error:0,prior_report_unknown:0,unavailable_pairs:0,counts:{reported_again:1},shares:{reported_again:1}}));
 d.approach_followup={statuses:[{id:'reported_again'}],denominator:'Equal rollout weights',earlier:{start:0,end:0,rows},later:{start:1,end:1,rows}};
 const {root,load}=boot(d);await load();
 let follow=root.querySelector('.bd-followup'),other=follow.querySelector('.bd-other-approaches');
 assert.equal(other.open,false);assert.ok(find(other,'h3','Unknown'));
 assert.ok(find(follow.children.find(e=>e.className==='bd-followup-row'),'h3','Continued'));
 all(root,e=>e.attrs['aria-label']==='Inspect Unknown')[0].onclick();
 follow=root.querySelector('.bd-followup');other=follow.querySelector('.bd-other-approaches');
 assert.ok(find(other,'h3','Continued'));assert.ok(find(follow.children.find(e=>e.className==='bd-followup-row'),'h3','Unknown'));
 assert.equal(root.children.indexOf(root.querySelector('.bd-trend'))<root.children.indexOf(follow),true);
});
