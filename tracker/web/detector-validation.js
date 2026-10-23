(() => {
 'use strict';
 const $=id=>document.getElementById(id),params=new URLSearchParams(location.search);
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 let library,documentSet,result,comparison,sequence=0;
 const binary=value=>documentSet?.review_kind==='opportunity'?(value?'Taken':'Not taken'):(value?'Present':'Absent');
 const human=value=>({taken:binary(true),not_taken:binary(false),not_opportunity:'Outside scope',unknown:'Unresolved reference',true_positive:'Correct positive',true_negative:'Correct negative',false_positive:'False positive',false_negative:'False negative',prediction_unavailable:'Prediction unavailable',reference_unknown:'Unresolved reference',scope_agreement:'Scope agrees',scope_unresolved:'Scope unresolved',scope_disagreement:'Scope disagrees',changed_inputs:'Inputs changed',not_applicable:'Outside scope',newly_decided:'Newly decided',lost_coverage:'Lost coverage'}[value]||value.replaceAll('_',' '));
 const percent=n=>n==null?'—':(100*n).toFixed(1)+'%';
 async function api(path,body){const r=await fetch('/api/detector-validation'+path,body==null?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||'Request failed');return data;}
 function fail(e){$('error').textContent=e.message;$('error').hidden=false;}
 function options(select,rows,current){select.replaceChildren(...rows.map(([id,text])=>{const o=el('option',text);o.value=id;return o;}));if(rows.some(([id])=>id===current))select.value=current;}
 function persist(){const u=new URL(location.href);for(const key of ['set','split','result','baseline']){const value=key==='set'?$('sets').value:key==='result'?$('results').value:$(key).value;if(value){u.searchParams.set(key,value);params.set(key,value);}else{u.searchParams.delete(key);params.delete(key);}}history.replaceState(history.state,'',u);}
 function sampleOptions(){const selected=$('sample-question').value,who=$('reviewer').value.trim(),samples=library.samples.filter(s=>JSON.stringify([s.review_kind,s.question])===selected);
  $('samples').replaceChildren();for(const s of samples){const l=el('label'),check=el('input');check.type='checkbox';check.value=s.id;check.checked=s.id===params.get('sample');check.disabled=!s.reviewers.includes(who);l.append(check,el('span',`${s.monitor_name} · ${s.size} sampled cases${check.disabled?' · no saved labels by this reviewer':''}`));$('samples').append(l);}
  $('sample-note').textContent=samples.length?'Only this reviewer’s saved judgments are included. Labels are frozen when the set is saved.':'Review a monitor’s outcomes first, then return here to save its cases.';
 }
 async function refresh(wanted){library=await api('');options($('sets'),library.sets.map(s=>[s.id,s.name]),wanted||$('sets').value||params.get('set'));
  const qs=new Map(library.samples.map(s=>[JSON.stringify([s.review_kind,s.question]),s.monitor_name]));
  const initial=library.samples.find(s=>s.id===params.get('sample'));options($('sample-question'),[...qs],initial?JSON.stringify([initial.review_kind,initial.question]):$('sample-question').value);
  const reviewers=[...new Set(library.samples.flatMap(s=>s.reviewers))];$('reviewer-names').replaceChildren(...reviewers.map(r=>{const o=el('option');o.value=r;return o;}));
  if(!$('reviewer').value)$('reviewer').value=localStorage.getItem('measurement-reviewer')||reviewers[0]||'';sampleOptions();await showSet();
 }
 async function showSet(){const ticket=++sequence;result=null;comparison=null;$('error').hidden=true;
  if(!$('sets').value){$('workspace').hidden=true;$('export-set').hidden=true;$('set-context').textContent='No validation sets yet. Open a monitor’s rollout values, review cases, then save a set here.';return;}
  try{const doc=await api('/sets/'+$('sets').value);if(ticket!==sequence)return;documentSet=doc;$('workspace').hidden=false;$('export-set').hidden=false;$('export-set').href='/api/detector-validation/sets/'+doc.id+'?download=1';
   const dev=doc.cases.filter(c=>c.split==='development').length,test=doc.cases.length-dev;
   $('set-context').replaceChildren(el('strong',doc.question),el('p',`${dev} development · ${test} held out · Reviewer: ${doc.reviewer} · ${doc.unreviewed_cases} unreviewed cases excluded · ${doc.runs_without_case_frame.length} rollouts without a review frame`));
   const compatible=library.monitors.filter(m=>m.review_kind===doc.review_kind&&m.question===doc.question);options($('detectors'),compatible.map(m=>[m.id,`${m.name} · ${m.version}`]),$('detectors').value);
   $('capture').disabled=!compatible.length;
   const split=$('split').value;$('code').textContent=`from rilldex import ValidationSet\n\nvalidation = ValidationSet(${JSON.stringify(library.database)}, ${JSON.stringify(doc.id)})\n\ndef detect(case):\n    events = case["source_events"]\n    return None  # Replace with your True / False result or status dictionary.\n\nresult = validation.evaluate(detect, name="My detector", version="v1", split=${JSON.stringify(split)})\nprint(result["report"])`;
   const available=library.results.filter(r=>r.set_id===doc.id&&r.split===split),name=(r,i)=>`${r.detector.name} · ${r.detector.version} · evaluation ${available.length-i}`;
   options($('results'),available.map((r,i)=>[r.id,name(r,i)]),params.get('result'));
   options($('baseline'),[['','No comparison'],...available.map((r,i)=>[r.id,name(r,i)])],params.get('baseline'));
   await showResult();
  }catch(e){if(ticket===sequence)fail(e);}
 }
 function score(label,value,detail){const n=el('div',null,'score');n.append(el('span',label),el('strong',value),el('small',detail));return n;}
 async function showResult(){const ticket=++sequence;comparison=null;result=null;$('scores').replaceChildren();$('changes').replaceChildren();$('export-result').hidden=true;
  if(!$('results').value){$('coverage-note').textContent='No evaluation for this split. Compare a saved monitor version or run the Python example.';renderCases();persist();return;}
  try{const data=await api('/results/'+$('results').value);if(ticket!==sequence)return;result=data;const r=data.report,c=r.counts,joint=(c.true_positive||0)+(c.true_negative||0)+(c.false_positive||0)+(c.false_negative||0),reference=(c.reference_positive||0)+(c.reference_negative||0);
   $('scores').append(score('Decided coverage',percent(r.coverage),`${joint} / ${reference} decidable references`),score('Agreement on decided cases',percent(r.agreement),`${(c.true_positive||0)+(c.true_negative||0)} / ${joint} match`),score('Precision',percent(r.precision),`${c.false_positive||0} false positives`),score('Positive cases detected',percent(r.positive_detection_coverage),`${c.true_positive||0} / ${c.reference_positive||0} positive references`));
   $('coverage-note').textContent=`${c.false_negative||0} false negatives · ${c.prediction_unavailable||0} unavailable predictions on decidable references · ${c.reference_unknown||0} unresolved references · ${c.scope_disagreement||0} scope disagreements. Unavailable predictions stay in the coverage denominator.`;
   $('export-result').hidden=false;$('export-result').href='/api/detector-validation/results/'+data.id+'?download=1';
   if($('baseline').value&&$('baseline').value!==data.id){const delta=await api('/compare?'+new URLSearchParams({left:$('baseline').value,right:data.id}));if(ticket!==sequence)return;comparison=delta;for(const [k,n]of Object.entries(comparison.counts))$('changes').append(el('span',`${n} ${human(k)}`));}
   renderCases();persist();
  }catch(e){if(ticket===sequence)fail(e);}
 }
 function renderCases(){const filter=$('filter').value,change=new Map((comparison?.rows||[]).map(r=>[r.case_id,r])),rows=result?.report.rows||[];$('case-table').replaceChildren();
  const selected=rows.filter(r=>filter==='all'||filter==='disagreements'&&['false_positive','false_negative','scope_disagreement'].includes(r.outcome)||filter==='unavailable'&&r.value==null||['regressed','improved'].includes(filter)&&change.get(r.case_id)?.change===filter);
  const priority=r=>change.get(r.case_id)?.change==='regressed'?0:['false_positive','false_negative','scope_disagreement'].includes(r.outcome)?1:r.value==null?2:3;
  selected.sort((a,b)=>priority(a)-priority(b)||a.title.localeCompare(b.title)||a.case_id.localeCompare(b.case_id));
  if(!selected.length)$('case-table').append(el('p',result?'No cases match this filter.':'Capture an evaluation to inspect predictions alongside the frozen labels.','muted'));
  let shown=0;const more=el('button','Show more cases');more.type='button';
  function append(){more.remove();for(const r of selected.slice(shown,shown+40)){const line=el('div',null,'case-row'),name=el('div');name.append(el('strong',r.title),el('small',human(r.outcome),['false_positive','false_negative','scope_disagreement'].includes(r.outcome)?'bad':''));
    const reference=el('div');reference.append(el('small','Reference'),el('span',human(r.reference)));
    const prediction=el('div');prediction.append(el('small','Prediction'),el('span',r.value==null?human(r.status):binary(r.value)));
    const delta=el('div');delta.append(el('small','Version comparison'),el('span',change.has(r.case_id)?human(change.get(r.case_id).change):'—'));
    const open=el('button','Inspect case');open.type='button';open.onclick=()=>inspect(r,change.get(r.case_id));line.append(name,reference,prediction,delta,open);$('case-table').append(line);}
   shown+=40;if(shown<selected.length)$('case-table').append(more);
  }more.onclick=append;append();
 }
 async function inspect(row,change){const setId=documentSet.id,d=el('dialog');d.setAttribute('aria-label','Validation case');const close=el('button','Close');close.type='button';close.onclick=()=>d.close();const body=el('div','Loading saved source…');d.append(el('h2',row.title),close,body);d.onclose=()=>d.remove();document.body.append(d);d.showModal();
  try{const data=await api('/sets/'+setId+'?case='+encodeURIComponent(row.case_id));if(!d.isConnected)return;body.replaceChildren();body.append(el('h3','Frozen reference'),el('p',`${human(data.reference.label)} · ${data.reference.reviewer} · ${human(data.reference.reviewer_role)}`),el('p',data.reference.note));
   for(const c of data.reference.citations)body.append(el('pre',c.text||JSON.stringify(c,null,2),'citation'));
   body.append(el('h3','Detector result'),el('p',`${row.value==null?human(row.status):binary(row.value)}${row.reason?' · '+row.reason:''}`));
   if(change)body.append(el('p',`Previous: ${human(change.before.outcome)} → Current: ${human(change.after.outcome)}`));
   const links=el('div',null,'actions'),review=el('a','Open review');review.href=data.review_url;links.append(review);if(row.measurement_id){const map=el('a','Open exact measurement →');map.href='/semantic-map?'+new URLSearchParams({run:row.run_id,value:row.measurement_id,return_to:location.pathname+location.search});links.append(map);}body.append(links);
   const source=el('details');source.append(el('summary',`Frozen source · ${data.source_events.length} events`));for(const e of data.source_events){source.append(el('h4',`${e.index+1} · ${e.actor} · ${e.kind}`),el('pre',e.text));if(e.arguments)source.append(el('pre',JSON.stringify(e.arguments,null,2)));}body.append(source);
  }catch(e){body.textContent=e.message;}
 }
 $('new-set').onclick=()=>{$('create-panel').hidden=false;$('set-name').focus();};$('cancel-create').onclick=()=>{$('create-panel').hidden=true;};$('reviewer').oninput=sampleOptions;$('sample-question').onchange=sampleOptions;
 $('create-form').onsubmit=async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;$('error').hidden=true;try{const doc=await api('/sets',{name:$('set-name').value,reviewer:$('reviewer').value.trim(),sample_ids:[...$('samples').querySelectorAll('input:checked')].map(n=>n.value),seed:$('seed').value,held_out_percent:Number($('holdout').value)});$('create-panel').hidden=true;params.delete('result');params.delete('baseline');await refresh(doc.id);}catch(err){fail(err);}finally{button.disabled=false;}};
 $('sets').onchange=()=>{params.delete('result');params.delete('baseline');showSet();};$('split').onchange=()=>{params.delete('result');params.delete('baseline');showSet();};$('results').onchange=showResult;$('baseline').onchange=showResult;$('filter').onchange=renderCases;
 $('capture').onclick=async()=>{$('capture').disabled=true;$('error').hidden=true;try{const saved=await api('/capture',{set_id:documentSet.id,split:$('split').value,monitor_id:$('detectors').value});params.set('result',saved.id);await refresh(documentSet.id);}catch(e){fail(e);}finally{$('capture').disabled=false;}};
 if(params.has('sample'))$('create-panel').hidden=false;if(['development','held_out','all'].includes(params.get('split')))$('split').value=params.get('split');
 refresh().catch(fail);
})();
