const test=require('node:test');
const assert=require('node:assert/strict');
const {orderedUnits,scopeThroughUnit,recordFocus,focusUnitIds,visibleUnitIds,unitConnections,visibleSequence,checkingObservations,materialObservation,relationReviewMatches,lineagesForUnit,lineageFocus}=require('../tracker/web/semantic-map.js');
const {methodObservation,methodGroupSummary}=require('../tracker/web/semantic-map.js');

test('declared-work focus includes later bound actions and responses with intervening units',()=>{
 const doc={units:['statement','intervening','action','response','outside'].map(id=>({id})),relations:[{type:'feedback_for',from:'response',to:'action'}],
 declared_work_history:{records:[{id:'work',updates:[{unit_id:'statement'}]}]},declared_work_actions:{relations:[{declared_work_id:'work',from:'action',to:'statement'}]}};
 assert.deepEqual([...focusUnitIds(doc,'declared:work')],['statement','intervening','action','response']);
 assert.deepEqual([...focusUnitIds(doc,'declared:missing')],[]);
});

test('stage focus retains the Plan anchor without expanding through it into sibling stages',()=>{
 const doc={units:[{id:'p',kind:'semantic'},{id:'a',kind:'action'},{id:'f',kind:'feedback'},{id:'b',kind:'action'}],relations:[{from:'a',to:'p',type:'attempts_plan_step'},{from:'b',to:'p',type:'attempts_plan_step'},{from:'f',to:'a',type:'feedback_for'}],plan_execution:{plans:[{plan_unit_id:'p',stages:[{id:'stage-a',focus_unit_ids:['p','a','f']}]}]}};
 assert.deepEqual([...focusUnitIds(doc,'stage:stage-a')],['p','a','f']);
 const visible=visibleUnitIds(doc,{focus:'stage:stage-a',connected:true}).visible;
 assert.ok(visible.has('p'));assert.ok(visible.has('a'));assert.ok(visible.has('f'));assert.ok(!visible.has('b'));
 assert.equal(focusUnitIds(doc,'stage:missing').size,0);
});

test('procedure measurement belongs to an exact pair and group, with unresolved and uninspected counts retained',()=>{
 const pair={previous_unit_id:'a',current_unit_id:'b',group_id:'g',status:'selected',comparison:'same_procedure'};
 const doc={method_comparison:{observations:[pair,{...pair,previous_unit_id:'b',current_unit_id:'c',comparison:'unresolved'},{...pair,previous_unit_id:'c',current_unit_id:'d',status:'needs_context_selection'}],review_notes:[{previous_unit_id:'a',current_unit_id:'b'}]}};
 assert.equal(methodObservation(doc,{previous_group_unit_id:'a',unit_id:'b',group_id:'g'}),pair);
 assert.equal(methodObservation(doc,{previous_group_unit_id:'x',unit_id:'b',group_id:'g'}),null);
 assert.equal(methodObservation(doc,{previous_group_unit_id:'a',unit_id:'b',group_id:'other'}),null);
 assert.deepEqual(methodGroupSummary(doc,'g'),{pairs:3,notInspected:1,counts:{same_procedure:1,unresolved:1},reviewed:1});
 assert.deepEqual(methodGroupSummary({},'g'),{pairs:0,notInspected:0,counts:{},reviewed:0});
});

test('unit history excludes later terms and scope membership does not create work correspondence',()=>{
 const u={id:'a',kind:'action',source:{event_id:'same',start:10,end:15}};
 const v=(id,event,start,end)=>({version_id:id,source_unit_id:id,source:{event_id:event,start,end},record:{text:id}});
 const record={record_id:'r',trajectory_id:'main',versions:[v('early','old',0,5),v('before','same',0,10),v('late','same',15,20)],dispatch_correspondences:[{action_unit_id:'a',version_id:'before'}]};
 const unrelated={...record,record_id:'other',dispatch_correspondences:[]};
 const data={work_lineage:{records:[record,unrelated]}};
 const run={events:[{id:'old',index:1},{id:'same',index:2}]};
 const rows=lineagesForUnit(data,run,u);
 assert.equal(rows.length,1);assert.deepEqual(rows[0].versions.map(v=>v.version_id),['early','before']);
 assert.equal(lineageFocus(record),recordFocus({id:'r',trajectory_id:'main'}));
 assert.deepEqual(lineagesForUnit({},run,u),[]);
});

test('work scope focus reuses units and does not include unselected membership',()=>{
 const doc={units:[{id:'origin',kind:'semantic'},{id:'a',kind:'action'},{id:'b',kind:'semantic'}],relations:[],work_context_overview:{groups:[{id:'frame',unit_ids:['a'],source_unit_ids:['origin'],partial_unit_ids:['b']}]}};
 assert.deepEqual([...focusUnitIds(doc,'context:frame')],['a','origin']);
 assert.deepEqual([...visibleUnitIds(doc,{focus:'context:frame',filter:'actions'}).visible],['a']);
 assert.deepEqual([...focusUnitIds(doc,'context:missing')],[]);
});

