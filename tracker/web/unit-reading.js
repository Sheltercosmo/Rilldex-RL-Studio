/* Reading aids over saved graph edges. No adjacency-based semantic inference. */
(function(root){
 'use strict';
 const L=typeof module!=='undefined'?require('./map-layout.js'):root.RolloutMapLayout;
 const S=typeof module!=='undefined'?require('./rollout-story.js'):root.RolloutStory;
 const feedback=new Set(['feedback_for','response_to']);
 const use=new Set(['assesses','assesses_response_group','uses_evidence','responds_to','assesses_attempt_prerequisite']);
 const clean=v=>L.text(v).replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').trim();
 const ref=n=>n.kind==='plan_step'?'“'+n.properties.id+'”':'#'+n.ordinal;
 const target=e=>e.display_target||e.target;
 function content(n){
  const p=n.properties||{},raw=clean(p.source?.text||p.text);
  if(n.lane===2)return S.preview(raw||n.summary).text;
  if(n.lane===1)return S.operation(n).text;
  return n.target||n.summary;
 }
 function evidenceText(n){
  // For a semantic relation, the actual expression is more useful than a
  // target-only label: it retains qualifications and stated interpretations.
  const p=n.properties||{},raw=clean(p.source?.text||p.text);
  return n.lane===0&&raw?raw:content(n);
 }
 function sections(layout,id){
  const selected=layout.byId.get(id);if(!selected)return [];
  const groups=new Map(),direct=layout.edges.filter(e=>e.family!=='sequence'&&(e.source===id||target(e)===id));
  const add=(key,title,e,other,via=null)=>{
   if(!other)return;
   if(!groups.has(key))groups.set(key,{key,title,rows:[]});
   const rows=groups.get(key).rows;
   if(!rows.some(r=>r.edge.id===e.id&&r.via?.edge.id===via?.edge.id))rows.push({edge:e,node:other,via});
  };
  for(const e of direct){
   const other=layout.byId.get(e.source===id?target(e):e.source);if(!other)continue;
   if(['contains_call','call_input','call_output','call_exception'].includes(e.type))add('trace','Call structure',e,other);
   else if(feedback.has(e.type))add('result',selected.lane===2?'Source action':'Returned feedback',e,other);
   else if(use.has(e.type))add('use',selected.lane===2?'Agent response to this evidence':'Feedback & evidence links',e,other);
   else if(['return','verification'].includes(e.family)||['revises','changes_attempt_procedure','changes_attempt_prerequisite','uses_correction_from'].includes(e.type))add('changes','Repeated work & changes',e,other);
   else if(e.family==='plan')add('plan','Plan correspondence',e,other);
   else if(e.family==='execution')add('dispatch','Recorded contribution & action',e,other);
   else add('other','Other saved links',e,other);
  }
  // A two-edge path is displayed as two claims, never collapsed to "caused" or "fixed".
  if(selected.lane===1){
   const returns=direct.filter(e=>feedback.has(e.type)&&target(e)===id);
   if(!returns.length)groups.set('result',{key:'result',title:'Returned feedback',rows:[],empty:L.capturedResponses(layout,id).length?'Full call feedback is available below; unit pairing is unresolved.':'No response is bound to this action in the saved graph.'});
   for(const response of returns){
    const r=layout.byId.get(response.source);if(!r||r.trajectory_id!==selected.trajectory_id)continue;
    for(const e of layout.edges){
     if(!use.has(e.type)||target(e)!==r.id)continue;
     const actor=layout.byId.get(e.source);if(!actor||actor.trajectory_id!==r.trajectory_id)continue;
     add('use','Agent response to the feedback',e,actor,{node:r,edge:response});
    }
   }
   if(returns.length&&!groups.has('use'))groups.set('use',{key:'use',title:'Agent response to the feedback',rows:[],empty:'No saved assessment or evidence-use link for these responses. This does not establish that feedback was ignored.'});
  }
  if(selected.lane===2&&!groups.has('use'))groups.set('use',{key:'use',title:'Agent response to this evidence',rows:[],empty:'No saved assessment or evidence-use link. This does not establish that feedback was ignored.'});
  const order=['trace','result','use','changes','plan','dispatch','other'];
  return order.filter(k=>groups.has(k)).map(k=>groups.get(k));
 }
 function foot(layout,n){
  const edges=layout.edges.filter(e=>e.family!=='sequence'&&(e.source===n.id||target(e)===n.id));
  if(n.lane===2){
   const usages=edges.filter(e=>use.has(e.type)&&target(e)===n.id);
   if(!usages.length)return (L.capturedResponses(layout,n.id).length?'Call linked':'Output excerpt')+' · no saved use link';
   const refs=[...new Set(usages.map(e=>ref(layout.byId.get(e.source))))];
   const prefix=usages.every(e=>['assesses','assesses_response_group'].includes(e.type))?'Assessed by ':usages.every(e=>e.type==='uses_evidence')?'Used as evidence by ':'Referenced by ';
   return prefix+refs.slice(0,2).join(', ')+(refs.length>2?' +'+(refs.length-2):'');
  }
  const result=edges.find(e=>feedback.has(e.type)&&target(e)===n.id),assessment=edges.find(e=>use.has(e.type)&&e.source===n.id),repeat=edges.find(e=>e.type==='revisits_after_error_report'&&e.source===n.id),plan=edges.find(e=>e.family==='plan');
  const parts=[];
  if(result)parts.push('Response '+ref(layout.byId.get(result.source)));
  else if(n.lane===1&&L.capturedResponses(layout,n.id).length)parts.push('Call feedback available');
  if(assessment)parts.push(L.relationMeaning(assessment).label+' '+ref(layout.byId.get(target(assessment))));
  if(repeat)parts.push('Returns to '+ref(layout.byId.get(target(repeat))));
  if(!parts.length&&plan){
   const incoming={attempts_plan_step:'Attempted by',prepares_plan_step:'Prepared by',checks_plan_step:'Checked by',contains_plan_step:'Declared by'};
   parts.push((plan.source===n.id?L.relationMeaning(plan).label:incoming[plan.type]||'Plan link from')+' '+ref(layout.byId.get(plan.source===n.id?target(plan):plan.source)));
  }
  return parts.join(' · ')||(edges.length?edges.length+' saved link'+(edges.length===1?'':'s'):'No saved links');
 }
 function sentence(layout,e){
  const from=layout.byId.get(e.source),to=layout.byId.get(target(e));
  return [ref(from),L.relationMeaning(e).label.toLowerCase(),ref(to)].join(' ');
 }
 function primaryLink(layout,id,visible){
  // Prioritize the result and its interpretation over context and duplicate work identity.
  // This orders existing links for reading; it is not a salience or quality score.
  const rows=sections(layout,id).flatMap(g=>g.rows).filter(r=>!r.via&&(!visible||visible.has(r.edge.family)));
  return rows[0]?.edge||null;
 }
 function connection(layout,e){
  if(!e||e.family==='sequence')return null;
  const from=layout.byId.get(e.source),to=layout.byId.get(target(e));
  if(!from||!to)return null;
  const questions={
   feedback_for:'What did the action return?',response_to:'What did the action return?',
   assesses:'How did the agent interpret this feedback?',assesses_response_group:'How did the agent interpret this feedback?',
   uses_evidence:'Which evidence did the agent use?',responds_to:'What is the agent responding to?',
   revises:'What earlier proposal changed?',revisits_after_error_report:'Which work did the agent retry?',
   same_action_target:'Are these attempts addressing the same target?',same_procedure:'Did the procedure change?',
   reconfigured_procedure:'Which attempt used different settings?',alternative_procedure:'Which attempt tried a different procedure?',
   uses_correction_from:'Where did this correction come from?',recorded_recheck_of:'Which earlier check was repeated?',
   attempts_plan_step:'Which planned step was attempted?',prepares_plan_step:'Which planned step was prepared?',
   checks_plan_step:'Which planned step was checked?',contains_plan_step:'What step did the agent declare?',
   recorded_with:'Which action was recorded with this contribution?',parent_message:'Which action belongs to this message?',
   same_work_target:'Do these units address the same work?',overlapping_work_scope:'Where does their work overlap?',
   in_work_context:'What earlier work provides context?'
  };
  const meaning=L.relationMeaning(e);
  // Preserve stored direction: feedback points to its action, and assessment
  // points to feedback. A reader must not mistake this for chronological flow.
  return {edge:e,from,to,label:meaning.label,meaning:meaning.meaning,
   question:questions[e.type]||'What relationship is recorded?',
   direction:ref(from)+' → '+ref(to),sentence:sentence(layout,e)};
 }
 function cardText(n){
  // Keep the observed statement (including qualifications) visible. A target
  // alone loses the difference between intending, interpreting and reporting.
  return n.lane===0?n.summary||n.target:content(n);
 }
 function inventory(layout,coverage={}){
  const valid=layout.edges.filter(e=>e.family!=='sequence'&&layout.byId.has(e.source)&&layout.byId.has(target(e))&&layout.byId.get(e.source).trajectory_id===layout.byId.get(target(e)).trajectory_id);
  const actions=layout.nodes.filter(n=>n.lane===1),responses=layout.nodes.filter(n=>n.lane===2);
  const responseRows=responses.map(n=>({node:n,links:valid.filter(e=>use.has(e.type)&&target(e)===n.id)}));
  const retryRows=actions.map(n=>({node:n,links:valid.filter(e=>e.type==='revisits_after_error_report'&&e.source===n.id)})).filter(r=>r.links.length);
  const planTypes=new Set(['attempts_plan_step','prepares_plan_step','checks_plan_step','attempts_declared_work','prepares_declared_work','checks_declared_work']);
  const planRows=actions.map(n=>({node:n,links:valid.filter(e=>planTypes.has(e.type)&&e.source===n.id)}));
  const linkedResponses=responseRows.filter(r=>r.links.length).length,linkedActions=planRows.filter(r=>r.links.length).length;
  const groups=[
   {id:'feedback',label:'Feedback referenced',value:linkedResponses+' / '+responses.length,
    question:'Which feedback did the agent assess or reference?',
    note:linkedResponses+' of '+responses.length+' returned-feedback cards have saved assessment or evidence-reference links. Missing links do not establish ignored feedback.',
    rows:responseRows,missing:'No saved assessment or evidence-reference link',linked:'Saved assessment / reference'},
   {id:'retries',label:'Recorded retries',value:String(retryRows.length),
    question:'Where did the agent retry earlier work?',
    note:retryRows.length+' actions have explicit retry-after-error links. Same-target and source-order links are excluded; a retry does not establish recovery.',
    rows:retryRows,missing:'No saved retry-after-error links',linked:'Earlier attempt'},
   {id:'plans',label:'Actions linked to work',value:linkedActions+' / '+actions.length,
    question:'Which actions attempt, prepare or check declared work?',
    note:linkedActions+' of '+actions.length+' action cards have a saved correspondence to declared work or a plan step. Unlinked actions are not evidence of deviation.',
    rows:planRows,missing:'No saved work correspondence',linked:'Declared work / plan step'}
  ];
  for(const group of groups){
   // A graph with one semantic layer does not establish coverage of another.
   // In particular, feedback annotations cannot turn absent retry/work links
   // into measured zeros. These are evidence inventories, not behavior rates.
   const hasLinks=group.rows.some(r=>r.links.length);
   group.evidence_status=hasLinks?'saved_links':'no_saved_links';
   group.status_label=hasLinks?'Saved evidence':'Not established';
   if(!hasLinks){
    group.value='—';
    group.note='No matching links are saved. This does not establish zero occurrences or that this relationship layer was measured. '+group.note;
    if(coverage.semantic_relations==='unavailable')group.note='Semantic observations are unavailable in this graph. '+group.note;
   }
  }
  return groups;
 }
 const api={content,evidenceText,sections,foot,sentence,ref,primaryLink,connection,cardText,inventory};
 if(typeof module!=='undefined')module.exports=api;else root.UnitReading=api;
})(typeof globalThis!=='undefined'?globalThis:this);
