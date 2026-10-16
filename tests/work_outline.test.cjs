const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../tracker/web/work-outline.js');
test('decision windows distinguish missing mapping, zero linked work and checks',()=>{
 const window={boundary:'observation_cutoff',end_event_index:99};
 assert.match(api.decisionWindowText({status:'execution_unmapped'}),/not mapped/);
 assert.match(api.decisionWindowText({status:'conflicting_statements'}),/conflict/);
 assert.match(api.decisionWindowText({status:'mapped',counts:{actions:0}}),/does not establish/);
 assert.equal(api.decisionWindowText({status:'mapped',counts:{actions:1,attempts:0,preparations:0,checks:1,with_assessment:0}}),'0 attempts · 0 preparations · 1 check · 0/1 actions with assessed feedback');
 assert.match(api.decisionWindowBoundary({window}),/record 100.*remains open/);
 assert.match(api.decisionWindowBoundary({window:{...window,boundary:'next_statement'}}),/before the next statement/);
});
test('shared subgoals retain their parents and branch-local paths',()=>{
 const m=api.model({items:['root','a','b','shared'].map(id=>({id})),links:[['a','root'],['b','root'],['shared','a'],['shared','b']].map(([source,target])=>({source,target,type:'part_of'}))});
 assert.deepEqual(m.parents.get('shared'),['a','b']);assert.deepEqual(m.path('b','shared'),['b','shared']);assert.equal(m.path('a','root'),null);
});
test('alternative and replacement links do not become containment',()=>{
 const m=api.model({items:[{id:'a'},{id:'b'}],links:[{source:'a',target:'b',type:'alternative_to'},{source:'b',target:'a',type:'replaces'}]});
 assert.equal(m.path('a','b'),null);assert.equal(m.connections('b').length,2);
});
test('quoted evidence uses Unicode codepoints and rejects ambiguous or absent text',()=>{
 assert.deepEqual(api.citation({id:'e1',text:'😀 Start here. Continue.'},'Start here.'),{event_id:'e1',start:2,end:13,text:'Start here.'});
 assert.throws(()=>api.citation({id:'e1',text:'same same'},'same'));assert.throws(()=>api.citation({id:'e1',text:'source'},'absent'));
});
test('outline evidence never becomes extra unit-map activity',()=>{
 const layout=require('../tracker/web/map-layout.js');
 const graph={nodes:[{id:'event:e1',kind:'event',trajectory_id:'main',event_index:0,properties:{kind:'reasoning',actor:'agent',text:'Task'}},{id:'outline:1',kind:'work_outline_item',event_index:0,properties:{label:'Task'}},{id:'decision:1',kind:'work_outline_decision',event_index:0,properties:{type:'defer'}},{id:'scope:1',kind:'work_scope_term',event_index:0,properties:{text:'Work'}},{id:'mention:1',kind:'work_mention',event_index:0,properties:{label:'Another content object'}}],edges:[]};
 const value=layout.project(graph);assert.deepEqual(value.nodes.map(n=>n.id),['event:e1']);
});
test('full outline expands shared work once and never treats alternatives as parentage',()=>{
 const m=api.model({items:['root','a','b','shared','alternative'].map(id=>({id})),links:[...['a','b'].map(source=>({source,target:'root',type:'part_of'})),...['a','b'].map(target=>({source:'shared',target,type:'part_of'})),{source:'alternative',target:'a',type:'alternative_to'}]});
 const tree=api.overview(m,'root');assert.equal(tree.children.length,2);
 assert.equal(tree.children[0].children[0].shared,false);assert.equal(tree.children[1].children[0].shared,true);
 assert.equal(api.overview(m,'root',new Set(['a'])).children[1].children[0].shared,false);
});
test('decision history preserves conflicting statements and exact evidence without parent propagation',()=>{
 const late={id:'later',type:'resume',event_index:5,evidence:{end:20,text:'Resume A.'}};
 const early={id:'earlier',type:'defer',event_index:2,evidence:{end:10,text:'Defer A.'}};
 const conflict={id:'conflict',type:'reported_complete',event_index:2,evidence:{end:10,text:'Defer A.'}};
 const data={items:[{id:'root',label:'Goal',decisions:[]},{id:'a',label:'A',decisions:[late,early,conflict]},{id:'b',label:'B',decisions:[late]}]};
 assert.deepEqual(api.decisionHistory(data,new Set(['root'])),[]);
 const history=api.decisionHistory(data,new Set(['a']));assert.equal(history.length,3);assert.equal(history[2].id,'later');assert.equal(history[0].item_id,'a');assert.equal(history[0].evidence.text,'Defer A.');
});

function timelineFixture(){
 const ref=(event_index,type,id)=>({id,type,event_index,evidence:{event_id:'e'+event_index,start:0,end:10,text:id}});
 const item=(id,index,decisions=[])=>({id,label:id,event_index:index,source_actor:id==='root'?'user':'agent',evidence:[{event_id:'e'+index,end:10,text:id}],decisions});
 return {cutoff_event_index:100,items:[item('root',0),item('a',5,[ref(10,'pursue','choose'),ref(20,'reported_failed','failed'),ref(25,'resume','retry')]),item('b',15),item('shared',30)],links:[['a','root'],['b','root'],['shared','a'],['shared','b']].map(([source,target])=>({source,target,type:'part_of'}))};
}
test('work timeline keeps explicit history scoped to each branch without inferring active durations',()=>{
 const data=timelineFixture(),before=JSON.stringify(data),t=api.workTimeline(data,'root');
 assert.equal(t.recordCount,101);assert.equal(t.start,0);assert.equal(t.end,100);
 assert.deepEqual(t.rows.map(r=>r.item.id),['root','a','shared','b']);
 assert.deepEqual(t.rows[1].points.map(p=>p.type),['introduced','pursue','reported_failed','resume']);
 assert.deepEqual(t.rows[0].points.map(p=>p.type),['requested']);
 assert.equal(t.rows[2].depth,2);assert.equal(JSON.stringify(data),before);
 assert.deepEqual(api.workTimeline(data,'a').rows.map(r=>r.item.id),['a','shared']);
 assert.deepEqual(api.workTimeline(data,'root',new Set(['root'])).rows.map(r=>r.item.id),['root']);
});
test('nearby and conflicting timeline statements are grouped, never dropped or assigned a new state',()=>{
 const points=[{event_index:5,type:'introduced'},{event_index:5,type:'reported_failed'},{event_index:5,type:'reported_complete'},{event_index:8,type:'resume'},{event_index:15,type:'defer'}];
 const groups=api.markerGroups(points,100);
 assert.equal(groups.length,2);assert.equal(groups[0].position,5);assert.equal(groups[0].points.length,4);
 assert.deepEqual(groups.flatMap(g=>g.points),points);assert.equal(groups[1].points[0].type,'defer');
 assert.equal(api.markerGroups([{event_index:0}],0)[0].position,0);
});
test('one quote that introduces and chooses work creates one point while conflicting decisions remain',()=>{
 const data=timelineFixture(),item=data.items[1];
 item.decisions=[{id:'start',type:'pursue',event_index:item.event_index,evidence:{...item.evidence[0]}},
  {id:'conflict',type:'defer',event_index:item.event_index,evidence:{...item.evidence[0]}}];
 const points=api.workTimeline(data,'a').rows[0].points;
 assert.equal(points.length,2);assert.ok(points.every(p=>p.introduces));assert.deepEqual(new Set(points.map(p=>p.type)),new Set(['pursue','defer']));
});