test('a review belongs to the exact relation and work version, not all links sharing units',()=>{
 const ref={from:'action',to:'request',type:'prepares_requested_work',requested_work_version_id:'v1'};
 const note={kind:'relation_review',unit_ids:['action','request'],relation_ref:ref};
 assert.equal(relationReviewMatches(note,{...ref}),true);
 assert.equal(relationReviewMatches(note,{...ref,requested_work_version_id:'v2'}),false);
 assert.equal(relationReviewMatches(note,{...ref,type:'same_action_target'}),false);
 assert.equal(relationReviewMatches(note,{...ref,from:'request',to:'action'}),false);
 assert.equal(relationReviewMatches({kind:'relation_review',unit_ids:['action','request']},ref),true);
});

test('material judgments join on the full check, facet, operation and response identity',()=>{
 const entry={unit_id:'owner',check_id:'check',facet_id:'contents',action_unit_id:'a',feedback_unit_id:'f',choice:'reference_only'};
 const observed={response_material:{observations:[entry]}};
 const before=JSON.stringify(observed);
 assert.equal(materialObservation(observed,'owner','check','contents','a','f'),entry);
 for(const args of [['owner','check','existence','a','f'],['other','check','contents','a','f'],['owner','changed','contents','a','f'],['owner','check','contents','another','f'],['owner','check','contents','a','other']])assert.equal(materialObservation(observed,...args),null);
 assert.equal(materialObservation({},'owner','check','contents','a','f'),null);
 assert.equal(JSON.stringify(observed),before);
});

const unit=(id,event,start=0,end=10,kind='semantic',trajectory='main')=>({id,source:{event_id:event,start,end},kind,trajectory_id:trajectory});
const units=[unit('final','e7'),unit('result','e5',0,10,'feedback'),unit('action','e4',0,10,'action'),unit('second','e3',11,20),unit('first','e3'),unit('other','e6',0,10,'action','other'),unit('initial','e1')];
const run={events:['e1','e3','e4','e5','e6','e7'].map((id,index)=>({id,index}))};
const record={id:'payment',trajectory_id:'main'};
const doc={units,relations:[{from:'result',to:'action',type:'feedback_for'},{from:'action',to:'first',requested_work_id:'payment'},{from:'other',to:'initial',requested_work_id:'payment'},{from:'first',to:'initial'}],
 requested_work:{records:[record],steps:[{unit_id:'first',state_after:['old']},{unit_id:'second',state_after:['revised']},{unit_id:'final',state_after:['future']}],changes:[{record_id:'payment',after:record,source_unit_id:'first'},{record_id:'payment',after:record,source_unit_id:'final'}]},
 work_paths:{paths:[{id:'p1',related_unit_ids:['result','action'],plan_stages:[{plan_unit_id:'initial'}]}]}};

test('checking inspector combines native and later correspondences without changing the saved pass',()=>{
 const observed={stated_checks:{observations:[{unit_id:'u1',check:{id:'check-1'},actions:[{action_unit_id:'a1'}]},{unit_id:'u2',actions:[]}]},
  check_followthrough:{observations:[{unit_id:'u1',check_id:'check-1',actions:[{action_unit_id:'a2',retrieval:'earlier_stated_check'}]},
   {unit_id:'u2',check_id:'stale-check',actions:[{action_unit_id:'a3'}]}]}};
 const before=JSON.stringify(observed),rows=checkingObservations(observed);
 assert.deepEqual(rows[0].actions.map(a=>a.action_unit_id),['a1','a2']);assert.equal(rows[0].laterActionCount,1);
 assert.deepEqual(rows[1].actions,[]);assert.equal(JSON.stringify(observed),before);
 assert.equal(observed.stated_checks.observations[0].actions.length,1);
});

test('source order interleaves feedback and participants without changing saved unit order',()=>{
 assert.deepEqual(orderedUnits(doc,run).map(u=>u.id),['initial','first','second','action','result','other','final']);
 assert.equal(doc.units[0].id,'final');
});
test('scope cutoff separates contributions in the same event and excludes later approval',()=>{
 assert.deepEqual(scopeThroughUnit(doc,run,units.find(u=>u.id==='first')).map(s=>s.unit_id),['first']);
 assert.deepEqual(scopeThroughUnit(doc,run,units.find(u=>u.id==='action')).map(s=>s.unit_id),['first','second']);
 assert.deepEqual(scopeThroughUnit(doc,run,units.find(u=>u.id==='other')),[]);
});
test('record focus uses identity and trajectory, while target focus preserves related plan context',()=>{
 assert.deepEqual([...focusUnitIds(doc,recordFocus(record))].sort(),['action','final','first']);
 assert.deepEqual([...focusUnitIds(doc,'path:p1')].sort(),['action','initial','result']);
});
test('recurrence comparison focuses its saved interval without duplicating units or expanding by default',()=>{
 const observed={...doc,work_history:{recurrences:[{unit_id:'action',context:{focus_unit_ids:['first','second','action','result']}}]}};
 assert.deepEqual([...focusUnitIds(observed,'episode:action')],['first','second','action','result']);
 assert.deepEqual([...focusUnitIds(observed,'episode:unknown')],[]);
 const result=visibleUnitIds(observed,{focus:'episode:action',connected:false});
 assert.deepEqual([...result.visible].sort(),['action','first','result','second']);
 assert.ok(!result.visible.has('other'));assert.ok(!result.visible.has('initial'));
 assert.deepEqual([...visibleUnitIds(observed,{focus:'episode:action',filter:'actions',connected:false}).visible],['action']);
});
test('repeated sequence focus retains source context without making new unit identities',()=>{
 const observed={...doc,sequence_patterns:{runs:[{id:'repeat',context:{focus_unit_ids:['first','action','result','action']}}]}};
 assert.deepEqual([...focusUnitIds(observed,'pattern:repeat')],['first','action','result']);
 assert.deepEqual([...focusUnitIds(observed,'pattern:missing')],[]);
 assert.deepEqual([...visibleUnitIds(observed,{focus:'pattern:repeat',connected:false}).visible].sort(),['action','first','result']);
 assert.deepEqual([...visibleUnitIds(observed,{focus:'pattern:repeat',filter:'actions',connected:false}).visible],['action']);
});
test('action focus shows each directly connected unit once and does not expand recursively',()=>{
 const result=visibleUnitIds(doc,{focus:recordFocus(record),filter:'actions'});
 assert.deepEqual([...result.direct],['action']);
 assert.deepEqual([...result.visible].sort(),['action','first','result']);
 assert.deepEqual([...visibleUnitIds(doc,{focus:recordFocus(record),filter:'actions',connected:false}).visible],['action']);
});

