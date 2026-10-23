/* Review repeated work from saved identities and exact graph witnesses. No inference. */
(function(root){
 'use strict';
 const T=typeof module!=='undefined'?require('./work-timeline.js'):root.WorkTimeline;
 const S=typeof module!=='undefined'?require('./rollout-story.js'):root.RolloutStory;
 const value=v=>typeof v==='string'?v:v?.text||'';
 const raw=n=>n?.kind==='event'?n.properties?.text:n?.properties?.source?.text;
 const summary=n=>value(n?.properties?.content?.summary)||raw(n)||'Source text unavailable';
 const feedbackTypes=new Set(['feedback_for','response_to']);
 const responseTypes=new Set(['assesses','uses_evidence','responds_to']);
 function comparisonFor(data,observations,episode){
  const absent=reason=>({dispatch:'unavailable',feedback:'unavailable',record:null,reason});
  if(!observations||observations.schema!=='repeated-work-comparisons/1'||!['graph_id','run_id','source_hash'].every(k=>data[k]&&data[k]===observations[k]))return absent('No recorded-input comparison for this saved graph.');
  const matches=observations.rows.filter(r=>r.episode?.id===episode?.id&&r.previous_node_id===episode?.previous_unit_id&&r.current_node_id===episode?.current_unit_id);
  if(matches.length!==1)return absent('This exact earlier/later pair has no unique saved comparison.');
  const record=matches[0];
  return {dispatch:record.inputs_changed===null?'unavailable':record.dispatch.status,feedback:record.feedback.status,record,reason:record.input_reasons.join(' · ')};
 }
 function project(data,graph,scopeAudit=null,procedureObservations=null,inputComparisons=null){
  const empty=reason=>({available:false,reason,targets:[],excluded_paths:0});
  if(!graph||!['run_id','source_hash'].every(k=>data[k]&&data[k]===graph[k])||data.graph_id!==graph.id)return empty('Work and source evidence must belong to the same saved graph.');
  if(data.axis==='contributions')return empty('This review compares dispatched actions. Use the timeline for contribution-level work.');
  const nodes=new Map(),duplicate=new Set(),incoming=new Map(),outgoing=new Map();
  for(const n of graph.nodes){if(nodes.has(n.id))duplicate.add(n.id);nodes.set(n.id,n);}
  const get=id=>duplicate.has(id)?null:nodes.get(id);
  for(const e of graph.edges){if(!incoming.has(e.target))incoming.set(e.target,[]);incoming.get(e.target).push(e);if(!outgoing.has(e.source))outgoing.set(e.source,[]);outgoing.get(e.source).push(e);}
  const responseKey=f=>get('event:'+f.properties?.source?.event_id)?.id||f.id,feedbackAliases=new Map();
  for(const f of graph.nodes)if(f.kind==='unit'&&f.properties?.kind==='feedback'){
   const key=responseKey(f);if(!feedbackAliases.has(key))feedbackAliases.set(key,[]);feedbackAliases.get(key).push(f);
  }
  const sameTrace=(a,b)=>a&&b&&a.trajectory_id!=null&&a.trajectory_id===b.trajectory_id;
  const ref=n=>({id:n.id,record:Number.isSafeInteger(n.event_index)?n.event_index+1:null,text:summary(n),raw:raw(n),source:n.properties?.source||null});
  function action(point,trajectory){
   const candidate=get(point.occurrence.unit_id),n=candidate?.trajectory_id===trajectory?candidate:null,responses=[];
   if(n?.kind==='unit'&&n.properties?.kind==='action'){
    const collected=new Map(),sourceId=n.properties.source?.event_id,source=get('event:'+sourceId);
    const targets=new Set([n.id]);if(source?.kind==='event')targets.add(source.id);
    const scope=n=>n?.properties?.context_id??get('event:'+n?.properties?.source?.event_id)?.properties?.context_id;
    for(const target of targets)for(const e of incoming.get(target)||[]){
     const candidate=get(e.source);if(!feedbackTypes.has(e.type)||candidate?.properties?.kind!=='feedback'||!sameTrace(n,candidate)||scope(n)!==scope(candidate))continue;
     const key=responseKey(candidate),f=get(key)||candidate;
     if(!collected.has(key))collected.set(key,{...ref(f),preview:S.preview(raw(f)||''),edges:[],references:[],shared:false,aliases:new Set([key])});
     const r=collected.get(key);r.edges.push(e.id);r.aliases.add(candidate.id);
    }
    for(const r of collected.values()){
     // References may target a source record or a fragment of that record.
     for(const f of feedbackAliases.get(r.id)||[])if(sameTrace(n,f))r.aliases.add(f.id);
     const refs=new Map();for(const alias of r.aliases){
      r.shared ||= (outgoing.get(alias)||[]).some(l=>feedbackTypes.has(l.type)&&!targets.has(l.target)&&(!get(l.target)||!targets.has(responseKey(get(l.target)))));
      for(const e of incoming.get(alias)||[]){const c=get(e.source);if(!responseTypes.has(e.type)||c?.kind!=='unit'||c.properties?.kind!=='semantic'||!sameTrace(c,n)||scope(n)!==scope(c))continue;
       if(!refs.has(c.id))refs.set(c.id,{...ref(c),edges:[],relations:[]});const x=refs.get(c.id);x.edges.push(e.id);if(!x.relations.includes(e.type))x.relations.push(e.type);
      }
     }
     delete r.aliases;r.references=[...refs.values()].sort((a,b)=>(a.record??Infinity)-(b.record??Infinity));responses.push(r);
    }
   }
   return {id:point.occurrence.unit_id||point.id,point,intent:value(point.occurrence.target)||value(point.visit.target)||'Work target not recorded',record:n&&Number.isSafeInteger(n.event_index)?n.event_index+1:null,available:!!n&&n.kind==='unit'&&n.properties?.kind==='action',
    operation:n?S.operation(n).text:'Action source unavailable',raw:n?raw(n):null,responses:responses.sort((a,b)=>(a.record??Infinity)-(b.record??Infinity))};
  }
  const projected=T.project(data,{scopeAudit,procedureObservations}),targets=[];
  for(const path of projected.paths.filter(p=>p.available)){
   const actions=new Map(path.points.map(p=>[p.id,action(p,path.path.trajectory_id)]));
   for(const row of path.rows){
    if(!row.group_id||row.disputed||row.points.length<2)continue;
    const steps=row.points.map(p=>actions.get(p.id)).sort((a,b)=>a.point.position-b.point.position),ids=new Set(row.points.map(p=>p.id));
    const pairs=path.pairs.filter(p=>ids.has(p.before)&&ids.has(p.after)).map(p=>{
     const a=actions.get(p.before),b=actions.get(p.after),ordered=a.point.order_known&&b.point.order_known&&p.category!=='interrupted';
     const episode=data.episodes.find(e=>e.id===p.link.episode_id),saved=comparisonFor(data,inputComparisons,episode);
     const usable=ordered&&a.available&&b.available;
     const errorEdges=(incoming.get(a.id)||[]).filter(e=>e.type==='revisits_after_error_report'&&e.source===b.id);
     return {...p,previous:a.id,current:b.id,ordered,dispatch:usable?saved.dispatch:'unavailable',input_comparison:usable?saved.record:null,comparison_reason:saved.reason,
      feedback:usable?saved.feedback:'unavailable',error_edges:ordered&&a.available&&b.available?errorEdges.map(e=>e.id):[],
      between:path.points.filter(q=>q.position>a.point.position&&q.position<b.point.position).map(q=>actions.get(q.id)).sort((a,b)=>a.point.position-b.point.position)};
    });
    const count={actions:steps.length,feedback:steps.filter(s=>s.responses.length).length,references:steps.filter(s=>s.responses.some(r=>r.references.length)).length,
     pairs:pairs.length,after_error:pairs.filter(p=>p.error_edges.length).length,dispatch_compared:pairs.filter(p=>p.dispatch!=='unavailable').length,
     dispatch_changed:pairs.filter(p=>p.dispatch==='changed').length,exact_repeats:pairs.filter(p=>p.dispatch==='unchanged'&&p.feedback==='unchanged').length,
     procedure_compared:pairs.filter(p=>p.comparison.key!=='unresolved').length,procedure_changed:pairs.filter(p=>['reconfigured_procedure','alternative_procedure'].includes(p.comparison.key)).length,
     procedure_unresolved:pairs.filter(p=>p.comparison.key==='unresolved').length};
    const nextPoint=path.points.filter(p=>p.position>steps.at(-1).point.position).sort((a,b)=>a.position-b.position)[0];
    targets.push({id:row.visits[0].id,target:row.target,path:path.path,group_id:row.group_id,steps,pairs,count,followups:T.followupCounts(pairs),next:nextPoint?actions.get(nextPoint.id):null,first:steps[0].point.position,last:steps.at(-1).point.position});
   }
  }
  targets.sort((a,b)=>b.count.actions-a.count.actions||a.first-b.first||a.id.localeCompare(b.id));
  return {available:true,graph_id:graph.id,run_id:graph.run_id,source_hash:graph.source_hash,targets,excluded_paths:projected.unavailable_paths};
 }
 const matches=(r,filter)=>filter==='errors_again'?r.followups?.reported_again>0:filter==='after_error'?r.count.after_error>0:filter==='exact_repeat'?r.count.exact_repeats>0:filter==='missing_feedback'?r.count.feedback<r.count.actions:true;
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 function renderReason(host,reason,unitButton){
  if(!reason||reason.status==='unavailable')return;
  const box=el('div',null,'wr-stated-reason');
  if(reason.status==='selected'&&reason.node_id&&typeof reason.text==='string'){
   box.append(el('small',"Agent's stated reason"),el('p',reason.text.length>320?reason.text.slice(0,320)+'…':reason.text),unitButton(reason.node_id,'Inspect stated reason'));
  }else box.append(el('small',reason.label));
  host.append(box);
 }
 function renderErrorFollowup(host,followup,unitButton){
  if(!followup||followup.category==='unknown')return;
  const box=el('div',null,'wr-executor-followup '+(followup.category==='reported_again'?'wr-error':''));
  box.append(el('strong',followup.label));
  const labels={reported:'Error reported',not_reported:'Inspected; no error reported',unresolved:'Report unresolved'};
  for(const [key,name]of [['previous','Earlier'],['current','Later']]){
   const side=followup[key],row=el('div');row.append(el('span',name+': '+labels[side.status]));
   for(const observation of side.observations){const ids=observation.unit_ids?.length?observation.unit_ids:[observation.node_id];for(const [i,id]of ids.entries())row.append(unitButton(id,'Inspect '+name.toLowerCase()+' response'+(ids.length>1?' · unit '+(i+1)+'/'+ids.length:'')));}
   box.append(row);
  }
  box.append(el('small','Executor diagnostics, not a task-success verdict.'));host.append(box);
 }
 const procedureCoverage=count=>count.pairs?`${count.procedure_compared}/${count.pairs} procedure comparisons established${count.procedure_compared?' · '+count.procedure_changed+' changed':''}${count.procedure_unresolved?' · '+count.procedure_unresolved+' unresolved':''}`:'No saved recurrence pairs to compare';
 function renderFollowupSummary(host,counts){
  const text=T.followupText(counts);if(!text)return;
  const box=el('div',null,'wr-followup-summary');box.append(el('span',text.main),el('span',text.coverage));host.append(box);
 }
 function render(host,model,{selected=null,filter='all',onSelect=()=>{},onFilter=()=>{},onUnit=()=>{},onPair=()=>{},onTimeline=()=>{}}={}){
  host.replaceChildren();host.classList.add('wr-review');
  if(!model.available){host.append(el('p',model.reason,'wn-note'));return;}
  const heading=el('div',null,'wr-heading');heading.append(el('h3','Where did work repeat?'),el('p','Compare what was tried, what came back, and how the agent responded. Targets are ordered by recorded action count.'));host.append(heading);
  const tools=el('div',null,'wr-tools'),label=el('label','Show '),select=el('select');select.setAttribute('aria-label','Repeated work filter');
  for(const [v,title]of [['all','All repeated targets'],['errors_again','Errors on both attempts'],['after_error','Returns after reported errors'],['exact_repeat','Matching inputs & feedback'],['missing_feedback','Missing feedback links']]){const o=el('option',title);o.value=v;select.append(o);}select.value=filter;select.onchange=()=>onFilter(select.value);label.append(select);tools.append(label,el('span',`${model.targets.filter(r=>matches(r,filter)).length} of ${model.targets.length} repeated targets`));host.append(tools);
  if(model.excluded_paths)host.append(el('p',`${model.excluded_paths} routes excluded because their occurrence positions or membership are incomplete.`,'wr-missing'));
  const cards=el('div',null,'wr-targets');
  for(const r of model.targets.filter(r=>matches(r,filter))){const b=el('button',null,'wr-target');b.type='button';b.dataset.reviewTarget=r.id;b.setAttribute('aria-pressed',String(selected===r.id));
   const counts=el('div',null,'wr-counts');counts.append(el('strong',`${r.count.actions} actions`));if(r.count.after_error)counts.append(el('span',`${r.count.after_error} ${r.count.after_error===1?'return':'returns'} after error reports`,'wr-error'));
   b.append(counts,el('span',r.target,'wr-name'));const last=r.steps.at(-1),out=last.responses.map(f=>f.preview.text).join(' · ');b.append(el('small',`Latest feedback · action ${last.point.position}`),el('span',out||'No feedback linked to the latest action.','wr-preview'));
   b.append(el('span',`${r.count.dispatch_compared?r.count.dispatch_changed+'/'+r.count.dispatch_compared+' compared dispatches changed':'Dispatch comparison unavailable'} · ${r.count.feedback}/${r.count.actions} actions have feedback`,'wr-meta'));
   b.append(el('span',procedureCoverage(r.count),'wr-meta'));
   renderFollowupSummary(b,r.followups);
   if(r.count.exact_repeats)b.append(el('span',`${r.count.exact_repeats} ${r.count.exact_repeats===1?'pair repeats':'pairs repeat'} captured inputs & feedback`,'wr-match'));
   b.onclick=()=>onSelect(r.id);cards.append(b);
  }
  host.append(cards);
  if(!cards.childElementCount)host.append(el('p',model.targets.length?'No repeated targets match this filter.':'No repeated action targets are established in this observation. The timeline retains all recorded work.','wr-missing'));
  const chosen=model.targets.find(r=>r.id===selected&&matches(r,filter));
  if(chosen){
   heading.hidden=true;tools.hidden=true;cards.hidden=true;
   const nav=el('div',null,'wr-target-nav'),back=el('button','← All targets');back.onclick=()=>onSelect(null);const pick=el('select');pick.setAttribute('aria-label','Review work target');
   for(const target of model.targets.filter(r=>matches(r,filter))){const option=el('option',`${target.count.actions} actions · ${target.target}`);option.value=target.id;pick.append(option);}pick.value=chosen.id;pick.onchange=()=>onSelect(pick.value);nav.append(back,pick);host.append(nav);
   const section=el('section',null,'wr-sequence');section.setAttribute('aria-label','Repeated work evidence');const title=el('div',null,'wr-sequence-title'),copy=el('div');copy.append(el('small','SELECTED WORK'),el('h3',chosen.target),el('p',`${chosen.count.actions} actions · ${chosen.count.feedback?chosen.count.references+'/'+chosen.count.feedback+' actions with feedback have a saved agent reference':'No feedback links saved'}`));
   const timeline=el('button','Locate in timeline');timeline.onclick=()=>onTimeline(chosen.id);title.append(copy,timeline);section.append(title);
   section.append(el('p',procedureCoverage(chosen.count),'wr-coverage'));
   renderFollowupSummary(section,chosen.followups);
   if(chosen.path.actor||chosen.path.trajectory_id)section.append(el('p',`Trajectory ${chosen.path.trajectory_id||'unknown'}${chosen.path.actor?' · '+chosen.path.actor:''} · positions are action order, not duration.`,'wr-meta'));
   const columns=el('div',null,'wr-columns');for(const text of ['Action','Returned feedback','Agent response to feedback'])columns.append(el('span',text));section.append(columns);
   const unitButton=(id,text,cls='wr-evidence')=>{const b=el('button',text,cls);b.type='button';b.onclick=()=>onUnit(id);return b;};
   for(const step of chosen.steps){
    const pairs=chosen.pairs.filter(p=>p.current===step.id);
    for(const pair of pairs){
     const band=el('div',null,'wr-between'),prev=chosen.steps.find(s=>s.id===pair.previous);band.append(el('strong',`Action ${prev.point.position} → ${step.point.position}`));
     const method=el('div',null,'wr-procedure '+pair.comparison.className),review=pair.comparison.key!=='unresolved'?pair.comparison.record?.episode?.method?.review:null;
     method.append(el('strong',pair.comparison.label),el('span',review?.note||pair.comparison.reason));if(review?.author)method.append(el('small','Source review · '+review.author));band.append(method);
     renderReason(band,pair.comparison.record?.stated_reason,unitButton);
     renderErrorFollowup(band,pair.comparison.record?.error_followup,unitButton);
     band.append(el('span',!pair.ordered?'Order or coverage unresolved':pair.dispatch==='unchanged'?'Recorded inputs unchanged':pair.dispatch==='changed'?'Recorded inputs changed':'Dispatch comparison unavailable'));
     if(pair.input_comparison){
      const d=pair.input_comparison.dispatch;band.append(el('small',d.basis==='recorded_fields'?'Compared native tool and arguments':'Compared full captured action text'));
      if(d.changes.length){const diff=el('details',null,'wr-input-diff');diff.append(el('summary','Input differences'));
       for(const change of d.changes){diff.append(el('strong',change.path||'Input'));for(const [label,v]of [['Earlier',change.before],['Later',change.after]])diff.append(el('small',label),el('pre',v.present?v.preview:'Not captured'));}
       if(d.changes_truncated||d.changes.some(c=>c.before.truncated||c.after.truncated))diff.append(el('small','Preview shortened; open the source action for full inputs.'));band.append(diff);}
     }else if(pair.comparison_reason)band.append(el('small',pair.comparison_reason));
     if(pair.error_edges.length)band.append(el('span','Saved return after error report','wr-error'));
     if(pair.feedback==='unchanged')band.append(el('span','Exact feedback text also repeats','wr-match'));
     else if(pair.feedback==='changed')band.append(el('span','Recorded feedback changed'));
     else band.append(el('span','Feedback comparison unavailable'),el('small',(pair.input_comparison?.feedback.reasons||[]).join(' · ')));
     const compare=el('button','Compare pair');compare.onclick=()=>onPair(pair.link);band.append(compare);
     if(pair.between.length){
      const bridge=el('div',null,'wr-bridge');bridge.append(el('small',`${pair.between.length} intervening action${pair.between.length===1?'':'s'} · recorded sequence, not a causal explanation`));
      const list=el('ol');
      const add=(host,a)=>{const item=el('li'),text=`Action ${a.point.position} · ${a.intent}${a.point.order_known?'':' · execution order unresolved'}`;item.append(a.available?unitButton(a.id,text):el('span',text+' · source unavailable'));host.append(item);};
      for(const a of pair.between.slice(0,4))add(list,a);bridge.append(list);
      if(pair.between.length>4){const d=el('details'),rest=el('ol');d.append(el('summary',`Show ${pair.between.length-4} more intervening actions`));for(const a of pair.between.slice(4))add(rest,a);d.append(rest);bridge.append(d);}band.append(bridge);
     }else band.append(el('small','No intervening action positions.'));
     section.append(band);
    }
    const row=el('article',null,'wr-step'),a=el('div',null,'wr-action'),f=el('div',null,'wr-feedback'),u=el('div',null,'wr-response');a.append(el('small',`ACTION ${step.point.position}${step.record?' · RECORD '+step.record:''}${step.point.order_known?'':' · order unresolved'}`),el('h4',step.intent),el('p',step.operation));if(step.available)a.append(unitButton(step.id,'Inspect action'));
    const references=new Map();
    for(const response of step.responses){const box=el('div');box.append(el('small',response.preview.label+(response.shared?' · shared response':'')),el('p',response.preview.text),unitButton(response.id,'Inspect feedback'+(response.record?' · record '+response.record:'')));f.append(box);
     for(const ref of response.references){if(!references.has(ref.id))references.set(ref.id,{...ref,feedback:[]});references.get(ref.id).feedback.push(response.record);}
    }
    if(!step.responses.length)f.append(el('p','No feedback link saved.','wr-missing'));
    for(const ref of references.values()){const box=el('div');box.append(el('small',ref.relations.map(t=>({assesses:'ASSESSMENT',uses_evidence:'EVIDENCE USE',responds_to:'RESPONSE'})[t]).join(' · ')),el('p',ref.text),unitButton(ref.id,'Inspect reference'+(ref.record?' · record '+ref.record:'')));
     const next=chosen.steps[chosen.steps.indexOf(step)+1];if(next?.record&&ref.record>=next.record)box.append(el('small','Recorded at or after the next action on this target.'));u.append(box);
    }
    if(!references.size)u.append(el('p','No assessment or evidence-use link saved.','wr-missing'));
    a.dataset.label='Action';f.dataset.label='Returned feedback';u.dataset.label='Agent response to feedback';row.append(a,f,u);section.append(row);
   }
   const follow=el('div',null,'wr-follow');follow.append(el('small','WHAT FOLLOWED'));
   if(chosen.next){const next=chosen.next;follow.append(el('p',`Next recorded action ${next.point.position} · ${next.point.visit.target}${next.point.order_known?'':' · execution order unresolved'}`),unitButton(next.id,next.operation));
    for(const f of next.responses){follow.append(el('p',f.preview.text),unitButton(f.id,'Inspect following feedback'));}
    follow.append(el('small','Source sequence only; this does not establish that the target was completed.'));
   }else follow.append(el('p','No later action is present in this route. Completion is not established by the trace ending.'));
   section.append(follow,el('p','Agent responses are claims. Matching text does not establish unchanged environment state or wasted effort. No saved reference does not mean feedback was ignored. Open evidence to inspect the full source and relationship.','wr-limit'));host.append(section);
  }else if(model.targets.some(r=>matches(r,filter)))host.append(el('p','Select a target to compare its complete action–feedback sequence and the work between returns.','wr-select-hint'));
  host.append(el('p','Counts describe this saved observation. Error returns require explicit links; repeated work alone is not a failure. Feedback excerpts are previews, not success judgments.','wr-limit'));
 }
 const api={project,matches,render,comparisonFor,renderReason,renderErrorFollowup};if(typeof module!=='undefined')module.exports=api;else root.WorkReview=api;
})(typeof globalThis!=='undefined'?globalThis:this);
