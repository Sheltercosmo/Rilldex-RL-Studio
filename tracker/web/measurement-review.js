'use strict';
const $=id=>document.getElementById(id),params=new URLSearchParams(location.search),sid=params.get('sample');
let sample,current,currentId,loadIndex=0;
const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const x=await r.json();if(!r.ok)throw Error(x.error||'Request failed');return x;}
function error(e){$('error').hidden=false;$('error').textContent=e.message;}
function label(v){if(current?.predicted_scope==='outside')return 'Not applicable';return v===true?(sample.review_kind==='rollout_condition'?'Condition present':'Opportunity taken'):v===false?(sample.review_kind==='rollout_condition'?'Condition absent':'Opportunity not taken'):'Unresolved';}
function summary(){
 $('title').textContent=sample.monitor_name;$('question').textContent=sample.question;
 const condition=sample.review_kind==='rollout_condition';
 $('population').textContent=`${sample.sample_size} sampled cases · ${sample.frame_cases} saved ${condition?'rollout results':'opportunities'} · ${sample.run_ids.length} selected rollouts`;
 $('review-limits').textContent=sample.limits;
 $('judgment-title').textContent=condition?'Is the defined condition present?':'Does this case take the measured opportunity?';
 for(const [value,text] of Object.entries(condition?{taken:'Yes · condition present',not_taken:'No · condition absent',not_opportunity:'Outside the rule’s scope'}:{taken:'Yes · opportunity taken',not_taken:'No · opportunity not taken',not_opportunity:'This is not an eligible opportunity'}))$('label').querySelector(`option[value="${value}"]`).textContent=text;
 const me=sample.reviewers.find(r=>r.reviewer===$('reviewer').value.trim());
 $('progress').textContent=`${me?.reviewed||0} / ${sample.sample_size} reviewed by ${$('reviewer').value.trim()||'you'} · ${sample.runs_without_case_frame.length} rollouts without a case frame`;
 $('export').href='/api/measurement-reviews/'+sample.id+'?download=1';
 $('case-list').replaceChildren(...sample.cases.map((c,i)=>{const b=el('button',`Case ${i+1}${c.reviewed_by.includes($('reviewer').value.trim())?' ✓':''}`);b.type='button';b.dataset.case=c.id;b.setAttribute('aria-current',String(c.id===currentId));b.append(el('small',c.run_id.slice(0,13)));b.onclick=()=>loadCase(c.id);return b;}));
 const table=el('table'),head=el('tr');['Reviewer / declared role','Reviewed','Comparable','Agreement','False positive','False negative','Unresolved reference','Unresolved prediction¹','Scope disagreements','Scope agreements','Unresolved scope'].forEach(x=>head.append(el('th',x)));table.append(head);
 for(const r of sample.reviewers){const tr=el('tr');[r.reviewer+' / '+r.declared_roles.join(', '),r.reviewed+'/'+sample.sample_size,r.comparable||0,r.agreement===null?'—':(100*r.agreement).toFixed(1)+'%',r.false_positive||0,r.false_negative||0,r.reference_unknown||0,r.prediction_unknown_with_decidable_reference||0,r.eligibility_disputes||0,r.scope_agreements||0,r.scope_unresolved||0].forEach(x=>tr.append(el('td',x)));table.append(tr);}
 $('review-results').replaceChildren(sample.reviewers.length?table:el('p','No judgments yet. Saved monitor outputs have not been treated as reference labels.'));
 if(sample.reviewers.length)$('review-results').append(el('p','¹ Among cases with a decidable reviewer judgment.'));
}
const citationRef=c=>c.input_name!==undefined?{input_name:c.input_name}:c.evaluation_id!==undefined?{evaluation_id:c.evaluation_id}:c.evaluator_input!==undefined?{evaluator_input:c.evaluator_input}:{event_id:c.event_id,start:c.start,end:c.end};
const spanKey=c=>JSON.stringify(citationRef(c));
function selectedCitations(){return [...new Map([...document.querySelectorAll('#source-events input:checked')].map(c=>{const ref=JSON.parse(c.dataset.ref);return [spanKey(ref),ref];})).values()];}
function citationCount(){$('citation-count').textContent=selectedCitations().length+' evidence records selected';}
function citeControl(ref,selected,title){const lab=el('label'),check=el('input');check.type='checkbox';check.dataset.ref=JSON.stringify(citationRef(ref));check.checked=selected.has(spanKey(ref));check.onchange=citationCount;lab.append(check,el('span',title));return lab;}
function sourcePassage(ref,title,selected,open=false){
 const d=el('details');d.open=open;if(open)d.className='witness';
 d.append(el('summary',title),el('pre',ref.text||'(No text recorded)'));
 if(ref.arguments!==undefined)d.append(el('strong','Recorded '+(ref.tool||'tool')+' arguments'),el('pre',JSON.stringify(ref.arguments,null,2)),el('small','Structured source attached to this dispatch. Passage citations above refer to its recorded text.'));
 if(ref.text)d.append(citeControl(ref,selected,'Cite this passage'));return d;
}
function inputEvidence(selected){
 const box=el('section');box.append(el('h3','Saved monitor inputs'));
 const config=el('details');config.append(el('summary','Rule configuration'),el('pre',JSON.stringify(current.monitor_configuration,null,2)));box.append(config);
 for(const input of current.declared_inputs||[]){const d=el('details');d.open=true;d.append(el('summary',(input.name==='@reward_definition'?'Recorded reward definition':input.name)+(input.present?'':' · missing')),el('small',input.pointer),el('pre',input.present?JSON.stringify(input.value,null,2):'No value recorded at this input path.'),citeControl({input_name:input.name},selected,'Cite this input'));box.append(d);}
 for(const [name,ids] of Object.entries(current.evaluator_inputs||{})){const d=el('details');d.append(el('summary',`${name} · ${ids.length} evaluator reports`),el('p','Reports selected when this result was computed. Later arrivals are excluded.'),citeControl({evaluator_input:name},selected,'Cite this saved selection'));box.append(d);}
 for(const report of current.evaluator_reports||[]){const d=el('details');d.append(el('summary',`${report.label||report.purpose} · ${report.verdict||report.status||'report'}`),el('pre',JSON.stringify(report,null,2)),citeControl({evaluation_id:report.id},selected,'Cite this evaluator report'));box.append(d);}
 return box;
}
function showCase(){
 const index=sample.cases.findIndex(c=>c.id===currentId);$('case-title').textContent=`Case ${index+1} · source evidence`;
 $('source-state').textContent=!current.freshness.current_source?'Earlier source snapshot':current.freshness.current_measurement?'Current saved measurement':'Pinned earlier measurement';
 $('source-notice').textContent=current.source_notice;
 const annotation=current.annotation,selected=new Set((annotation?.citations||[]).map(spanKey));
 const focus=current.focus_spans,context=current.source_events.map(e=>({...e,event_id:e.id,start:0,end:[...e.text].length}));
 const passages=focus.map((p,i)=>sourcePassage(p,`Passage ${i+1} · source ${p.index+1} · ${p.actor} · characters ${p.start}–${p.end}`,selected,true));
 const jump=el('button','Go to latest passage');jump.type='button';jump.onclick=()=>passages.at(-1)?.scrollIntoView({block:'nearest'});
 const condition=sample.review_kind==='rollout_condition';
 if(condition)$('source-events').replaceChildren(inputEvidence(selected));
 else $('source-events').replaceChildren(el('h3',`Case passages · ${focus.length}`),jump,...passages);
 if(current.source_subject){const s=current.source_subject,box=el('section');box.id='review-subject';box.append(el('h3','Entry being reviewed'),el('strong',s.value.title||s.value.content),el('pre',JSON.stringify(s.value,null,2)),el('small','Source '+s.event_id+' · arguments '+s.argument_pointer));$('source-events').prepend(box);}
 const known=new Set([...focus,...context].map(spanKey));
 for(const ref of annotation?.citations||[])if(ref.event_id&&!known.has(spanKey(ref)))$('source-events').append(sourcePassage(ref,'Saved citation',selected));
 const earlier=el('details');earlier.id='earlier-context';earlier.open=condition;earlier.append(el('summary',`${condition?'Full saved rollout':'Earlier source context'} · ${context.length} events`),...context.map(e=>sourcePassage(e,`${e.index+1} · ${e.actor} · ${e.kind}`,selected)));
 $('source-events').append(earlier);
 $('state-details').hidden=!current.recorded_work_state;$('state-inputs').textContent=current.recorded_work_state?JSON.stringify(current.recorded_work_state,null,2):'';
 $('label').value=annotation?.label||'';$('note').value=annotation?.note||'';if(annotation)$('role').value=annotation.reviewer_role;
 $('saved').textContent=annotation?'Judgment saved. Editing creates a new revision.':'';$('save').disabled=!$('reviewer').value.trim();
 $('comparison').hidden=!annotation;
 if(annotation){$('comparison-text').textContent=`Monitor: ${label(current.prediction)}. Reviewer: ${$('label').selectedOptions[0].textContent}.`;
  $('map-link').href='/semantic-map?'+new URLSearchParams({run:current.run_id,value:current.measurement_id});}
 $('next').disabled=index===sample.cases.length-1;citationCount();summary();
}
async function loadCase(cid){const token=++loadIndex;currentId=cid;current=null;$('error').hidden=true;$('comparison').hidden=true;$('label').value='';$('note').value='';$('save').disabled=true;$('source-events').textContent='Loading frozen source…';summary();try{const data=await api('/api/measurement-reviews/'+sid+'?'+new URLSearchParams({case:cid,reviewer:$('reviewer').value.trim()}));if(token!==loadIndex)return;current=data;showCase();}catch(e){if(token===loadIndex)error(e);}}
$('reviewer').oninput=()=>{$('save').disabled=true;};
$('reviewer').onchange=()=>{localStorage.setItem('measurement-reviewer',$('reviewer').value.trim());if(currentId)loadCase(currentId);};
$('judgment').onsubmit=async e=>{e.preventDefault();if(!current)return;$('save').disabled=true;$('error').hidden=true;const token=loadIndex;
 try{const citations=selectedCitations();
  const result=await api('/api/measurement-reviews/labels',{sample_id:sid,case_id:currentId,reviewer:$('reviewer').value.trim(),reviewer_role:$('role').value,label:$('label').value,note:$('note').value,citations,supersedes:current.annotation?.id||null});
  if(token!==loadIndex)return;sample=result.sample;current=result.case;showCase();
 }catch(err){if(token===loadIndex){error(err);$('save').disabled=false;}}
};
$('next').onclick=()=>{const i=sample.cases.findIndex(c=>c.id===currentId);if(i+1<sample.cases.length)loadCase(sample.cases[i+1].id);};
$('samples').onchange=()=>{location.href='/measurement-review?sample='+encodeURIComponent($('samples').value);};
(async()=>{try{if(!sid)throw Error('Open a sampled review from a rate or binary code monitor’s rollout values.');$('reviewer').value=localStorage.getItem('measurement-reviewer')||'';sample=await api('/api/measurement-reviews/'+sid);summary();
 const siblings=await api('/api/measurement-reviews?monitor='+encodeURIComponent(sample.monitor_id));$('samples').replaceChildren(...ChoiceLabels.choices(siblings.map(s=>({id:s.id,label:`${s.sample_size} cases · Seed ${s.seed}`})),{noun:'Sample'}).map(r=>{const o=ChoiceLabels.option(r);o.selected=r.id===sid;return o;}));
 await loadCase(sample.cases[0].id);
}catch(e){error(e);}})();
