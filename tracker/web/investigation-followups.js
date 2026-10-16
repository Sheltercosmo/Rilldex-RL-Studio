'use strict';
const InvestigationFollowups = (() => {
 const labels={supports:'Supports hypothesis',contradicts:'Contradicts hypothesis',inconclusive:'Inconclusive',not_run:'Not run'};
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 const button=(text,fn,cls)=>{const b=el('button',text,cls);b.type='button';b.onclick=fn;return b;};
 const url=(id,panel='checks')=>'/investigate?'+new URLSearchParams({saved:id,panel});
 const comparisonUrl=id=>url(id,'comparison')+'&return_to='+encodeURIComponent(location.pathname+location.search);
 let dialogId=0;
 const link=(text,href)=>{const a=el('a',text);a.href=href;return a;};
 async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);const data=await r.json();if(!r.ok)throw Error(data.error||'Request failed');return data;}
 function field(form,label,{value='',required=true,short=false,placeholder=''}={}){
  const wrap=el('label',label),input=el(short?'input':'textarea');input.setAttribute('aria-label',label);input.value=value;input.required=required;input.maxLength=short?160:6000;input.placeholder=placeholder;if(!short)input.rows=3;wrap.append(input);form.append(wrap);return input;
 }
 function choice(form,label,options){const wrap=el('label',label),select=el('select');select.setAttribute('aria-label',label);for(const [value,text]of options){const o=el('option',text);o.value=value;select.append(o);}wrap.append(select);form.append(wrap);return select;}
 function dialog(title){
  const d=el('dialog',null,'if-dialog'),head=el('div',null,'if-dialog-head'),body=el('div',null,'if-dialog-body');
  const heading=el('h2',title);heading.id='followup-dialog-heading-'+(++dialogId);d.setAttribute('aria-labelledby',heading.id);
  head.append(heading,button('Close',()=>d.close()));d.append(head,body);d.addEventListener('close',()=>d.remove());document.body.append(d);d.showModal();return{d,body};
 }
 function describe(parent,label,value){if(!value)return;const part=el('div',null,'if-description');part.append(el('small',label),el('p',value));parent.append(part);}
 const procedureLabels={same_procedure:'Same dispatched procedure',reconfigured_procedure:'Changed explicit settings or payload',alternative_procedure:'Different procedure',unresolved:'Unresolved'};
 const evaluationPurpose={reward:'Reward evaluation',independent_check:'Independent check (reported)',repair_check:'Repair check'};
 const evaluationStatus={agreement:'Verdicts agree',disagreement:'Verdicts disagree',different_source:'Different rollout or source revision',different_inputs:'Different declared inputs',missing_inputs:'Input revisions missing',execution_error:'Evaluation execution error',unresolved:'Check incomplete or verdict unknown'};
 function evaluationComparison(parent,pair){
  const current=pair.schema==='evaluation-comparison/2';const box=el('section',null,'if-case-row');box.append(el('strong',current?(evaluationStatus[pair.status]||pair.status):'Earlier comparison · criterion scope not checked'));
  for(const row of pair.observations)box.append(el('p',`${row.label}: ${row.verdict} · ${row.execution}${row.score==null?'':' · score '+row.score}`));
  if(pair.missing_inputs.length)box.append(el('small','Missing: '+pair.missing_inputs.map(x=>x.replaceAll('_',' ')).join(', ')));
  if(pair.different_inputs.length)box.append(el('small','Changed: '+pair.different_inputs.map(x=>x.replaceAll('_',' ')).join(', ')));
  if(current&&['agreement','disagreement'].includes(pair.status))box.append(el('small','Same declared task, criterion, artifact, environment and output boundary. '+(pair.evaluator_changed?'Evaluator definition changed.':'Same evaluator definition; independent implementation is not established.')));
  box.append(el('small','Producer-reported evidence. Disagreement does not establish reward hacking or its cause.'));parent.append(box);
 }
 window.openProcedureReview=async episode=>{
  const {d,body}=dialog('Review the procedure comparison'),error=el('p',null,'if-error');error.setAttribute('role','alert');body.append(error);
  try{
   const data=await api('/api/procedure-reviews?'+new URLSearchParams({graph:episode.graph_id,previous:episode.previous_unit_id,current:episode.current_unit_id}));if(!d.isConnected)return;
   body.append(el('p','Compare how the two actions are dispatched. Intervening file edits or dependency changes remain separate context. This saves a named review in a new graph; it makes no model call.','if-muted'));
   const pair=el('div',null,'if-procedure-pair');
   for(const [id,label]of [[episode.previous_unit_id,'Earlier dispatch'],[episode.current_unit_id,'Later dispatch']]){
    const c=data.episode.cards.find(c=>c.unit_id===id),part=el('section');part.append(el('h3',label+' · '+c.event_id),el('pre',c.text));pair.append(part);
   }body.append(pair);
   const context=el('details');context.append(el('summary','Inspect the intervening context'),window.renderWorkEpisode(data.episode,null,{review:false}));body.append(context);
   const form=el('form',null,'if-form');body.append(form);
   const previous=data.document.reviews.find(r=>r.previous_unit_id===episode.previous_unit_id&&r.current_unit_id===episode.current_unit_id);
   const selected=choice(form,'Procedure relationship',[['','Choose from the evidence…'],...Object.keys(data.choices).map(k=>[k,procedureLabels[k]])]);selected.required=true;selected.value=previous?.comparison||'';
   const definition=el('p',selected.value?data.choices[selected.value]:'Choose a relationship to see its inclusion rule.','if-muted');form.append(definition);selected.onchange=()=>{definition.textContent=data.choices[selected.value]||'';};
   const author=field(form,'Reviewer',{short:true,value:previous?.review.author||data.document.revision.author||''}),note=field(form,'Source-based explanation',{value:previous?.review.note||'',placeholder:'Describe what the dispatches show. Keep changed files and outcomes separate.'});author.maxLength=240;note.maxLength=2400;
   const save=el('button','Save reviewed graph','primary');save.type='submit';form.append(el('p',data.limit,'if-muted'),save);
   form.onsubmit=async event=>{event.preventDefault();save.disabled=true;error.textContent='';try{
    const row={previous_unit_id:episode.previous_unit_id,current_unit_id:episode.current_unit_id,comparison:selected.value,review:{author:author.value,note:note.value}};
    const document={...data.document,reviews:[...data.document.reviews.filter(r=>r.previous_unit_id!==row.previous_unit_id||r.current_unit_id!==row.current_unit_id),row],revision:row.review};
    const result=await api('/api/procedure-reviews',document);form.replaceChildren(el('p','Reviewed graph saved. Existing cases, findings and measurements retain their original evidence.'));
    const links=el('div',null,'if-actions');for(const [label,href]of [
     ['Open reviewed map','/semantic-map?'+new URLSearchParams({run:result.run_id,graph:result.graph_id,observer:result.observer,level:'work',return_to:location.pathname+location.search})],
     ['Compare reviewed behavior','/investigate?'+new URLSearchParams({run:result.run_id,observer:result.observer,panel:'process',return_to:location.pathname+location.search})]]){
     const a=link(label+' (new tab)',href);a.target='_blank';a.rel='noopener';links.append(a);
    }form.append(links);
   }catch(e){error.textContent=e.message;save.disabled=false;}};
  }catch(e){error.textContent=e.message;}
 };
 function trainingEvidence(parent,s){
  parent.append(el('p',`${s.counts.bound_samples} bound ${s.counts.bound_samples===1?'sample':'samples'} · ${s.counts.returned_samples} ${s.counts.returned_samples===1?'candidate':'candidates'}`,'if-question'),el('p','Recorded membership is not parameter influence. Missing use remains unknown.','if-muted'));
  if(!s.completeness.complete)parent.append(el('p','Lookup limits reached. Counts cover the returned, fully read samples only. Narrow the experiment with the API for further inspection.','if-warning'));
  if(!s.counts.returned_samples)parent.append(el('p','No sample declaration is pinned to this source revision. Training use is unknown; this does not mean the rollout was rejected or unused.','if-empty'));
  for(const c of s.cohorts){
   const card=el('section',null,'if-case-row');card.append(el('strong',`${c.experiment} · ${c.split==='train'?'Training':'Evaluation'} · ${c.schema==='training-records/2'?'independent samples':'rollout samples'}`));
   const rates=el('div',null,'if-rates if-use-rates');for(const [label,count,receipts]of [['Backward',c.samples_with_backward,c.backward_receipts],['Optimizer',c.samples_with_optimizer,c.optimizer_receipts]]){
    const item=el('div');item.append(el('small',label+' membership'),el('strong',`${count} / ${c.bound_samples}`),el('span',`${receipts} ${receipts===1?'receipt':'receipts'} · ${count===1?'sample':'samples'} counted once`));rates.append(item);
   }card.append(rates,el('small',`Positive backward mask recorded: ${c.samples_with_positive_backward_mask} / ${c.bound_samples} samples. Stages are not additive.`));parent.append(card);
  }
  for(const [index,row]of s.samples.entries()){
   const task=row.records.find(r=>r.kind==='sample')?.data.task_id;
   const label=row.display_name&&row.display_name!==row.sample_id?row.display_name:task?task+' · sample '+(index+1):'Sample '+(index+1);
   const card=el('details',null,'if-case-row');card.append(el('summary',`${label} · ${row.bound?'Bound source':'Unresolved binding'}`));
   describe(card,'Source mapping',row.binding.replaceAll('_',' '));
   if(row.bound)describe(card,'Scope',row.binding==='exact_source_spans'?'Exact declared spans match this source. A whole-episode verdict is not attributed to these spans.':'Whole source reference only; the trained span is not established.');
   if(!row.bound)card.append(el('p','Excluded from membership totals. Inspect the declaration conflict or limit below.','if-warning'));
   if(row.records_complete){
    describe(card,'Recorded use',`${row.use_counts.backward_completed||0} backward receipts; ${row.use_counts.optimizer_step_completed||0} optimizer receipts. Missing stages remain unknown.`);
    describe(card,'Backward mask evidence',`${row.backward_mask_counts.positive||0} positive · ${row.backward_mask_counts.zero||0} zero · ${row.backward_mask_counts.unrecorded||0} unrecorded. Counts refer to backward receipts.`);
    for(const filter of row.filters){const box=el('div');describe(box,'Selection',`${filter.filter} · ${filter.definition} · ${filter.producer}: ${filter.state.replaceAll('_',' ')}`);for(const b of filter.batches)box.append(el('small',`${b.batch_id}: ${b.decision}`));card.append(box);}
    if(!row.filters.length)card.append(el('p','No selection decisions recorded.'));
    for(const score of row.scores)describe(card,'Score component',`${score.component} · ${score.definition}: ${score.status}${score.value==null?'':' · '+score.value}`);
   }
   const records=el('details');records.append(el('summary','Native record identities & evidence'),el('pre',JSON.stringify(row.records,null,2)));card.append(records);parent.append(card);
  }
  const scope=el('details');scope.append(el('summary','Scope & interpretation limits'),el('p',s.coverage_scope),el('p',s.boundary));parent.append(scope);
 }
 async function lookupTraining(run,hash,editing,onAttach){
  const {d,body}=dialog('Selection & training use'),status=el('p','Reading exact source bindings…');body.append(status);
  try{
   const query=new URLSearchParams({run_id:run});if(hash)query.set('source_hash',hash);
   const s=await api('/api/training-exposure?'+query);if(!d.isConnected)return;status.remove();trainingEvidence(body,s);
   if(onAttach){const error=el('p',null,'if-error');error.setAttribute('role','alert');const attach=button('Attach this training snapshot',async()=>{attach.disabled=true;try{await onAttach({kind:'training_exposure',run_id:s.run_id,source_hash:s.source_hash,experiment:s.experiment,snapshot_id:s.snapshot_id});d.close();}catch(e){error.textContent=e.message;attach.disabled=false;}},'primary');const actions=el('div',null,'if-actions');actions.append(attach);body.append(actions,error);}
   else body.append(el('p','To preserve this lookup, open Record finding and choose Selection & training use. Existing findings retain their saved evidence.','if-muted'));
   const raw=el('details');raw.append(el('summary','Lookup scope & fields'),el('pre',JSON.stringify(s,null,2)));body.append(raw);
  }catch(e){status.textContent=e.message;status.className='if-error';status.setAttribute('role','alert');}
 }
 function showEvidence(e,editing=false,onAttach=null){
  const {body}=dialog(e.title);
  const inspectLink=(label,href)=>{const a=link(label,href);if(editing){a.target='_blank';a.rel='noopener';a.textContent+=' (new tab)';}return a;};
  if(editing)body.append(el('p','Evidence links open separately so your unsaved finding stays available.','if-muted'));
  if(e.kind==='investigation'){
   body.append(el('p','Saved comparison. Its population, case selection and measurements are pinned.'),inspectLink('Open saved comparison',comparisonUrl(e.id)),el('p',e.snapshot_id,'if-identity'));
   for(const [key,value] of Object.entries(e.scope||{}))describe(body,key.replaceAll('_',' '),typeof value==='object'?JSON.stringify(value):String(value));
  }else if(e.kind==='behavior_case'){
   const r=e.record,c=r.case;body.append(el('p',e.investigation_title+' · '+r.cohort+' cases','if-muted'));
   if(e.annotation_review?.notes?.length){
    const notes=el('details',null,'if-review-notes');notes.append(el('summary',`${e.annotation_review.notes.length} annotation review notes`));
    for(const note of e.annotation_review.notes)notes.append(el('p',note.text||JSON.stringify(note)));
    body.append(notes);
   }else if(e.annotation_review?.status==='graph_unavailable')body.append(el('p','The original graph is unavailable. This saved case is retained, but its annotation review context cannot be inspected.','if-warning'));
   if(e.family==='recurrence')body.append(window.renderWorkEpisode(c,r.observer));
   else{
    body.append(el('h3',r.status_label),el('p',`${c.attempts.length} recorded follow-up checks · ${c.window_closed?'window resolved':'window incomplete'}`));
    for(const [i,a]of c.attempts.entries())describe(body,'Follow-up '+(i+1),a.result+' · '+(a.comparable?'Comparable recorded check':'Comparability not established')+(a.issues.length?' · '+a.issues.map(v=>v.replaceAll('_',' ')).join(', '):''));
    if(c.unknown_reasons.length)describe(body,'Why this remains unknown',c.unknown_reasons.map(v=>v.replaceAll('_',' ')).join(', '));
    body.append(inspectLink('Open failure and follow-up checks','/semantic-map?'+new URLSearchParams({run:r.run_id,graph:r.graph_id,focus_unit:'event:'+c.failure_action_id,return_to:location.pathname+location.search})));
   }
   body.append(inspectLink('Open originating comparison',comparisonUrl(e.investigation_id)));
   for(const limit of e.limits)body.append(el('p',limit,'if-muted'));
   if(editing)for(const a of body.querySelectorAll('a')){a.target='_blank';a.rel='noopener';}
  }else if(e.kind==='evaluation'){
   const r=e.receipt;body.append(el('p',evaluationPurpose[r.purpose]+' · '+r.execution+' · '+r.verdict,'if-question'));
   describe(body,'Reported by',r.producer+' · '+r.performed_at);describe(body,'Summary',r.summary);
   if(r.score!=null)describe(body,'Reported score',String(r.score));
   body.append(el('p',e.boundary,'if-muted'));
   const inputs=el('div',null,'if-case-list');for(const [role,input]of Object.entries(r.inputs)){
    const card=el('section',null,'if-case-row');card.append(el('strong',role.replaceAll('_',' ')),el('p',input?.label||'Revision not recorded'));
    if(input){const details=el('details');details.append(el('summary','Declared SHA-256'),el('code',input.sha256));card.append(details);}inputs.append(card);
   }body.append(inputs);
   for(const item of r.evidence){const detail=el('details');detail.append(el('summary',item.label),el('pre',item.text));body.append(detail);}
   body.append(button('Look up selection & training use',()=>lookupTraining(r.run_id,r.source_hash,editing,onAttach)));
   body.append(inspectLink('Open bound rollout','/semantic-map?'+new URLSearchParams({run:r.run_id,observer:'source',return_to:location.pathname+location.search})));
  }else if(e.kind==='training_exposure'){
   body.append(el('p','Saved training evidence. Late records do not alter this snapshot.','if-muted'));trainingEvidence(body,e.snapshot);
   body.append(button('Inspect current records',()=>lookupTraining(e.run_id,e.snapshot.source_hash,editing,onAttach)));
  }else if(e.kind==='unit'){
   const unit=e.unit.properties,source=unit.source||{};
   body.append(el('p','Saved rollout unit · '+e.observer),el('blockquote',source.text||unit.text||unit.label||unit.title||'Inspect the retained unit fields below.'),
    inspectLink('Open unit in behavior map','/semantic-map?'+new URLSearchParams({run:e.run_id,observer:e.observer,graph:e.graph_id,focus_unit:e.unit_id,level:'units',return_to:location.pathname+location.search})));
  }else{
   const s=e.snapshot;body.append(el('p','Pinned continuation evidence · '+s.experiment));
   const rates=el('div',null,'if-rates');for(const arm of ['before','after']){const a=s.arms[arm],box=el('div');box.append(el('small',arm==='before'?'Before the region':'After the region'),el('strong',a.rate==null?'Unknown':(a.rate*100).toFixed(1)+'%'),el('span',`${a.successes} successes / ${a.observed} eligible · ${a.expected} planned`));rates.append(box);}body.append(rates);
   body.append(el('p',s.difference==null?'Comparison unavailable':`Observed difference: ${(s.difference*100).toFixed(1)} percentage points`),el('p',s.interpretation));
   for(const issue of s.issues)body.append(el('p',issue,'if-warning'));
   const cases=el('details');cases.append(el('summary','Inspect continuation cases'));
   for(const arm of ['before','after'])for(const row of s.arms[arm].cases){const item=el('p',`${arm} · ${row.sample.id} · ${row.eligible?(row.outcome?'success':'failure'):'unresolved'}`);if(row.run_id)item.append(' · ',inspectLink('Unit map','/semantic-map?'+new URLSearchParams({run:row.run_id,level:'units',return_to:location.pathname+location.search})));cases.append(item);}body.append(cases);
  }
  const raw=el('details');raw.append(el('summary','Pinned evidence fields'),el('pre',JSON.stringify(e,null,2)));body.append(raw);
 }
 function planDialog(doc,onSaved,follows=null){
  const {d,body}=dialog(follows?'Plan a follow-up check':'Plan a check'),form=el('form',null,'if-form');
  body.append(el('p','Uses this investigation’s saved population and case selection. No experiment or model call will run.','if-muted'),form);
  const title=field(form,'Check title',{short:true,placeholder:'Selection records for successful rollouts'}),hypothesis=field(form,'Hypothesis',{value:follows?'':doc.hypothesis||'',placeholder:'The explanation this check should examine'}),procedure=field(form,'Check to perform',{placeholder:'Inspect recorded selection and training use for the successful sample.'}),expected=field(form,'Expected result',{placeholder:'If selection is responsible, the success should be rejected or absent from the admitted population.'}),controls=field(form,'Controls, missing evidence or cost limit (optional)',{required:false});
  const branch=choice(form,'Follow-up to', [['','Independent check'],...(doc.follow_up?.checks||[]).map(c=>[c.id,c.title])]);branch.value=follows?.id||'';
  const error=el('p',null,'if-error');error.setAttribute('role','alert');const save=el('button','Save check','primary');save.type='submit';form.append(error,save);
  form.onsubmit=async event=>{event.preventDefault();save.disabled=true;error.textContent='';try{
   const result=await api('/api/investigations/follow-ups',{parent_id:doc.id,action:'plan',check:{title:title.value,hypothesis:hypothesis.value,procedure:procedure.value,expected_result:expected.value,controls:controls.value,follows_check:branch.value||null}});
   d.close();await onSaved(result);
  }catch(e){error.textContent=e.message;save.disabled=false;}};
 }
 function localReference(value,kind){
  if(kind==='investigation'&&/^investigation-[a-f0-9]+$/.test(value.trim()))return{kind,id:value.trim()};
  const u=new URL(value.trim(),location.origin);if(u.origin!==location.origin)throw Error('Use a link from this workspace.');
  if(kind==='investigation'&&u.pathname==='/investigate'&&u.searchParams.get('saved'))return{kind,id:u.searchParams.get('saved')};
  if(kind==='unit'&&u.pathname==='/semantic-map'&&u.searchParams.get('graph')&&u.searchParams.get('focus_unit'))return{kind,graph_id:u.searchParams.get('graph'),unit_id:u.searchParams.get('focus_unit')};
  throw Error(kind==='unit'?'Open a unit in a pinned behavior map and paste its link (graph and focus_unit required).':'Paste a saved investigation link or identity.');
 }
 async function casePicker(root,doc,add,error,active){
  const source=choice(root,'Cases from saved comparison',[[doc.id,'This investigation · '+doc.title]]),filters=el('div',null,'if-case-filters');root.append(filters);
  const family=choice(filters,'Case family',[['recurrence','Returns and repeated work'],['recovery','Comparable recovery checks']]);
  const cohort=choice(filters,'Case population',[['all','Focus + reference'],['focus','Focus only'],['reference','Reference only']]);
  const status=choice(filters,'Case status',[['all','All recorded categories']]);
  const feedback=choice(filters,'Feedback evidence',[['all','All cases'],['recorded','Recorded reference'],['unestablished','Reference unestablished']]);
  const query=field(root,'Find work target or criterion',{short:true,required:false,placeholder:'e.g. convert report'});query.maxLength=240;
  const summary=el('p',null,'if-case-summary'),coverage=el('p',null,'if-muted'),list=el('div',null,'if-case-list'),nav=el('div',null,'if-actions');
  let offset=0,request=0,total=0;const previous=button('Previous cases',()=>{offset=Math.max(0,offset-10);load();}),next=button('More cases',()=>{offset+=10;load();});
  nav.append(previous,next);root.append(button('Find cases',()=>{offset=0;load();}),summary,coverage,list,nav);
  const ref=row=>({kind:'behavior_case',investigation_id:source.value,family:family.value,case_id:row.id});
  async function load(){
   const token=++request;error.textContent='';summary.textContent='Finding recorded cases…';coverage.textContent='';list.replaceChildren();previous.disabled=next.disabled=true;
   try{
    const v=await api('/api/investigations/'+encodeURIComponent(source.value)+'/cases?'+new URLSearchParams({family:family.value,cohort:cohort.value,status:status.value,feedback:feedback.value,q:query.value,offset,limit:10}));
    if(token!==request||!active())return;
    const selected=status.value;status.replaceChildren();for(const [key,label]of [['all','All recorded categories'],...Object.entries(v.statuses)]){const o=el('option',label);o.value=key;status.append(o);}status.value=selected;
    total=v.matched_cases;summary.textContent=`${v.matched_cases} matching cases · ${v.matched_rollouts} distinct rollouts · ${v.total_cases} cases before case filters`;
    const c=v.coverage;coverage.textContent=`${c.projected_rollouts}/${c.scope_rollouts} rollouts with this saved projection. `+(family.value==='recurrence'?`${c.represented_actions}/${c.recorded_actions} actions represented; ${c.first_or_unresolved_actions} first or unresolved. `:`${c.captured_checks}/${c.recorded_checks} checks with captured state. `)+v.feedback_definition+'. An unestablished link is not evidence that feedback was ignored.';
    if(c.ambiguous_projection_rollouts)coverage.append(` ${c.ambiguous_projection_rollouts} rollouts withheld because annotation versions conflict.`);
    if(v.availability==='not_recorded')list.append(el('p','This comparison has no supported saved projection for these cases. Choose a saved behavior comparison, or attach a unit. No analysis or model call has run.','if-empty'));
    else if(!v.cases.length)list.append(el('p','No recorded cases match these filters. Missing observations do not establish absence of the behavior.','if-empty'));
    for(const row of v.cases){const receiptRef=ref(row),card=el('article',null,'if-case-row'),actions=el('div',null,'if-actions');card.append(el('strong',row.target),el('small',`${row.location} · ${row.status_label}`),el('small',`${row.cohort} · rollout ${row.run_id.slice(0,8)} · ${row.recorded_feedback_reference?'Feedback reference recorded':'Feedback reference unestablished'}`));
     const inspect=button('Inspect case',async()=>{inspect.disabled=true;try{const value=await api('/api/investigations/follow-ups/preview',{evidence:[receiptRef]});if(active())showEvidence(value.evidence[0],true);}catch(e){error.textContent=e.message;}finally{inspect.disabled=false;}});
     const attach=button('Attach case',async()=>{attach.disabled=true;try{await add(receiptRef);error.textContent='';attach.textContent='Attached';}catch(e){error.textContent=e.message;attach.disabled=false;}});
     actions.append(inspect,attach);card.append(actions);list.append(card);}
    previous.disabled=offset===0;next.disabled=offset+v.cases.length>=total;nav.hidden=total<=10;
   }catch(e){if(token===request&&active()){error.textContent=e.message;summary.textContent='Case retrieval unavailable';}}
  }
  for(const s of [source,cohort,status,feedback])s.onchange=()=>{offset=0;load();};
  family.onchange=()=>{status.value='all';offset=0;load();};query.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();offset=0;load();}};
  load();
  try{const v=await api('/api/investigations');if(!active())return;source.append(...ChoiceLabels.choices(v.investigations.filter(r=>r.id!==doc.id).map(r=>({id:r.id,label:r.title,suffix:`${r.check_count||0} checks / ${r.finding_count||0} findings`})),{noun:'Review',fallback:'Saved investigation'}).map(ChoiceLabels.option));}catch(e){if(active())error.textContent=e.message;}
 }
 function resultDialog(doc,check,onSaved){
  const {d,body}=dialog('Record finding · '+check.title),form=el('form',null,'if-form');
  describe(body,'Expected result, saved before this finding',check.expected_result);body.append(form);
  const assessment=choice(form,'Finding',[['inconclusive',labels.inconclusive],['supports',labels.supports],['contradicts',labels.contradicts],['not_run',labels.not_run]]);
  const conclusion=field(form,'Conclusion',{placeholder:'What did the evidence show, and what remains unresolved?'}),limitations=field(form,'Limitations or missing evidence (optional)',{required:false}),next=field(form,'Next action (optional)',{required:false});
  const evidenceBox=el('fieldset',null,'if-evidence-picker');evidenceBox.append(el('legend','Returned evidence'),el('p','Attach existing records. Supports / contradicts requires evidence; the interpretation remains yours.','if-muted'));form.append(evidenceBox);
  const type=choice(evidenceBox,'Evidence type',[['behavior_case','Behavior case'],['evaluation','Verifier / independent check'],['training_exposure','Selection & training use'],['investigation','Saved comparison'],['unit','Rollout unit'],['continuation','Continuation experiment']]);
  const picker=el('div'),attached=el('div',null,'if-attached'),error=el('p',null,'if-error');error.setAttribute('role','alert');evidenceBox.append(picker,attached);let refs=[],receipts=[],comparisons=[],loadId=0,attaching=false;
  const showAttached=()=>{attached.replaceChildren();receipts.forEach((e,i)=>{const row=el('div',null,'if-attached-row');row.append(button(e.title+(e.record?.location?' · '+e.record.location:''),()=>showEvidence(e,true,add)),button('Remove',()=>{if(attaching){error.textContent='Wait for the pending evidence attachment.';return;}refs.splice(i,1);receipts.splice(i,1);showAttached();}));attached.append(row);});for(const pair of comparisons)if(receipts.some(e=>e.id===pair.left)&&receipts.some(e=>e.id===pair.right))evaluationComparison(attached,pair);};
  async function add(ref){
   if(attaching)throw Error('Wait for the pending evidence attachment.');
   if(refs.length>=8)throw Error('Up to eight evidence items per finding.');
   attaching=true;save.disabled=true;
   try{const result=await api('/api/investigations/follow-ups/preview',{evidence:[...refs,ref]});if(!d.isConnected)return;refs.push(ref);receipts=result.evidence;comparisons=result.evaluation_comparisons||[];showAttached();}
   finally{attaching=false;save.disabled=false;}
  }
  async function populate(){
   const token=++loadId;picker.replaceChildren();error.textContent='';
   if(type.value==='behavior_case'){await casePicker(picker,doc,add,error,()=>token===loadId&&d.isConnected);return;}
   if(type.value==='training_exposure'){
    const runs=[...new Set((doc.selected_samples||doc.snapshot?.rows||[]).map(r=>r.run_id||r.id).filter(Boolean))];
    const choose=choice(picker,'Rollout in this investigation',runs.map((id,i)=>[id,'Rollout '+(i+1)+' · '+id.slice(0,8)]));
    picker.append(el('p','Find explicit source-to-sample bindings, named filter decisions and separate backward / optimizer receipts. No use is inferred from reward.','if-muted'),button('Inspect training records',()=>lookupTraining(choose.value,null,true,add)));
    return;
   }
   if(type.value==='evaluation'){
    const runs=[...new Set((doc.selected_samples||doc.snapshot?.rows||[]).map(r=>r.run_id||r.id).filter(Boolean))];
    const choose=choice(picker,'Rollout in this investigation',runs.map((id,i)=>[id,'Rollout '+(i+1)+' · '+id.slice(0,8)])),list=el('div',null,'if-case-list');
    const previousRuns=[...new Set((check.results||[]).flatMap(r=>r.evidence.filter(e=>e.kind==='evaluation').map(e=>e.run_id)))];if(previousRuns.length===1&&runs.includes(previousRuns[0]))choose.value=previousRuns[0];
    const manual=field(picker,'Receipt identity (optional)',{short:true,required:false,placeholder:'evaluation-…'});manual.maxLength=100;
    picker.append(button('Attach by identity',async()=>{try{await add({kind:'evaluation',id:manual.value.trim()});error.textContent='';}catch(e){error.textContent=e.message;}}),list);
    let offset=0,request=0;const more=button('More evaluations',()=>load(true));picker.append(more);
    const help=el('details');help.append(el('summary','Send results from Python or an external worker'),el('p','Run the check in your evaluation environment, then save its report. Rilldex retains declared input hashes and reported outcomes; it does not execute the check or replace training reward.'),el('pre','import json\nfrom pathlib import Path\nfrom rilldex import Workspace\n\nw = Workspace("study.sqlite")\nreceipt = json.loads(Path("evaluation.json").read_text())\nsaved = w.record_evaluation(receipt)\n\n# HTTP workers: POST /api/evaluations with the same JSON.\n# Contract and runnable example: docs/EVALUATOR_EVIDENCE.md'));picker.append(help);
    async function load(append=false){const current=++request;if(!append){offset=0;list.replaceChildren();}more.disabled=true;try{
     if(!choose.value){list.append(el('p','No rollout is bound to this investigation. Attach a saved receipt by identity.'));return;}
     const page=await api('/api/evaluations?'+new URLSearchParams({run_id:choose.value,limit:10,offset}));if(current!==request||token!==loadId||!d.isConnected)return;
     if(!page.receipts.length&&!append)list.append(el('p','No evaluation reports for this rollout. Send a report from your worker; missing reports are not passing checks.','if-empty'));
     for(const r of page.receipts){const card=el('article',null,'if-case-row'),actions=el('div',null,'if-actions');card.append(el('strong',r.label),el('small',`${evaluationPurpose[r.purpose]} · ${r.execution} · ${r.verdict}`),el('small',r.producer+' · '+r.performed_at));
      actions.append(button('Inspect report',()=>showEvidence({kind:'evaluation',title:r.label,receipt:r,boundary:page.boundary},true,add)),button('Attach report',async()=>{try{await add({kind:'evaluation',id:r.id});error.textContent='';}catch(e){error.textContent=e.message;}}));card.append(actions);list.append(card);}
     offset+=page.receipts.length;more.hidden=!page.more;
    }catch(e){if(current===request&&token===loadId&&d.isConnected)error.textContent=e.message;}finally{if(current===request)more.disabled=false;}}
    choose.onchange=()=>load();await load();return;
   }
   if(type.value!=='continuation'){
    const input=field(picker,type.value==='unit'?'Pinned unit link':'Saved comparison link or identity',{short:true,required:false});input.maxLength=4096;
    if(type.value==='investigation'){
     try{const list=await api('/api/investigations');if(token!==loadId||!d.isConnected)return;const select=choice(picker,'Recent saved comparisons',[['','Choose a comparison…'],...list.investigations.filter(r=>r.id!==doc.id).map(r=>[r.id,`${r.title} · ${r.check_count||0} checks / ${r.finding_count||0} findings · ${r.created_at.slice(11,19)}`])]);select.onchange=()=>{input.value=select.value;};}catch(e){error.textContent=e.message;}
    }
    if(token!==loadId||!d.isConnected)return;const addButton=button('Attach evidence',async()=>{addButton.disabled=true;try{await add(localReference(input.value,type.value));error.textContent='';}catch(e){error.textContent=e.message;}finally{addButton.disabled=false;}});picker.append(addButton);return;
   }
   const choose=choice(picker,'Recorded experiment',[['','Loading studies…']]),summary=el('p',null,'if-muted'),more=button('Load more studies',()=>loadStudies());picker.append(summary,more);let studies=[],offset=0;
   function selection(){return studies.find(s=>s.snapshot_id===choose.value);}
   choose.onchange=()=>{const s=selection();summary.textContent=s?`${s.experiment} · ${s.arms.before.successes}/${s.arms.before.observed} before; ${s.arms.after.successes}/${s.arms.after.observed} after. ${s.issues.length?'Incomplete or incompatible evidence.':'Recorded comparison available.'}`:'';};
   async function loadStudies(){more.disabled=true;try{const r=await api('/api/continuation-studies?limit=50&offset='+offset);if(token!==loadId||!d.isConnected)return;const previous=choose.value;studies.push(...r.studies);offset+=r.studies.length;choose.replaceChildren();for(const s of studies){const option=el('option',s.design.label+' · '+s.experiment);option.value=s.snapshot_id;choose.append(option);}if(studies.some(s=>s.snapshot_id===previous))choose.value=previous;more.hidden=offset>=r.total;choose.disabled=!studies.length;if(studies.length)choose.onchange();else summary.textContent='No imported studies. Import results through Connections / Integration guide.';}catch(e){error.textContent=e.message;}finally{more.disabled=false;}}
   const addButton=button('Attach evidence',async()=>{const s=selection();if(!s){error.textContent='Choose an imported study first.';return;}addButton.disabled=true;try{await add({kind:'continuation',producer:s.producer,experiment:s.experiment,study_id:s.design.id,snapshot_id:s.snapshot_id});error.textContent='';}catch(e){error.textContent=e.message;}finally{addButton.disabled=false;}});picker.append(addButton);await loadStudies();
  }
  type.onchange=populate;populate();assessment.onchange=()=>{evidenceBox.hidden=assessment.value==='not_run';};
  const save=el('button','Save finding','primary');save.type='submit';form.append(error,save);
  form.onsubmit=async event=>{event.preventDefault();if(attaching){error.textContent='Wait for the pending evidence attachment.';return;}save.disabled=true;error.textContent='';try{
   const result=await api('/api/investigations/follow-ups',{parent_id:doc.id,action:'result',check:{id:check.id,assessment:assessment.value,conclusion:conclusion.value,limitations:limitations.value,next_action:next.value,evidence:assessment.value==='not_run'?[]:refs}});
   d.close();await onSaved(result);
  }catch(e){error.textContent=e.message;save.disabled=false;}};
 }
 function finding(parent,r,badge=true){
  const box=el('div',null,'if-finding');if(badge)box.append(el('span',labels[r.assessment],'if-badge '+r.assessment));describe(box,'Researcher conclusion',r.conclusion);describe(box,'Limitations',r.limitations);describe(box,'Next action',r.next_action);
  const row=el('div',null,'if-evidence-links');for(const e of r.evidence)row.append(button(e.title+(e.record?.location?' · '+e.record.location:''),()=>showEvidence(e)));box.append(row);if(!r.evidence.length)box.append(el('p','No result evidence attached.','if-muted'));parent.append(box);
  for(const pair of r.evaluation_comparisons||[])evaluationComparison(box,pair);
 }
 function render(doc,onSaved,onNotes){
  const section=el('section',null,'iv-panel if-workflow');section.id='investigation-checks';const head=el('div',null,'if-heading');head.append(el('div'));
  head.firstChild.append(el('span','QUESTION → CHECK → FINDING','eyebrow'),el('h2','Checks & findings'));section.append(head);
  if(!doc){section.append(el('p','Save this comparison to preserve its population and start an investigation.'),button('Save comparison first',onNotes,'primary'));return section;}
  head.append(button('Plan a check',()=>planDialog(doc,onSaved),'primary'));
  const checks=doc.follow_up?.checks||[],pending=checks.filter(c=>!c.results.length).length;
  section.append(el('p',doc.hypothesis||doc.title,'if-question'),el('p',`${checks.length} ${checks.length===1?'check':'checks'} · ${pending} awaiting a finding · Original evidence stays pinned`,'if-muted'));
  const history=el('div',null,'if-revisions');if(doc.parent_id)history.append(link('Previous revision',url(doc.parent_id)));
  api('/api/investigations/'+encodeURIComponent(doc.id)+'/revisions').then(r=>{if(!history.isConnected)return;for(const item of r.revisions)history.append(link('Later revision · '+new Date(item.created_at).toLocaleString(),url(item.id)));if(r.revisions.length)history.prepend(el('span','Later work is available. This revision remains unchanged.'));}).catch(e=>{if(history.isConnected)history.append(el('span','Revision history unavailable: '+e.message));});section.append(history);
  if(!checks.length)section.append(el('div','No checks saved. Use Plan a check to add one, then Record finding to attach results and evidence.','if-empty'));
  const cards=el('div',null,'if-check-list');checks.forEach((c,index)=>{
   const card=el('article',null,'if-check'),latest=c.results.at(-1),header=el('div',null,'if-check-head');card.id=c.id;
   header.append(el('small','CHECK '+(index+1)),el('span',latest?labels[latest.assessment]:'Awaiting finding','if-badge '+(latest?.assessment||'pending')));card.append(header,el('h3',c.title));
   if(c.follows_check){const previous=checks.find(x=>x.id===c.follows_check);card.append(link('Follows: '+(previous?.title||'Earlier check'),'#'+c.follows_check));}
   describe(card,'Hypothesis',c.hypothesis);describe(card,'Expected result',c.expected_result);
   const design=el('details');design.append(el('summary','Check design & original scope'));describe(design,'Check to perform',c.procedure);describe(design,'Controls / missing evidence / cost',c.controls);design.append(link('Open original case selection',comparisonUrl(c.basis_id)));card.append(design);
   if(latest)finding(card,latest,false);
   if(c.results.length>1){const older=el('details');older.append(el('summary',`${c.results.length-1} earlier findings`));for(const r of c.results.slice(0,-1))finding(older,r);card.append(older);}
   const actions=el('div',null,'if-actions');actions.append(button(latest?'Add another finding':'Record finding',()=>resultDialog(doc,c,onSaved)),button('Plan follow-up',()=>planDialog(doc,onSaved,c)));card.append(actions);cards.append(card);
  });section.append(cards,el('p','Findings retain your assessment and linked evidence. Saved comparisons remain unchanged when new data arrives.','if-muted'));return section;
 }
 return{render};
})();
