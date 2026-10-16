const {test}=require('node:test');
const assert=require('node:assert/strict');
const {project,matches}=require('../tracker/web/work-review.js');
function fixture(){
 const unit=(id,index,kind,text,extra={})=>({id,kind:'unit',trajectory_id:'main',event_index:index,properties:{kind,source:{text,event_id:'e'+index},...extra}});
 const graph={id:'g',run_id:'r',source_hash:'h',nodes:[unit('a',0,'action','run'),unit('f1',1,'feedback','reported issue'),unit('think',2,'semantic','Try a different input'),unit('b',3,'action','edit'),unit('c',4,'action','run'),unit('f2',5,'feedback','reported issue')],edges:[
  {id:'f1e',type:'feedback_for',source:'f1',target:'a'},
  {id:'f1-alias',type:'response_to',source:'f1',target:'a'},
  {id:'f2e',type:'feedback_for',source:'f2',target:'c'},
  {id:'assessment',type:'assesses',source:'think',target:'f1'},
  {id:'error',type:'revisits_after_error_report',source:'c',target:'a'}]};
 const visits=['a','b','c'].map((id,i)=>({id:'v'+id,group_id:id==='b'?'other':'same',target:id==='b'?'Edit setup':'Run task',order_known:true,positions:[i+1],occurrences:[{unit_id:id,order_known:true}]}));
 const data={graph_id:'g',run_id:'r',source_hash:'h',visits,paths:[{trajectory_id:'main',actor:'agent',visit_ids:visits.map(v=>v.id)}],episodes:[{id:'ep',category:'returned',previous_unit_id:'a',current_unit_id:'c'}],links:[{id:'return',episode_id:'ep',type:'same_work_return',category:'returned',source:'vc',target:'va'}]};
 return {data,graph};
}
test('complete repeated-work sequence keeps intervening actions and exact edge witnesses',()=>{
 const {data,graph}=fixture(),before=JSON.stringify({data,graph}),r=project(data,graph),t=r.targets[0];
 assert.equal(r.available,true);assert.deepEqual(t.steps.map(x=>x.id),['a','c']);assert.deepEqual(t.pairs[0].between.map(x=>x.id),['b']);
 assert.deepEqual(t.steps[0].responses[0].edges,['f1e','f1-alias']);assert.deepEqual(t.steps[0].responses[0].references[0].edges,['assessment']);
 assert.deepEqual(t.pairs[0].error_edges,['error']);assert.equal(t.count.after_error,1);assert.equal(t.count.references,1);assert.equal(t.count.exact_repeats,1);
 assert.equal(JSON.stringify({data,graph}),before);
});
test('a response preview match is insufficient for exact text equality',()=>{
 const {data,graph}=fixture();graph.nodes.find(n=>n.id==='f1').properties.source.text='ERROR: x\nmetadata one';graph.nodes.find(n=>n.id==='f2').properties.source.text='ERROR: x\nmetadata two';
 const t=project(data,graph).targets[0];assert.equal(t.steps[0].responses[0].preview.text,t.steps[1].responses[0].preview.text);assert.equal(t.pairs[0].feedback,'changed');assert.equal(t.count.exact_repeats,0);
});
test('error text alone never creates a return-after-error classification',()=>{
 const {data,graph}=fixture();graph.edges=graph.edges.filter(e=>e.id!=='error');for(const n of graph.nodes.filter(n=>n.properties.kind==='feedback'))n.properties.source.text='ERROR: boom';
 assert.equal(project(data,graph).targets[0].count.after_error,0);
});
test('missing feedback and missing references remain coverage gaps, not negative findings',()=>{
 const {data,graph}=fixture();graph.edges=graph.edges.filter(e=>!['f2e','assessment'].includes(e.id));const t=project(data,graph).targets[0];
 assert.equal(t.count.feedback,1);assert.equal(t.count.references,0);assert.equal(t.pairs[0].feedback,'unavailable');assert.equal(matches(t,'missing_feedback'),true);
});
test('no work identity is inferred from identical labels or commands',()=>{
 const {data,graph}=fixture();data.visits[2].group_id='distinct';assert.equal(project(data,graph).targets.length,0);
});
test('mismatched saved versions and contribution observations are not compared as actions',()=>{
 const {data,graph}=fixture();for(const key of ['id','run_id','source_hash'])assert.equal(project(data,{...graph,[key]:'different'}).available,false);
 assert.equal(project({...data,axis:'contributions'},graph).available,false);
});
test('disputed identity and invalid path membership do not produce target metrics',()=>{
 const {data,graph}=fixture();assert.equal(project(data,graph,{affected_subject_ids:['same']}).targets.length,0);
 data.paths.push(data.paths[0]);const r=project(data,graph);assert.equal(r.targets.length,0);assert.equal(r.excluded_paths,2);
});
test('parallel or incomplete order does not establish unchanged ordered attempts or error-return counts',()=>{
 const {data,graph}=fixture();data.visits[2].occurrences[0].order_known=false;const t=project(data,graph).targets[0];
 assert.equal(t.pairs[0].ordered,false);assert.equal(t.pairs[0].dispatch,'unavailable');assert.equal(t.count.after_error,0);
});
test('cross-trajectory feedback and agent references cannot leak into a target',()=>{
 const {data,graph}=fixture();graph.nodes.find(n=>n.id==='think').trajectory_id='other';assert.equal(project(data,graph).targets[0].count.references,0);
 graph.nodes.find(n=>n.id==='f2').trajectory_id='other';assert.equal(project(data,graph).targets[0].count.feedback,1);
});
test('an occurrence cannot attach source evidence from a different trajectory',()=>{
 const {data,graph}=fixture();graph.nodes.find(n=>n.id==='a').trajectory_id='other';const t=project(data,graph).targets[0];assert.equal(t.steps[0].available,false);assert.equal(t.count.after_error,0);assert.equal(t.steps[0].raw,null);
});
test('shared responses are displayed but cannot establish exact repeated feedback',()=>{
 const {data,graph}=fixture();graph.edges.push({id:'shared',type:'feedback_for',source:'f1',target:'b'});const t=project(data,graph).targets[0];
 assert.equal(t.steps[0].responses[0].shared,true);assert.equal(t.pairs[0].feedback,'unavailable');assert.equal(t.count.exact_repeats,0);
});
test('metadata-only and empty responses cannot be labeled repeated feedback',()=>{
 for(const text of ['', '[Jupyter current working directory: /workspace]']){const {data,graph}=fixture();for(const n of graph.nodes.filter(n=>n.properties.kind==='feedback'))n.properties.source.text=text;
  assert.equal(project(data,graph).targets[0].pairs[0].feedback,'unavailable');}
});
test('duplicate source IDs fail closed and missing source units retain their occurrences',()=>{
 const {data,graph}=fixture();graph.nodes.push({...graph.nodes[0]});const t=project(data,graph).targets[0];assert.equal(t.steps.length,2);assert.equal(t.steps[0].available,false);assert.equal(t.pairs[0].dispatch,'unavailable');assert.equal(t.count.feedback,1);
});
test('late references retain actual record position rather than becoming explanations of a retry',()=>{
 const {data,graph}=fixture();graph.nodes.find(n=>n.id==='think').event_index=20;const t=project(data,graph).targets[0];assert.equal(t.steps[0].responses[0].references[0].record,21);assert.equal(t.steps[1].record,5);
});
test('filters select exact saved findings without changing target counts',()=>{
 const {data,graph}=fixture();const t=project(data,graph).targets[0];assert.equal(matches(t,'all'),true);assert.equal(matches(t,'after_error'),true);assert.equal(matches(t,'exact_repeat'),true);assert.equal(matches(t,'missing_feedback'),false);
});
test('following work stays in the same route and is not labeled completion',()=>{
 const {data,graph}=fixture();data.paths[0].visit_ids.push('vd');data.visits.push({id:'vd',group_id:'later',target:'Check file',positions:[4],order_known:true,occurrences:[{unit_id:'d'}]});graph.nodes.push({id:'d',kind:'unit',trajectory_id:'main',event_index:7,properties:{kind:'action',source:{text:'ls'}}});
 const t=project(data,graph).targets[0];assert.equal(t.next.id,'d');assert.equal(t.next.point.position,4);assert.equal(Object.hasOwn(t,'completed'),false);assert.equal(t.count.actions,2);
});

