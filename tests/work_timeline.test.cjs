const {test}=require('node:test');
const assert=require('node:assert/strict');
const {project,overview}=require('../tracker/web/work-timeline.js');
function fixture(){
 const visit=(id,group,positions)=>({id,group_id:group,target:'Identical wording',order_known:true,positions,occurrences:positions.map(i=>({unit_id:'u'+i,event_id:'e'+i,order_known:true}))});
 const visits=[visit('a','x',[1]),visit('b','y',[2]),visit('gap',null,[3]),visit('c','x',[4,5]),visit('d','z',[6])];
 const episodes=[{id:'back',previous_unit_id:'u1',current_unit_id:'u4',category:'interrupted'},{id:'next',previous_unit_id:'u4',current_unit_id:'u5',category:'continued'}];
 const links=episodes.map(e=>({id:'l-'+e.id,type:'same_work_return',episode_id:e.id,source:'c',target:e.id==='back'?'a':'c',category:e.category}));
 return {graph_id:'g',visits,paths:[{actor:'agent',trajectory_id:'t',visit_ids:visits.map(v=>v.id)}],episodes,links};
}
test('all occurrences survive grouping and equal wording never merges distinct identities',()=>{
 const data=fixture(),before=JSON.stringify(data),p=project(data);
 assert.equal(p.axis,'Action');assert.equal(p.count,6);assert.equal(p.paths[0].rows.length,4);
 assert.deepEqual(p.paths[0].rows[0].points.map(p=>p.position),[1,4,5]);
 assert.equal(p.paths[0].pairs.length,2);assert.equal(JSON.stringify(data),before);
});
test('source gaps, unordered calls and disputed identity remain explicit without joining disputed visits',()=>{
 const d=fixture();d.visits[1].occurrences[0].order_known=false;
 const p=project(d,{scopeAudit:{affected_subject_ids:['x']}}).paths[0];
 assert.equal(p.rows.length,5);assert.equal(p.pairs.length,0);
 assert.equal(p.points.filter(p=>p.unresolved).length,1);assert.equal(p.points.filter(p=>!p.order_known).length,1);
 assert.equal(p.points.filter(p=>p.disputed).length,3);
});
test('recurrence symbols require exact same-route endpoints and a unique matching saved episode',()=>{
 for(const change of [d=>d.episodes=[],d=>d.episodes.push({...d.episodes[0]}),d=>d.links[0].category='returned',d=>d.episodes[0].current_unit_id='u2',d=>d.links[0].target='b',d=>d.episodes[0].previous_unit_id='u5']){
  const d=fixture();change(d);const p=project(d).paths[0];assert.ok(!p.pairs.some(p=>p.link.episode_id==='back'));
 }
 const d=fixture();d.links.push({...d.links[0],id:'duplicate-witness'});assert.equal(project(d).paths[0].pairs.length,2);
});
test('a focused window keeps absolute positions and omits returns whose earlier evidence is outside it',()=>{
 const d=fixture(),p=project(d,{visitIds:['gap','c']}).paths[0];
 assert.equal(p.start,3);assert.equal(p.end,5);assert.equal(p.points.length,3);
 assert.deepEqual(p.pairs.map(p=>p.category),['continued']);assert.equal(p.points[0].unresolved,true);
});
test('paths keep their own axes and identically named work cannot cross trajectories',()=>{
 const d=fixture();d.visits.push({...d.visits[0],id:'other',positions:[1],occurrences:[{unit_id:'u7',order_known:true}]});d.paths.push({actor:'agent',trajectory_id:'another',visit_ids:['other']});
 d.episodes.push({id:'cross',previous_unit_id:'u1',current_unit_id:'u7',category:'returned'});d.links.push({id:'cross',type:'same_work_return',episode_id:'cross',source:'other',target:'a',category:'returned'});
 const p=project(d);assert.equal(p.count,7);assert.equal(p.paths.length,2);assert.equal(p.paths[1].pairs.length,0);assert.equal(p.paths[1].start,1);assert.equal(p.paths[1].end,1);
});
test('invalid route structure cannot silently draw misleading positions or partial counts',()=>{
 for(const change of [d=>d.visits.pop(),d=>d.paths.push({visit_ids:['a']}),d=>d.visits.push({...d.visits[0]}),d=>d.visits[3].positions=[4],d=>d.visits[3].positions=[1,5],d=>d.visits[3].positions=[NaN,5]]){
  const d=fixture();change(d);const p=project(d);assert.equal(p.paths[0].available,false);assert.ok(p.paths[0].issues.length);assert.equal(p.paths[0].points.length,0);
 }
});
test('contributions are not relabeled as attempts; sparse recording positions stay sparse',()=>{
 const d=fixture();d.axis='contributions';d.visits[4].positions=[12];const p=project(d);
 assert.equal(p.axis,'Contribution');assert.equal(p.count,6);assert.equal(p.paths[0].end,12);
 assert.equal(p.paths[0].points.filter(p=>p.position>6&&p.position<12).length,0);
});
test('a dense route retains the full tail rather than sampling the first screen',()=>{
 const d=fixture();d.visits=[{id:'all',group_id:'x',target:'Work',order_known:true,positions:Array.from({length:1500},(_,i)=>i+1),occurrences:Array.from({length:1500},(_,i)=>({unit_id:'u'+i,order_known:true}))}];d.paths=[{visit_ids:['all']}];d.links=[];d.episodes=[];
 const p=project(d);assert.equal(p.count,1500);assert.equal(p.paths[0].end,1500);assert.equal(p.paths[0].points.at(-1).position,1500);
});
test('compact overview preserves every mark while explicitly aggregating other identities',()=>{
 const d=fixture(),path=project(d).paths[0],rows=overview(path);
 assert.equal(rows.length,2);assert.equal(rows[0].group_id,'x');assert.equal(rows[1].aggregate,true);
 assert.equal(rows.flatMap(r=>r.points).length,6);assert.equal(new Set(rows.flatMap(r=>r.points.map(p=>p.id))).size,6);
 assert.deepEqual(rows[1].points.map(p=>p.visit_id),['b','gap','d']);assert.equal(rows[1].points[1].unresolved,true);
 assert.equal(path.rows.length,4);
 const disputed=project(d,{scopeAudit:{affected_subject_ids:['x']}}).paths[0];assert.deepEqual(overview(disputed),disputed.rows);
});
test('a recorded absence of an immediate work target is not unresolved identity',()=>{
 const d=fixture();d.axis='contributions';d.visits[2].occurrences[0].identity_status='not_applicable';
 const point=project(d).paths[0].points.find(p=>p.position===3);
 assert.equal(point.not_applicable,true);assert.equal(point.unresolved,false);assert.equal(point.pairs.length,0);
});
