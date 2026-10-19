const {test}=require('node:test');
const assert=require('node:assert/strict');
const {project,route}=require('../tracker/web/map-layout.js');

test('source-order projection separates sessions and never bridges unordered cards',()=>{
 const nodes=[0,1,2].map(i=>({id:'u'+i,kind:'unit',event_index:i,trajectory_id:'main',properties:{kind:'action'}}));
 const graph={nodes,edges:[]},rows=Object.fromEntries(nodes.map(n=>[n.id,{scope:['main','a'],event_id:n.id,index:n.event_index,start:0,end:5,reason:null,hidden:false}]));
 const order={version:'graph-unit-order/1',nodes:rows},pairs=()=>project(graph,[],[],order).edges.map(e=>[e.source,e.target]);
 assert.deepEqual(pairs(),[['u0','u1'],['u1','u2']]);
 rows.u1.scope=['main','b'];assert.deepEqual(pairs(),[['u0','u2']]);
 rows.u1.scope=['main','a'];rows.u1.reason='unresolved_source_order';assert.deepEqual(pairs(),[]);
 rows.u1.reason='parallel_dispatch';rows.u0.reason='parallel_dispatch';assert.deepEqual(pairs(),[]);
});

test('stored row links cannot override parallel evidence or hide legitimate feedback links',()=>{
 const nodes=[0,1].map(i=>({id:'event:'+i,kind:'event',event_index:i,trajectory_id:'main',properties:{id:String(i),kind:'action',text:'call'}}));
 const graph={nodes,edges:[{id:'row',type:'next_record',source:nodes[0].id,target:nodes[1].id},{id:'feedback',type:'response_to',source:nodes[1].id,target:nodes[0].id}]};
 const order={version:'graph-unit-order/1',nodes:Object.fromEntries(nodes.map(n=>[n.id,{scope:['main',null],event_id:n.properties.id,index:n.event_index,start:0,end:4,reason:'parallel_dispatch',hidden:false}]))};
 const before=JSON.stringify(graph),view=project(graph,[],[],order);
 assert.deepEqual(view.edges.map(e=>e.id),['feedback']);assert.equal(JSON.stringify(graph),before);
});

test('exact spans keep their internal order while overlapping spans and hidden records do not',()=>{
 const nodes=[0,1].map(i=>({id:'u'+i,kind:'unit',event_index:0,trajectory_id:'main',properties:{kind:'semantic'}}));
 const order={version:'graph-unit-order/1',nodes:{u0:{scope:['main',null],event_id:'e',index:0,start:0,end:5,reason:'unresolved_source_order'},u1:{scope:['main',null],event_id:'e',index:0,start:5,end:10,reason:'unresolved_source_order'}}};
 const view=()=>project({nodes,edges:[]},[],[],order);
 assert.equal(view().edges.length,1);order.nodes.u1.start=4;assert.equal(view().edges.length,0);
 order.nodes.u1.start=5;order.nodes.u0.hidden=true;assert.equal(view().edges.length,0);
});

test('derived verification records do not become agent units and incompatible edges are not drawn',()=>{
 const graph={nodes:[{id:'a',kind:'event',event_index:1,trajectory_id:'t',properties:{kind:'action',actor:'agent',text:'check'}},
 {id:'b',kind:'event',event_index:2,trajectory_id:'t',properties:{kind:'feedback',actor:'environment',text:'result'}},
 {id:'derived',kind:'delivery_verification',event_index:2,trajectory_id:'t',properties:{status:'conflicting_check_results'}}],
 edges:[{id:'invalid',source:'a',target:'b',type:'assesses',properties:{}}]};
 const before=JSON.stringify(graph),view=project(graph,['invalid']);
 assert.equal(view.nodes.length,2);assert.ok(!view.byId.has('derived'));
 assert.ok(!view.edges.some(e=>e.id==='invalid'));assert.equal(JSON.stringify(graph),before);
});
test('invalid local content falls back to original source without a phantom Plan stage',()=>{
 const graph={nodes:[{id:'event:e1',kind:'event',event_index:0,trajectory_id:'t',properties:{kind:'message',actor:'agent',text:'Original source'}},
 {id:'u',kind:'unit',activity:'plan',event_index:0,trajectory_id:'t',properties:{kind:'semantic',source:{event_id:'e1'},content:{summary:{text:'Unsupported meaning'}}}},
 {id:'u:stage',kind:'plan_step',event_index:0,trajectory_id:'t',properties:{id:'stage',text:'Unsupported stage'}}],
 edges:[{id:'g',source:'u',target:'event:e1',type:'grounded_in',properties:{}},{id:'s',source:'u',target:'u:stage',type:'contains_plan_step',properties:{}}]};
 const view=project(graph,[],['u']);assert.deepEqual(view.nodes.map(n=>n.id),['event:e1']);
 assert.equal(view.nodes[0].summary,'Original source');assert.equal(graph.nodes.length,3);
});

