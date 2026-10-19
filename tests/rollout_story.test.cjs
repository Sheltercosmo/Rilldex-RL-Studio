const {test}=require('node:test');
const assert=require('node:assert/strict');
const L=require('../tracker/web/map-layout.js');
const S=require('../tracker/web/rollout-story.js');
const n=(id,index,kind,extra={})=>({id,kind:'event',event_index:index,trajectory_id:'main',properties:{id:id.replace('event:',''),kind,actor:kind==='feedback'?'environment':'agent',text:id,...extra}});
const edge=(source,target,type)=>({id:source+type+target,source,target,type,properties:{}});
const story=(nodes,edges=[],outcome={})=>{const g={id:'g',nodes,edges};return S.project(g,{outcome},L.project(g));};

test('source-linked dispatches compress into moments without losing feedback or standalone contributions',()=>{
 const a=n('event:a',1,'action'),r=n('event:r',2,'feedback',{text:'{"error":"Invalid query"}'}),b=n('event:b',3,'action'),report=n('event:end',4,'message');
 const s=story([a,r,b,report],[edge(r.id,a.id,'response_to')]);
 assert.equal(s.moments.length,3);assert.equal(s.moments[0].responses[0].kind,'error-field');
 assert.equal(s.moments[1].responses.length,0);assert.equal(s.relations.length,0);
 assert.equal(s.moments.reduce((sum,m)=>sum+m.nodes.length,0),4);
 assert.equal(s.counts.changes,0); // Error followed by another action is not inferred recovery.
});
test('shared parent groups sibling calls but actor and trajectory boundaries remain intact',()=>{
 const a=n('event:a',1,'action',{parent_id:'p'}),b=n('event:b',2,'action',{parent_id:'p'}),c=n('event:c',3,'action',{parent_id:'p',actor:'second'}),d={...n('event:d',4,'action',{parent_id:'p'}),trajectory_id:'other'};
 const s=story([a,b,c,d]);assert.equal(s.moments.length,3);assert.equal(s.moments[0].actions.length,2);
 assert.equal(s.moments[0].title,'event:a / event:b');
});
test('thinking attaches only through a source link, not adjacency or textual similarity',()=>{
 const thought=n('event:t',0,'message'),action=n('event:a',1,'action');
 assert.equal(story([thought,action]).moments.length,2);
 const s=story([thought,action],[edge(thought.id,action.id,'parent_message')]);
 assert.equal(s.moments.length,1);assert.equal(s.moments[0].contributions[0].id,thought.id);
});
test('cross-trajectory feedback and ambiguous action ownership are kept unpaired',()=>{
 const a=n('event:a',0,'action'),b=n('event:b',1,'action'),r=n('event:r',2,'feedback');
 const s=story([a,b,r],[edge(r.id,a.id,'response_to'),edge(r.id,b.id,'response_to')]);
 assert.equal(s.moments.length,3);assert.equal(s.moments[0].feedback.length,0);
 assert.equal(s.moments[2].responses.length,1);assert.equal(s.moments[2].title,'Unpaired response');
 const cross=story([a,{...r,trajectory_id:'other'}],[edge(r.id,a.id,'response_to')]);assert.equal(cross.moments.length,2);
});
test('text mentioning failures or nested error fields never becomes a failed-operation claim',()=>{
 assert.equal(S.preview('The test previously failed').kind,'text');
 assert.equal(S.preview('{"document":{"error":"example"}}').kind,'structured');
 assert.equal(S.preview('{"error":""}').kind,'fields');
 assert.equal(S.preview('').label,'Empty response');
});
test('retrieval preview shows actual first document and preserves the complete result',()=>{
 const raw=JSON.stringify({result:[[{document:{contents:'first source'}},{document:{contents:'second source'}}]]});
 const p=S.preview(raw);assert.equal(p.label,'2 retrieved documents');assert.equal(p.text,'first source');assert.equal(p.raw,raw);
});
test('saved revision and assessment links retain exact endpoints and are not generated from order',()=>{
 const a=n('event:a',0,'action'),r=n('event:r',1,'feedback'),b=n('event:b',2,'message');
 const s=story([a,r,b],[edge(r.id,a.id,'response_to'),edge(b.id,r.id,'assesses')]);
 assert.equal(s.relations.length,1);assert.equal(s.relations[0].target,r.id);assert.equal(s.moments[1].hasSignal,true);
 assert.equal(s.counts.changes,0);
});
test('native check result remains scoped to the check and does not set rollout success',()=>{
 const a=n('event:a',0,'action'),c={id:'check:c',kind:'check',trajectory_id:'main',event_index:0,properties:{criterion_id:'unit tests',result:'passed'}};
 const s=story([a,c],[edge(c.id,a.id,'requested_by')]);assert.equal(s.moments[0].checks[0].properties.result,'passed');assert.deepEqual(s.recorded,[]);
});
test('dataset final label is not silently translated into success or reward',()=>{
 const s=story([n('event:a',0,'action')],[],{source_final_annotation:{value:1},reward:0});
 assert.deepEqual(s.recorded,[{label:'Recorded reward',value:'0'},{label:'Dataset final label',value:'1'}]);
});
test('request and system context stay separate from agent activity, empty graph stays usable',()=>{
 const s=story([n('event:s',0,'context',{actor:'system'}),n('event:u',1,'instruction',{actor:'user'}),n('event:a',2,'action')]);
 assert.equal(s.requests.length,1);assert.equal(s.context.length,1);assert.equal(s.moments.length,1);assert.equal(s.represented,3);
 assert.equal(story([]).moments.length,0);
});
test('projection leaves saved graph and source immutable',()=>{
 const g={id:'g',nodes:[n('event:a',0,'action')],edges:[]};const before=JSON.stringify(g);S.project(g,{outcome:{}},L.project(g));assert.equal(JSON.stringify(g),before);
});