test('separated-return focus retains the gap and feedback in the same map',()=>{
 const observed={...doc,sequence_patterns:{returns:[{id:'return',context:{focus_unit_ids:['first','second','action','result','action']}}]}};
 assert.deepEqual([...focusUnitIds(observed,'return:return')],['first','second','action','result']);
 assert.deepEqual([...focusUnitIds(observed,'return:missing')],[]);
 assert.deepEqual([...visibleUnitIds(observed,{focus:'return:return',connected:false}).visible].sort(),['action','first','result','second']);
 assert.deepEqual([...visibleUnitIds(observed,{focus:'return:return',filter:'actions',connected:false}).visible],['action']);
 assert.ok(!visibleUnitIds(observed,{focus:'return:return',connected:false}).visible.has('other'));
});
test('search intersects focus; an explicitly opened connection remains available without inventing membership',()=>{
 const result=visibleUnitIds(doc,{focus:'path:p1',matches:new Set(['other']),revealed:'first'});
 assert.equal(result.direct.size,0);assert.deepEqual([...result.visible],['first']);
});

test('unit connection focus preserves direction and multiple work relations without duplicating units',()=>{
 const graph={...doc,relations:[...doc.relations,{from:'action',to:'first',type:'checks',requested_work_id:'other-payment'}]};
 const result=unitConnections(graph,'action');
 assert.equal(result.incoming.length,1);assert.equal(result.outgoing.length,2);
 assert.deepEqual([...result.unitIds].sort(),['action','first','result']);
 assert.deepEqual([...focusUnitIds(graph,'unit:action')].sort(),['action','first','result']);
});

test('following a unit never pulls in neighbors of its neighbors or treats source adjacency as a link',()=>{
 const result=visibleUnitIds(doc,{focus:'unit:action',connected:true});
 assert.deepEqual([...result.visible].sort(),['action','first','result']);
 assert.ok(!result.visible.has('initial'));assert.ok(!result.visible.has('second'));
});

test('relation filter respects incoming edges, with the anchor retained outside action/search filters',()=>{
 const result=visibleUnitIds(doc,{focus:'unit:action',relation:'feedback_for',filter:'actions',matches:new Set(['result']),connected:false});
 assert.equal(result.direct.size,0);assert.deepEqual([...result.visible],['action']);
 assert.equal(result.neighborhood.incoming.length,1);assert.equal(result.neighborhood.outgoing.length,0);
 const all=visibleUnitIds(doc,{focus:'unit:action',relation:'feedback_for'});
 assert.deepEqual([...all.visible].sort(),['action','result']);
});

test('empty or unknown connection focuses add no guessed links; explicit jumps do not change membership',()=>{
 assert.deepEqual([...visibleUnitIds(doc,{focus:'unit:second'}).visible],['second']);
 assert.equal(unitConnections(doc,'unknown').unitIds.size,0);
 const result=visibleUnitIds(doc,{focus:'unit:action',revealed:'final'});
 assert.ok(result.visible.has('final'));assert.ok(!result.neighborhood.unitIds.has('final'));
});

test('filtered sequence accounts for all hidden units, including multiple units in one event',()=>{
 const result=visibleSequence(doc,run,new Set(['first','action','other']));
 assert.deepEqual(result.sequence.map(s=>[s.unit.id,s.hiddenBefore]),[['first',1],['action',1],['other',1]]);
 assert.equal(result.hiddenAfter,1);
 assert.equal(result.sequence.length+result.sequence.reduce((n,s)=>n+s.hiddenBefore,0)+result.hiddenAfter,doc.units.length);
 assert.equal(visibleSequence(doc,run,new Set()).hiddenAfter,doc.units.length);
});