test('relationship paths and labels avoid all card interiors on a populated grid',()=>{
 const {connectionRoute}=require('../tracker/web/map-layout.js');
 const cards=Array.from({length:15},(_,i)=>({row:Math.floor(i/3),lane:i%3,x:60+i%3*370,y:50+Math.floor(i/3)*142,width:284,height:112}));
 const inside=(value,lo,hi)=>value>lo+.01&&value<hi-.01;
 const cross=(p,q,c)=>p[0]===q[0]?inside(p[0],c.x,c.x+c.width)&&Math.max(p[1],q[1])>c.y+.01&&Math.min(p[1],q[1])<c.y+c.height-.01:
  inside(p[1],c.y,c.y+c.height)&&Math.max(p[0],q[0])>c.x+.01&&Math.min(p[0],q[0])<c.x+c.width-.01;
 for(const a of cards)for(const b of cards){
  const r=connectionRoute(a,b,3),{x,y,width,lines}=r.badge,height=lines*12+8;
  for(const c of cards){
   for(let i=1;i<r.points.length;i++)assert.equal(cross(r.points[i-1],r.points[i],c),false,JSON.stringify({a,b,c,path:r.points}));
   assert.equal(x+width/2>c.x&&x-width/2<c.x+c.width&&y+height/2>c.y&&y-height/2<c.y+c.height,false,'badge overlaps a card');
  }
  assert.ok(r.points.every(([x,y])=>x>=0&&x<=1140&&y>=0));
  const onBoundary=(p,c)=>((p[0]===c.x||p[0]===c.x+c.width)&&p[1]>=c.y&&p[1]<=c.y+c.height)||((p[1]===c.y||p[1]===c.y+c.height)&&p[0]>=c.x&&p[0]<=c.x+c.width);
  assert.ok(onBoundary(r.points[0],a));assert.ok(onBoundary(r.points.at(-1),b));
 }
});

test('adjacent assessment returns directly through the gap and preserves its backward direction',()=>{
 const {connectionRoute}=require('../tracker/web/map-layout.js');
 const a={row:1,lane:0,x:60,y:192,width:284,height:112},b={row:0,lane:2,x:800,y:50,width:284,height:112};
 const r=connectionRoute(a,b);
 assert.equal(r.points[0][1],a.y);assert.equal(r.points.at(-1)[1],b.y+b.height);
 assert.ok(r.points.every(([x,y])=>x>=a.x&&x<=b.x+b.width&&y>=b.y+b.height&&y<=a.y));
 assert.equal(r.badge.lines,1);
});

test('same question across activities is a work relation, not a claimed return or recovery',()=>{
 const {family}=require('../tracker/web/map-layout.js');
 assert.equal(family('same_work_target'),'work');
});

test('native annotation namespace is displayed as reference evidence without product Plan mapping',()=>{
 const nodes=[0,1].map(i=>({id:'u'+i,kind:'unit',activity:'native:planning',event_index:i+1,trajectory_id:'main',properties:{actor:'agent',kind:'semantic',source:{start:0},content:{summary:{text:'Native source'}}}}));
 const graph={nodes,edges:[{id:'e',source:'u1',target:'u0',type:'native:backref:plan:verify',properties:{}}],
  semantic_context:{reference_annotation:{label_namespace:'native:'}}};
 const before=JSON.stringify(graph),view=project(graph);
 assert.equal(view.edges.find(e=>e.id==='e').family,'context');
 assert.equal(view.nodes[0].activity,'native:planning');assert.equal(JSON.stringify(graph),before);
 delete graph.semantic_context;
 assert.equal(project(graph).edges.find(e=>e.id==='e').family,'plan');
});

