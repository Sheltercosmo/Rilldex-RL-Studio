const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const context={window:{WorkTimeline:require('../tracker/web/work-timeline.js')}};
vm.runInNewContext(fs.readFileSync(require.resolve('../tracker/web/work-navigation.js'),'utf8'),context);
const {recurringWork,workWindow}=context.window.WorkNavigationView;
const plain=v=>JSON.parse(JSON.stringify(v));
function fixture(){
 const v=(id,group,positions)=>({id,group_id:group,target:'Same text',positions,occurrences:positions.map(i=>({unit_id:'u'+i,event_id:'e'+i})),order_known:true});
 const visits=[v('a','x',[1]),v('b','y',[2]),v('gap',null,[3]),v('c','x',[4,5]),v('d','z',[6])];
 const ep=(id,a,b,category)=>({id,previous_unit_id:'u'+a,current_unit_id:'u'+b,category,assessment_unit_ids:[]});
 const link=(id,source,target,category)=>({id,episode_id:id,type:'same_work_return',source,target,category});
 return {graph_id:'g',run_id:'r',source_hash:'s',visits,paths:[{visit_ids:visits.map(v=>v.id)}],episodes:[ep('back',1,4,'interrupted'),ep('again',4,5,'continued')],links:[link('back','c','a','interrupted'),link('again','c','c','continued')]};
}
test('same labels do not merge targets, and collapsed repetitions retain distinct pairs',()=>{
 const d=fixture(),before=JSON.stringify(d),rows=recurringWork(d);
 assert.equal(rows.length,1);assert.equal(rows[0].occurrences,3);assert.equal(rows[0].links.length,2);
 assert.equal(rows[0].continued,1);assert.equal(rows[0].interrupted,1);assert.equal(rows[0].returns,0);
 assert.deepEqual(plain(rows[0].visits).map(v=>v.id),['a','c']);assert.equal(JSON.stringify(d),before);
});
test('focused window preserves intervening work and gaps without including future visits',()=>{
 const d=fixture(),w=workWindow(d,recurringWork(d)[0]);
 assert.deepEqual(plain(w.visits).map(v=>v.id),['a','b','gap','c']);
 assert.deepEqual(plain(w.focusIds),['a','c']);assert.equal(w.visits[2].group_id,null);
 assert.equal(workWindow(d,null).visits.length,5);
});
test('duplicate witnesses are not extra recurrence opportunities',()=>{
 const d=fixture();d.links.push({...d.links[0],id:'duplicate'});
 assert.equal(recurringWork(d)[0].links.length,2);
});
test('missing episodes and mismatched endpoints cannot generate an apparent return',()=>{
 for(const change of [d=>d.episodes=[],d=>d.episodes.forEach(e=>e.current_unit_id='not-an-endpoint'),d=>d.episodes.forEach(e=>e.category='returned')]){
  const d=fixture();change(d);assert.equal(recurringWork(d).length,0);
 }
});
test('different routes stay separate even when their group identifier is reused',()=>{
 const d=fixture(),v={...d.visits[0],id:'other',occurrences:[{unit_id:'u6'}],positions:[1]};d.visits.push(v);d.paths.push({visit_ids:['other']});
 d.links.push({id:'cross',type:'same_work_return',source:'other',target:'a',episode_id:'cross',category:'returned'});
 d.episodes.push({id:'cross',previous_unit_id:'u1',current_unit_id:'u6',category:'returned'});
 assert.equal(recurringWork(d).length,1);assert.equal(recurringWork(d)[0].links.length,2);
});
test('ambiguous route membership is withheld and missing context falls back to the whole route',()=>{
 const d=fixture(),row=recurringWork(d)[0];d.visits=d.visits.filter(v=>v.id!=='b');
 assert.equal(workWindow(d,row).available,false);
 const other=fixture();other.paths.push({visit_ids:['a','c']});assert.equal(recurringWork(other).length,0);
});
test('procedure counts require the same snapshot and exact pair and retain unknowns',()=>{
 const d=fixture(),p={graph_id:'g',run_id:'r',source_hash:'s',records:[{episode_id:'back',previous_unit_id:'u1',current_unit_id:'u4',procedure:'alternative_procedure'}]};
 d.episodes[0].category=d.links[0].category='returned';
 let r=recurringWork(d,null,p)[0];assert.equal(r.procedure_changed,1);assert.equal(r.procedure_known,1);assert.equal(r.links.length,2);
 for(const key of ['graph_id','run_id','source_hash'])assert.equal(recurringWork(d,null,{...p,[key]:'different'})[0].procedure_known,0);
 assert.equal(recurringWork(d,null,{...p,records:[{...p.records[0],current_unit_id:'u5'}]})[0].procedure_known,0);
 assert.equal(recurringWork(d,null,{...p,records:[...p.records,...p.records]})[0].procedure_known,0);
});

test('overview cannot count a procedure that timeline withholds for incomplete order or disputed identity',()=>{
 for(const reason of ['interrupted','unordered','disputed','nested_mismatch']){
  const d=fixture();d.episodes[0].category=d.links[0].category='returned';
  const p={graph_id:'g',run_id:'r',source_hash:'s',records:[{episode_id:'back',previous_unit_id:'u1',current_unit_id:'u4',procedure:'alternative_procedure'}]};
  let audit=null;
  if(reason==='interrupted')d.episodes[0].category=d.links[0].category='interrupted';
  if(reason==='unordered')d.visits[0].occurrences[0].order_known=false;
  if(reason==='disputed')audit={affected_subject_ids:['x']};
  if(reason==='nested_mismatch')p.records[0].episode={...d.episodes[0],category:'continued'};
  assert.equal(recurringWork(d,audit,p)[0].procedure_known,0,reason);
 }
});
test('contribution counts are not dispatch counts, and disputes remain explicit',()=>{
 const d=fixture();d.axis='contributions';const r=recurringWork(d,{affected_subject_ids:['x']})[0];
 assert.equal(r.disputed,true);assert.equal(r.feedback_assessed,null);assert.equal(r.occurrences,3);
});
test('filtered window preserves unordered parallel siblings and does not relabel gap recurrence',()=>{
 const d=fixture();d.visits[1].order_known=false;d.visits[2].order_known=false;
 const r=recurringWork(d)[0],w=workWindow(d,r);
 assert.equal(r.interrupted,1);assert.equal(w.visits.filter(v=>!v.order_known).length,2);
});