test('large source records never become unbounded story headings or navigation labels',()=>{
 const raw='Inspect the snapshot implementation.\n'+('source line\n'.repeat(3000));
 const s=story([n('event:long',0,'reasoning',{text:raw}),n('event:action',1,'action',{text:raw})]);
 for(const m of s.moments){
  assert.ok(m.displayTitle.length<=160);assert.doesNotMatch(m.displayTitle,/\n/);
  assert.equal(m.nodes[0].properties.text,raw);
  assert.ok(S.matches(m,'all','source line'),'search still includes full source');
 }
});

test('story excerpts bound both line count and characters without losing source',()=>{
 const raw='x\n'.repeat(500);
 assert.ok(S.excerpt(raw).split('\n').length<=6);
 assert.ok(S.excerpt('a'.repeat(10000)).length<=420);
 assert.ok(S.excerpt(raw).endsWith('…'));
 assert.equal(S.excerpt('short text'),'short text');
 for(const value of [JSON.stringify({output:raw}),JSON.stringify({error:raw}),JSON.stringify({result:[[{document:{contents:raw}}]]})]){
  const p=S.preview(value);assert.ok(p.text.length<=420);assert.ok(p.text.split('\n').length<=6);assert.equal(p.raw,value);
 }
});

test('story renderer uses compact headings and keeps full-source search and navigation usable',()=>{
 const fs=require('node:fs'),vm=require('node:vm');
 class Element{
  constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.dataset={};this.className='';this.value='';this.hidden=false;this.classList={add:s=>{this.className+=' '+s;}};}
  set textContent(value){this.copy=String(value);this.children=[];}
  get textContent(){return (this.copy||'')+this.children.map(c=>c.textContent).join('');}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(k,v){this.attributes[k]=v;}
  scrollIntoView(){this.scrolled=true;}
  focus(){this.focused=true;}
 }
 const raw='Inspect the implementation.\n'+'source line\n'.repeat(3000)+'TAIL_MARKER';
 const g={id:'long',nodes:[n('event:long',0,'reasoning',{text:raw}),n('event:other',1,'message',{text:'Other work'})],edges:[]};
 const context=vm.createContext({RolloutMapLayout:L,document:{createElement:tag=>new Element(tag)}});
 vm.runInContext(fs.readFileSync(require.resolve('../tracker/web/rollout-story.js'),'utf8'),context);
 const host=new Element('section'),data=S.project(g,{},L.project(g));context.RolloutStory.render(host,data,g,()=>{});
 const all=e=>[e,...e.children.flatMap(all)],elements=all(host),cards=elements.filter(e=>e.tag==='article');
 assert.equal(cards.length,2);
 assert.ok(elements.filter(e=>e.tag==='h3').every(e=>e.textContent.length<=160));
 const full=elements.find(e=>e.attributes['aria-label']==='Full contribution');
 assert.equal(full.textContent,raw);assert.equal(full.tabIndex,0);
 const search=elements.find(e=>e.attributes['aria-label']==='Search rollout story');
 search.value='TAIL_MARKER';search.oninput();assert.equal(cards[0].hidden,false);assert.equal(cards[1].hidden,true);
 const jump=elements.find(e=>e.attributes['aria-label']==='Jump to story moment');
 assert.ok(jump.children.every(e=>e.textContent.length<=170));
 jump.value='event:other';jump.onchange();assert.equal(cards[1].hidden,false);assert.equal(cards[1].scrolled,true);assert.equal(cards[1].focused,true);
});