test('state facts attach to source steps without becoming activity cards or hiding unannotated events',()=>{
 const {stateEvidence}=require('../tracker/web/map-layout.js');
 const n=(id,kind,properties)=>({id,kind,properties,trajectory_id:'main',event_index:id==='event:a'?1:2});
 const g={nodes:[n('event:a','event',{kind:'action'}),n('event:r','event',{kind:'feedback'}),
  n('check:a','check',{criterion_id:'acceptance',criterion_version:'v1',result:'failed',required_objects:['code']}),
  n('snapshot:s','artifact_snapshot',{event_id:'a'}),n('version:v','object_version',{object:'code',version:'sha256:one'}),
  n('view:v','file_view',{event_id:'r'}),n('u','unit',{kind:'semantic',source:{event_id:'elsewhere'}})],
  edges:[['check:a','event:a','requested_by'],['check:a','event:r','result_recorded_at'],['check:a','snapshot:s','checked_snapshot'],
   ['snapshot:s','event:a','grounded_in'],['snapshot:s','version:v','contains_version'],['view:v','event:r','grounded_in']].map(([source,target,type])=>({source,target,type}))};
 const before=JSON.stringify(g),p=project(g);assert.equal(p.nodes.length,3);assert.ok(p.byId.has('event:a'));assert.ok(p.byId.has('event:r'));
 assert.ok(p.edges.every(e=>e.type==='source_order'));assert.equal(JSON.stringify(g),before);
 for(const id of ['event:a','event:r']){const e=stateEvidence(g,id);assert.equal(e.checks.length,1);assert.equal(e.checks[0].properties.result,'failed');assert.equal(e.snapshots[0].objects[0].properties.version,'sha256:one');}
 assert.equal(stateEvidence(g,'event:r').views.length,1);
 g.nodes.find(n=>n.id==='u').properties.source.event_id='a';g.edges.push({source:'u',target:'event:a',type:'grounded_in'});
 assert.equal(project(g).byId.has('event:a'),false);assert.equal(project(g).byId.has('event:r'),true);assert.equal(stateEvidence(g,'u').checks.length,1);
});

test('expressed scope nodes do not fabricate units or sequence steps',()=>{
 const units=[0,1].map(i=>({id:'u'+i,kind:'unit',event_index:i+1,trajectory_id:'main',properties:{actor:'agent',kind:'semantic',source:{start:0}}}));
 const plain=project({nodes:units,edges:[]});
 const g={nodes:[{id:'scope:request',kind:'work_scope',event_index:0,trajectory_id:'main',properties:{text:'Requested work'}},...units],edges:units.map(u=>({id:'scope-edge:'+u.id,source:u.id,target:'scope:request',type:'in_work_scope',properties:{}}))};
 const view=project(g);assert.deepEqual(view.nodes,plain.nodes);assert.deepEqual(view.edges,plain.edges);assert.equal(g.nodes.length,3);assert.equal(g.edges.length,2);
});

test('prose-only rollouts omit empty action lanes without dropping cards or ordering',()=>{
 const nodes=['orient','verify','construct'].map((activity,i)=>({id:'u'+i,kind:'unit',activity,event_index:1,trajectory_id:'a',properties:{kind:'semantic',source:{event_id:'prose',start:i*10,end:i*10+5}}}));
 const p=project({nodes,edges:[]});assert.deepEqual(p.lanes,[0]);assert.equal(p.width,400);assert.equal(p.nodes.length,3);assert.equal(p.edges.length,2);assert.ok(p.nodes.every(n=>n.x===60));
 for(const e of p.edges)assert.ok(!route(p.byId.get(e.source),p.byId.get(e.target)).includes('NaN'));
});

test('recorded rechecks connect visible occurrences without adding fake activity cards',()=>{
 const events=['a','b'].map((id,i)=>({id:'event:'+id,kind:'event',event_index:i,trajectory_id:'main',properties:{id,kind:'action',text:'validate()'}}));
 const checks=['a','b'].map(id=>({id:'check:'+id,kind:'check',properties:{action_id:id}}));
 for(const semantic of [false,true]){
  const units=semantic?events.map(e=>({id:'unit-'+e.properties.id,kind:'unit',event_index:e.event_index,trajectory_id:'main',properties:{kind:'action',source:{event_id:e.properties.id,start:0}}})):[];
  const graph={nodes:[...events,...checks,...units],edges:[...units.map(u=>({id:'ground-'+u.id,source:u.id,target:'event:'+u.properties.source.event_id,type:'grounded_in'})),{id:'recheck',source:'check:b',target:'check:a',type:'recorded_recheck_of',properties:{comparable:false,causal:false}}]};
  const before=JSON.stringify(graph),p=project(graph),edge=p.edges.find(e=>e.id==='recheck');
  assert.equal(p.nodes.length,2);assert.equal(edge.source,semantic?'unit-b':'event:b');assert.equal(edge.target,semantic?'unit-a':'event:a');
  assert.equal(edge.stored_source,'check:b');assert.equal(edge.stored_target,'check:a');assert.equal(edge.family,'verification');
  assert.equal(edge.properties.comparable,false);assert.equal(JSON.stringify(graph),before);
  assert.ok(!route(p.byId.get(edge.source),p.byId.get(edge.target)).includes('NaN'));
 }
});

