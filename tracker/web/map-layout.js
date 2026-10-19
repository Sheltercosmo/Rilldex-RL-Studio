'use strict';
// A view of recorded identities. Layout does not infer causal or behavioral links.
(function(root){
 // Card colors identify record kinds; edge colors identify relationships.
 // Dash patterns, arrowheads and textual labels keep meaning available without color.
 const colors={sequence:'#718096',execution:'#526176',feedback:'#3273c7',plan:'#98620e',review:'#b44976',return:'#7754c1',verification:'#158065',work:'#147b70',context:'#617087'};
 const patterns={sequence:'4 7',execution:'',feedback:'',plan:'10 4',review:'8 3 2 3',return:'12 5',verification:'',work:'3 4',context:'2 5'};
 function cardStyle(n){
  if(n.lane===2)return {key:'feedback',color:'#975b12',tint:'#fff5e5',symbol:'↳',label:'Returned feedback'};
  if(n.lane===1)return {key:'action',color:'#087b7b',tint:'#eaf8f5',symbol:'↗',label:'Action'};
  if(n.kind==='event')return {key:'source',color:'#617080',tint:'#f1f4f6',symbol:'□',label:'Source record'};
  return {key:'contribution',color:'#4d5eb8',tint:'#eef1ff',symbol:'◇',label:'Contribution'};
 }
 function family(type){if(['next_record','source_order'].includes(type))return 'sequence';if(['recorded_with','parent_message'].includes(type))return 'execution';if(['feedback_for','response_to'].includes(type))return 'feedback';if(['same_work_target','overlapping_work_scope','different_work_same_subject','similar_operation_distinct_target'].includes(type))return 'work';if(type.includes('plan')||type.includes('declared_work')||type==='declares_same_work_as')return 'plan';if(['assesses','assesses_response_group','revises','uses_evidence','responds_to','changes_attempt_procedure','changes_attempt_prerequisite','attempts_declared_change','assesses_attempt_prerequisite','attempts_local_adjustment','adjustment_before_retry'].includes(type))return 'review';if(['same_action_target','revisits_after_error_report','completed_after_failed_call','same_procedure','reconfigured_procedure','alternative_procedure','uses_correction_from'].includes(type))return 'return';return 'context';}
 function text(v){return typeof v==='string'?v:v?.text||'';}
 function declaredPlans(graph,nodeId){
  const nodes=new Map(graph.nodes.map(n=>[n.id,n]));
  return graph.edges.filter(e=>e.type==='declared_plan_at'&&e.target===nodeId).map(e=>nodes.get(e.source)).filter(n=>n?.kind==='declared_plan_snapshot').map(n=>{
   const previous=graph.edges.find(e=>e.type==='previous_plan_declaration'&&e.source===n.id);
   return {snapshot:n.properties,previous:nodes.get(previous?.target)?.properties||null,comparable:previous?.properties.comparable??null};
  });
 }
 function declaredWork(graph,nodeId){
  const byId=new Map(graph.nodes.map(n=>[n.id,n])),selected=byId.get(nodeId);if(!selected)return [];
  const eventId=selected.kind==='event'?nodeId:'event:'+selected.properties.source?.event_id;
  return graph.edges.filter(e=>e.type==='declared_work_at'&&e.target===eventId).map(e=>{
   const record=byId.get(e.source);if(!record)return null;
   let goal=record.kind==='declared_work_node'?record:byId.get(graph.edges.find(x=>x.type==='scopes_declared_work_record'&&x.target===record.id)?.source);
   if(goal?.properties.kind!=='goal')goal=byId.get(graph.edges.find(x=>x.type==='contains_declared_work'&&x.target===goal?.id)?.source);
   return goal?{goal,record}:null;
  }).filter(Boolean);
 }
 function stateEvidence(graph,nodeId){
  const nodes=new Map(graph.nodes.map(n=>[n.id,n])),selected=nodes.get(nodeId);if(!selected)return {checks:[],snapshots:[],views:[]};
  const eventIds=new Set(selected.kind==='event'?[selected.id]:graph.edges.filter(e=>e.source===nodeId&&e.type==='grounded_in').map(e=>e.target));
  if(selected.properties.source?.event_id)eventIds.add('event:'+selected.properties.source.event_id);
  const checks=graph.edges.filter(e=>['requested_by','result_recorded_at'].includes(e.type)&&eventIds.has(e.target)).map(e=>nodes.get(e.source)).filter(n=>n?.kind==='check');
  const checkIds=new Set(checks.map(n=>n.id)),snapshotIds=new Set();
  for(const e of graph.edges){
   if(e.type==='grounded_in'&&eventIds.has(e.target)&&nodes.get(e.source)?.kind==='artifact_snapshot')snapshotIds.add(e.source);
   if(['input_snapshot','effect_snapshot'].includes(e.type)&&eventIds.has(e.source)||e.type==='checked_snapshot'&&checkIds.has(e.source))snapshotIds.add(e.target);
  }
  const snapshots=[...snapshotIds].map(id=>({node:nodes.get(id),objects:graph.edges.filter(e=>e.source===id&&e.type==='contains_version').map(e=>nodes.get(e.target)).filter(Boolean)})).filter(s=>s.node);
  const views=graph.edges.filter(e=>e.type==='grounded_in'&&eventIds.has(e.target)).map(e=>nodes.get(e.source)).filter(n=>n?.kind==='file_view');
  return {checks:[...new Map(checks.map(n=>[n.id,n])).values()],snapshots,views};
 }
 function historyEvidence(graph,nodeId){
  const nodes=new Map(graph.nodes.map(n=>[n.id,n])),selected=nodes.get(nodeId);if(!selected)return [];
  const eventIds=new Set(selected.kind==='event'?[selected.id]:graph.edges.filter(e=>e.source===nodeId&&e.type==='grounded_in').map(e=>e.target));
  if(selected.properties.source?.event_id)eventIds.add('event:'+selected.properties.source.event_id);
  return graph.edges.filter(e=>e.type==='observes_dispatch'&&eventIds.has(e.target)).map(dispatch=>{
   const observation=nodes.get(dispatch.source),edges=graph.edges.filter(e=>e.source===dispatch.source),queryEdge=edges.find(e=>e.type==='evaluated_by_query');
   return {observation,dispatch,query:nodes.get(queryEdge?.target),edges,
    facts:edges.filter(e=>e.type==='uses_recorded_fact').map(e=>nodes.get(e.target)).filter(Boolean)};
  }).filter(row=>row.observation?.kind==='history_evidence_observation'&&row.query?.kind==='history_evidence_query');
 }
 function requestedClauses(graph,versionId){
  const nodes=new Map(graph.nodes.map(n=>[n.id,n])),record=nodes.get(versionId);if(!record||record.properties.kind!=='condition')return null;
  const rows=graph.edges.filter(e=>e.source===versionId&&e.type==='contains_requested_clause').sort((a,b)=>a.properties.position-b.properties.position);
  const clauses=rows.map(edge=>({node:nodes.get(edge.target),edge})),retired=graph.edges.filter(e=>e.source===versionId&&e.type==='retires_requested_clause').map(edge=>({node:nodes.get(edge.target),edge}));
  return {clauses,retired,status:graph.semantic_context?.requested_history?'clauses' in record.properties?'structured':'unstructured':'not_projected'};
 }
 function requestContext(graph,actionId){
  const edge=graph.edges.find(e=>e.type==='request_context_at_dispatch'&&e.source===actionId);if(!edge)return null;
  const nodes=new Map(graph.nodes.map(n=>[n.id,n])),snapshot=nodes.get(edge.target),members=new Set(graph.edges.filter(e=>e.source===snapshot.id&&e.type==='contains_requested_version').map(e=>e.target));
  const versions=snapshot.properties.version_ids.map(id=>'requested-version:'+id).filter(id=>members.has(id)).map(id=>nodes.get(id));
  const labels={prepares:'Prepares this work',attempts:'Attempts this work',checks:'Checks this work’s result',none:'No specific work correspondence selected',unresolved:'Work correspondence unresolved'};
  return {snapshot,edge,versions:versions.map(n=>({node:n,choice:edge.properties.choices[n.properties.version_id]||null,
   clauses:requestedClauses(graph,n.id),label:n.properties.kind==='condition'?'Condition in context · satisfaction not inspected':labels[edge.properties.choices[n.properties.version_id]]||'Work correspondence not inspected'}))};
 }
 function requestedHistory(graph){
  const info=graph.semantic_context?.requested_changes||graph.semantic_context?.requested_history;if(!info)return null;
  const terms={equivalent:'Same requested terms',additional_specification:'Additional specification',replacement_or_removal:'Replaced or removed terms',mixed_change:'Replaced and added terms',unresolved:'Term comparison unresolved'};
  const nodes=new Map(graph.nodes.map(n=>[n.id,n])),updates=new Map(graph.edges.filter(e=>e.type==='updates_requested_version').map(e=>[e.source,e])),groups=new Map();
  for(const n of graph.nodes.filter(n=>n.kind==='requested_work_version').sort((a,b)=>a.event_index-b.event_index||a.id.localeCompare(b.id))){
   const record=n.properties,key=JSON.stringify([n.trajectory_id,record.id]),edge=updates.get(n.id),p=edge?.properties||{},selections=p.selections||{},before=edge?nodes.get(edge.target):null;
   let label='Introduced request',review=false;
   if(edge){
    if(p.operation==='withdraw')label='Request withdrawn';
    else if(p.operation==='restore')label='Request restored';
    else if(p.status==='not_inspected')label='Recorded revision · terms not compared';
    else if(p.status==='needs_context_selection'){label='Comparison not inspected';review=true;}
    else if(selections.support?.value==='unsupported'){label='Record interpretation disputed';review=true;}
    else if(selections.support?.value!=='supported'){label='Source support unresolved';review=true;}
    else if(selections.scope?.value==='different_undertaking')label='Different undertaking';
    else if(selections.scope?.value!=='same_undertaking'){label='Undertaking unresolved';review=true;}
    else {label=terms[selections.terms?.value]||'Term comparison unavailable';review=!selections.terms||selections.terms.value==='unresolved';}
   }
   if(!groups.has(key))groups.set(key,{id:key,record_id:record.id,trajectory_id:n.trajectory_id,kind:record.kind,versions:[]});
   groups.get(key).versions.push({node:n,before,edge,label,review,source_unit_id:record.source_unit_id,source_event_id:nodes.get(record.source_unit_id)?.properties.source?.event_id});
  }
  return {info,groups:[...groups.values()]};
 }
 function lane(n){const p=n.properties;if(n.kind==='plan_step')return 0;if(n.kind==='unit')return p.kind==='action'?1:p.kind==='feedback'?2:0;return p.kind==='action'?1:['observation','tool_result','feedback'].includes(p.kind)||p.role==='tool'?2:0;}
 function project(graph,excludedEdgeIds=[],excludedUnitIds=[],sourceOrder=null){
  const sourceEvents=new Map(graph.nodes.filter(n=>n.kind==='event').map(n=>[n.properties.id,n.properties]));
  function orderInfo(n){
   if(sourceOrder)return sourceOrder.nodes[n.id]||{scope:[],reason:'missing_source_order'};
   const span=n.properties.source||{},p=sourceEvents.get(span.event_id)||n.properties;
   return {scope:[n.trajectory_id??null,p.context_id??null],event_id:span.event_id||(n.kind==='event'?p.id:null),index:n.event_index,
    start:span.start??0,end:n.kind==='event'?text(p.text).length:span.end,
    hidden:!!(p.copied_context||p.agent_visible===false||p.agent_visibility==='not_established'||p.kind?.startsWith('external_')),
    reason:p.order_known===false?'unresolved_source_order':p.batch_size>1?'parallel_dispatch':null};
  }
  function orderedPair(a,b){
   const x=orderInfo(a),y=orderInfo(b);
   if(JSON.stringify(x.scope)!==JSON.stringify(y.scope)||x.hidden||y.hidden)return false;
   if(x.event_id!=null&&x.event_id===y.event_id)return Number.isInteger(x.end)&&Number.isInteger(y.start)&&x.end<=y.start;
   return !x.reason&&!y.reason&&Number.isInteger(x.index)&&Number.isInteger(y.index)&&x.index<y.index;
  }
  const excluded=new Set(excludedEdgeIds);
  const invalid=new Set(excludedUnitIds);
  for(const e of graph.edges)if(e.type==='contains_plan_step'&&invalid.has(e.source))invalid.add(e.target);
  if(excluded.size||invalid.size)graph={...graph,nodes:graph.nodes.filter(n=>!invalid.has(n.id)),edges:graph.edges.filter(e=>!excluded.has(e.id)&&!invalid.has(e.source)&&!invalid.has(e.target))};
  const units=new Set(graph.nodes.filter(n=>n.kind==='unit').map(n=>n.id)),semantic=units.size>0,covered=new Set(graph.edges.filter(e=>e.type==='grounded_in'&&units.has(e.source)).map(e=>e.target));
  // Empty assistant envelopes duplicate their separately recorded tool calls.
  // Collapse only proven parent/child envelopes; keep blank results, orphan
  // messages, media and any envelope with its own semantic relationship.
  const folded=[];
  const raw=graph.nodes.filter(n=>{
   // Scope nodes are a higher-level view. They must not become fake units or
   // introduce extra source-order steps into the detailed rollout canvas.
   if(['work_subject','work_scope','work_scope_term','work_mention','requested_work_version','requested_state','requested_clause_version','history_evidence_query','history_evidence_observation','source_json_fact','artifact_snapshot','object_version','check','delivery_verification','file_view','declared_plan_snapshot','declared_plan_item','declared_work_node','declared_work_record','work_outline_item','work_outline_decision'].includes(n.kind))return false;
   if(n.kind!=='event')return true;
   if(semantic&&covered.has(n.id))return false;
   const p=n.properties,children=graph.nodes.filter(c=>p.id&&c.kind==='event'&&c.trajectory_id===n.trajectory_id&&c.properties.kind==='action'&&c.properties.parent_id===p.id);
   const media=['attachments','images','audio','media','content_parts'].some(k=>p[k]&&(!Array.isArray(p[k])||p[k].length));
   const related=graph.edges.some(e=>!['next_record','source_order','grounded_in'].includes(e.type)&&(e.source===n.id||e.target===n.id))||graph.edges.some(e=>e.type==='grounded_in'&&e.target===n.id&&graph.nodes.some(s=>s.id===e.source&&['artifact_snapshot','file_view'].includes(s.kind)));
   if(p.actor==='agent'&&['message','reasoning'].includes(p.kind)&&!text(p.text).trim()&&!media&&!related&&children.length){folded.push({id:n.id,child_event_ids:children.map(c=>c.id)});return false;}
   return true;
  });
  const parents=new Map(graph.edges.filter(e=>e.type==='contains_plan_step').map(e=>[e.target,e.source]));
  const sort=(a,b)=>(a.event_index??Infinity)-(b.event_index??Infinity)||(a.properties.source?.start??0)-(b.properties.source?.start??0)||a.id.localeCompare(b.id);
  const ordered=raw.filter(n=>n.kind!=='plan_step').sort(sort),sequence=[];
  for(const n of ordered){const stepOrder=(n.properties.plan_structure?.steps||[]).map(s=>s.id);sequence.push(n);sequence.push(...raw.filter(s=>parents.get(s.id)===n.id).sort((a,b)=>stepOrder.indexOf(a.properties.id)-stepOrder.indexOf(b.properties.id)));}
  sequence.push(...raw.filter(n=>n.kind==='plan_step'&&!sequence.includes(n)));
  const lanes=[...new Set(sequence.map(lane))].sort((a,b)=>a-b);
  const byId=new Map(),occupied=new Set(),nodes=[];let lastRow=-1,ordinal=0;
  for(const n of sequence){
   const col=lane(n);let row=null;
   if(col!==0){const pair=graph.edges.find(e=>['recorded_with','parent_message','feedback_for','response_to'].includes(e.type)&&(e.source===n.id&&byId.has(e.target)||e.target===n.id&&byId.has(e.source)));
    const prior=pair&&byId.get(pair.source===n.id?pair.target:pair.source);if(prior&&!occupied.has(prior.row+':'+col))row=prior.row;}
   if(row===null)row=++lastRow;occupied.add(row+':'+col);
   const p=n.properties,summary=text(p.content?.summary)||text(p.text)||text(p.source?.text)||text(p.label)||(n.kind==='event'?'Empty '+(p.kind||'source')+' record · source retained':n.id);
   const target=text(p.content?.work_target)||text(p.content?.target)||text(p.target),activity=n.activity|| (n.kind==='plan_step'?'plan step':p.kind||n.kind);
   const node={...n,lane:col,row,x:60+lanes.indexOf(col)*370,y:50+row*142,width:284,height:112,ordinal:n.kind==='plan_step'?null:++ordinal,summary,target,activity};
   nodes.push(node);byId.set(n.id,node);
  }
  function checkOccurrence(id){
   if(byId.has(id))return id;
   const check=graph.nodes.find(n=>n.id===id&&n.kind==='check');if(!check)return id;
   const event='event:'+check.properties.action_id;if(byId.has(event))return event;
   const action=nodes.find(n=>n.kind==='unit'&&n.properties.kind==='action'&&n.properties.source?.event_id===check.properties.action_id);
   return action?.id||id;
  }
  const projectedEdges=graph.edges.map(e=>e.type==='recorded_recheck_of'?{...e,stored_source:e.source,stored_target:e.target,
   source:checkOccurrence(e.source),target:checkOccurrence(e.target)}:e);
  const edges=projectedEdges.filter(e=>byId.has(e.source)&&byId.has(e.target)&&e.type!=='grounded_in'&&
   (!['next_record','source_order'].includes(e.type)||orderedPair(byId.get(e.source),byId.get(e.target)))).map(e=>{
   const stage=e.properties?.plan_step_id&&e.target+':'+e.properties.plan_step_id;
   const namespace=graph.semantic_context?.reference_annotation?.label_namespace;
   return {...e,family:namespace&&e.type.startsWith(namespace)?'context':e.type==='recorded_recheck_of'?'verification':family(e.type),display_target:stage&&byId.has(stage)?stage:e.target};
  });
  for(const n of nodes)for(const link of n.properties.plan_structure?.links||[]){const source=n.id+':'+link.from,target=n.id+':'+link.to;if(byId.has(source)&&byId.has(target))edges.push({id:'plan-link:'+source+':'+target,source,target,type:'plan_'+link.kind,family:'plan',properties:{...link,basis:'stored plan_structure.links',parent_unit:n.id}});}
  if(semantic||folded.length||sourceOrder){const previous=new Map();for(const n of nodes.filter(n=>n.kind!=='plan_step'&&n.kind!=='unresolved_reference')){const scope=JSON.stringify(orderInfo(n).scope),prev=previous.get(scope);if(prev&&orderedPair(prev,n)&&!edges.some(e=>e.source===prev.id&&e.target===n.id&&e.family==='sequence'))edges.push({id:'order:'+prev.id+':'+n.id,source:prev.id,target:n.id,type:'source_order',family:'sequence',properties:{basis:'recorded source order within the same session; not execution or causality'}});previous.set(scope,n);}}
  return {nodes,edges,byId,semantic,folded,lanes,width:Math.max(1,lanes.length)*370+30,height:Math.max(240,80+(lastRow+1)*142)};
 }
 function connectionRoute(a,b,index=0){
  // The grid's gutters belong to relationships; card interiors belong to evidence.
  // Ports follow the stored edge direction, including links back to earlier rows.
  const ax=a.x+a.width/2,bx=b.x+b.width/2,ab=a.y+a.height,bb=b.y+b.height;
  let points,badge,kind;
  if(a.row===b.row&&a.lane!==b.lane&&Math.abs(a.x-b.x)<=370){
   const right=b.x>a.x,start=right?a.x+a.width:a.x,end=right?b.x:b.x+b.width;
   points=[[start,a.y+a.height/2],[end,b.y+b.height/2]];kind='row';
   badge={x:(start+end)/2,y:a.y+a.height/2,width:Math.abs(end-start)-8,lines:2};
  }else if(a.lane!==b.lane&&Math.abs(a.row-b.row)<=1){
   // Adjacent rows can connect directly through their shared gap. A same-row
   // jump across an occupied middle lane uses the gap below the cards.
   const same=a.row===b.row,down=b.row>a.row;
   const sy=same||down?ab:a.y,ty=same||!down?bb:b.y,y=same?Math.max(ab,bb)+15:(sy+ty)/2;
   points=[[ax,sy],[ax,y],[bx,y],[bx,ty]];kind='gap';
   badge={x:(ax+bx)/2,y,width:Math.min(166,Math.abs(ax-bx)-24),lines:1};
  }else if(a.lane===b.lane){
   const rail=a.x+a.width+22+(index%4)*8;
   points=[[a.x+a.width,a.y+70],[rail,a.y+70],[rail,b.y+42],[b.x+b.width,b.y+42]];kind='rail';
   badge={x:a.x+a.width+27,y:a.y+25,width:46,lines:2};
  }else{
   const down=b.row>a.row,sy=down?ab:a.y,ty=down?b.y:bb,ay=sy+(down?15:-15),by=ty+(down?-15:15),rail=a.x+a.width+22+(index%4)*8;
   points=[[ax,sy],[ax,ay],[rail,ay],[rail,by],[bx,by],[bx,ty]];kind='rail';
   badge={x:(ax+rail)/2,y:ay,width:Math.min(138,rail-ax-12),lines:1};
  }
  return {d:points.map(([x,y],i)=>(i?'L':'M')+x+','+y).join(' '),points,badge,kind};
 }
 function route(a,b,index=0){return connectionRoute(a,b,index).d;}
 // Reading lenses select existing edges only. They never add a behavioral claim.
 function connectionView(layout,mode='all',selected=null,selectedEdge=null,proof=new Set()){
  const families={response:new Set(['execution','feedback']),feedback:new Set(['review']),plan:new Set(['plan']),changes:new Set(['return','review','verification'])};
  return layout.edges.filter(e=>{
   if(proof.has(e.id)||e.id===selectedEdge)return true;
   if(e.family==='sequence')return false; // Card order already represents chronology.
   if(mode==='selected'||mode==='selected_all')return !!selected&&(e.source===selected||(e.display_target||e.target)===selected);
   if(mode==='feedback')return ['assesses','assesses_response_group','uses_evidence','responds_to','assesses_attempt_prerequisite'].includes(e.type);
   return mode==='all'||families[mode]?.has(e.family);
  });
 }
 function relationMeaning(e){
  const meanings={
   recorded_with:['Recorded with','Connects an expressed contribution to its recorded action. This pairing does not establish that the action fulfilled the intention.'],
   parent_message:['Contains action','The recorded model message contains this dispatched action.'],
   feedback_for:['Response to','This returned observation belongs to the linked action. Read its result before interpreting the next attempt.'],
   response_to:['Response to','This returned observation belongs to the linked action.'],
   assesses:['Assesses feedback','The contribution describes or interprets this feedback. Assessment does not establish correctness.'],
   assesses_response_group:['Assesses feedback','The contribution assesses the linked response group.'],
   uses_evidence:['Uses evidence','The contribution explicitly uses information from the linked source.'],
   responds_to:['Responds to','The contribution responds to this earlier item.'],
   revises:['Revises','The later contribution changes the linked earlier proposal or claim.'],
   revisits_after_error_report:['Returns after error','An attempt returns to linked work after an error report. This does not establish recovery.'],
   same_action_target:['Same action target','The actions address the same recorded target. Their procedures or results may differ.'],
   same_procedure:['Same procedure','The compared attempts use the same reviewed procedure.'],
   reconfigured_procedure:['Changed settings','The compared attempts keep the procedure but change its settings.'],
   alternative_procedure:['Different procedure','The attempts use different reviewed procedures.'],
   uses_correction_from:['Uses correction','This attempt uses a correction from the linked earlier work.'],
   attempts_plan_step:['Attempts step','The action attempts this declared plan step; this link alone does not show completion.'],
   prepares_plan_step:['Prepares step','The action prepares for this declared step.'],
   checks_plan_step:['Checks step','The action checks an aspect of this declared step. Inspect the returned evidence for the result.'],
   contains_plan_step:['Declares step','This contribution declares the linked plan step.'],
   in_work_context:['Work context','The contribution is linked to this earlier work context; this is not a causal dependency.'],
   same_work_target:['Same work','The units address the same question or intended outcome.'],
   overlapping_work_scope:['Shared part of work','The units share part of their work scope, but are not identical tasks.'],
   recorded_recheck_of:['Rechecks criterion','The recorded check revisits a criterion. Comparability and results remain separate evidence.']
  };
  const [label,meaning]=meanings[e.type]||[e.type.replaceAll('_',' '),e.properties?.explanation||'A saved relationship between these two records. Open its evidence to inspect the basis.'];
  return {label,meaning};
 }
 function zoomAnchor(oldZoom,newZoom,left,top,x,y){return {left:(left+x)*newZoom/oldZoom-x,top:(top+y)*newZoom/oldZoom-y};}
 const api={project,requestedHistory,requestedClauses,requestContext,historyEvidence,stateEvidence,declaredPlans,declaredWork,route,connectionRoute,family,colors,patterns,cardStyle,text,connectionView,relationMeaning,zoomAnchor};if(typeof module!=='undefined')module.exports=api;else root.RolloutMapLayout=api;
})(typeof globalThis!=='undefined'?globalThis:this);