test('follow-up cards expose the exact returned record and assessment, never the next message by order',()=>{
 const a=n('event:a',0,'action'),r=n('event:r',1,'feedback',{text:'Permission denied'}),unrelated=n('event:x',2,'message'),assessment=n('event:b',3,'message',{text:'Try the --user flag.'});
 const s=story([a,r,unrelated,assessment],[edge(r.id,a.id,'response_to'),edge(assessment.id,r.id,'assesses')]);
 const attempt=s.moments[0].attempts[0],reaction=attempt.responses[0].reactions[0];
 assert.equal(reaction.node.id,assessment.id);assert.equal(reaction.edge.target,r.id);assert.equal(attempt.responses.length,1);
 assert.equal(reaction.node.properties.text,'Try the --user flag.');assert.equal(s.counts.feedbackWithFollowup,1);
 assert.ok(S.matches(s.moments[0],'linked','--user'));assert.equal(S.matches(s.moments[0],'unlinked'),false);
 assert.equal(S.matches(s.moments[0],'changes'),false); // An assessment is not a revision or successful fix.
});

test('multiple assessments count one response, while unlinked feedback and missing responses stay distinct',()=>{
 const a=n('event:a',0,'action'),r=n('event:r',1,'feedback'),r2=n('event:r2',2,'feedback'),b=n('event:b',3,'message'),c=n('event:c',4,'message'),d=n('event:d',5,'action');
 const s=story([a,r,r2,b,c,d],[edge(r.id,a.id,'response_to'),edge(r2.id,a.id,'response_to'),edge(b.id,r.id,'assesses'),edge(c.id,r.id,'uses_evidence')]);
 assert.equal(s.counts.feedbackWithFollowup,1);assert.equal(s.moments[0].attempts[0].responses[0].reactions.length,2);
 assert.ok(S.matches(s.moments[0],'unlinked'));assert.ok(S.matches(s.moments[0],'linked'));
 assert.equal(S.matches(s.moments[0],'missing'),false);assert.ok(S.matches(s.moments.at(-1),'missing'));
 assert.equal(S.matches(s.moments.at(-1),'unlinked'),false);
});

test('sibling actions retain their own responses and follow-ups without copying batch evidence',()=>{
 const a=n('event:a',0,'action',{parent_id:'p'}),b=n('event:b',1,'action',{parent_id:'p'}),r=n('event:r',2,'feedback'),c=n('event:c',3,'message');
 const s=story([a,b,r,c],[edge(r.id,b.id,'response_to'),edge(c.id,r.id,'assesses')]);
 assert.equal(s.moments[0].attempts[0].responses.length,0);assert.equal(s.moments[0].attempts[1].responses[0].reactions[0].node.id,c.id);
});

test('cross-trajectory references cannot create a response-use chain',()=>{
 const a=n('event:a',0,'action'),r=n('event:r',1,'feedback'),b={...n('event:b',2,'message'),trajectory_id:'other'};
 const s=story([a,r,b],[edge(r.id,a.id,'response_to'),edge(b.id,r.id,'assesses')]);
 assert.equal(s.moments[0].responses[0].reactions.length,0);assert.equal(s.counts.feedbackWithFollowup,0);
});