test('sparse action and feedback lanes retain their meaning and compact cross-lane routes',()=>{
 const nodes=[{id:'a',kind:'event',event_index:1,properties:{kind:'action'}},{id:'f',kind:'event',event_index:3,properties:{kind:'feedback'}}];
 const p=project({nodes,edges:[]});assert.deepEqual(p.lanes,[1,2]);assert.equal(p.width,770);assert.equal(p.byId.get('a').lane,1);assert.equal(p.byId.get('f').lane,2);
 const path=route(p.byId.get('a'),p.byId.get('f'),3);const nums=[...path.matchAll(/\d+(?:\.\d+)?/g)].map(m=>Number(m[0]));assert.ok(Math.max(...nums)<p.width);
});
test('revision and procedure relationships remain distinct display families',()=>{
 const {family}=require('../tracker/web/map-layout.js');
 for(const type of ['changes_attempt_procedure','changes_attempt_prerequisite','attempts_declared_change','assesses_attempt_prerequisite','attempts_local_adjustment','adjustment_before_retry'])assert.equal(family(type),'review');
 for(const type of ['same_procedure','reconfigured_procedure','alternative_procedure','uses_correction_from'])assert.equal(family(type),'return');
 for(const type of ['declares_same_work_as','attempts_declared_work','prepares_declared_work','checks_declared_work'])assert.equal(family(type),'plan');
});
test('empty tool wrappers collapse without deleting their calls, feedback or source data',()=>{
 const n=(id,index,p)=>({id:'event:'+id,kind:'event',event_index:index,trajectory_id:'main',properties:{id,...p}});
 const nodes=[n('before',0,{kind:'instruction',text:'Task'}),n('wrapper',1,{actor:'agent',kind:'message',text:''}),n('call',2,{actor:'agent',kind:'action',parent_id:'wrapper',text:'search()'}),n('result',3,{kind:'feedback',text:''})];
 const edges=[{id:'response',source:'event:result',target:'event:call',type:'response_to'}];
 for(const semantic of [false,true])for(const kind of ['message','reasoning']){
  const g={nodes:nodes.map(n=>n.id==='event:wrapper'?{...n,properties:{...n.properties,kind}}:n),edges:[...edges]};if(semantic){g.nodes.push({id:'u',kind:'unit',event_index:2,trajectory_id:'main',properties:{kind:'action',source:{event_id:'call'},content:{summary:'Search'}}});g.edges.push({source:'u',target:'event:call',type:'grounded_in'});}
  const before=JSON.stringify(g),p=project(g);assert.equal(p.folded.length,1);assert.equal(p.byId.has('event:wrapper'),false);assert.ok(p.byId.has(semantic?'u':'event:call'));assert.ok(p.byId.has('event:result'));assert.match(p.byId.get('event:result').summary,/Empty feedback/);assert.equal(JSON.stringify(g),before);
 }
 for(const property of [{text:'I will search'},{attachments:['image.png']}])assert.equal(project({nodes:nodes.map(n=>n.id==='event:wrapper'?{...n,properties:{...n.properties,...property}}:n),edges}).folded.length,0);
 assert.equal(project({nodes:nodes.filter(n=>n.id!=='event:call'),edges:[]}).folded.length,0);
 assert.equal(project({nodes,edges:[...edges,{source:'event:wrapper',target:'event:before',type:'revises'}]}).folded.length,0);
 assert.equal(project({nodes:[...nodes,{id:'snapshot:s',kind:'artifact_snapshot',properties:{event_id:'wrapper'}}],edges:[...edges,{source:'snapshot:s',target:'event:wrapper',type:'grounded_in'}]}).folded.length,0);
});
test('whole rollout retains unannotated records, units, stages and stored links without creating causality',()=>{
 const n=(id,kind,index,properties={})=>({id,kind,event_index:index,trajectory_id:'a',properties});
 const graph={nodes:[n('event:0','event',0,{kind:'instruction',text:'Task'}),n('event:1','event',1),n('plan','unit',1,{kind:'semantic',source:{start:0},activity:'plan'}),n('plan:s1','plan_step',1,{id:'s1',text:'Build'}),n('act','unit',2,{kind:'action'}),n('out','unit',3,{kind:'feedback'})],edges:[{id:'g',source:'plan',target:'event:1',type:'grounded_in'},{id:'s',source:'plan',target:'plan:s1',type:'contains_plan_step'},{id:'p',source:'act',target:'plan',type:'recorded_with'},{id:'f',source:'out',target:'act',type:'feedback_for'}]};
 const before=JSON.stringify(graph),p=project(graph);assert.equal(p.nodes.length,5);assert.ok(p.byId.has('event:0'));assert.ok(!p.byId.has('event:1'));assert.equal(p.byId.get('act').row,p.byId.get('out').row);assert.equal(p.byId.get('act').row,p.byId.get('plan').row);
 assert.equal(new Set(p.nodes.map(n=>n.row+':'+n.lane)).size,5);assert.equal(p.edges.filter(e=>e.type==='source_order').length,3);assert.equal(p.edges.filter(e=>e.type==='feedback_for').length,1);assert.equal(JSON.stringify(graph),before);
 for(const e of p.edges)assert.ok(!route(p.byId.get(e.source),p.byId.get(e.target)).includes('NaN'));
});
test('source-only maps retain every record without semantic labels or duplicate sequence links',()=>{
 const g={nodes:[{id:'a',kind:'event',event_index:0,properties:{kind:'action'}},{id:'b',kind:'event',event_index:1,properties:{kind:'feedback'}}],edges:[{id:'n',source:'a',target:'b',type:'next_record'},{id:'f',source:'b',target:'a',type:'response_to'}]};
 const p=project(g);assert.equal(p.semantic,false);assert.equal(p.nodes.length,2);assert.equal(p.edges.length,2);assert.equal(p.byId.get('a').row,p.byId.get('b').row);
});

