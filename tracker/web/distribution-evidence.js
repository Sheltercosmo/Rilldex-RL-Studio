'use strict';
(function(root){
 const VERSION='distribution-evidence/1',WINDOWS=['all','windows','earlier','later','outside','unplaced'];
 const REPORTS={reported_again:'Error reported again',no_reported_error:'No error reported in later response',followup_unknown:'Later report unresolved',no_prior_error:'No error reported in earlier response',unknown:'Earlier report unresolved'};
 const reportCategory=c=>Object.hasOwn(REPORTS,c.error_followup?.category)?c.error_followup.category:'unknown';
 const validStep=v=>Number.isSafeInteger(v)&&v>=0;
 const displayText=value=>String(value||'').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').trim();
 function inside(step,window){return validStep(step)&&validStep(window?.start)&&validStep(window?.end)&&window.start<=step&&step<=window.end;}
 function membership(d,point){
  if(!validStep(point.step))return 'unplaced';
  const a=inside(point.step,d.baseline),b=inside(point.step,d.current);
  return a&&b?'both':a?'earlier':b?'later':'outside';
 }
 function matchesWindow(group,window){return window==='all'||window==='windows'&&['earlier','later','both'].includes(group)||group===window||group==='both'&&['earlier','later'].includes(window);}
 function preview(c){
  const e=c.episode,cards=e?.cards||[];
  const one=id=>{if(!id)return null;const found=cards.filter(c=>c.unit_id===id);return found.length===1?found[0]:null;};
  const context=c.response_context;
  return {earlier:one(e?.previous_unit_id),later:one(e?.current_unit_id),
   responses:context?(context.previous?.status==='available'?context.previous.records:[]):[...new Set(e?.feedback_unit_ids||[])].map(one).filter(Boolean),
   laterResponses:context?.current?.status==='available'?context.current.records:[],
   reason:c.stated_reason?.status==='selected'?c.stated_reason:null,
   positions:Number.isSafeInteger(e?.start_position)&&e.start_position>0&&Number.isSafeInteger(e?.end_position)&&e.end_position>e.start_position?[e.start_position,e.end_position]:null};
 }
 function select(d,raw={},pageSize=12){
  if(!Number.isSafeInteger(pageSize)||pageSize<1||pageSize>100)throw Error('Use 1–100 cases per page');
  const category=d.categories.some(c=>c.id===raw.category)?raw.category:d.categories[0]?.id;
  const window=WINDOWS.includes(raw.window)?raw.window:d.comparable?'windows':'all';
  const query=String(raw.query||'').trim().slice(0,200),needle=query.toLocaleLowerCase();
  const report=d.lens==='procedure'&&Object.hasOwn(REPORTS,raw.report)?raw.report:null;
  const taskScope=raw.task_scope==='shared'?'shared':'all',shared=new Set(d.task_mix?.shared_task_ids||[]);
  const points=d.points.filter(p=>matchesWindow(membership(d,p),window)&&(taskScope==='all'||shared.has(p.task?.id)));
  const byRun=new Map(points.map(p=>[p.run_id,p]));
  const bound=[],unjoined=[];
  for(const c of d.cases){
   if(c.category!==category)continue;
   const p=byRun.get(c.run_id);if(!p)continue;
   if(c.graph_id!==p.graph_id||c.input_id!==p.input_id){unjoined.push(c);continue;}
   bound.push({...c,window:membership(d,p),task:p.task,rollout_category_count:p.counts[category]||0,rollout_total:p.total});
  }
  const pointOrder=new Map(points.map((p,i)=>[p.run_id,i]));
  // Retain source case order within a rollout. IDs never order concurrent work.
  bound.sort((a,b)=>pointOrder.get(a.run_id)-pointOrder.get(b.run_id));
  const matches=bound.filter(c=>{
   if(report&&reportCategory(c)!==report)return false;
   if(!needle)return true;
   const p=preview(c),cards=[p.earlier,p.later,p.reason,...p.responses,...p.laterResponses].filter(Boolean);
   return [c.text,c.run_id,c.id,c.error_followup?.label,...cards.flatMap(v=>[v.label,v.text,v.event_id])].some(v=>displayText(v).toLocaleLowerCase().includes(needle));
  });
  const pages=Math.max(1,Math.ceil(matches.length/pageSize));
  const page=Math.min(Number.isSafeInteger(raw.page)&&raw.page>=0?raw.page:0,pages-1);
  const expected=points.reduce((sum,p)=>sum+(p.counts[category]||0),0);
  return {schema:VERSION,filters:{category,window,query,task_scope:taskScope,...(report?{report}:{})},page,pages,page_size:pageSize,
    rows:matches.slice(page*pageSize,(page+1)*pageSize),matches,
    expected_cases:expected,available_cases:bound.length,unjoined_cases:unjoined.length,
    matching_cases:matches.length,matching_rollouts:new Set(matches.map(c=>c.run_id)).size,
    window_rollouts:points.length,window_opportunities:points.reduce((s,p)=>s+p.total,0)};
 }
 function exportSelection(d,view){
  const selected=select(d,view.filters,view.page_size);
  const ids=new Set(selected.matches.map(c=>c.run_id));
  return {schema:VERSION,snapshot_id:d.snapshot_id,lens:d.lens,observer:d.observer,cohort_id:d.cohort_id,
   grouping:d.grouping,weighting:d.weighting,population_mode:d.population_mode,definition:d.definition,
   metadata:d.metadata,categories:d.categories,axis:d.axis,denominator:d.denominator,annotation_status:d.annotation_status,
   windows:{earlier:d.baseline,later:d.current},filters:selected.filters,
   ...(d.approach_followup?{approach_followup:d.approach_followup}:{}),
   counts:{matches:selected.matching_cases,rollouts:selected.matching_rollouts,available_cases:selected.available_cases,
    expected_cases:selected.expected_cases,unjoined_cases:selected.unjoined_cases},
   cases:selected.matches,points:d.points.filter(p=>ids.has(p.run_id)),
   analysis_receipts:(d.analysis_receipts||[]).filter(r=>ids.has(r.run_id)),
   limit:'Case retrieval from the displayed snapshot. Text filtering does not recompute category shares or establish semantic similarity. Overlapping windows select a case once.'};
 }
 const api={VERSION,WINDOWS,REPORTS,reportCategory,membership,select,preview,displayText,exportSelection};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.DistributionEvidence=api;
})(typeof window==='undefined'?globalThis:window);
