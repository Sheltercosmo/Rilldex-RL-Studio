/* Inspection paths are projections of saved evidence, never new graph claims. */
(function(root){
 'use strict';
 const resultTypes=new Set(['feedback_for','response_to']);
 const useTypes=new Set(['assesses','assesses_response_group','uses_evidence','responds_to','assesses_attempt_prerequisite']);
 const retryTypes=new Set(['revisits_after_error_report','completed_after_failed_call']);
 const pairTypes=new Set([...retryTypes,'same_action_target','recorded_recheck_of']);
 const changeTypes=new Set(['changes_attempt_procedure','changes_attempt_prerequisite','attempts_local_adjustment','adjustment_before_retry','attempts_declared_change','uses_correction_from']);
 const followTypes=new Set([...retryTypes,'recorded_recheck_of']),maxAttempts=64;
 const target=e=>e.display_target||e.target;
 const captured=(layout,id)=>(layout.nativeResponses||[]).filter(r=>!r.visible_edge_id&&r.action_card_ids.includes(id));
 const order=(a,b)=>(a.ordinal??Infinity)-(b.ordinal??Infinity)||a.id.localeCompare(b.id);
 function catalog(graph,layout,excludedEdgeIds=[]){
  const excluded=new Set(excludedEdgeIds),nodes=layout.byId;
  const valid=layout.edges.filter(e=>!excluded.has(e.id)&&e.family!=='sequence'&&nodes.has(e.source)&&nodes.has(target(e))&&nodes.get(e.source).trajectory_id===nodes.get(target(e)).trajectory_id);
  const incoming=new Map(),incident=new Map();
  const add=(map,key,value)=>{if(!map.has(key))map.set(key,[]);map.get(key).push(value);};
  for(const e of valid){add(incoming,target(e),e);add(incident,e.source,e);add(incident,target(e),e);}
  const sourceCards=new Map();
  for(const n of layout.nodes){
   const source=n.kind==='event'?n.id:n.properties?.source?.event_id?'event:'+n.properties.source.event_id:null;
   if(source)add(sourceCards,source,n);
  }
  // Check nodes are not cards. Resolve their recorded action/result attachments
  // through source identities, not matching strings or a nearby tool call.
  const graphNodes=new Map(graph.nodes.map(n=>[n.id,n])),attachments=new Map(),checksByAction=new Map();
  for(const e of graph.edges){
   if(excluded.has(e.id)||!['requested_by','result_recorded_at'].includes(e.type))continue;
   const check=graphNodes.get(e.source);if(check?.kind!=='check')continue;
   const lane=e.type==='requested_by'?1:2;
   const candidates=(sourceCards.get(e.target)||[]).filter(n=>n.lane===lane&&n.trajectory_id===check.trajectory_id);
   // Multiple units in one source event do not identify which unit performed
   // the captured check. Keep that attachment unresolved instead of duplicating it.
   const cards=candidates.length===1?candidates:[];
   if(!attachments.has(check.id))attachments.set(check.id,{check,actions:[],responses:[]});
   const row=attachments.get(check.id),key=lane===1?'actions':'responses';
   for(const card of cards)if(!row[key].some(n=>n.id===card.id))row[key].push(card);
  }
  for(const row of attachments.values())for(const n of row.actions)add(checksByAction,n.id,row.check);
  function follow(actionIds,seedEdges=[]){
   const ids=new Set(actionIds),edges=new Map(seedEdges.map(e=>[e.id,e])),queue=[...ids];let truncated=false;
   for(let i=0;i<queue.length;i++){
    for(const e of incoming.get(queue[i])||[]){
     if(!followTypes.has(e.type)||nodes.get(e.source).lane!==1||e.source===target(e))continue;
     if(!ids.has(e.source)){
      if(ids.size>=maxAttempts){truncated=true;continue;}
      ids.add(e.source);queue.push(e.source);
     }
     edges.set(e.id,e);
    }
   }
   return {ids:[...ids],edges:[...edges.values()],truncated};
  }
  function path(id,title,actionIds,seedEdges=[],extraNodes=[],checkRecords=[]){
   const ids=new Set([...actionIds,...extraNodes]),edges=new Map(seedEdges.map(e=>[e.id,e]));
   const take=e=>{edges.set(e.id,e);ids.add(e.source);ids.add(target(e));};
   const responses=new Set(extraNodes.filter(id=>nodes.get(id)?.lane===2));
   for(const id of actionIds){
    for(const e of incoming.get(id)||[])if(resultTypes.has(e.type)){take(e);responses.add(e.source);}
    for(const e of incident.get(id)||[])if(changeTypes.has(e.type))take(e);
   }
   for(const id of responses)for(const e of incoming.get(id)||[])if(useTypes.has(e.type))take(e);
   // Include one explicit revision hop from the expressions already in this
   // path. Do not recursively pull in the rest of a plan or work cluster.
   for(const id of [...ids])for(const e of incident.get(id)||[])if(e.type==='revises')take(e);
   const actions=[...new Set(actionIds)].map(id=>nodes.get(id)).filter(Boolean).sort(order);
   const checks=[...new Map([...checkRecords,...actions.flatMap(n=>checksByAction.get(n.id)||[])].map(n=>[n.id,n])).values()];
   return {id,title,anchor_id:actions[0]?.id||extraNodes[0],node_ids:[...ids].filter(id=>nodes.has(id)),edge_ids:[...edges.keys()],
    nodes:[...ids].map(id=>nodes.get(id)).filter(Boolean).sort(order),edges:[...edges.values()],checks,
    attempts:actions.map(n=>({node:n,responses:[...new Set((incoming.get(n.id)||[]).filter(e=>resultTypes.has(e.type)).map(e=>e.source))].map(id=>nodes.get(id)).sort(order),captured_responses:captured(layout,n.id),checks:checksByAction.get(n.id)||[]})),
    gaps:[...(!responses.size&&!actions.some(n=>captured(layout,n.id).length)?['No returned feedback is attached.']:[]),...(![...edges.values()].some(e=>useTypes.has(e.type))?['No saved feedback-use link.']:[])]};
  }
  const retries=[],pairs=new Map(),failed=[];
  for(const e of valid){
   if(!pairTypes.has(e.type)||nodes.get(e.source).lane!==1||nodes.get(target(e)).lane!==1||e.source===target(e))continue;
   const ids=[e.source,target(e)].sort(),key=JSON.stringify(ids);
   if(!pairs.has(key))pairs.set(key,{id:'pair:'+key,ids,edges:[]});pairs.get(key).edges.push(e);
  }
  for(const pair of pairs.values()){
   const retry=pair.edges.filter(e=>retryTypes.has(e.type));
   if(retry.length){
    const chain=follow(pair.ids,retry),item=path('retry:'+pair.id,'Retry after an error',chain.ids,chain.edges);
    item.truncated=chain.truncated;if(chain.truncated)item.gaps.push('This view shows up to '+maxAttempts+' linked attempts. Additional follow-ups remain in the full map.');retries.push(item);
   }
  }
  for(const row of attachments.values()){
   if(row.check.properties.result!=='failed')continue;
   const actions=row.actions.map(n=>n.id),next=[];
   for(const id of actions)for(const e of incoming.get(id)||[])if((retryTypes.has(e.type)||e.type==='recorded_recheck_of')&&nodes.get(e.source).lane===1)next.push(e);
   const chain=follow(actions),item=path('check:'+row.check.id,row.check.properties.criterion_id||'Recorded failed check',chain.ids,chain.edges,row.responses.map(n=>n.id),[row.check]);
   item.truncated=chain.truncated;if(chain.truncated)item.gaps.push('This view shows up to '+maxAttempts+' linked attempts. Additional follow-ups remain in the full map.');
   if(!item.node_ids.length)continue;
   if(!next.length)item.gaps.push('No linked retry or recheck is saved.');
   // Keep comparability explicit: a passing later operation is not necessarily
   // the same criterion, input scope, environment, or independently checked task.
   item.check_id=row.check.id;failed.push(item);
  }
  const compare=[...pairs.values()].map(p=>path(p.id,'Linked attempts',p.ids,p.edges));
  const groups=[
   {id:'failed-checks',label:'Failed checks',title:'Follow a failed check',description:'Follow the recorded failure through linked retries, changes and rechecks. Select an attempt to inspect its source.',empty:'No structured failed checks are attached to this map. Source error text alone is not a recorded check result.',cases:failed},
   {id:'retry-paths',label:'Retries',title:'Inspect a retry',description:'Start at a saved retry link and follow later linked attempts. Paths can overlap; they are not independent recovery episodes.',empty:'No explicit retry-after-error links are saved. Repeated action text alone does not establish a retry.',cases:retries},
   {id:'attempt-pairs',label:'Compare attempts',title:'Compare linked attempts',description:'Read action text and returned results side by side. The saved link states why the attempts are paired.',empty:'No same-target, retry or recheck pairs are saved. Open an action to inspect its source, or run semantic analysis.',cases:compare}
  ];
  for(const group of groups)group.cases.sort((a,b)=>order(nodes.get(a.anchor_id),nodes.get(b.anchor_id))||a.id.localeCompare(b.id));
  return groups;
 }
 function summary(item){
  const checks=[...new Map(item.checks.map(n=>[n.id,n])).values()];
  return {attempts:item.attempts.length,checks:checks.length,
   failed:checks.filter(n=>n.properties.result==='failed').length,
   passed:checks.filter(n=>n.properties.result==='passed').length,
   unknown:checks.filter(n=>!['passed','failed'].includes(n.properties.result)).length,
   feedbackUses:item.edges.filter(e=>useTypes.has(e.type)).length,
   changes:item.edges.filter(e=>changeTypes.has(e.type)||e.type==='revises').length,
   truncated:!!item.truncated};
 }
 const api={catalog,summary};if(typeof module!=='undefined')module.exports=api;else root.InspectionPaths=api;
})(typeof globalThis!=='undefined'?globalThis:this);