test('recorded response, action and feedback share one turn row without inferring semantic intent',()=>{
 const nodes=['message','action','feedback'].map((kind,i)=>({id:'event:'+i,kind:'event',event_index:i,trajectory_id:'episode',properties:{kind,text:kind}}));
 const g={nodes,edges:[{id:'dispatch',source:'event:0',target:'event:1',type:'parent_message',properties:{semantic_causality:false}},
  {id:'return',source:'event:2',target:'event:1',type:'response_to'}]};
 const before=JSON.stringify(g),p=project(g);
 assert.equal(new Set(p.nodes.map(n=>n.row)).size,1);
 assert.deepEqual(p.nodes.map(n=>n.lane),[0,1,2]);
 assert.equal(p.edges.find(e=>e.id==='dispatch').family,'execution');
 assert.equal(p.edges.find(e=>e.id==='dispatch').properties.semantic_causality,false);
 assert.equal(p.edges.find(e=>e.id==='return').family,'feedback');
 assert.equal(JSON.stringify(g),before);
});
test('plan stages retain declared order and route stage-specific links without changing stored endpoints',()=>{
 const nodes=[{id:'p',kind:'unit',event_index:1,properties:{kind:'semantic',plan_structure:{steps:[{id:'draft'},{id:'convert'}],links:[{from:'draft',to:'convert',kind:'precedes',evidence:[{text:'First draft, then convert'}]}]}}},...['convert','draft'].map(id=>({id:'p:'+id,kind:'plan_step',event_index:1,properties:{id,text:id}})),{id:'a',kind:'unit',event_index:2,properties:{kind:'action'}}];
 const edges=[...['convert','draft'].map(id=>({id,source:'p',target:'p:'+id,type:'contains_plan_step'})),{id:'attempt',source:'a',target:'p',type:'attempts_plan_step',properties:{plan_step_id:'convert'}}];const p=project({nodes,edges});assert.ok(p.byId.get('p:draft').row<p.byId.get('p:convert').row);const edge=p.edges.find(e=>e.id==='attempt');assert.equal(edge.target,'p');assert.equal(edge.display_target,'p:convert');assert.equal(p.edges.find(e=>e.type==='plan_precedes').properties.evidence[0].text,'First draft, then convert');
});