function procedures(data,procedure='reconfigured_procedure'){
 const e=data.episodes[0];return {graph_id:data.graph_id,run_id:data.run_id,source_hash:data.source_hash,records:[{episode_id:e.id,previous_unit_id:e.previous_unit_id,current_unit_id:e.current_unit_id,episode:{...e},procedure,procedure_reason:'Saved exact-pair procedure review.'}]};
}
test('review preserves exact saved procedure evidence separately from identical dispatch and feedback',()=>{
 const {data,graph}=fixture(),observations=procedures(data),before=JSON.stringify(observations),t=project(data,graph,null,observations).targets[0];
 assert.equal(t.pairs[0].comparison.key,'reconfigured_procedure');assert.equal(t.pairs[0].dispatch,'unchanged');assert.equal(t.count.exact_repeats,1);
 assert.deepEqual([t.count.procedure_compared,t.count.procedure_changed,t.count.procedure_unresolved],[1,1,0]);assert.equal(JSON.stringify(observations),before);
});
test('missing, stale, conflicting and unordered procedure evidence stays unresolved in review counts',()=>{
 const cases=[()=>null,d=>({...procedures(d),graph_id:'stale'}),d=>({...procedures(d),records:[...procedures(d).records,...procedures(d).records]}),d=>{d.visits[2].occurrences[0].order_known=false;return procedures(d);}];
 for(const build of cases){const {data,graph}=fixture(),t=project(data,graph,null,build(data)).targets[0];assert.equal(t.pairs[0].comparison.key,'unresolved');assert.equal(t.count.procedure_compared,0);assert.equal(t.count.procedure_unresolved,1);}
});
test('per-occurrence intent and ordered intervening context survive broad target grouping',()=>{
 const {data,graph}=fixture();data.visits[0].occurrences[0].target='Convert report with default engine';data.visits[2].occurrences[0].target='Convert report with selected engine';data.visits[1].occurrences[0].target='Install the missing engine';
 const t=project(data,graph).targets[0];assert.equal(t.target,'Run task');assert.deepEqual(t.steps.map(s=>s.intent),['Convert report with default engine','Convert report with selected engine']);assert.equal(t.pairs[0].between[0].intent,'Install the missing engine');
 assert.equal(Object.hasOwn(t,'successful'),false);assert.equal(Object.hasOwn(t,'exploration'),false);
});

