const test=require('node:test');
const assert=require('node:assert/strict');
const E=require('../tracker/web/distribution-evidence.js');
function fixture(){
 const d={snapshot_id:'distribution-frozen',lens:'procedure',observer:'reviewed',cohort_id:'cohort-1',weighting:'rollout',
  categories:[{id:'same'},{id:'unknown'}],baseline:{start:0,end:2},current:{start:5,end:7},comparable:true,
  points:[],cases:[],analysis_receipts:[],task_mix:{shared_task_ids:['task-A']}};
 for(const [id,step,n,task]of [['r0',0,2,'task-A'],['r2',2,4,'task-A'],['r3',3,1,'task-B'],['r5',5,26,'task-A'],['r7',7,1,'task-B'],['r8',8,1,'task-A'],['ru',null,1,'task-A']]){
  d.points.push({run_id:id,step,graph_id:'graph-'+id,input_id:'input-'+id,task:{id:task},total:n+1,counts:{same:n,unknown:1}});
  for(let i=0;i<=n;i++)d.cases.push({id:'case-'+i,run_id:id,step,graph_id:'graph-'+id,input_id:'input-'+id,
   category:i===n?'unknown':'same',text:'Convert report '+i,map_url:'/semantic-map?run='+id+'&graph=graph-'+id+'&work_episode=case-'+i});
  d.analysis_receipts.push({run_id:id,graph_id:'graph-'+id,plan_id:'plan-'+id});
 }
 return d;
}
test('window boundaries include step zero and both endpoints; missing positions remain unplaced',()=>{
 const d=fixture();assert.equal(E.select(d,{category:'same',window:'earlier'}).matching_cases,6);
 assert.equal(E.select(d,{category:'same',window:'later'}).matching_cases,27);
 assert.equal(E.select(d,{category:'same',window:'outside'}).matching_cases,2);
 assert.equal(E.select(d,{category:'same',window:'unplaced'}).matching_cases,1);
 assert.equal(E.select(d,{category:'same'}).matching_cases,33);
 assert.equal(E.membership(d,{step:false}),'unplaced');
});
test('overlapping windows select union once while membership remains explicit',()=>{
 const d=fixture();d.current={start:2,end:5};d.comparable=false;
 const v=E.select(d,{category:'same',window:'windows'});
 assert.equal(v.matching_cases,33);assert.equal(v.matches.filter(r=>r.window==='both').length,4);
 assert.equal(new Set(v.matches.map(r=>r.run_id+'|'+r.id)).size,33);
 assert.equal(E.select(d,{category:'same'}).filters.window,'all');
});
test('every case is reachable, including more than three in one rollout',()=>{
 const d=fixture();const all=[];
 for(let page=0;page<3;page++)all.push(...E.select(d,{category:'same',window:'later',page}).rows);
 assert.equal(all.length,27);assert.equal(new Set(all.map(r=>r.run_id+'|'+r.id)).size,27);
 assert.equal(E.select(d,{category:'same',window:'later',page:999}).page,2);
 assert.equal(E.select(d,{category:'same',window:'later',page:-1}).page,0);
});
test('shared-task evidence excludes tasks outside the fixed-task comparison',()=>{
 const d=fixture();const v=E.select(d,{category:'same',window:'later',task_scope:'shared'});
 assert.equal(v.matching_cases,26);assert.equal(v.matching_rollouts,1);
 assert.ok(v.matches.every(c=>c.run_id==='r5'));assert.equal(v.expected_cases,26);
});
test('text search changes retrieval only and does not redefine rollout proportions',()=>{
 const d=fixture(),before=JSON.stringify(d),v=E.select(d,{category:'same',window:'later',query:'report 25'});
 assert.equal(v.matching_cases,1);assert.equal(v.available_cases,27);assert.equal(v.expected_cases,27);
 assert.equal(v.rows[0].rollout_category_count,26);assert.equal(v.rows[0].rollout_total,27);
 assert.equal(JSON.stringify(d),before);
 assert.equal(E.select(d,{category:'same',window:'later',query:'r7'}).matching_cases,1);
 assert.equal(E.select(d,{category:'same',window:'later',query:'missing'}).matching_cases,0);
});
test('case identities cannot silently cross source projections',()=>{
 const d=fixture();d.cases.find(c=>c.run_id==='r5').graph_id='other-version';
 const v=E.select(d,{category:'same',window:'later'});
 assert.equal(v.available_cases,26);assert.equal(v.expected_cases,27);assert.equal(v.unjoined_cases,1);
});
test('export includes all matching pages with original snapshot and graph provenance',()=>{
 const d=fixture(),v=E.select(d,{category:'same',window:'later',task_scope:'shared',page:1});
 const out=E.exportSelection(d,v);
 assert.equal(out.snapshot_id,d.snapshot_id);assert.equal(out.cases.length,26);
 assert.deepEqual(out.points.map(p=>p.run_id),['r5']);assert.equal(out.analysis_receipts[0].plan_id,'plan-r5');
 assert.equal(out.filters.task_scope,'shared');assert.equal(out.windows.later,d.current);
 assert.ok(out.cases.every(c=>c.map_url.includes('graph=graph-r5')));
});
test('unplaced-only data remains inspectable without inventing a training window',()=>{
 const d=fixture();d.baseline={start:null,end:null};d.current={start:null,end:null};d.comparable=false;
 const v=E.select(d,{category:'same'});assert.equal(v.filters.window,'all');assert.equal(v.matching_cases,36);
 assert.equal(E.select(d,{category:'same',window:'windows'}).matching_cases,0);
});
test('inline source preview uses exact pair and response identities, never role or text guesses',()=>{
 const c={episode:{previous_unit_id:'before',current_unit_id:'after',feedback_unit_ids:['f','f'],start_position:4,end_position:9,
  cards:[{unit_id:'before',text:'run --old'},{unit_id:'after',text:'run --new'},{unit_id:'f',text:'failure'},
   {unit_id:'other',role:'Returned feedback',text:'irrelevant success'}]}};
 const p=E.preview(c);assert.equal(p.earlier.text,'run --old');assert.equal(p.later.text,'run --new');
 assert.deepEqual(p.responses.map(r=>r.text),['failure']);assert.deepEqual(p.positions,[4,9]);
 c.episode.cards.push({unit_id:'before',text:'ambiguous'});assert.equal(E.preview(c).earlier,null);
 assert.equal(E.preview({}).later,null);
});
test('search can retrieve a recorded error or invocation without semantic classification',()=>{
 const d=fixture(),c=d.cases.find(c=>c.run_id==='r5'&&c.category==='same');
 c.episode={previous_unit_id:'a',current_unit_id:'b',feedback_unit_ids:['f'],cards:[
  {unit_id:'a',text:'pandoc input.md -o out.pdf'},{unit_id:'b',text:'pandoc --pdf-engine=xelatex input.md -o out.pdf'},
  {unit_id:'f',text:'pdflatex not found'}]};
 for(const query of ['PDFLATEX NOT FOUND','--pdf-engine=xelatex']){
  const v=E.select(d,{category:'same',window:'later',query});assert.equal(v.matching_cases,1);assert.equal(v.expected_cases,27);
 }
});
test('terminal formatting is removed only for display and search, never exported source',()=>{
 const d=fixture(),c=d.cases.find(c=>c.run_id==='r5');
 const raw='\x1b[31mERROR:\x1b[0m no pip';c.episode={feedback_unit_ids:['f'],cards:[{unit_id:'f',text:raw}]};
 assert.equal(E.displayText(raw),'ERROR: no pip');
 const v=E.select(d,{category:'same',window:'later',query:'ERROR: no pip'});assert.equal(v.matching_cases,1);
 assert.equal(E.exportSelection(d,v).cases[0].episode.cards[0].text,raw);
});