test('short recorded commands distinguish identical targets; script annotations retain their basis',()=>{
 const a=n('event:a',0,'action',{text:'Running command: pip install x --user',target:'Install packages'});
 const b=n('event:b',1,'action',{text:'Running command: pip install x',target:'Install packages'});
 const s=story([a,b]);assert.equal(s.moments[0].attempts[0].operation.text,'pip install x --user');assert.equal(s.moments[1].attempts[0].operation.text,'pip install x');
 assert.equal(s.moments[0].attempts[0].operation.basis,'Recorded action');
 assert.deepEqual(S.operation({kind:'unit',properties:{source:{text:'x\n'.repeat(300)},content:{operation:'Write the loader'}},summary:'Prepare file'}),{text:'Write the loader',basis:'Action annotation'});
});

test('unpaired feedback remains searchable and reviewable without attributing it to an action',()=>{
 const r=n('event:r',0,'feedback',{text:'Unpaired result'}),b=n('event:b',1,'message',{text:'Discuss this result'});
 const noLink=story([r,b]);assert.ok(S.matches(noLink.moments[0],'unlinked'));assert.equal(S.matches(noLink.moments[0],'missing'),false);
 const linked=story([r,b],[edge(b.id,r.id,'assesses')]);assert.ok(S.matches(linked.moments[0],'linked','Discuss'));assert.equal(linked.counts.feedbackWithFollowup,1);assert.equal(linked.moments[0].attempts.length,0);
});

test('canonical source outcomes appear without translating task claims into verified success',()=>{
 const s=story([],[],{verified_success:false,recorded_reward:0,success:true,reward:1});
 assert.deepEqual(s.recorded,[{label:'Recorded success',value:'false'},{label:'Recorded reward',value:'0'}]);
 assert.deepEqual(story([],[],{termination:'submitted',recorded_steps:33}).recorded,[]);
});

test('latest source prose remains visible when no report was annotated, without becoming a report',()=>{
 const s=story([n('event:a',0,'reasoning',{text:'I think the job is finished.'}),n('event:b',1,'action',{text:'ls'})]);
 assert.equal(s.latestAgentText.id,'event:a');assert.equal(s.reports.length,0);assert.deepEqual(s.recorded,[]);
});

test('repeated dispatch navigation preserves originals, actor boundaries and distinct arguments',()=>{
 const a=n('event:a',0,'action',{tool:'shell',arguments:{a:1,b:2},text:'pip install x --user'});
 const b=n('event:b',2,'action',{tool:'shell',arguments:{b:2,a:1},text:'pip install x --user'});
 const c=n('event:c',3,'action',{tool:'shell',arguments:{a:1,b:3},text:'pip install x --user'});
 const d={...b,id:'event:d',event_index:4,trajectory_id:'other'};
 const s=story([a,b,c,d]);assert.equal(s.counts.repeatedDispatches,1);assert.equal(s.repetitionGroups.length,1);
 assert.deepEqual(s.repetitionGroups[0].actionIds,['event:a','event:b']);assert.equal(s.counts.changes,0);
 assert.ok(S.matches(s.moments[0],'repeated'));assert.ok(S.matches(s.moments[1],'repeated'));assert.equal(S.matches(s.moments[2],'repeated'),false);
});

test('error excerpt navigation is explicitly text evidence, not an execution failure or recovery',()=>{
 const a=n('event:a',0,'action'),r=n('event:r',1,'feedback',{text:'Example from a manual:\nPermission denied'});
 const s=story([a,r],[edge(r.id,a.id,'response_to')]);assert.equal(s.counts.notableOutputs,1);
 assert.equal(s.moments[0].responses[0].kind,'text');assert.match(s.moments[0].responses[0].label,/inspect context/);
 assert.ok(S.matches(s.moments[0],'output'));assert.equal(s.counts.changes,0);assert.deepEqual(s.recorded,[]);
 assert.equal(S.preview('{"document":{"error":"quoted error"}}').notable,undefined);
});