class Element{
 constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.attributes={};this.classList={add(){}};}
 append(...children){this.children.push(...children);}replaceChildren(...children){this.children=children;}
 setAttribute(key,value){this.attributes[key]=value;}get childElementCount(){return this.children.length;}
}
const descendants=n=>[n,...n.children.flatMap(descendants)];
const renderedText=n=>descendants(n).map(e=>e.textContent||'').join(' ');
function draw(model,options={}){
 const prior=global.document;global.document={createElement:tag=>new Element(tag)};
 try{const host=new Element('div');require('../tracker/web/work-review.js').render(host,model,options);return host;}finally{global.document=prior;}
}
test('rendered review puts procedure coverage, intervening purpose and exact source links next to each return',()=>{
 const {data,graph}=fixture();data.visits[1].occurrences[0].target='Update the input artifact';
 const observations=procedures(data,'same_procedure');observations.records[0].episode.method={review:{author:'Named development review',note:'The same invocation follows a stored-input edit; this is separate context.'}};
 const model=project(data,graph,null,observations),opened=[],pairs=[];
 const host=draw(model,{selected:model.targets[0].id,onUnit:id=>opened.push(id),onPair:id=>pairs.push(id)}),text=renderedText(host);
 assert.match(text,/1\/1 procedure comparisons established · 0 changed/);assert.match(text,/Same dispatched procedure/);assert.match(text,/Same dispatch text/);
 assert.match(text,/same invocation follows a stored-input edit/);assert.match(text,/Source review · Named development review/);
 assert.match(text,/recorded sequence, not a causal explanation/);
 const bridge=descendants(host).find(n=>n.className==='wr-bridge');assert.equal(descendants(bridge).some(n=>n.tag==='details'),false);
 const button=descendants(bridge).find(n=>n.tag==='button');assert.match(button.textContent,/Action 2 · Update the input artifact/);button.onclick();assert.deepEqual(opened,['b']);
 descendants(host).find(n=>n.textContent==='Compare pair').onclick();assert.equal(pairs[0].id,'return');
});
test('rendered unknown comparison gives its reason and never presents missing review as zero changes',()=>{
 const {data,graph}=fixture(),model=project(data,graph),text=renderedText(draw(model,{selected:model.targets[0].id}));
 assert.match(text,/0\/1 procedure comparisons established · 1 unresolved/);assert.match(text,/No procedure comparisons for this exact graph and source/);assert.doesNotMatch(text,/0 changed/);
});

test('work-navigation passes saved procedure observations to the review at the actual UI boundary',()=>{
 const fs=require('node:fs'),vm=require('node:vm'),{data,graph}=fixture(),observations=procedures(data),stop=new Error('projection captured');
 data.available=true;data.counts={recorded_actions:3,visits:3,returned:1};let received;
 const context={document:{createElement:tag=>new Element(tag)},window:{WorkTimeline:require('../tracker/web/work-timeline.js'),WorkReview:{project(...args){received=args;throw stop;}}}};
 vm.runInNewContext(fs.readFileSync(require.resolve('../tracker/web/work-navigation.js'),'utf8'),context);
 assert.throws(()=>context.window.WorkNavigationView.render(new Element('div'),data,()=>{},()=>{},null,()=>{},null,()=>{},()=>{},{graph,procedures:observations}),error=>error===stop);
 assert.deepEqual(received,[data,graph,null,observations]);
});
