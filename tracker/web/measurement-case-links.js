'use strict';
// Stable addresses within one immutable measurement, never the latest graph.
(function(root){
 const text=v=>typeof v==='string'&&v.length>0;
 function key(kind,item){
  const id=kind==='analysis'?item.id:kind==='anchor'?item.anchor:kind==='feedback'?item.request_hash:null;
  if(text(id))return kind+':'+id;
  if(['revision','retry'].includes(kind)&&text(item.failed_event_id)&&text(item.retry_event_id))return kind+':'+JSON.stringify([item.failed_event_id,item.retry_event_id]);
  return null;
 }
 function entries(explanation={}){
  const groups=[['analysis',explanation.analysis_cases],['anchor',[...(explanation.cases||[]),...(explanation.unavailable_windows||[])]],
   ['revision',explanation.revision_observation?.episodes],['retry',explanation.retry_observation?.episodes],['feedback',explanation.feedback_assessment?.observations]];
  return groups.flatMap(([kind,rows])=>(rows||[]).map(item=>({kind,item,key:key(kind,item),label:item.label||
   (kind==='anchor'?'Relationship from '+item.anchor:kind==='feedback'?'Feedback for '+item.action_event_id:
    item.failed_event_id?'Attempt '+item.failed_event_id+' → '+item.retry_event_id:'Recorded case'),
   status:item.status||item.retry_outcome||'Recorded observation'})));
 }
 function find(explanation,address){const found=entries(explanation).filter(e=>e.key===address&&e.key);return found.length===1?found[0]:null;}
 function address(explanation,kind,item){const k=key(kind,item);return k&&find(explanation,k)?k:null;}
 function nodes(entry){const c=entry.item;return [...new Set(c.node_ids||c.evidence_ids||
  (entry.kind==='anchor'?[c.anchor,...(c.matches||[]).flatMap(m=>m.node_ids||[])]:
   entry.kind==='feedback'?[c.action_event_id,...(c.response_event_ids||[]),c.assessment_event_id].filter(Boolean).map(id=>'event:'+id):
   [c.failed_unit_id,c.retry_unit_id].filter(Boolean)))];}
 function cohorts(panel,{scope,task}={}){
  if(scope==='matched')return panel.same_tasks?[{points:Object.fromEntries(['baseline','current'].map(side=>[side,panel.same_tasks.tasks.filter(t=>t.measured_on_both).flatMap(t=>t.points[side])]))}]:[];
  if(scope==='task')return (panel.same_tasks?.tasks||[]).filter(t=>task&&Object.keys(t.context).length===Object.keys(task).length&&Object.entries(t.context).every(([k,v])=>JSON.stringify(v)===JSON.stringify(task[k])));
  if(scope&&scope!=='all')return [];
  return panel.points?[{points:panel.points}]:(panel.cohorts||[]);
 }
 function returnUrl(current,{monitor,side,value,caseKey,scope,task}){
  const url=new URL(current,'http://rilldex.local');
  for(const [key,fieldValue]of Object.entries({evidence_monitor:monitor,evidence_side:side,evidence_value:value,evidence_case:caseKey,evidence_scope:scope,evidence_task:task?JSON.stringify(task):null}))
   if(fieldValue)url.searchParams.set(key,fieldValue);else url.searchParams.delete(key);
  return url.pathname+url.search+url.hash;
 }
 function mapUrl(receipt,entry,back){
  const addressKey=address(receipt.explanation,entry.kind,entry.item);
  if(!addressKey||!receipt.graph||!receipt.measurement?.id||receipt.run?.id!==receipt.graph.run_id)return null;
  return '/semantic-map?'+new URLSearchParams({run:receipt.run.id,observer:receipt.graph.observer,graph:receipt.graph.id,
   value:receipt.measurement.id,level:'units',measure_case:addressKey,return_to:back});
 }
 const api={entries,key,find,address,nodes,cohorts,mapUrl,returnUrl};root.MeasurementCaseLinks=api;
 if(typeof module!=='undefined')module.exports=api;
})(globalThis);
