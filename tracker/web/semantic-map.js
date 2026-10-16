'use strict';
const $=s=>document.querySelector(s);
const state={doc:null,run:null,selected:null,focus:'all',filter:'all',relation:'all',revealed:null,layout:'blueprint'};

// These projections preserve source units and selected relations; they add no judgments.
function sourceOrder(run,a,b){
 const positions=new Map(run.events.map((e,i)=>[e.id,e.index??i]));
 return (positions.get(a.source.event_id)??Infinity)-(positions.get(b.source.event_id)??Infinity)||a.source.start-b.source.start||a.source.end-b.source.end;
}
function orderedUnits(doc,run){return [...doc.units].sort((a,b)=>sourceOrder(run,a,b));}
function scopeThroughUnit(doc,run,u){
 const byId=new Map(doc.units.map(v=>[v.id,v]));
 return (doc.requested_work?.steps||[]).filter(s=>{
  const origin=byId.get(s.unit_id);
  return origin&&origin.trajectory_id===u.trajectory_id&&sourceOrder(run,origin,u)<=0;
 });
}
function recordFocus(record){return 'record:'+JSON.stringify([record.trajectory_id,record.id]);}
function lineageFocus(record){return recordFocus({trajectory_id:record.trajectory_id,id:record.record_id});}
function lineagesForUnit(doc,run,u){
 const positions=new Map(run.events.map((e,i)=>[e.id,e.index??i])),cut=[positions.get(u.source.event_id),u.kind==='action'?u.source.start:u.source.end];
 return (doc.work_lineage?.records||[]).filter(r=>r.versions.some(v=>v.source_unit_id===u.id)||r.dispatch_correspondences.some(c=>c.action_unit_id===u.id)).map(r=>{
  const versions=r.versions.filter(v=>{const e=positions.get(v.source.event_id);return e<cut[0]||e===cut[0]&&v.source.end<=cut[1];});
  return {record:r,versions,correspondences:r.dispatch_correspondences.filter(c=>c.action_unit_id===u.id)};
 }).filter(r=>r.versions.length);
}
function unitConnections(doc,id,type='all'){
 const ids=new Set(doc.units.map(u=>u.id)),valid=ids.has(id);
 const relations=valid?doc.relations.filter(r=>(r.from===id||r.to===id)&&ids.has(r.from)&&ids.has(r.to)&&(type==='all'||r.type===type)):[];
 return {anchor:valid?id:null,relations,incoming:relations.filter(r=>r.to===id),outgoing:relations.filter(r=>r.from===id),
  unitIds:new Set(valid?[id,...relations.flatMap(r=>[r.from,r.to])]:[])};
}
function visibleSequence(doc,run,visible){
 const sequence=[];let hidden=0;
 for(const u of orderedUnits(doc,run)){
  if(!visible.has(u.id)){hidden++;continue;}
  sequence.push({unit:u,hiddenBefore:hidden});hidden=0;
 }
 return {sequence,hiddenAfter:hidden};
}
function checkingObservations(doc){
 return (doc.stated_checks?.observations||[]).map(o=>{
  const later=doc.check_followthrough?.observations.find(r=>r.unit_id===o.unit_id&&r.check_id===o.check?.id);
  return {...o,actions:[...o.actions,...(later?.actions||[])],laterActionCount:later?.actions.length||0};
 });
}
function materialObservation(doc,owner,check,facet,action,feedback){
 return doc.response_material?.observations.find(r=>r.unit_id===owner&&r.check_id===check&&r.facet_id===facet&&r.action_unit_id===action&&r.feedback_unit_id===feedback)||null;
}
const materialFormLabels={contents:'Requested information recorded',partial_contents:'Some requested information recorded',reference_only:'Reference only · contents not supplied',recorded_uninspected:'Recorded payload not inspected',absent:'Requested material absent',unresolved:'Material scope unresolved'};
const deliveryLabels={read:'Read or lookup operation',compute:'Computation or test operation',change:'Attempted artifact or environment change',relay:'Statement relay',mixed:'Combined operations',unresolved:'Delivery mechanism unresolved'};
const methodLabels={same_procedure:'Same procedure',reconfigured_procedure:'Reconfigured procedure',alternative_procedure:'Alternative procedure',different_work:'Different work · grouping disputed',unresolved:'Procedure unresolved'};
function methodObservation(doc,recurrence){return doc.method_comparison?.observations?.find(r=>r.previous_unit_id===recurrence.previous_group_unit_id&&r.current_unit_id===recurrence.unit_id&&r.group_id===recurrence.group_id)||null;}
function methodGroupSummary(doc,groupId){
 const rows=doc.method_comparison?.observations?.filter(r=>r.group_id===groupId)||[],counts={};
 for(const row of rows)if(row.status==='selected')counts[row.comparison]=(counts[row.comparison]||0)+1;
 return {pairs:rows.length,notInspected:rows.filter(r=>r.status!=='selected').length,counts,
  reviewed:rows.filter(r=>(doc.method_comparison?.review_notes||[]).some(n=>n.previous_unit_id===r.previous_unit_id&&n.current_unit_id===r.current_unit_id)).length};
}
function inspectResponseDelivery(u,host){
 const rows=state.doc.response_material?.deliveries.filter(r=>r.feedback_unit_id===u.id||r.action_unit_id===u.id)||[];
 if(!rows.length)return;
 const details=el('details',undefined,'dispatch-scope');details.append(el('summary','How the response was returned'));
 for(const row of rows){
  details.append(el('p',row.event_id+' · '+deliveryLabels[row.choice]));
  const explanation={read:'The dispatched operation requests existing information. A file read does not rerun tests described inside it.',compute:'The dispatched operation requests a computation or test. Its result and execution success still require inspection.',change:'The dispatched operation attempts a change. Returned artifact text can include supplied or previously stored claims; it does not independently verify those claims or establish that the change succeeded.',relay:'The response relays a statement. Its appearance in a tool response does not validate it.',mixed:'Several mechanisms contribute to the response. Their individual material origins still need attribution.',unresolved:'The operation and response do not establish the delivery mechanism.'};
  details.append(el('p',explanation[row.choice],'muted'));
  if(u.id!==row.feedback_unit_id)details.append(button('Open response · '+row.event_id,()=>inspect(row.feedback_unit_id),'source-button'));
 }
 details.append(el('p',state.doc.response_material.schema==='response-material/2'?'Mechanism selected from the local action and dispatch before its response. Execution success and original authorship are separate questions.':'Jev-selected response mechanism, not an activity tag or an original-authorship judgment.','muted'));host.append(details);
}
function renderWorkHistory(){
 const history=state.doc.work_history,host=$('#work-overview');host.hidden=!history?.available;
 renderDeclaredWork();if(state.doc.declared_work_items)host.hidden=false;
 if(!history?.available)return;
 renderWorkContexts();renderWorkSequences();
 const counts=history.counts,all=$('#history-singletons').checked;
 $('#work-history-summary').textContent=`${quantity(counts.operations,'operation')} · ${counts.recurring_assignments} matched to earlier work · ${quantity(counts.recurring_groups,'recurring target group')}`+(counts.unresolved_or_uninspected?` · ${quantity(counts.unresolved_or_uninspected,'unresolved or uninspected identity')}`:'');
 if(counts.unrepresented_operations)$('#work-history-summary').textContent+=` · ${quantity(counts.unrepresented_operations,'recorded operation')} in this span without a selected unit`;
 const lanes=$('#work-history-lanes');lanes.replaceChildren();
 for(const stream of history.streams){
  const section=el('section',undefined,'history-stream');
  if(history.streams.length>1)section.append(el('h3',label(stream.actor)+' · '+stream.trajectory_id));
  if(stream.unrepresented_action_event_ids.length){
   const missing=el('details',undefined,'review-flag');missing.append(el('summary','Recorded operations without selected units'));
   for(const id of stream.unrepresented_action_event_ids){const event=state.run.events.find(e=>e.id===id);if(event.text.length)missing.append(cite({event_id:id,source_pointer:event.source_pointer,start:0,end:event.text.length,text:event.text}));else missing.append(el('p',id+' · No recorded action text is available.'));}
   section.append(missing);
  }
  const groups=stream.groups.filter(g=>all||g.occurrences.length>1);
  if(!groups.length){section.append(el('p','No repeated target assignment was selected in this trajectory. This does not establish that all work was new.','muted'));lanes.append(section);continue;}
  const scroll=el('div',undefined,'history-scroll');scroll.setAttribute('role','region');scroll.setAttribute('aria-label','Operation positions for '+stream.actor);scroll.tabIndex=0;
  const inner=el('div',undefined,'history-lane');inner.style.setProperty('--operations',stream.position_count);
  const axis=el('div',undefined,'history-axis');axis.append(el('span','Operation 1'),el('span','Operation '+stream.position_count));inner.append(axis);
  for(const group of groups){
   const row=el('div',undefined,'history-row');row.dataset.pathId=group.id;
   const title=button(group.target,()=>{$('#map-search').value='';focusWork('path:'+group.id);},'history-target');
   title.setAttribute('aria-pressed',String(state.focus==='path:'+group.id));row.append(title);
   const details=[quantity(group.occurrences.length,'operation')];
   if(group.consecutive_recurrences)details.push(quantity(group.consecutive_recurrences,'consecutive recurrence'));
   if(group.spaced_recurrences)details.push(`${group.spaced_recurrences} with intervening operations`);
  row.append(el('p',details.join(' · '),'history-counts'));
  const methods=methodGroupSummary(state.doc,group.id);
  if(methods.pairs){row.append(el('p',Object.entries(methods.counts).map(([k,n])=>`${methodLabels[k]}: ${n}`).join(' · ')+(methods.notInspected?` · Not inspected: ${methods.notInspected}`:''),'history-counts'));
   if(methods.reviewed)row.append(el('p',`${quantity(methods.reviewed,'comparison')} has a source-review note. Selected labels remain unchanged.`,'review-label'));}
   if(group.disputed_identity)row.append(el('p','A source review disputes this grouping.','review-label'));
   const ribbon=el('div',undefined,'history-ribbon');
   for(const occurrence of group.occurrences){
    const u=unit(occurrence.unit_id),recurrence=history.recurrences[occurrence.recurrence_index];
    const hit=button(String(occurrence.position),()=>{focusConnections(u.id);inspect(u.id);},'history-hit');
    hit.style.gridColumn=String(occurrence.position);hit.dataset.unitId=u.id;
    hit.classList.toggle('recurring',Boolean(recurrence));
    hit.classList.toggle('identity-open',['unresolved','multiple_distinct_targets','needs_target_candidate_retrieval','not_inspected'].includes(occurrence.identity_status));
    hit.setAttribute('aria-label',`Operation ${occurrence.position} · ${unitName(u.id)} · ${u.content.summary.text}`);
    hit.title=unitName(u.id)+' · '+u.content.summary.text+(recurrence?` · ${recurrence.intervening_action_unit_ids.length+recurrence.intervening_unrepresented_action_event_ids.length} intervening operations since the previous occurrence in this group.`:' · First occurrence in this selected group; not established as novel work.');
    const method=recurrence&&methodObservation(state.doc,recurrence);if(method?.status==='selected')hit.title+=' · '+methodLabels[method.comparison];
    ribbon.append(hit);
   }
   row.append(ribbon);inner.append(row);
  }
  scroll.append(inner);section.append(scroll);lanes.append(section);
 }
}
const declarationLabel={commits:'Undertakes',proposes:'Proposes',defers:'Postpones',withdraws:'Withdraws',reports_finished:'Reports finished',reports_blocked:'Reports blocked'};
const workResultLabel={fulfilled:'Work scope fulfilled',partial:'Some work established',failed:'Work attempt failed',pending:'Work result pending',not_established:'Work result not established'};
const unmetLabel={reported:'An unmet condition is reported',not_reported:'No unmet condition is reported; this does not prove satisfaction',unresolved:'Unmet-condition evidence is unresolved'};
function inspectWorkResult(row){
 const host=$('#inspector');host.replaceChildren(el('p','WORK RESULT · SOURCE EVIDENCE','eyebrow'),el('h2',row.scope_text),el('p',workResultLabel[row.result],'work-result-badge '+row.result));
 host.append(el('p',unmetLabel[row.unmet_condition]||'No separate unmet-condition observation in this version.'),el('p',state.doc.work_results.limits,'muted'));
 if(state.doc.work_results.review_summary)host.append(el('p',state.doc.work_results.review_summary,'review-flag'));
 if(row.operation_context){
  const context=row.operation_context,details=el('details',undefined,'dispatch-scope');details.open=true;
  details.append(el('summary','Operation evidence used for this work result'),
   el('p',deliveryLabels[context.mechanism.value]+' · Operation '+context.outcome.replaceAll('_',' ')),
   el('p','Executor error: '+context.executor_report.error.replaceAll('_',' ')+' · Warning: '+context.executor_report.warning.replaceAll('_',' ')));
  if(context.source_material){
   const names={invocation_echo_only:'Command echo or prompt only',returned_material:'Returned contents or state',execution_report:'Executor report',material_and_report:'Contents and executor report',no_readable_material:'No readable material',unresolved:'Response material unresolved'};
   details.append(el('p','Response inspection: '+names[context.source_material.value]));
  }
  details.append(el('p','The operation and the named work have different scopes. Completed reading does not verify a claim inside the file.','muted'));
  if(!context.complete_readable_response)details.append(el('p','Some recorded response material was not inspected.','review-flag'));
  host.append(details);
 }
 if(row.candidate_constraints?.includes('absence_requires_complete_readable_response'))host.append(el('p','An absence claim was unavailable because part of the response was uninspected. Positive reports and unresolved remained selectable.','muted'));
 if(row.uninspected_material)host.append(el('p','Some response material was omitted or remains uninspected. The raw selection is preserved; inspect the supplied evidence.','review-flag'));
 for(const note of row.review_notes||[])host.append(el('p','Review flag: '+note.text,'review-flag'));
 host.append(button('Earlier work · '+unitName(row.scope_unit_id),()=>inspect(row.scope_unit_id),'connection-jump'),button('Attempt · '+unitName(row.action_unit_id),()=>inspect(row.action_unit_id),'connection-jump'));
 host.append(el('p','Known through '+row.cutoff.event_id+'; later reports do not supply earlier evidence.','muted'));
 for(const ref of row.evidence)host.append(cite(ref,()=>inspectWorkResult(row)));
 host.append(el('small','Decision '+row.request_hash));presentInspector(host);
}
function declaredRecord(doc,id){return doc.declared_work_history?.records.find(r=>r.id===id);}
function declaredActionLinks(doc,id){return (doc.declared_work_actions?.relations||[]).filter(r=>r.declared_work_id===id);}
function declaredEvidenceUnits(doc,id){
 const record=declaredRecord(doc,id);if(!record)return new Set();
 const ids=new Set(record.updates.map(u=>u.unit_id));
 for(const r of declaredActionLinks(doc,id))ids.add(r.from);
 for(const r of doc.relations)if(r.type==='feedback_for'&&ids.has(r.to))ids.add(r.from);
 return ids;
}
function renderDeclaredActions(record,host){
 if(!state.doc.declared_work_actions)return;
 const links=declaredActionLinks(state.doc,record.id),roles={attempts_declared_work:'Attempt',prepares_declared_work:'Preparation',checks_declared_work:'Check'};
 const section=el('details',undefined,'dispatch-scope');section.open=true;section.append(el('summary','Dispatched work and recorded results'));
 if(state.doc.declared_work_action_review)section.append(el('p',state.doc.declared_work_action_review.limitations,'review-flag'));
 if(!links.length)section.append(el('p','No action correspondence selected for this work record. Missing or unresolved evidence does not establish abandonment.','muted'));
 for(const r of links){
  const action=unit(r.from),row=el('div',undefined,'inspector-connection');
  row.append(button(unitName(action.id)+' · '+roles[r.type]+' · '+action.content.summary.text,()=>inspect(action.id),'connection-jump'));
  for(const note of (state.doc.declared_work_action_review?.notes||[]).filter(n=>relationReviewMatches(n,r)))row.append(el('p',note.text,'review-flag'));
  const responses=state.doc.relations.filter(v=>v.type==='feedback_for'&&v.to===action.id);
  for(const response of responses){
   const u=unit(response.from),outcome=state.doc.operation_outcomes?.observations.find(o=>o.response_event_id===u.source.event_id);
   row.append(button(unitName(u.id)+' · '+(outcome?'Operation '+outcome.outcome.replaceAll('_',' '):'Recorded response; outcome not inspected'),()=>inspect(u.id),'source-button'));
   for(const result of state.doc.work_results?.observations||[])if(result.declared_work_id===record.id&&result.action_unit_id===action.id&&result.response_event_id===u.source.event_id){
    row.append(button((result.review_notes?.length?'Review flag · ':'')+workResultLabel[result.result]+' · '+unitName(u.id),()=>inspectWorkResult(result),'work-result-badge '+result.result));
    row.append(el('small',unmetLabel[result.unmet_condition]||''));
   }
  }
  if(!responses.length)row.append(el('p','No response unit linked to this action.','muted'));
  for(const p of state.doc.plan_execution?.plans||[])for(const stage of p.stages)if(stage.bindings.some(b=>b.unit_id===action.id)){
   const stageRoles=stage.bindings.filter(b=>b.unit_id===action.id).map(b=>b.role).join(', ');
   row.append(button('Plan stage · '+stageRoles+' · '+stage.text,()=>focusWork('stage:'+stage.id),'connection-jump'));
  }
  section.append(row);
 }
 section.append(el('p','These links compare each dispatch with earlier statements. They do not establish that a statement stayed active or that a reported achievement passed verification. Plan links are the separately selected correspondence of the same action.','muted'));host.append(section);
}
function declaredReviews(id){return state.doc.declared_work_history?.review_notes?.filter(n=>n.record_ids.includes(id))||[];}
function scopePartsFor(unitId,itemId){return state.doc.work_scope_parts?.observations.find(r=>r.unit_id===unitId&&r.item_id===itemId);}
function inspectScopeParts(row){
 const host=$('#inspector');host.replaceChildren(el('p','WORK SCOPE · EXPERIMENTAL','eyebrow'),el('h2',row.work));
 host.append(el('p','Jev-selected reading of this work statement. These parts do not establish execution or success.','muted'));
 if(row.status==='needs_review')host.append(el('p','Needs review · '+(row.faithfulness==='needs_revision'?'The work wording may change the source meaning.':row.faithfulness==='unresolved'?'The source meaning is unresolved.':'The proposed parts need refinement.'),'review-flag'));
 const names={work:'Work itself · includes required methods and conditions',purpose:'Downstream purpose · why this work is undertaken',prerequisite:'Prerequisite · when this work can proceed',unresolved:'Role unresolved'};
 const list=el('dl');for(const part of row.groups)list.append(el('dt',names[part.role]),el('dd',part.text.trim()));host.append(list);
 host.append(el('p','These spans come from the selected work description. Open the original contribution below to check the reading.','muted'));
 host.append(el('p','Experimental: nested purposes and simple prerequisites produced errors in development checks. These readings are not applied to completion metrics.','review-flag'));
 host.append(button('Back to '+unitName(row.unit_id),()=>inspect(row.unit_id),'connection-jump'));
 for(const ref of row.evidence)host.append(cite(ref,()=>inspectScopeParts(row),'Back to work scope'));
 const audit=el('details');audit.append(el('summary','Decision details'),el('p','Faithfulness: '+row.faithfulness.replaceAll('_',' ')+' · Partition: '+row.partition.replaceAll('_',' ')),el('small',row.request_hash));host.append(audit);presentInspector(host);
}
function renderDeclaredWork(){
 const local=state.doc.declared_work_items,host=$('#declared-work-overview');host.replaceChildren();host.hidden=!local;if(!local)return;
 host.append(el('h3','What the agent says it will do or has done'),el('p',`${local.coverage.selected_units} of ${local.coverage.eligible_units} prose units inspected. These are attributed statements about work; completed operations and verified task outcomes are separate.`,'muted'));
 const history=state.doc.declared_work_history;if(!history)return;
 const unresolved=history.observations.filter(r=>r.status!=='selected').length;
 host.append(el('p',`${history.records.length} selected work records · ${unresolved} unresolved item identities. A first occurrence is not a new direction.`,'muted'));
 for(const record of history.records){
  const row=el('details',undefined,'work-sequence');row.append(el('summary',record.updates[0].work+' · '+record.updates.length+' statements'+(declaredReviews(record.id).length?' · Review scope':'')));
  for(const note of declaredReviews(record.id))row.append(el('p',note.text,'review-flag'));
  for(const update of record.updates)row.append(button(unitName(update.unit_id)+' · '+declarationLabel[update.declaration]+' · '+update.work,()=>inspect(update.unit_id),'connection-jump'));
  row.append(button('Follow these statements and intervening work',()=>{$('#include-connected').checked=false;$('#map-search').value='';focusWork('declared:'+record.id);},'connection-jump'));host.append(row);
 }
}
function renderDeclaredFocus(){
 const host=$('#declared-work-focus'),record=state.focus.startsWith('declared:')?declaredRecord(state.doc,state.focus.slice(9)):null;
 host.replaceChildren();host.hidden=!record;if(!record)return;
 host.append(el('h3',record.updates[0].work),el('p','Selected references to the same work, with their original wording and source units. Intervening activities remain in the map. A completion statement is a claim.','muted'));
 for(const note of declaredReviews(record.id))host.append(el('p',note.text,'review-flag'));
 for(const update of record.updates){
  host.append(button(unitName(update.unit_id)+' · '+declarationLabel[update.declaration]+' · '+update.work,()=>inspect(update.unit_id),'connection-jump'));
  const parts=scopePartsFor(update.unit_id,update.item_id);if(parts)host.append(button('Inspect work scope · '+unitName(update.unit_id),()=>inspectScopeParts(parts),'source-button'));
 }
 renderDeclaredActions(record,host);
}
function inspectDeclaredWork(u,host){
 const row=state.doc.declared_work_items?.observations.find(r=>r.unit_id===u.id);if(!row)return;
 const box=el('details',undefined,'dispatch-scope');box.open=true;box.append(el('summary','Stated work in this contribution'));
 if(!row.items.length)box.append(el('p','No work declaration selected for this contribution.'));
 for(const item of row.items){
  box.append(el('p',declarationLabel[item.declaration]+' · '+item.work));for(const ref of item.evidence)box.append(cite(ref));
  const parts=scopePartsFor(u.id,item.id);if(parts)box.append(button('Inspect work scope'+(parts.status==='needs_review'?' · needs review':''),()=>inspectScopeParts(parts),'source-button'));
  const record=state.doc.declared_work_history?.records.find(r=>r.updates.some(v=>v.unit_id===u.id&&v.item_id===item.id));
  if(record){for(const note of declaredReviews(record.id))box.append(el('p',note.text,'review-flag'));box.append(button('Follow statements about this work',()=>{$('#include-connected').checked=false;focusWork('declared:'+record.id);},'connection-jump'));}
 }
 box.append(el('p','Candidate author: '+row.candidate_producer+'. Jev selected this bundle; these are not verified work outcomes.','muted'));host.append(box);
}
function renderWorkContexts(){
 const data=state.doc.work_context_overview,host=$('#work-context-overview');host.replaceChildren();host.hidden=!data;
 if(!data)return;
 host.append(el('h3','Work scopes across contributions'),el('p',`${data.selected_units} of ${data.units_inspected} agent contributions have a selected work scope. Actions and prose share these scopes; immediate targets remain separate.`,'muted'));
 for(const group of data.groups){
  if(!group.unit_ids.length)continue;
  const row=el('div',undefined,'context-scope-row');
  const title=button(group.text.length>320?group.text.slice(0,320)+'…':group.text,()=>{$('#map-search').value='';$('#include-connected').checked=false;focusWork('context:'+group.id);},'context-scope-title');title.title=group.text;
  title.setAttribute('aria-pressed',String(state.focus==='context:'+group.id));row.append(title);
  row.append(el('p',`${group.source.event_id} · ${quantity(group.prose_units,'prose contribution')} · ${quantity(group.action_units,'operation')}`,'muted'));
  host.append(row);
 }
 host.append(el('p','These are source-linked scopes, not completed tasks or inferred strategies. A scope can contain several targets. Select one to follow its contributions in the same map.','muted'));
}
function renderWorkSequences(){
 const data=state.doc.sequence_patterns,host=$('#work-sequences');host.replaceChildren();host.hidden=!data?.available;
 if(!data?.available)return;
 host.append(el('h3','Repeated work sequences'));
 if(!data.runs.length)host.append(el('p','No consecutive repeated target sequence is established by the selected identities.','muted'));
 else host.append(el('p',`${data.counts.periodic_regions} periodic regions · ${data.counts.multi_target_regions} with several targets · ${data.counts.repeated_operation_positions} repeated operation positions, counted once across overlapping regions.`,'muted'));
 for(const row of data.runs){
  const box=el('details',undefined,'work-sequence');box.dataset.patternId=row.id;
  const meaning=row.pattern_targets.slice(0,2).join(' → ')+(row.period>2?' → …':'');
  box.append(el('summary',`${meaning} · ${row.full_copies} consecutive ${row.period===1?'operations':'copies'}`),el('p',`Operations ${row.start_position}–${row.end_position} · ${quantity(row.period,'operation')} per copy${row.partial_tail?` + ${row.partial_tail} trailing operations`:''}`,'muted'));
  const pattern=el('ol');for(const target of row.pattern_targets)pattern.append(el('li',target));box.append(pattern);
  box.append(button('Follow this repeated sequence',()=>{$('#map-search').value='';$('#include-connected').checked=false;focusWork('pattern:'+row.id);},'connection-jump'));
  for(const [i,copy] of row.copies.entries()){const p=el('div',undefined,'sequence-copy');p.append(el('span',`${copy.length===row.period?'Copy':'Partial copy'} ${i+1}: `));for(const uid of copy)p.append(button(unitName(uid),()=>inspect(uid),'source-button'));box.append(p);}
  box.append(el('p','The target sequence repeats. Methods, feedback and work terms may differ; follow the interval to inspect them.','muted'));host.append(box);
 }
 renderReturningSequences(data,host);
 const disclosure=el('details');disclosure.append(el('summary','Pattern basis and coverage'),el('p',data.basis),el('p',data.limits));
 for(const stream of data.streams)disclosure.append(el('p',`${stream.actor} · ${stream.trajectory_id}: periods through ${stream.scan.considered_period}; ${stream.scan.missing_positions.length} missing or disputed positions break matching.`));host.append(disclosure);
}
function returnById(doc,id){return doc.sequence_patterns?.returns?.find(r=>r.id===id)||null;}
function returnTitle(row){return row.pattern_targets.join(' → ');}
function returnMethod(pair){return methodObservation(state.doc,{group_id:pair.group_id,previous_group_unit_id:pair.previous_unit_id,unit_id:pair.current_unit_id});}
function returnUpdates(row){return [...new Set(row.comparisons.flatMap(p=>(p.context.requested_scope?.updates||[]).map(u=>u.source_unit_id)))];}
function renderReturningSequences(data,host){
 if(!data.returns)return;
 host.append(el('h3','Returning after intervening work'));
 const uninspected=data.streams.filter(s=>s.return_scan?.status!=='complete');
 if(uninspected.length)host.append(el('p',`${quantity(uninspected.length,'trajectory stream')} exceeds the return scanner’s position limit and needs segment selection. Absence of a displayed return is not an inspected negative.`,'missing'));
 if(!data.returns.length)host.append(el('p','No separated multi-target return was found in the inspected streams. Single-target recurrence remains in the target history below.','muted'));
 else host.append(el('p',`${quantity(data.returning_patterns.length,'pattern')} · ${quantity(data.returns.length,'return interval')}. Intervals may overlap; these are not counts of distinct work or wasted actions.`,'muted'));
 for(const row of data.returns){
  const box=el('details',undefined,'work-sequence');box.dataset.returnId=row.id;
  box.append(el('summary',returnTitle(row)),el('p',`Operations ${row.previous.start_position}–${row.previous.end_position} → ${row.gap.operation_positions} intervening → ${row.current.start_position}–${row.current.end_position}`,'muted'));
  const updates=returnUpdates(row);
  box.append(el('p',updates.length?'Requested terms change between the aligned operations.':row.comparisons.every(p=>p.context.requested_scope?.available)?'The selected requested terms are unchanged at the aligned dispatches.':'Requested-term comparison is unavailable for some aligned operations.','comparison-summary'));
  box.append(button('Follow this return and what changed',()=>{$('#map-search').value='';$('#include-connected').checked=false;focusWork('return:'+row.id);},'connection-jump'));
  if(row.gap.unresolved_identity_positions.length)box.append(el('p',`${quantity(row.gap.unresolved_identity_positions.length,'intervening operation')} has missing or disputed target identity; its position is retained.`,'missing'));
  host.append(box);
 }
 const scope=el('details');scope.append(el('summary','Return matching scope'),el('p','Exact sequences of selected immediate targets, with at least two distinct targets and intervening operations. Each later occurrence uses its nearest earlier disjoint match. Continuous periodic regions appear above; all original positions remain.','muted'));
 for(const stream of data.streams){const scan=stream.return_scan;if(scan)scope.append(el('p',`${label(stream.actor)} · ${stream.trajectory_id}: ${scan.positions} positions; maximum pattern length ${scan.max_length}; position limit ${scan.position_limit}; ${label(scan.status)}.`,'muted'));}
 if(data.returning_patterns.some(p=>p.at_length_limit))scope.append(el('p','Some patterns reach the configured length limit; longer extensions were not inspected.','missing'));
 host.append(scope);
}
function renderReturnFocus(){
 const host=$('#work-return-focus'),row=state.focus.startsWith('return:')?returnById(state.doc,state.focus.slice(7)):null;
 host.replaceChildren();host.hidden=!row;if(!row)return;
 host.append(el('h3',returnTitle(row)),el('p','Earlier sequence → intervening work → later sequence. The detailed map below retains the original units from all participants, including prose and feedback.','muted'));
 const blocks=el('div',undefined,'return-blocks');
 for(const [title,block]of [['Earlier sequence',row.previous],['Intervening operations',row.gap],['Later sequence',row.current]]){
  const section=el('section');section.append(el('h4',title),el('p',`Operations ${block.start_position}–${block.end_position}`,'muted'));
  for(const uid of block.action_unit_ids){const u=unit(uid);section.append(button(unitName(uid)+' · '+u.content.summary.text,()=>inspect(uid),'connection-jump'));}
  if(block.unrepresented_action_event_ids?.length)section.append(el('p','No selected unit: '+block.unrepresented_action_event_ids.join(', '),'missing'));
  blocks.append(section);
 }
 host.append(blocks);
 const updates=returnUpdates(row);
 if(updates.length){host.append(el('h4','Requested terms changed'));for(const uid of updates)host.append(button(unitName(uid)+' · '+unit(uid).content.summary.text,()=>inspect(uid),'connection-jump'));}
 host.append(el('h4','Compare aligned operations'));
 for(const [i,pair]of row.comparisons.entries()){
  const comparison=el('section',undefined,'return-pair'),method=returnMethod(pair);
  comparison.append(el('p',`${i+1}. ${row.pattern_targets[i]} · ${unitName(pair.previous_unit_id)} → ${unitName(pair.current_unit_id)}`,'comparison-summary'),el('p',method?.status==='selected'?methodLabels[method.comparison]:'Procedure comparison not inspected for these exact endpoints.','muted'));
  inspectRecurrenceComparison({group_id:pair.group_id,previous_group_unit_id:pair.previous_unit_id,unit_id:pair.current_unit_id,context:pair.context},comparison,null);host.append(comparison);
 }
 if(row.context.unrepresented_source_ranges.length){const gaps=el('details',undefined,'review-flag');gaps.append(el('summary',`${quantity(row.context.unrepresented_source_ranges.length,'source range')} without a selected unit`));for(const ref of row.context.unrepresented_source_ranges)gaps.append(cite(ref));host.append(gaps);}
 if(row.context.after_current_dispatch_unit_ids.length)host.append(el('p',`Retrospective evidence after the last dispatch: ${row.context.after_current_dispatch_unit_ids.map(unitName).join(', ')}. These units were unavailable when that action was chosen.`,'muted'));
 host.append(el('p','Repeated immediate work can serve changed requests. This structure does not establish waste, a goal change, exploration, exploitation or a causal response.','muted'));
}
function inspectWorkContext(u,host){
 const result=state.doc.work_context,row=result?.observations.find(r=>r.unit_id===u.id);if(!row)return;
 const box=el('details',undefined,'dispatch-scope');box.append(el('summary','Enclosing work scope'));
 if(!row.frame_ids.length)box.append(el('p',({no_work_context:'No task-work context selected.',missing_scope:'The visible work scope has no supplied candidate.',unresolved:'Work context unresolved.',needs_frame_retrieval:'More frame retrieval is required.',inconsistent_multiple:'The multiple-scope selection is inconsistent and needs review.'})[row.status]||label(row.status),'muted'));
 if(row.status!=='selected'&&row.frame_ids.length)box.append(el('p','Scope membership is incomplete. These selections are retained for review.','review-flag'));
 for(const id of row.frame_ids){const frame=result.frames.find(f=>f.id===id);box.append(el('p',frame.text),cite(frame.source));
  box.append(button('Follow contributions in this scope',()=>{$('#map-search').value='';$('#include-connected').checked=false;focusWork('context:'+id);},'connection-jump'));
 }
 box.append(el('p','This broader scope does not replace the unit’s immediate target or action-to-work links. Membership does not establish that every item in the scope is being attempted, authorized or fulfilled.','muted'));host.append(box);
}
function openLineage(record){$('#map-search').value='';$('#include-connected').checked=false;focusWork(lineageFocus(record));}
function versionTrail(record,versions,host){
 const trail=el('div',undefined,'version-trail');
 for(const [index,v]of versions.entries()){
  if(index)trail.append(el('span','→','muted'));
  const hit=button(v.source.event_id+' · '+label(v.operation),()=>inspect(v.source_unit_id),'source-button');
  hit.title=v.record.text;trail.append(hit);
 }
 host.append(trail);
}
function inspectWorkLineage(u,host){
 const rows=lineagesForUnit(state.doc,state.run,u);if(!rows.length)return;
 const box=el('details',undefined,'dispatch-scope');box.append(el('summary','Persistent work and earlier terms'));
 for(const {record,versions,correspondences}of rows){
  const current=versions.at(-1),row=el('section',undefined,'lineage-record');
  row.append(el('p',(record.kind==='work'?'Work':'Condition')+' · '+current.record.text));
  versionTrail(record,versions,row);
  for(const c of correspondences){row.append(el('p',label(c.relation.type)+' · terms from '+versions.find(v=>v.version_id===c.version_id)?.source.event_id,'muted'));if(c.reviews.length)row.append(el('p','This correspondence has a source-review disagreement.','review-label'));}
  row.append(button('View complete history, including later changes',()=>openLineage(record),'connection-jump'));box.append(row);
 }
 box.append(el('p','Earlier terms are shown only through this unit’s cutoff. A shared scope does not link this action to every work item.','muted'));host.append(box);
}
function renderLineageFocus(){
 const host=$('#work-lineage-focus'),data=state.doc.work_lineage;host.replaceChildren();host.hidden=true;
 if(!data?.available)return;
 const record=data.records.find(r=>lineageFocus(r)===state.focus);
 if(record){
  host.hidden=false;host.append(el('h3',record.kind==='work'?'History of this requested work':'History of these conditions'),el('p',record.versions[0].record.text));
  host.append(el('p',`${record.versions.length} versions · latest requested state: ${record.latest_status}.`,'muted'));
  if(record.kind==='work')host.append(el('p',`${record.counts.preparation_dispatches} preparations · ${record.counts.attempt_dispatches} attempts · ${record.counts.checking_dispatches} checks (${record.counts.linked_dispatches} distinct dispatches). These are selected roles, not successful outcomes.`,'muted'));
  else host.append(el('p','This view tracks condition versions. Action-to-condition correspondence is not established by this history layer.','muted'));
  if(record.counts.reviewed_correspondences)host.append(el('p',`${record.counts.reviewed_correspondences} correspondences have source-review disagreements.`,'review-label'));
  versionTrail(record,record.versions,host);
  for(const [index,v]of record.versions.entries()){
   const detail=el('details',undefined,'lineage-version');detail.append(el('summary',v.source.event_id+' · '+label(v.operation)+' · '+v.record.text));
   changeContents({operation:v.operation,before:index?record.versions[index-1].record:null,after:v.record,retired_clauses:v.retired_clauses},detail);
   detail.append(button('Open source contribution',()=>inspect(v.source_unit_id),'source-button'));host.append(detail);
  }
  const last=record.versions.at(-1);
  if(!record.later_recorded_dispatch_event_ids.length)host.append(el('p','No later agent dispatch is recorded after the latest change at '+last.source.event_id+'. Fulfillment is not established by this history.','review-flag'));
  host.append(el('p','Whole recorded history. Earlier dispatches retain the terms selected at their own cutoffs. Versions are requested terms; changes and attempts are not successful completion.','muted'));return;
 }
 if(!state.focus.startsWith('context:'))return;
 const update=data.scope_updates.find(r=>r.frame_id===state.focus.slice(8));if(!update?.changes.length)return;
 host.hidden=false;host.append(el('h3','Work changed in this scope'));
 for(const change of update.changes){
  const r=data.records.find(r=>r.id===change.lineage_id),v=r.versions.find(v=>v.version_id===change.version_id),at=r.versions.indexOf(v),row=el('section',undefined,'lineage-record');
  row.append(el('p',label(change.operation)+' · '+(r.kind==='work'?'Work item':'Condition'),'eyebrow'),el('p',v.record.text));
  versionTrail(r,r.versions.slice(0,at+1),row);
  row.append(button('Follow this record through the trace',()=>openLineage(r),'connection-jump'));host.append(row);
 }
 host.append(el('p','Each row keeps its earlier record identity. A revision can clarify or change terms; it does not by itself establish a new objective.','muted'));
}
function inspectWorkHistory(u,host){
 const history=state.doc.work_history,recurrence=history?.recurrences.find(r=>r.unit_id===u.id);
 if(!recurrence)return;
 const group=history.streams.flatMap(s=>s.groups).find(g=>g.id===recurrence.group_id);
 const details=el('details',undefined,'dispatch-scope');details.append(el('summary','Earlier work on this target'),el('p',group.target));
 const gapCount=recurrence.intervening_action_unit_ids.length+recurrence.intervening_unrepresented_action_event_ids.length;
 details.append(el('p',gapCount?`${quantity(gapCount,'intervening operation')} by this actor since the previous occurrence in this selected group.`:'The previous dispatch by this actor belongs to the same selected target group.'));
 if(recurrence.intervening_unrepresented_action_event_ids.length)details.append(el('p',`${quantity(recurrence.intervening_unrepresented_action_event_ids.length,'recorded intervening operation')} has no selected unit. Its target correspondence is not established.`,'review-flag'));
 details.append(button('Open previous occurrence · '+unitName(recurrence.previous_group_unit_id),()=>inspect(recurrence.previous_group_unit_id),'source-button'),button('Follow this target',()=>focusWork('path:'+group.id),'connection-jump'));
 if(recurrence.context)inspectRecurrenceComparison(recurrence,details);
 if(recurrence.intervening_action_unit_ids.length){const gap=el('details');gap.append(el('summary','Inspect intervening operations'));
  for(const id of recurrence.intervening_action_unit_ids)gap.append(button(unitName(id)+' · '+unit(id).content.summary.text,()=>inspect(id),'connection-jump'));details.append(gap);}
 const proof=el('details');proof.append(el('summary','Selected identity links'));
 for(const ref of recurrence.supporting_identity_relations){
  const edge=state.doc.relations.find(r=>r.from===ref.from&&r.to===ref.to&&r.type===ref.type);
  proof.append(el('p',unitName(ref.from)+' → same selected target → '+unitName(ref.to)));
  if(edge)relationEvidence(edge,proof);
 }
 details.append(proof,el('p','Only positive identity selections establish this grouping. Intervening operations are shown as context; no failed retry, strategy, causation or progress is inferred.','muted'));host.append(details);
}
function inspectRecurrenceComparison(recurrence,host,focusValue='episode:'+recurrence.unit_id){
 const context=recurrence.context,box=el('details',undefined,'recurrence-comparison');
 box.append(el('summary','Compare occurrences and what happened between them'));
 const comparison=context.dispatch_comparison;
 box.append(el('p',comparison.status==='identical'?'Same recorded invocation. Inspect the intervening work and feedback to see what changed.':comparison.status==='changed'?'The recorded invocation changed.':comparison.source_text_status==='identical'?'Same recorded action text. Native invocation arguments are unavailable for comparison.':comparison.source_text_status==='different'?'The recorded action text differs. Native invocation arguments are unavailable for comparison.':'Recorded invocations cannot be compared structurally.','comparison-summary'));
 if(comparison.status==='changed')box.append(el('p',(comparison.tool_changed?`Tool: ${comparison.tool_before} → ${comparison.tool_after}. `:'')+(comparison.changed_top_level_arguments.length?'Changed arguments: '+comparison.changed_top_level_arguments.join(', ')+'.':''),'muted'));
 inspectMethodComparison(recurrence,box);
 function contribution(parent,id){
  const item=unit(id),row=el('div',undefined,'comparison-contribution');
  row.append(el('p',`${label(item.actor)} · ${label(item.activity||item.kind)}`,'eyebrow'),button(unitName(id)+' · '+item.content.summary.text,()=>inspect(id),'connection-jump'));
  if(item.kind==='feedback')row.append(el('pre',responsePreview(item.content.recorded_response?.text||item.source.text||''),'response-preview'));
  row.append(cite(item.source));parent.append(row);
 }
 const sides=el('div',undefined,'comparison-sides');
 for(const [title,endpoint]of [['Earlier occurrence',context.previous],['Later occurrence',context.current]]){
  const side=el('section',undefined,'comparison-side');side.append(el('h4',title));
  for(const id of endpoint.recorded_expression_unit_ids){side.append(el('p',endpoint.expression_timing[id]==='after_dispatch'?'Associated expression recorded after this dispatch':'Expression recorded before this dispatch','muted'));contribution(side,id);}
  contribution(side,endpoint.action_unit_id);sides.append(side);
 }
 box.append(sides);
 const scope=context.requested_scope;
 if(scope?.available){
  const changes=el('details',undefined,'request-comparison');
  changes.append(el('summary',scope.version_state_changed?'Requested scope changed between these dispatches':'Same selected requested scope at both dispatches'));
  changes.append(el('p','These are recorded request versions. A clarification can change a record without changing the objective; correspondence does not establish current intent or fulfillment.','muted'));
  for(const [title,id]of [['Earlier dispatch',context.previous.action_unit_id],['Later dispatch',context.current.action_unit_id]])changes.append(button(title+' · inspect its requested scope',()=>inspect(id),'connection-jump'));
  for(const update of scope.updates){
   const row=el('section');row.append(button(unitName(update.source_unit_id)+' · '+unit(update.source_unit_id).content.summary.text,()=>inspect(update.source_unit_id),'connection-jump'));
   for(const change of update.changes){
    const saved=state.doc.requested_work.changes.find(c=>c.after.version_id===change.after_version_id);
    if(saved){const item=el('details');item.append(el('summary',label(change.operation)+' · '+saved.after.text));changeContents(saved,item);row.append(item);}
   }
   changes.append(row);
  }
  box.append(changes);
 }else if(scope)box.append(el('p','Requested-scope comparison unavailable: '+scope.reason,'muted'));
 const previousResponses=context.previous.response_unit_ids.filter(id=>context.available_at_current_dispatch_unit_ids.includes(id));
 if(previousResponses.length){const response=el('details');response.append(el('summary','Earlier response available before the later dispatch'));for(const id of previousResponses)contribution(response,id);box.append(response);}
 const interval=el('details');interval.append(el('summary',`Between the occurrences · ${quantity(context.between_unit_ids.length,'unit')}`));
 if(!context.between_unit_ids.length)interval.append(el('p','No intervening selected unit is recorded.','muted'));
 for(const id of context.between_unit_ids)contribution(interval,id);box.append(interval);
 if(context.assessment_relation_indices.length){const assessments=el('details');assessments.append(el('summary','How the agent interpreted feedback'));
  for(const index of context.assessment_relation_indices){const relation=state.doc.relations[index];assessments.append(el('p',`${unitName(relation.from)} → assesses → ${unitName(relation.to)}`));relationEvidence(relation,assessments);}box.append(assessments);
 }
 if(context.after_current_dispatch_unit_ids.length){const later=el('details');later.append(el('summary','Recorded after the later dispatch'));
  later.append(el('p','These responses or expressions were unavailable when the later action was dispatched.','muted'));for(const id of context.after_current_dispatch_unit_ids)contribution(later,id);box.append(later);
 }
 if(context.unrepresented_source_ranges.length||context.events_without_text.length){const gaps=el('details',undefined,context.unrepresented_source_ranges.length?'review-flag':'muted');gaps.append(el('summary',context.unrepresented_source_ranges.length?'Source coverage gaps in this interval':'Source events with no text'));
  for(const ref of context.unrepresented_source_ranges)gaps.append(el('p','Recorded text without a selected unit'),el('pre',responsePreview(ref.text),'response-preview'),cite(ref));
  if(context.events_without_text.length)gaps.append(el('p',context.events_without_text.join(', ')+' · These source events contain no text; empty message content is not an annotation omission.'));box.append(gaps);
 }
 if(comparison.status!=='not_comparable'){const args=el('details');args.append(el('summary','Exact earlier and later invocation arguments'),el('pre',JSON.stringify({earlier:{tool:comparison.tool_before,arguments:comparison.before_arguments},later:{tool:comparison.tool_after,arguments:comparison.after_arguments}},null,2),'quote'));box.append(args);}
 if(focusValue)box.append(button('Focus this comparison in the map',()=>{$('#map-search').value='';$('#include-connected').checked=false;focusWork(focusValue);},'connection-jump'));
 box.append(el('p','Includes all participants in the interval, plus the expressions and responses linked to the endpoints. Identical calls can follow changed artifacts or new information; neither recurrence nor a changed argument establishes strategy or progress.','muted'));
 host.append(box);
}
function inspectMethodComparison(recurrence,host){
 const row=methodObservation(state.doc,recurrence);if(!row)return;
 const box=el('section',undefined,'method-comparison');box.append(el('h4','Procedure across these occurrences'));
 if(row.status!=='selected'){box.append(el('p','Not inspected: '+label(row.status)+'. This is not evidence of an unchanged procedure.','missing'));host.append(box);return;}
 box.append(el('p',methodLabels[row.comparison],'comparison-summary'));
 if(row.comparison==='different_work')box.append(el('p','This selection disputes the shared work grouping. The earlier target-identity decision is retained for review.','review-flag'));
 if(row.upstream_identity_disputed)box.append(el('p','The upstream target grouping already has a review disagreement.','review-flag'));
 const basis=unit(row.stated_basis);
 if(basis){box.append(el('p','Agent’s stated basis · '+basis.source.event_id,'eyebrow'),el('p',basis.content.summary.text),button('Open stated basis · '+unitName(basis.id),()=>inspect(basis.id),'connection-jump'),cite(basis.source));}
 else box.append(el('p',({no_expressed_basis:'No explicit agent explanation selected for this occurrence.',distributed_basis:'The expressed basis spans several contributions; no single primary statement selected.',unresolved_basis:'The expressed basis is unresolved.',not_inspected:'A basis was not selected because work-instance comparability was not established.'})[row.stated_basis]||'Basis not inspected.','muted'));
 for(const note of state.doc.method_comparison.review_notes||[])if(note.previous_unit_id===row.previous_unit_id&&note.current_unit_id===row.current_unit_id){box.append(el('p',note.text,'review-flag'));for(const ref of note.evidence||[])box.append(cite(ref));}
 const source=el('details');source.append(el('summary','Comparison definition and supplied evidence'),el('p',state.doc.method_comparison.definitions[row.comparison]),el('p','Work instance: '+label(row.work_instance||'joint decision')+' · '+state.doc.method_comparison.schema,'muted'));
 for(const ref of row.inspector_context?.source_ranges||[]){const event=state.run.events.find(e=>e.id===ref.event_id);if(event)source.append(cite({...ref,source_pointer:event.source_pointer,text:event.text.slice(ref.start,ref.end)}));}
 const omitted=row.inspector_context?.omitted_source_events||[];
 if(omitted.length)source.append(el('p',`${omitted.length} earlier source events were not supplied as readable evidence. The full trace remains available.`,'muted'));
 if(row.inspector_context?.unobserved_media.length)source.append(el('p','Some recorded media was not inspected by this text observer.','missing'));
 source.append(el('p','Raw-argmax request: '+row.request,'muted'));box.append(source,el('p','Development selection. The stated basis remains an agent claim. Procedure changes and repeats do not establish exploration, blind retries, success or improvement.','muted'));host.append(box);
}
function showRecurrenceComparison(){
 const comparison=$('#inspector .recurrence-comparison');if(!comparison)return;
 for(let parent=comparison;parent&&parent.id!=='inspector';parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
 comparison.scrollIntoView({block:'start'});
}
function planStage(doc,id){for(const plan of doc.plan_execution?.plans||[]){const stage=plan.stages.find(s=>s.id===id);if(stage)return {plan,stage};}return null;}
function focusUnitIds(doc,focus){
 if(focus==='all')return new Set(doc.units.map(u=>u.id));
 if(focus.startsWith('declared:')){
  const record=declaredRecord(doc,focus.slice(9));if(!record)return new Set();
  const selected=declaredEvidenceUnits(doc,record.id),ordered=doc.units,indices=ordered.map((u,i)=>selected.has(u.id)?i:-1).filter(i=>i>=0);
  return new Set(indices.length?ordered.slice(Math.min(...indices),Math.max(...indices)+1).map(u=>u.id):[]);
 }
 if(focus.startsWith('context:')){const group=doc.work_context_overview?.groups.find(g=>g.id===focus.slice(8));return new Set(group?[...group.unit_ids,...group.source_unit_ids]:[]);}
 if(focus.startsWith('unit:'))return unitConnections(doc,focus.slice(5)).unitIds;
 if(focus.startsWith('episode:'))return new Set(doc.work_history?.recurrences.find(r=>r.unit_id===focus.slice(8))?.context?.focus_unit_ids||[]);
 if(focus.startsWith('pattern:'))return new Set(doc.sequence_patterns?.runs.find(r=>r.id===focus.slice(8))?.context?.focus_unit_ids||[]);
 if(focus.startsWith('return:'))return new Set(returnById(doc,focus.slice(7))?.context?.focus_unit_ids||[]);
 if(focus.startsWith('stage:'))return new Set(planStage(doc,focus.slice(6))?.stage.focus_unit_ids||[]);
 if(focus.startsWith('path:')){
  const path=doc.work_paths?.paths.find(p=>'path:'+p.id===focus);
  return new Set(path?[...path.related_unit_ids,...path.plan_stages.map(s=>s.plan_unit_id)]:[]);
 }
 const record=doc.requested_work?.records.find(r=>recordFocus(r)===focus);
 if(!record)return new Set();
 const ids=new Set((doc.requested_work?.changes||[]).filter(c=>c.record_id===record.id&&c.after.trajectory_id===record.trajectory_id).map(c=>c.source_unit_id));
 for(const r of doc.relations)if(r.requested_work_id===record.id&&doc.units.find(u=>u.id===r.from)?.trajectory_id===record.trajectory_id){ids.add(r.from);ids.add(r.to);}
 return ids;
}
function visibleUnitIds(doc,{focus='all',filter='all',matches=null,connected=true,revealed=null,relation='all'}={}){
 const neighborhood=focus.startsWith('unit:')?unitConnections(doc,focus.slice(5),relation):null;
 const focused=neighborhood?neighborhood.unitIds:focusUnitIds(doc,focus);
 const direct=new Set(doc.units.filter(u=>focused.has(u.id)&&(filter!=='actions'||u.kind==='action')&&(!matches||matches.has(u.id))).map(u=>u.id));
 const visible=new Set(direct);
 const stageAnchor=focus.startsWith('stage:')?planStage(doc,focus.slice(6))?.plan.plan_unit_id:null;
 if(stageAnchor)visible.add(stageAnchor);
 if(neighborhood?.anchor)visible.add(neighborhood.anchor);
 if(!neighborhood&&connected)for(const r of doc.relations){if(direct.has(r.from)&&r.from!==stageAnchor)visible.add(r.to);if(direct.has(r.to)&&r.to!==stageAnchor)visible.add(r.from);}
 if(revealed&&doc.units.some(u=>u.id===revealed))visible.add(revealed);
 return {direct,visible,neighborhood};
}
const label=s=>s.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
const quantity=(n,word)=>`${n} ${word}${n===1?'':'s'}`;
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function button(text,fn,cls){const b=el('button',text,cls);b.type='button';b.onclick=fn;return b;}
async function api(url){const r=await fetch(url);const data=await r.json();if(!r.ok)throw Error(data.error||'Request failed');return data;}
function unit(id){return state.doc.units.find(u=>u.id===id);}
function responsePreview(text){
 const readable=text.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').replace(/data:([^;,\s]+);base64,[A-Za-z0-9+/=]+/g,'[Encoded $1 retained in source; not visually inspected]');
 return readable.length>280?readable.slice(0,140)+'\n…\n'+readable.slice(-140):readable;
}
function unitName(id){return state.doc.provenance.origin==='jev_selected_model_candidates'?'U'+(orderedUnits(state.doc,state.run).findIndex(u=>u.id===id)+1):id;}
function searchUnits(){
 const query=$('#map-search').value.trim().toLocaleLowerCase();
 const terms=query.split(/\s+/).filter(Boolean);
 const matches=new Set(state.doc.units.filter(u=>{
  const text=[u.activity||'',...Object.entries(u.content).filter(([key])=>key!=='recorded_response').map(([,v])=>v.text),...(u.plan_structure?.steps||[]).map(s=>s.text+' '+s.target)].join(' ').toLocaleLowerCase();
  return terms.every(t=>text.includes(t));
 }).map(u=>u.id));
 for(const step of state.doc.requested_work?.steps||[]){
  const text=step.changes.flatMap(c=>[c.after.text,...(c.after.clauses||[]).map(v=>v.text),...(c.retired_clauses||[]).map(v=>v.previous.text+' '+v.reason)]).join(' ').toLocaleLowerCase();
  if(query&&terms.every(t=>text.includes(t)))matches.add(step.unit_id);
 }
 for(const item of state.doc.stated_checks?.observations||[]){
  if(!item.check)continue;
  const text=[item.check.text,...item.check.facets.map(f=>f.text)].join(' ').toLocaleLowerCase();
  if(query&&terms.every(t=>text.includes(t)))matches.add(item.unit_id);
 }
 const projection=visibleUnitIds(state.doc,{focus:state.focus,filter:state.filter,matches:query?matches:null,connected:$('#include-connected').checked,revealed:state.revealed,relation:state.relation});
 state.search={query,matches,...projection};
}
function searchExcerpt(u){
 const terms=state.search.query.split(/\s+/).filter(Boolean);
 for(const [key,value]of Object.entries(u.content)){
  if(['recorded_response','summary','target'].includes(key)||value.text===u.content.summary.text||value.text===u.content.target.text)continue;
  const lower=value.text.toLocaleLowerCase(),positions=terms.map(t=>lower.indexOf(t)).filter(i=>i>=0);
  if(!positions.length)continue;
  const start=Math.max(0,Math.min(...positions)-45),end=Math.min(value.text.length,start+230);
  return label(key)+': '+(start?'…':'')+value.text.slice(start,end)+(end<value.text.length?'…':'');
 }
 return '';
}
function presentInspector(host,open=true){
 if(open&&!state.inspectorReturn)state.inspectorReturn={left:window.scrollX,top:window.scrollY};
 host.classList.toggle('drawer-open',open);
 const toolbar=el('div',undefined,'inspector-toolbar');toolbar.append(button('Back to map',()=>{
  host.classList.remove('drawer-open');
  const target=document.querySelector(`#map [data-unit-id="${CSS.escape(state.selected||'')}"]`);
  target?.focus({preventScroll:true});
  if(state.inspectorReturn){const position=state.inspectorReturn;window.scrollTo(position);requestAnimationFrame(()=>window.scrollTo(position));state.inspectorReturn=null;}
 },'inspector-close'));host.prepend(toolbar);
}
function cite(ref,returnTo=null,returnLabel='Back to work result'){return button(`${ref.event_id} · ${ref.start}–${ref.end}`,()=>source(ref,returnTo,returnLabel),'source-button');}
function stageLinks(u){return state.doc.relations.filter(r=>r.from===u.id&&r.plan_step_id);}
function relationName(r){const scope=r.plan_step_text||r.check_text||r.work_text;return (r.work_result_review?'Review flag · ':'')+(workResultLabel[r.work_result]||label(r.type))+(scope?' · '+scope:'');}
function relationReviewMatches(note,relation){
 if(note.kind!=='relation_review')return false;
 if(note.relation_ref)return Object.entries(note.relation_ref).every(([key,value])=>relation[key]===value);
 return (note.unit_ids||[]).includes(relation.from)&&(note.unit_ids||[]).includes(relation.to);
}
function deltaSummary(r){
 const d=r.argument_delta;if(!d||d.status!=='compared')return 'Structured arguments are not comparable.';
 const changed=d.changes.map(c=>c.path).join(', ');
 return (d.tool_changed?`Tool changed: ${d.tool_before} → ${d.tool_after}. `:'Same recorded tool. ')+(changed?'Arguments changed: '+changed+'.':'Recorded argument objects are identical.');
}
function relationEvidence(r,host){
 if(r.work_result_id){const row=state.doc.work_results?.observations.find(v=>v.id===r.work_result_id);if(row)host.append(button(workResultLabel[row.result]+' · '+row.scope_text,()=>inspectWorkResult(row),'work-result-badge '+row.result),el('p',unmetLabel[row.unmet_condition]||'','muted'));}
 if(r.type==='declares_same_work_as')host.append(el('p','Work: '+r.work_text),el('p','Local items '+r.from_item_id+' → '+r.to_item_id+'. The current declaration is observed through '+r.cutoff.event_id+'; later results are not used.','muted'));
 if(['attempts_declared_work','prepares_declared_work','checks_declared_work'].includes(r.type))host.append(el('p','Work at dispatch: '+r.work_text),el('p',declarationLabel[r.declaration_at_dispatch]+' · observed through '+r.cutoff.event_id+'. Later responses were withheld from this correspondence choice.','muted'));
 if(r.declared_work_id)for(const note of declaredReviews(r.declared_work_id))host.append(el('p',note.text,'review-flag'));
 if(r.type==='completed_after_failed_call'){
  host.append(el('p',`Earlier failed-call responses: ${r.previous_response_ids.join(', ')}. Later completed-call responses: ${r.current_response_ids.join(', ')}.`),el('p',r.explanation,'muted'),el('p',`This transition is observable at ${r.cutoff.event_id}, after the later result arrives. It was not known at the later dispatch.`,'muted'));
 }
 if(r.coverage)host.append(el('p',label(r.coverage)+' support · established: '+(r.supported_content||[]).join('; ')+' · not established: '+(r.not_established||[]).join('; '),'muted'));
 if(r.requested_work_version_id){
  host.append(el('p','Requested work at dispatch: '+r.requested_work_text),el('p','Scope status: '+r.requested_status_at_dispatch+'. This correspondence does not establish authorization, condition satisfaction or successful completion.','muted'));
  if(r.requested_before_withdrawal)host.append(el('p','Terms before withdrawal: '+r.requested_before_withdrawal,'muted'));
 }
 for(const note of state.doc.review_notes.filter(n=>relationReviewMatches(n,r))){host.append(el('p',note.text,'review-flag'));}
 for(const ref of r.evidence||[])host.append(cite(ref));
 if(r.context_evidence?.length){host.append(el('p',r.context_label||'Recorded parent expression · context for this link','muted'));for(const ref of r.context_evidence)host.append(cite(ref));}
 if(r.assessment_text)host.append(el('p','Agent’s interpretation: '+r.assessment_text),el('p','Whether the response supports this interpretation has not been judged.','muted'));
 if(r.omitted_feedback_ranges?.length)host.append(el('p',`${r.omitted_feedback_ranges.length} intervals from the source response were omitted from the inspector input; the original response remains available.`,'muted'));
 if(r.assessment_group?.joint){host.append(el('p',`Joint assessment across ${r.assessment_group.response_units.length} responses:`,'muted'));for(const id of r.assessment_group.response_units)host.append(button(unitName(id),()=>inspect(id),'source-button'));}
 if(r.argument_delta&&r.type==='same_action_target'){
  host.append(el('p',deltaSummary(r),'muted'));
    const d=r.argument_delta;
  if(d.status==='compared'&&d.changes.length){const details=el('details');details.append(el('summary','Exact argument changes · earlier → current'));
   for(const change of d.changes){details.append(el('h4',change.path),el('pre',('before' in change?JSON.stringify(change.before,null,2):'[not present]')+'\n↓\n'+('after' in change?JSON.stringify(change.after,null,2):'[not present]'),'quote'));}
   details.append(el('p',d.meaning,'muted'));host.append(details);
  }
 }
}
function inspectPlan(u,host){
 if(!u.plan_structure)return;
 const plan=u.plan_structure;host.append(el('h3','Plan stages · intended work'),el('p','Stages belong to this Plan unit. Their order is not evidence that any stage was performed.','muted'));
 for(const [i,step] of plan.steps.entries()){
  const box=el('section',undefined,'plan-stage');box.append(el('h4',`${i+1}. ${step.text}`),el('p','Target: '+step.target));
  for(const ref of step.evidence)box.append(cite(ref));
  const linked=state.doc.relations.filter(r=>r.to===u.id&&r.plan_step_id===step.id);
  for(const r of linked)box.append(button(`${label(r.type)} · ${unitName(r.from)}: ${unit(r.from).content.summary.text}`,()=>inspect(r.from),'stage-action'));
  if(!linked.length)box.append(el('p','No linked action in the inspected sample.','muted'));
  host.append(box);
 }
 for(const link of plan.links){const a=plan.steps.find(s=>s.id===link.from),b=plan.steps.find(s=>s.id===link.to);const line=el('p',`${a.text} ${link.kind==='precedes'?'→ before →':'→ requires →'} ${b.text}`,'muted');for(const ref of link.evidence)line.append(cite(ref));host.append(line);}
 const c=plan.completion_criterion;host.append(el('p',c.status==='expressed'?'Stated completion criterion: '+c.text:'No explicit completion check is stated in this plan.','muted'));
}
function inspectContext(u,host){
 inspectChecks(u,host);requestedWork(host,u);relatedPaths(u,host);
 const planReview=state.doc.plan_relation_review?.find(r=>r.action_unit_id===u.id);
 if(planReview&&planReview.status!=='linked')host.append(el('p','Plan correspondence: '+label(planReview.status)+'. This is not a deviation judgment.','missing'));
 const notes=state.doc.review_notes.filter(n=>(n.unit_ids||[]).includes(u.id));
 if(notes.length){const reviews=el('details');reviews.append(el('summary',`${quantity(notes.length,'source review note')}`));
  for(const note of notes){const box=el('section',undefined,'review-flag');box.append(el('strong',label(note.kind)),el('p',note.text));for(const ref of note.evidence)box.append(cite(ref));reviews.append(box);}host.append(reviews);
 }
 const selection=state.doc.assessment_review?.find(r=>r.unit_id===u.id);
 if(selection&&selection.status!=='linked')host.append(el('p',`Feedback reference selection: ${label(selection.status)}. ${selection.candidate_count} responses offered; this does not establish that no assessment occurred.`,'missing'));
 const c=u.inspector_context;if(!c)return;
 const details=el('details');details.append(el('summary','Inspector context and unobserved evidence'));
 details.append(el('p',`${c.included_event_ids.length} source events supplied; ${c.omitted_event_ids.length} older events omitted.`,'muted'));
 if(c.retained_instruction_event_ids){details.append(el('p',`Retained instruction events: ${c.retained_instruction_event_ids.join(', ')}.`,'muted'),el('p',c.instruction_retention,'muted'));}
 if(c.omitted_text_ranges?.length)details.append(el('p',`${c.omitted_text_ranges.length} text ranges omitted from long events. Original text remains stored and retrievable.`,'muted'));
 const media=[...(c.unobserved_media||[]),...(c.unobserved_media_parts||[]),...(c.unobserved_auxiliary_media||[])];
 if(media.length){details.append(el('p','Media listed below was not decoded or inspected by this text observation. Encoded payloads are not evidence about image or audio contents.','muted'));for(const m of media)details.append(el('p',`${m.event_id} · ${m.mime_type||m.type} · unobserved`,'muted'));}
 if(u.candidate_producer)details.append(el('p','Candidate producer: '+u.candidate_producer,'muted'));
 if(c.candidate_readings){
  const readings=c.candidate_readings,box=el('details');box.append(el('summary','Candidate readings supplied to Jev'),el('p',readings.meaning,'muted'),el('p','Producer: '+readings.producer,'muted'));
  for(const reading of readings.readings){
   box.append(el('h4',label(reading.activity)+(reading.activity===readings.selected_activity?' · selected activity':'')),el('p',reading.text));
   for(const ref of reading.evidence||[])box.append(cite(ref));
  }
  details.append(box);
 }
 host.append(details);
}
function source(ref,returnTo=null,returnLabel='Back to work result'){const host=$('#inspector');host.replaceChildren(el('p','SOURCE EVIDENCE','eyebrow'),el('h3',`${ref.event_id} · ${ref.source_pointer}`),el('p',`Characters ${ref.start}–${ref.end} (end exclusive)`,'muted'),el('pre',ref.text,'quote'));const event=state.run.events.find(e=>e.id===ref.event_id);const d=el('details');d.append(el('summary','Full source event'),el('pre',event.text,'quote'));host.append(d);if(returnTo)host.append(button(returnLabel,returnTo));else if(state.selected)host.append(button('Back to selected unit',()=>inspect(state.selected)));presentInspector(host);}
function card(u){
 const b=button('',()=>inspect(u.id),`unit ${u.kind}${state.selected===u.id?' selected':''}`);b.dataset.unitId=u.id;
 if(state.search&&(state.search.query||state.focus!=='all'||state.filter!=='all')){
  const direct=state.search.direct.has(u.id),anchor=state.search.neighborhood?.anchor===u.id;
  b.append(el('span',anchor?'Focus unit':direct?(state.search.neighborhood?'Directly connected':'In focus'):'Connected/opened context','match-origin'));b.classList.toggle('context-only',!direct&&!anchor);
 }
 const meta=el('div',undefined,'meta');meta.append(el('span',unitName(u.id)),el('span',label(u.actor),'speaker'),el('span',u.activity?label(u.activity):'Environment feedback','activity'),el('span',u.source.event_id));
 b.append(meta,el('div',u.content.summary.text,'summary'),el('div','Target: '+u.content.target.text,'target-text'));
 if(state.search?.query&&state.search.matches.has(u.id)){const excerpt=searchExcerpt(u);if(excerpt)b.append(el('div',excerpt,'search-excerpt'));}
 if(u.kind==='feedback'&&u.content.recorded_response)b.append(el('div',responsePreview(u.content.recorded_response.text),'response-preview'));return b;
}
function conditionContents(record,host){
 if(!record?.clauses?.length)return;
 const names={requirement:'Requirement',requested_check:'Requested check',attributed_claim:'Attributed claim'};
 const details=el('details',undefined,'condition-contents');
 if(state.search?.query)details.open=record.clauses.some(c=>state.search.query.split(/\s+/).every(t=>c.text.toLocaleLowerCase().includes(t)));
 details.append(el('summary','Requirements, requested checks and claims'));
 for(const clause of record.clauses){
  const row=el('section',undefined,'condition-clause');row.dataset.clauseId=clause.id;
  row.append(el('p',names[clause.kind]||label(clause.kind),'eyebrow'),el('p',clause.text));
  if(clause.kind==='requested_check')row.append(el('p','Requested checking work; no passing result is established here.','muted'));
  else if(clause.kind==='attributed_claim')row.append(el('p','Attributed assertion; not independently established by this record.','muted'));
  for(const ref of clause.evidence)row.append(cite(ref));details.append(row);
 }
 host.append(details);
}
function changeContents(change,host){
 host.append(el('p',change.after.text));conditionContents(change.after,host);
 if(change.before){const previous=el('details');previous.append(el('summary','Previous terms'),el('p',change.before.text));conditionContents(change.before,previous);host.append(previous);}
 for(const retired of change.retired_clauses||[]){
  const removed=el('div',undefined,'retired-clause');removed.append(el('p','Removed from current terms: '+retired.previous.text),el('p',retired.reason,'muted'));
  for(const ref of retired.evidence)removed.append(cite(ref));host.append(removed);
 }
 for(const ref of change.after.evidence)host.append(cite(ref));
}
function requestedWork(host,u){
 if(!state.doc.requested_work)return;
 const steps=scopeThroughUnit(state.doc,state.run,u),step=steps.at(-1);
 const dispatch=state.doc.work_correspondence?.actions.find(a=>a.action_unit_id===u.id);
 const records=dispatch?.state_at_dispatch||step?.state_after||[];
 const section=el('details',undefined,'dispatch-scope');section.append(el('summary',u.kind==='action'?'Requested scope available at this dispatch':'Requested scope through this unit'));
 section.append(el('p','Source order limits this snapshot. Requested terms do not establish authorization validity, execution or fulfillment.','muted'));
 if(!records.length)section.append(el('p','No earlier requested-work record is available.','muted'));
 const history=steps.flatMap(s=>s.changes);
 for(const record of records){
  const versions=history.filter(c=>c.record_id===record.id&&c.after.trajectory_id===record.trajectory_id);
  const box=el('section',undefined,'request-record');box.dataset.recordId=record.id;
  const meta=el('div',undefined,'request-meta');meta.append(el('span',record.kind==='work'?'Work item':'Condition'),el('span',record.status==='withdrawn'?'Withdrawn':'Requested',record.status));
  box.append(meta,el('h3',record.text));conditionContents(record,box);
  box.append(button('Follow this record through the trace',()=>focusWork(recordFocus(record)),'connection-jump'));
  if(dispatch&&record.kind==='work'){const role=dispatch.choices[record.version_id];box.append(el('p',role&&role!=='none'?'Selected correspondence: '+label(role):'No specific work correspondence selected.','muted'));}
  const details=el('details',undefined,'request-history');details.append(el('summary',`${quantity(versions.length,'version')} through this point`));
  for(const change of versions){
   const row=el('section',undefined,'request-version');row.append(el('p',`${label(change.operation)} · ${unit(change.source_unit_id).source.event_id}`,'eyebrow'));changeContents(change,row);
   row.append(button('Open contribution and meaning',()=>inspect(change.source_unit_id),'source-button'));details.append(row);
  }
  box.append(details);section.append(box);
 }
 host.append(section);
}
function relatedPaths(u,host){
 const paths=(state.doc.work_paths?.paths||[]).filter(p=>p.related_unit_ids.includes(u.id));if(!paths.length)return;
 const details=el('details',undefined,'dispatch-scope');details.append(el('summary','Related action targets'));
 for(const path of paths){
  details.append(button(path.target,()=>focusWork('path:'+path.id),'connection-jump'),el('p',`${quantity(path.counts.dispatches,'dispatch')} · ${quantity(path.counts.source_responses,'response')}`,'muted'));
  if(path.disputed_identity)details.append(el('p','This grouping has a disputed target relation.','review-flag'));
  const selected=path.identity_selections.find(r=>r.action_unit_id===u.id);
  if(selected)details.append(el('p','Target correspondence: '+label(selected.status),'muted'));
 }
 details.append(el('p','A target groups related work. Grouping does not establish progress or recovery.','muted'));host.append(details);
}
function inspectChecks(u,host){
 const row=state.doc.check_correspondence?.actions.find(a=>a.action_unit_id===u.id||a.responses.some(r=>r.feedback_unit_id===u.id));
 if(!row)return;
 const details=el('details',undefined,'dispatch-scope');details.append(el('summary','Requested checks and returned evidence'));
 if(!row.candidates.length){details.append(el('p','No retained checking request was available in the inspected state at dispatch.','muted'));host.append(details);return;}
 const responseLabels={sufficient:'Contains requested evidence',partial:'Contains only part of the requested evidence',no_answer:'Does not supply the requested answer',unresolved:'Evidence sufficiency unresolved'};
 details.append(el('p','Dispatch correspondence uses prior context. Response sufficiency judges the recorded payload separately; it does not mean a check passed or the user received an answer.','muted'));
 const scopeNotes=state.doc.review_notes.filter(n=>n.kind==='check_scope_review'&&(n.unit_ids||[]).includes(u.id));
 if(scopeNotes.length){const reviews=el('details',undefined,'review-flag');reviews.append(el('summary',`${quantity(scopeNotes.length,'checking scope review')}`));for(const note of scopeNotes)reviews.append(el('p',note.text));details.append(reviews);}
 for(const candidate of row.candidates){
  const clause=candidate.clause,box=el('section');box.dataset.checkClauseId=clause.id;box.append(el('h4',clause.text));
  for(const ref of clause.evidence)box.append(cite(ref));
  if(u.kind==='action')box.append(el('p','Dispatch: '+({attempts:'Attempts this check',prepares:'Prepares for this check',none:'No specific correspondence selected',unresolved:'Correspondence unresolved'}[row.dispatch_choices[clause.version_id]]||'Not inspected')));
  const responses=row.responses.filter(r=>u.kind==='action'||r.feedback_unit_id===u.id);
  for(const response of responses)box.append(el('p',responseLabels[response.choices[clause.version_id]]||'Not inspected'),button('Open recorded response · '+response.event_id,()=>inspect(response.feedback_unit_id),'source-button'));
  if(!responses.length)box.append(el('p','No linked recorded response is available. This is missing evidence, not a failed check.','muted'));
  details.append(box);
 }
 host.append(details);
}
function inspectStatedChecks(u,host){
 const pass=state.doc.stated_checks;if(!pass)return;
 const materialMode=['stated-check-evidence/3','stated-check-evidence/4','stated-check-evidence/5'].includes(pass.schema);
 const items=checkingObservations(state.doc).filter(o=>o.unit_id===u.id||o.actions.some(a=>a.action_unit_id===u.id||a.facets.some(f=>f.responses.some(r=>r.feedback_unit_id===u.id))));
 if(!items.length){if(pass.uninspected_unit_ids.includes(u.id))host.append(el('p','Checking contents have not been inspected for this contribution.','muted'));return;}
 const details=el('details',undefined,'dispatch-scope');details.append(el('summary','Stated checks and evidence'));
 details.append(el('p',pass.schema==='stated-check-evidence/5'?'Checks, reports and requests for a decision are distinguished before extracting checking contents. The original unit and activity stay intact.':'Parts of the agent’s expressed check, within the original unit. Recorded expression/action pairing retrieves candidates; correspondence and returned evidence are judged separately.','muted'));
 const scopeNotes=state.doc.review_notes.filter(n=>n.kind==='check_scope_review'&&(n.unit_ids||[]).includes(u.id));
 if(scopeNotes.length){const reviews=el('details',undefined,'review-flag');reviews.append(el('summary',`${quantity(scopeNotes.length,'checking scope review')}`));for(const note of scopeNotes)reviews.append(el('p',note.text));details.append(reviews);}
 const roles={attempts:'Attempts this part',prepares:'Prepares for this part',none:'No correspondence selected',unresolved:'Correspondence unresolved'};
 const evidenceLabels={sufficient:'Supplies the checking evidence',partial:materialMode?'Some requested material':'Supplies only part of the evidence',no_answer:'Does not supply answering evidence',unresolved:materialMode?'Material scope unresolved':'Evidence unresolved',available:'Requested material available',absent:'Requested material absent from this response',unobserved:'Recorded material not inspected'};
 const specificationLabels={test_defined:'A condition or test is specified',observation_only:'Inspection requested; no acceptance condition specified',unresolved:'Basis for judging the check unresolved'};
 const applicabilityLabels={checking_work:'Checking work expressed',report_only:'Reported facts, check or assurance; no new checking work selected',decision_only:'Decision or authorization; no factual checking work selected',other:'Other contents; checking extraction not opened',unresolved:'Checking applicability unresolved'};
 for(const item of items){
  const revision=state.doc.check_candidate_revisions?.find(r=>r.unit_id===item.unit_id);
  if(revision){
   const history=el('details',undefined,'candidate-revision');history.append(el('summary','Checking candidate repair history'),el('p','Producer: '+revision.producer,'muted'),el('p',revision.scope,'muted'));
   history.append(el('h4','Previous candidates · '+label(revision.previous_selection)));
   for(const candidate of revision.previous_candidates)history.append(el('p',candidate.text));
   history.append(el('h4','Revised candidates · '+(item.check?'one selected by Jev':label(item.selection))));
   revision.proposed_candidates.forEach((candidate,index)=>{history.append(el('p',(item.selection==='c'+index?'Selected candidate: ':'Alternative: ')+candidate.text));for(const ref of candidate.evidence)history.append(cite(ref));});
   history.append(el('p','The proposal is externally supplied. Source validation does not prove semantic accuracy; the recorded Jev choice remains raw argmax.','muted'));details.append(history);
  }
  if(item.applicability){details.append(el('p','Applicability: '+applicabilityLabels[item.applicability.choice],'muted'));
   if(item.applicability.choice==='checking_work'&&item.selection==='none')details.append(el('p','Stage disagreement: applicability selected checking work, but content selection chose none. Review the expression and offered candidates; this is not an established absence of checking.','review-flag'));
  }
  if(item.selection.startsWith('route:'))continue;
  if(!item.check){details.append(el('p',({none:'No checking work selected in this contribution.',no_suitable_candidate:'Checking work needs better content candidates.',unresolved:'Checking contents unresolved.'})[item.selection]||'Checking contents not selected.','muted'));continue;}
  details.append(el('h4',item.check.text));
  if(item.laterActionCount)details.append(el('p',`${quantity(item.laterActionCount,'later operation candidate')} examined against this historical checking target. Matching work does not establish continuing intent, active scope or completion.`,'muted'));
  if(item.unit_id!==u.id)details.append(button('Open stated check · '+unitName(item.unit_id),()=>inspect(item.unit_id),'source-button'));
  for(const ref of item.check.evidence)details.append(cite(ref));
  for(const facet of item.check.facets){
   const section=el('section',undefined,'condition-clause');section.append(el('p',facet.text));
   const specification=item.specifications?.find(s=>s.facet_id===facet.id);
   if(specification)section.append(el('p','Specification: '+(specificationLabels[specification.choice]||label(specification.choice)),'muted'));
   for(const action of item.actions){
    if(u.kind==='action'&&action.action_unit_id!==u.id)continue;
    const value=action.facets.find(f=>f.facet_id===facet.id);if(!value)continue;
    const responses=value.responses.filter(r=>u.kind!=='feedback'||r.feedback_unit_id===u.id);
    if(u.kind==='feedback'&&!responses.length)continue;
    const actionHost=action.retrieval==='earlier_stated_check'?el('details',undefined,'later-check-action'):section;
    const currentMaterial=r=>materialObservation(state.doc,item.unit_id,item.check.id,facet.id,action.action_unit_id,r.feedback_unit_id);
    if(actionHost!==section){actionHost.append(el('summary',`${unitName(action.action_unit_id)} · ${roles[value.dispatch_choice]}${responses.length?' · '+responses.map(r=>{const m=currentMaterial(r);return m?materialFormLabels[m.choice]:evidenceLabels[r.choice]||label(r.choice);}).join('; '):''}`));section.append(actionHost);}
    const dispatchLine=el('div',undefined,'check-selection');dispatchLine.append(el('span','Operation: '+roles[value.dispatch_choice]));
    if(action.action_unit_id!==u.id)dispatchLine.append(button('Open operation · '+unitName(action.action_unit_id),()=>inspect(action.action_unit_id),'source-button'));
    actionHost.append(dispatchLine);
    for(const response of responses){
     const material=currentMaterial(response);
     const responseLine=el('div',undefined,'check-selection');responseLine.append(el('span',(material?'Material form: ':materialMode?'Material: ':'Response: ')+(material?materialFormLabels[material.choice]:evidenceLabels[response.choice]||label(response.choice))));
     if(response.feedback_unit_id!==u.id)responseLine.append(button('Open response · '+response.event_id,()=>inspect(response.feedback_unit_id),'source-button'));
     actionHost.append(responseLine);
     const observed=material||response;
     if(observed.unobserved_media.length)actionHost.append(el('p','Response includes media that this text observer has not inspected.','missing'));
     if(observed.omitted_text_ranges.length)actionHost.append(el('p','Some response text was omitted from the inspector input. Original evidence remains available.','muted'));
     if(material){
      const delivery=state.doc.response_material.deliveries.find(r=>r.feedback_unit_id===response.feedback_unit_id);
      if(delivery)actionHost.append(el('p','Returned through: '+deliveryLabels[delivery.choice]+'. This does not establish a passing check.','muted'));
      for(const flag of material.review_flags)actionHost.append(el('p',flag,'review-flag'));
      const previous=el('details',undefined,'candidate-revision');previous.append(el('summary','Earlier material selection'),el('p',evidenceLabels[material.previous_choice]||label(material.previous_choice)),el('p','The earlier raw choice is preserved. This observer separately selects material form; it does not establish correctness or a fresh evaluation.','muted'));actionHost.append(previous);
     }else if(response.choice==='unobserved'&&!response.unobserved_media.length&&!response.omitted_text_ranges.length)actionHost.append(el('p','Review this selection: no omitted response text or recorded uninspected media is listed. A reference to an image or file alone does not supply its contents.','review-flag'));
    }
    if(value.response_status)actionHost.append(el('p','No linked recorded response is available.','muted'));
   }
   if(!item.actions.length)section.append(el('p','No dispatch with a recorded source association was available to this pass.','muted'));
   details.append(section);
  }
 }
 details.append(el('p',materialMode?'Specification and returned material are separate observations. Neither establishes a passing result or task completion.':'Evidence availability does not establish a passing result, correctness, or completion.','muted'));host.append(details);
}
function populateFocus(){
 const select=$('#work-focus');select.replaceChildren(el('option','Whole trace'));select.firstChild.value='all';
 if(state.focus.startsWith('unit:')){const anchor=unit(state.focus.slice(5));if(anchor){const option=el('option','Connections around '+unitName(anchor.id));option.value=state.focus;select.append(option);}}
 if(state.focus.startsWith('episode:')){const recurrence=state.doc.work_history?.recurrences.find(r=>'episode:'+r.unit_id===state.focus);if(recurrence?.context){const option=el('option','Compare '+unitName(recurrence.previous_group_unit_id)+' → '+unitName(recurrence.unit_id));option.value=state.focus;select.append(option);}}
 const contexts=state.doc.work_context_overview?.groups.filter(g=>g.unit_ids.length)||[];
 const declarations=state.doc.declared_work_history?.records||[];
 if(declarations.length){const group=el('optgroup');group.label='Stated work histories';for(const record of declarations){const option=el('option',record.updates[0].work+' · '+record.updates.length+' statements');option.value='declared:'+record.id;group.append(option);}select.append(group);}
 const stagePlans=state.doc.plan_execution?.plans||[];
 if(stagePlans.length){const group=el('optgroup');group.label='Plan stages';for(const plan of stagePlans)for(const stage of plan.stages){const option=el('option',stage.text);option.value='stage:'+stage.id;group.append(option);}select.append(group);}
 const patterns=state.doc.sequence_patterns?.runs||[];
 if(patterns.length){const group=el('optgroup');group.label='Repeated work sequences';for(const row of patterns){const option=el('option',`Operations ${row.start_position}–${row.end_position} · ${row.period}-operation pattern × ${row.full_copies}`);option.value='pattern:'+row.id;group.append(option);}select.append(group);}
 const returns=state.doc.sequence_patterns?.returns||[];
 if(returns.length){const group=el('optgroup');group.label='Returns after intervening work';for(const row of returns){const option=el('option',returnTitle(row)+` · ${row.previous.start_position}–${row.previous.end_position} → ${row.current.start_position}–${row.current.end_position}`);option.value='return:'+row.id;group.append(option);}select.append(group);}
 if(contexts.length){const group=el('optgroup');group.label='Enclosing work scopes';for(const context of contexts){const option=el('option',context.source.event_id+' · '+context.text);option.value='context:'+context.id;group.append(option);}select.append(group);}
 const records=state.doc.requested_work?.records||[];
 if(records.length){const group=el('optgroup');group.label='Requested work and conditions';
  for(const record of records){const option=el('option',(record.kind==='condition'?'Condition: ':'Work: ')+record.text);option.value=recordFocus(record);group.append(option);}select.append(group);
 }
 const paths=state.doc.work_paths?.paths||[];
 if(paths.length){const group=el('optgroup');group.label='Related action targets';
  for(const path of paths){const option=el('option',path.target);option.value='path:'+path.id;group.append(option);}select.append(group);
 }
 if(![...select.options].some(o=>o.value===state.focus))state.focus='all';select.value=state.focus;$('#unit-filter').value=state.filter;
}
function focusWork(value){
 state.focus=value;state.filter='all';state.relation='all';state.revealed=null;populateFocus();applyFilters();
 $('#inspector').classList.remove('drawer-open');$('#work-focus').focus();
 if(value.startsWith('return:'))$('#work-return-focus').scrollIntoView({block:'start'});
}
function focusConnections(id){
 $('#map-search').value='';$('#include-connected').checked=true;
 focusWork('unit:'+id);
}
function connectionFocus(){
 const host=$('#connection-focus'),anchored=state.focus.startsWith('unit:');host.hidden=!anchored;
 $('.context-toggle').hidden=anchored;
 if(!anchored){state.relation='all';return;}
 const all=unitConnections(state.doc,state.focus.slice(5)),anchor=unit(all.anchor);
 const select=$('#relation-filter');select.replaceChildren();
 const option=el('option',`All connection types (${all.relations.length})`);option.value='all';select.append(option);
 const counts=new Map();for(const r of all.relations)counts.set(r.type,(counts.get(r.type)||0)+1);
 for(const [type,count]of [...counts].sort(([a],[b])=>a.localeCompare(b))){const option=el('option',`${label(type)} (${count})`);option.value=type;select.append(option);}
 if(state.relation!=='all'&&!counts.has(state.relation))state.relation='all';select.value=state.relation;
 $('#connection-title').textContent='Connections around '+unitName(anchor.id);
 $('#connection-summary').textContent=anchor.content.summary.text;
 $('#inspect-anchor').onclick=()=>inspect(anchor.id);
}
function applyFilters(){
 state.revealed=null;render();
 if(!state.search.visible.has(state.selected)){const first=orderedUnits(state.doc,state.run).find(u=>state.search.visible.has(u.id));if(first)inspect(first.id,false);else $('#inspector').replaceChildren(el('p','No units match this focus. Reset the focus or change the search.','muted'));}
}
function timelineRow(u){
 const row=el('article',undefined,'timeline-row');row.dataset.timelineUnit=u.id;row.append(card(u));
 const neighborhood=state.search.neighborhood;
 if(neighborhood?.anchor===u.id)row.classList.add('focus-anchor');
 else if(neighborhood?.unitIds.has(u.id))row.classList.add('connected-unit');
 const changes=(state.doc.requested_work?.steps||[]).find(s=>s.unit_id===u.id)?.changes||[];
 if(changes.length){
  const section=el('details',undefined,'unit-work-update');section.append(el('summary',`${quantity(changes.length,'requested-scope update')}`));
  for(const change of changes){const item=el('section',undefined,'request-version');item.append(el('p',`${label(change.operation)} · ${change.after.kind==='work'?'Work item':'Condition'}`,'eyebrow'));changeContents(change,item);section.append(item);}row.append(section);
 }
 const links=(neighborhood?neighborhood.relations:state.doc.relations).filter(r=>r.from===u.id);
 if(links.length){
  const section=el('div',undefined,'timeline-links');
  for(const r of (neighborhood?links:links.slice(0,2))){const jump=button(`${unitName(r.from)} — ${relationName(r)} → ${unitName(r.to)} · ${r.requested_work_text||unit(r.to).content.summary.text}`,()=>inspect(r.to),'timeline-link');jump.dataset.relationType=r.type;jump.dataset.from=r.from;jump.dataset.to=r.to;section.append(jump);}
  if(!neighborhood&&links.length>2)section.append(button(`+ ${links.length-2} more connections`,()=>inspect(u.id),'source-button'));row.append(section);
 }
 if(u.kind==='action'&&!state.doc.relations.some(r=>r.type==='feedback_for'&&r.to===u.id))row.append(el('p','No linked recorded response.','missing'));
 if(state.revealed===u.id&&!state.search.direct.has(u.id))row.append(el('p','Opened from a connection outside the current focus.','muted'));
 return row;
}
function render(){
 if(!state.doc)return;renderWorkHistory();renderLineageFocus();renderReturnFocus();renderDeclaredFocus();connectionFocus();searchUnits();const host=$('#map');const oldViewport=host.querySelector('.blueprint-viewport'),scroll=oldViewport?{top:oldViewport.scrollTop,left:oldViewport.scrollLeft}:null;host.replaceChildren();host.classList.remove('blueprint-host');
 const address=new URL(location.href);address.searchParams.delete('view');
 if(state.layout==='timeline')address.searchParams.set('layout','timeline');else address.searchParams.delete('layout');$('#map-layout').value=state.layout;
 for(const [key,value,empty]of [['focus',state.focus,'all'],['show',state.filter,'all'],['q',$('#map-search').value,''],['relation',state.relation,'all'],['targets',$('#history-singletons').checked?'all':'repeated','repeated']]){if(value===empty)address.searchParams.delete(key);else address.searchParams.set(key,value);}
 if($('#include-connected').checked)address.searchParams.delete('connected');else address.searchParams.set('connected','0');
 history.replaceState(null,'',address);
 $('#view-explanation').textContent=state.layout==='blueprint'?'Cards preserve individual contributions, actions and responses. Dashed lines show source order; colored arrows show saved relationships. Select a card to highlight its links, or a line to inspect the relationship. Work summaries above focus the same graph.':'Source order runs downward. Each unit appears once; named links show its connections. Hidden-unit markers show gaps in a filtered trace. Select a unit to follow its connections or inspect its contents and evidence.';
 if(state.focus.startsWith('pattern:'))$('#view-explanation').textContent='Repeated target-sequence interval: original operations, intervening contributions and linked feedback. This retrospective view retains changed procedures and conditions; sequence repetition does not establish a loop failure or unchanged reasoning.';
 if(state.focus.startsWith('return:'))$('#view-explanation').textContent='Return interval: earlier and later target sequences, with all intervening selected units and endpoint feedback. Action positions belong to one actor’s trajectory; the interval also retains other participants. Only aligned operations are compared.';
 if(state.focus.startsWith('episode:')){
  const recurrence=state.doc.work_history?.recurrences.find(r=>'episode:'+r.unit_id===state.focus),context=recurrence?.context;
  if(context){
   $('#view-explanation').textContent='Comparison interval: both occurrences, their recorded expressions and responses, and intervening selected units from all participants. Responses after the later dispatch remain retrospective evidence.';
   const note=el('div',undefined,'dispatch-scope');note.append(button('Inspect this comparison',()=>{inspect(recurrence.unit_id);showRecurrenceComparison();},'connection-jump'));
   if(context.unrepresented_source_ranges.length)note.append(el('p',`${quantity(context.unrepresented_source_ranges.length,'source range')} without a selected unit. Open the comparison for original evidence.`,'review-flag'));
   host.append(note);
  }
 }
 const {sequence,hiddenAfter}=visibleSequence(state.doc,state.run,state.search.visible),visible=sequence.map(v=>v.unit);
 if(state.layout==='blueprint'){
  const mounted=BehaviorBlueprint.mount(host,state.doc,state.run,state.search.visible,{selected:state.selected,focus:state.focus,onUnit:id=>inspect(id),onStage:stage=>focusWork('stage:'+stage.id),onStageEvidence:inspectStageEvidence,onTransition:inspectStageTransition,onDeclaredLink:(plan,link)=>{
   const detail=$('#inspector');detail.replaceChildren(el('p','DECLARED PLAN ORGANIZATION','eyebrow'),el('h2',`${link.from} ${link.kind} ${link.to}`),el('p','This connection is stated in the Plan. It does not establish execution order.','muted'));for(const ref of link.evidence)detail.append(cite(ref));presentInspector(detail);
  },onRelation:r=>{
   state.selected=r.from;const detail=$('#inspector');detail.replaceChildren(el('p','SAVED CONNECTION','eyebrow'),el('h2',relationName(r)),el('p',r.explanation||r.basis||''));
   detail.append(button('From '+unitName(r.from)+' · '+unit(r.from).content.summary.text,()=>inspect(r.from),'connection-jump'),button('To '+unitName(r.to)+' · '+unit(r.to).content.summary.text,()=>inspect(r.to),'connection-jump'));relationEvidence(r,detail);presentInspector(detail);
  }});if(scroll&&state.lastGraphFocus===state.focus){mounted.viewport.scrollTop=scroll.top;mounted.viewport.scrollLeft=scroll.left;}state.lastGraphFocus=state.focus;
 }else{
  for(const [index,{unit:u,hiddenBefore}]of sequence.entries()){if(hiddenBefore)host.append(el('p',`${quantity(hiddenBefore,index?'intervening unit':'earlier unit')} hidden by this focus`,'timeline-gap'));host.append(timelineRow(u));}
  if(hiddenAfter&&visible.length)host.append(el('p',`${quantity(hiddenAfter,'later unit')} hidden by this focus`,'timeline-gap'));
 }
 for(const item of host.querySelectorAll('.unit[data-unit-id]')){const notes=state.doc.review_notes.filter(n=>(n.unit_ids||[]).includes(item.dataset.unitId));if(notes.length)item.append(el('div',[...new Set(notes.map(n=>label(n.kind)))].join(' · '),'review-label'));}
 const narrowed=state.focus!=='all'||state.filter!=='all'||Boolean(state.search.query);
 const extra=visible.length-state.search.direct.size;
 const neighborhood=state.search.neighborhood;
 $('#search-status').textContent=`${visible.length} of ${state.doc.units.length} units shown`+(neighborhood?` · Focus unit: ${neighborhood.incoming.length} incoming / ${neighborhood.outgoing.length} outgoing connections`+(extra?` · ${quantity(extra,'retained/opened unit')} outside the filter`:''):narrowed?` · ${state.search.direct.size} in focus`+(extra?` + ${quantity(extra,'connected/opened unit')}`:''):'')+'.';
 if(!visible.length)host.append(el('p','No units match. Reset the focus or change the search.','missing'));
 $('#reset-focus').disabled=!narrowed&&!state.revealed&&$('#include-connected').checked;
}
function inspectStageEvidence(plan,stage){
 const host=$('#inspector');host.replaceChildren(el('p','PLAN STAGE · EVIDENCE','eyebrow'),el('h2',stage.text),el('p','Target: '+stage.target),button('Open source Plan',()=>inspect(plan.plan_unit_id),'connection-jump'));
 host.append(el('p','Preparation, attempt, recorded material and verified completion are separate observations. Material may be stored or authored content; its presence does not validate its claims.','muted'));
 for(const ref of stage.evidence)host.append(cite(ref));
 for(const result of stage.work_result_history||[])host.append(button(result.response_event_id+' · '+workResultLabel[result.result],()=>inspectWorkResult(result),'work-result-badge '+result.result));
 for(const r of stage.response_evidence){
  const box=el('section',undefined,'inspector-connection'),m=r.material_index===null?null:state.doc.plan_stage_material?.observations[r.material_index],er=r.executor_report_index===null?null:state.doc.execution_reports?.observations[r.executor_report_index];
  box.append(el('p',`${r.response_event_id} · ${r.roles.map(label).join(' / ')}`,'eyebrow'),button('Open action: '+unit(r.action_unit_id).content.summary.text,()=>inspect(r.action_unit_id),'connection-jump'));
  if(m){box.append(el('p','Material: '+(BehaviorBlueprint.materialLabels[m.form]||label(m.form))),el('p',`Decision ${m.request_hash}`,'muted'));for(const ref of m.evidence)box.append(cite(ref));}
  else box.append(el('p',r.roles.includes('prepares')?'Preparation response; downstream product not assessed.':'Stage material has not been inspected.','muted'));
  if(er)box.append(el('p',`Executor error: ${label(er.error)} · warning: ${label(er.warning)}`,'muted'));
  if(r.response_unit_id)box.append(button('Open recorded response',()=>inspect(r.response_unit_id),'connection-jump'));host.append(box);
 }
 if(!stage.response_evidence.length)host.append(el('p','No source-bound response is available for this stage.','muted'));
 host.append(el('p','Stage completion: not established.','muted'));presentInspector(host);
}
function inspectStageTransition(plan,transition){
 const name=id=>plan.stages.find(s=>s.stage_id===id)?.text||id,host=$('#inspector');
 host.replaceChildren(el('p','OBSERVED STAGE WORK','eyebrow'),el('h2',name(transition.from_stage_id)+' → '+name(transition.to_stage_id)),el('p',transition.order_status==='source_order'?'Later dispatched work corresponds to another stage of this Plan. This does not prove completion of the earlier stage or a mental return to the Plan.':'Source order is recorded, but execution order is not established for this action batch.','muted'));
 for(const id of [...transition.from_unit_ids,...transition.to_unit_ids])host.append(button('Open '+unitName(id)+': '+unit(id).content.summary.text,()=>inspect(id),'connection-jump'));
 if('prior_stage_result_at_entry' in transition){
  const row=transition.prior_stage_result_at_entry;host.append(el('h3','Earlier-stage result available at this entry'));
  if(row)host.append(button(workResultLabel[row.result]+' · '+row.response_event_id,()=>inspectWorkResult(row),'work-result-badge '+row.result),el('p',unmetLabel[row.unmet_condition]||'','muted'));
  else host.append(el('p','No inspected work result was available before this stage entry.','muted'));
 }
 host.append(el('p',`${transition.gap_action_event_ids.length} unassigned intervening dispatches · ${transition.reentry?'a previously observed stage recurs':'first observed entry to this stage'}`,'muted'),el('h3','Earlier-stage material recorded before this entry'));
 for(const index of transition.prior_stage_material_before_entry){const m=state.doc.plan_stage_material.observations[index];host.append(el('p',m.response_event_id+' · '+(BehaviorBlueprint.materialLabels[m.form]||label(m.form))));for(const ref of m.evidence)host.append(cite(ref));}
 if(!transition.prior_stage_material_before_entry.length)host.append(el('p','No inspected earlier-stage material is available before this entry.','muted'));
 host.append(el('p',`Evidence cutoff: ${transition.cutoff.event_id}. Later responses do not fill earlier knowledge.`, 'muted'));presentInspector(host);
}
function inspectExecutionReports(u,host){
 const rows=(state.doc.execution_reports?.observations||[]).filter(r=>[r.action_event_id,r.response_event_id].includes(u.source.event_id));
 if(!rows.length)return;
 host.append(el('h3','Executor reports'));
 for(const r of rows){
  const box=el('section',undefined,'inspector-connection');
  box.append(el('p',`${r.response_event_id} · Error: ${label(r.error)} · Warning: ${label(r.warning)}`,'eyebrow'),el('p',state.doc.execution_reports.limits,'muted'));
  if(!r.complete_readable_response)box.append(el('p','Some response material was not inspected. A negative selection is excluded from absence-based statistics.','muted'));
  const details=el('details');details.append(el('summary','Inspected response and decision binding'),el('p',`Request: ${r.request_hash}`,'muted'));
  for(const ref of r.evidence)details.append(cite(ref));box.append(details);host.append(box);
 }
}
function inspectOperationOutcomes(u,host){
 const rows=(state.doc.operation_outcomes?.observations||[]).filter(r=>[r.action_event_id,r.response_event_id].includes(u.source.event_id));
 if(!rows.length)return;
 host.append(el('h3','Operation outcome'));
 for(const r of rows){
  const box=el('section',undefined,'inspector-connection');
  box.append(el('p',`${r.response_event_id} · ${label(r.outcome)}`,'eyebrow'),el('p',state.doc.operation_outcomes.limits,'muted'));
  box.append(el('p',`Operation mechanism: ${label(r.mechanism)}. Executor error report: ${label(r.executor_error_report)}.`,'muted'));
  if(!r.complete_readable_response||!r.complete_readable_dispatch)box.append(el('p','Some operation evidence was not inspected. The selection stays visible but cannot establish a whole-call transition.','muted'));
  const details=el('details');details.append(el('summary','Inspected operation evidence'),el('p',`Request: ${r.request_hash}`,'muted'));
  details.append(el('p',`Selected option: ${r.selected_option}. Candidate constraints: ${r.candidate_constraints.length?r.candidate_constraints.join(', '):'none'}.`,'muted'));
  for(const ref of r.evidence)details.append(cite(ref));box.append(details);host.append(box);
 }
}
function inspect(id,open=true){
 if(open&&!state.inspectorReturn)state.inspectorReturn={left:window.scrollX,top:window.scrollY};
 const u=unit(id);state.selected=id;if(!state.search.visible.has(id))state.revealed=id;render();
 if(open&&state.inspectorReturn){const position=state.inspectorReturn;window.scrollTo(position);requestAnimationFrame(()=>window.scrollTo(position));}
 const host=$('#inspector');host.replaceChildren(el('p',`${unitName(u.id)} · ${label(u.actor)} · ${u.kind==='feedback'?'SOURCE RESULT':label(u.activity)}`,'eyebrow'),el('h2',u.content.summary.text),el('p',u.kind==='feedback'?'Recorded environment evidence · no semantic judgment':state.doc.provenance.origin==='assistant_authored_reference'?'Assistant-authored reference · needs independent review':'Jev selection from model-proposed candidates · needs independent review','badge'));
 const connections=unitConnections(state.doc,id);
 const follow=button('Follow connections',()=>focusConnections(id),'follow-connections');follow.id='follow-connections';
 host.append(follow,el('p',`${connections.incoming.length} incoming / ${connections.outgoing.length} outgoing · ${quantity(connections.unitIds.size-1,'connected unit')}`,'muted'));
 if(state.doc.work_history?.recurrences.some(r=>r.unit_id===id&&r.context))host.append(button('Compare with previous occurrence',showRecurrenceComparison,'connection-jump'));
 if(!connections.relations.length)host.append(el('p','No connections were selected for this unit in this observation.','muted'));
 const dl=el('dl');for(const [name,v]of Object.entries(u.content)){if(name==='summary')continue;dl.append(el('dt',label(name)));const dd=el('dd',v.text);dd.append(el('br'));for(const ref of v.evidence)dd.append(cite(ref));dl.append(dd);}host.append(dl);
 inspectDeclaredWork(u,host);inspectOperationOutcomes(u,host);inspectExecutionReports(u,host);inspectWorkContext(u,host);inspectWorkLineage(u,host);inspectPlan(u,host);inspectWorkHistory(u,host);inspectResponseDelivery(u,host);inspectStatedChecks(u,host);
 const rs=state.doc.relations.filter(r=>r.from===id||r.to===id);
 if(rs.length){host.append(el('h3','Connections'));
  for(const r of rs){
   const other=r.from===id?r.to:r.from,box=el('section',undefined,'inspector-connection');
   box.append(el('p',`${unitName(r.from)} → ${relationName(r)} → ${unitName(r.to)}`,'eyebrow'),button(`Open ${unitName(other)}: ${r.requested_work_text||unit(other).content.summary.text}`,()=>inspect(other),'connection-jump'));
   const evidence=el('details');evidence.append(el('summary','Connection evidence'),el('p',r.explanation,'muted'),el('p',r.basis,'muted'));relationEvidence(r,evidence);box.append(evidence);host.append(box);
  }
 }
 inspectContext(u,host);
 const original=el('details');original.append(el('summary','Original unit and boundaries'),el('h3','Why this is one unit'),el('p',u.boundary_reason,'muted'),el('pre',u.source.text,'quote'));host.append(original);presentInspector(host,open);
}
async function load(){
 const selected=state.maps?.find(m=>m.key===$('#run').value);if(!selected)return;
 const rid=selected.run_id,observer=selected.observer, sequence=(state.loadSequence||0)+1;state.loadSequence=sequence;$('#error').hidden=true;
 try{
  const [ref,bundle]=await Promise.all([api('/api/semantic-map/'+rid+'?observer='+encodeURIComponent(observer)+'&patterns=2&plans=1'),api('/api/runs/'+rid)]);
  if(sequence!==state.loadSequence)return;
  if(!ref.available)throw Error('No semantic observation is available for this run.');
  state.doc=ref.document;state.run=bundle.run;state.revealed=null;state.observer={...ref.observer,extraction_hash:selected.extraction_hash};state.exportDigest=ref.export_digest;state.selected=state.doc.units[0]?.id||null;
  selected.observer_label=ref.observer.label;selected.task=bundle.run.metadata?.task_id||rid;
  const selectedOption=[...$('#run').options].find(o=>o.value===selected.key);if(selectedOption)selectedOption.textContent=selected.task+' · '+selected.observer_label;
  const authored=state.doc.provenance.origin==='assistant_authored_reference';
  $('#provenance-notice').textContent=authored?'Authored reference map. Rebuilt from source by the implementation assistant; not automatic extractor output or independently validated labels.':'Jev local extraction. Recorded dispatch boundaries come from the source; prose boundaries, activities and content bundles are selected by raw argmax. Each unit records its boundary origin and candidate producer. Semantic accuracy is not independently measured.';
  history.replaceState(null,'','/semantic-map?run='+rid+'&observer='+encodeURIComponent(observer));$('#raw-link').href='/#run='+rid;$('#title').textContent=state.doc.title;
  $('#provenance-notice').textContent+=' Observer: '+selected.observer_label+'. Switching observers compares annotations on the same recorded source.';
  $('#objective').textContent='Recorded initial objective: '+state.doc.objective.text;
  const instructionHistory=$('#instruction-history');instructionHistory.replaceChildren();
  const initial=state.doc.objective.evidence?.[0]?.event_id;
  for(const e of state.run.events.filter(e=>e.kind==='instruction'&&e.actor==='user'&&e.id!==initial)){
   const details=el('details',undefined,'instruction-event');details.append(el('summary',`${e.id} · Later user input`),el('p',e.text));
   if(e.text.trim())details.append(cite({event_id:e.id,source_pointer:e.source_pointer,start:0,end:e.text.length,text:e.text}));instructionHistory.append(details);
  }
  const scope=ref.validation.scope;
  const coveragePrefix=scope?`Complete selected episode ${scope.first_event_id}–${scope.last_event_id} · `:ref.validation.coverage==='selected windows only'?'Selected source windows only · ':ref.validation.participant_scope?'Complete recorded user and agent content · ':'Complete recorded agent content · ';
  $('#coverage').textContent=authored?`${ref.validation.agent_units} agent units · ${ref.validation.actions} dispatches · ${ref.validation.relations} typed relations · all recorded agent prose and dispatches accounted for. Semantic accuracy is not measured.`:`${coveragePrefix}${ref.validation.agent_units} agent contributions${ref.validation.user_units?' + '+ref.validation.user_units+' user contributions':''} · ${ref.validation.actions} dispatches · ${ref.validation.source_feedback_links||0} recorded responses. Source coverage and saved selections checked.${(ref.validation.context_policies||[]).some(p=>p!=='null')?' Each unit shows the context supplied to its inspector and any omitted evidence.':''}`;
  const exclusions=$('#scope-exclusions');exclusions.replaceChildren();
  if(state.doc.source_exclusions?.length){
   const details=el('details',undefined,'review-flag');details.append(el('summary',`${quantity(state.doc.source_exclusions.length,'source region')} explicitly outside this semantic pass`));
   for(const item of state.doc.source_exclusions){const row=el('section');row.append(el('p',item.reason),el('pre',item.source.text,'quote'),cite(item.source),el('p','Recorded basis: '+item.basis,'muted'));details.append(row);}
   exclusions.append(details);
  }
  if(ref.validation.stated_checks){
   const c=ref.validation.stated_checks,d=c.content_dispositions||{};
   if(c.applicability)$('#coverage').textContent+=` Checking applicability reviewed for ${quantity(c.units_inspected,'prose contribution')}; ${c.content_selections} advanced to content selection. ${quantity(c.checks_selected,'bundle')} selected; ${d.no_suitable_candidate||0} need better candidates; ${quantity(c.applicability_content_disagreements||0,'stage disagreement')}. ${quantity(c.units_uninspected,'contribution')} uninspected by this layer.`;
   else{$('#coverage').textContent+=` Checking contents inspected for ${c.units_inspected} prose contributions; ${c.units_uninspected} remain uninspected by that layer.`;if(c.content_dispositions)$('#coverage').textContent+=` ${d.selected||0} checking bundles selected; ${d.none||0} without selected checking work; ${d.no_suitable_candidate||0} need better candidates; ${d.unresolved||0} unresolved.`;}
  }
  if(ref.validation.check_followthrough){const c=ref.validation.check_followthrough;$('#coverage').textContent+=` Later correspondence: ${c.later_action_pairs} check/action candidates inspected; ${c.native_pairs_reused} native pairs reused. Historical correspondence does not establish current intent or completion.`;}
  if(ref.validation.response_material){const c=ref.validation.response_material;$('#coverage').textContent+=` Material form: ${c.target_response_pairs} target/response pairs; delivery mechanism: ${c.responses} responses. Original authorship and verification success are not established.`;}
  $('#plan-status').textContent=state.doc.plan_status;
  const track=$('#target-track');track.replaceChildren();
  for(const [i,t]of state.doc.targets.entries()){if(i)track.append(el('span','→'));const block=el('div',t.text,'target');block.append(el('small',i?'New immediate work target':'Initial work target'));track.append(block);}
  const notes=$('#notes');notes.replaceChildren();
  if(state.doc.method_comparison?.available)notes.append(el('p','The original source reviews below are retained from earlier passes. The procedure comparisons in Work over time and the inspector are later observations.','muted'));
  if(state.doc.review_origin)notes.append(el('p',state.doc.review_origin,'muted'));
  for(const n of state.doc.review_notes){const block=el('div',undefined,'note');block.append(el('p',n.text));for(const r of n.evidence)block.append(cite(r));notes.append(block);}
  if(!state.doc.review_notes.length)notes.append(el('p','No cross-unit diagnosis has been generated. Review the local targets, requested work and source evidence first.','muted'));
  populateFocus();render();const first=orderedUnits(state.doc,state.run).find(u=>state.search.visible.has(u.id));if(first)inspect(first.id,false);
 }catch(e){if(sequence===state.loadSequence){$('#error').textContent=e.message;$('#error').hidden=false;}}
}
async function initialize(){
 try{
  const params=new URLSearchParams(location.search),rid=params.get('run'),observer=params.get('observer');
  state.layout=params.get('layout')==='timeline'?'timeline':'blueprint';
  state.filter=params.get('show')==='actions'||params.get('view')==='actions'?'actions':'all';state.focus=params.get('focus')||'all';state.relation=params.get('relation')||'all';$('#map-search').value=params.get('q')||'';$('#include-connected').checked=params.get('connected')!=='0';$('#history-singletons').checked=params.get('targets')==='all';
  const select=$('#run'),direct=Boolean(rid&&observer);
  // The requested map is audited by its own endpoint. Auditing every other
  // saved observer first can delay an otherwise available deep link for minutes.
  if(direct){
   const seed={run_id:rid,observer,observer_label:observer,key:observer+':'+rid};state.maps=[seed];
   const option=el('option','Loading selected observer…');option.value=seed.key;select.replaceChildren(option);select.value=seed.key;
   await load();
  }
  const catalog=await api('/api/semantic-maps'),currentKey=select.value;state.maps=catalog.maps.map(m=>({...m,key:m.observer+':'+m.run_id}));
  if(catalog.unavailable?.length){const notice=$('#catalog-status');notice.hidden=false;notice.textContent=`${quantity(catalog.unavailable.length,'registered observation')} unavailable because saved evidence changed, is missing, or failed its audit. Register the intended audited version to display it.`;}
  select.replaceChildren();
  for(const m of state.maps){const option=el('option',`${m.task} · ${m.observer_label}`);option.value=m.key;select.append(option);}
  if(!state.maps.length)throw Error('No complete saved semantic maps are available.');
  if(direct&&state.maps.some(m=>m.key===currentKey)){select.value=currentKey;return;}
  const selected=rid?state.maps.find(m=>m.run_id===rid&&(!observer||m.observer===observer)):state.maps[0];
  if(!selected)throw Error('The requested run and observer have no complete saved map. Choose an available pass.');
  select.value=selected.key;await load();
 }catch(e){$('#error').textContent=e.message;$('#error').hidden=false;}
}
// Browser bindings are separate from the read-only projection functions above.
if(typeof document!=='undefined'){
 $('#map-layout').onchange=()=>{state.layout=$('#map-layout').value;render();};
 $('#map-search').oninput=applyFilters;$('#include-connected').onchange=applyFilters;
 $('#unit-filter').onchange=()=>{state.filter=$('#unit-filter').value;applyFilters();};
 $('#work-focus').onchange=()=>{state.focus=$('#work-focus').value;applyFilters();};
 $('#relation-filter').onchange=()=>{state.relation=$('#relation-filter').value;applyFilters();};
 $('#clear-search').onclick=()=>{$('#map-search').value='';applyFilters();$('#map-search').focus();};
 $('#reset-focus').onclick=()=>{state.focus='all';state.filter='all';$('#map-search').value='';$('#include-connected').checked=true;populateFocus();applyFilters();};
 $('#run').onchange=()=>{state.focus='all';state.revealed=null;load();};
 $('#history-singletons').onchange=()=>render();
 $('#export').onclick=()=>{
  if(!state.doc)return;
  if(!state.exportDigest){$('#error').textContent='Reload the map before exporting this observation.';$('#error').hidden=false;return;}
  const a=el('a');a.href='/api/semantic-map/'+encodeURIComponent(state.doc.run_id)+'?observer='+encodeURIComponent(state.observer.id)+'&patterns=2&plans=1&download=1&expected_digest='+encodeURIComponent(state.exportDigest);
  a.download='semantic-map-'+state.doc.run_id+'-'+state.observer.id+'.json';document.body.append(a);a.click();a.remove();
 };initialize();
}
if(typeof module!=='undefined')module.exports={orderedUnits,scopeThroughUnit,recordFocus,focusUnitIds,visibleUnitIds,unitConnections,visibleSequence,checkingObservations,materialObservation,relationReviewMatches,lineagesForUnit,lineageFocus,methodObservation,methodGroupSummary,declaredEvidenceUnits,declaredActionLinks};
