'use strict';
(function(root){
 const names={DB:'Final database state',ENV_ASSERTION:'Environment checks',COMMUNICATE:'Communication checks',ACTION:'Action matching',NL_ASSERTION:'Language checks'};
 const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
 function description(text){try{const value=JSON.parse(text);if(value&&typeof value.name==='string'&&value.arguments&&typeof value.arguments==='object')return value.name+' · '+Object.entries(value.arguments).map(([k,v])=>k+': '+(typeof v==='string'?v:JSON.stringify(v))).join(', ');}catch{}return text;}
 function model(record){
  const components=(record.components||[]).map(c=>({name:names[c.id]||c.id,role:c.role==='reward'?'Counts toward reward':'Diagnostic only',score:c.value??'Not recorded'}));
  const checks=[...(record.criteria||[])].sort((a,b)=>(a.met===false?0:a.met==null?1:2)-(b.met===false?0:b.met==null?1:2)).map(c=>({
   name:description(c.description),verdict:c.met===true?'Met':c.met===false?'Not met':'Unknown',role:c.role==='reward'?'Counts toward reward':c.role==='diagnostic'?'Diagnostic only':`Rubric weight: ${c.weight}`,
   reference:c.verdict_reference||c.source_reference}));
  return {available:record.available===true,status:record.status,components,checks,issues:record.issues||[],limits:record.limits};
 }
 function render(record){
  const m=model(record),section=node('section',undefined,'evaluation-evidence');section.append(node('h3','Evaluator evidence'));
  if(!m.available){section.append(node('p','No supported evaluator record is attached. Tool responses alone cannot establish task success.'));return section;}
  const title=record.protocol?.endsWith('/tau-bench')?'Native τ²-bench evaluator':record.definition||'Recorded evaluator';
  const meta=node('p',`${title} · ${m.status}`,'evaluation-meta');meta.title=record.definition||'';section.append(meta);
  if(m.issues.length){const warning=node('p',`Cannot calculate reliable component measures: ${m.issues.map(i=>i.note).join(' ')}`);warning.setAttribute('role','status');section.append(warning);}
  if(m.components.length){const wrap=node('div',undefined,'evaluation-table'),table=node('table'),head=node('tr');for(const text of ['Component','Role','Score'])head.append(node('th',text));table.append(head);
   for(const c of m.components){const row=node('tr');row.append(node('td',c.name),node('td',c.role),node('td',String(c.score)));table.append(row);}wrap.append(table);section.append(wrap);
  }
  if(m.checks.length){const details=node('details'),failed=m.checks.filter(c=>c.verdict==='Not met').length;details.open=failed>0;
   details.append(node('summary',`${m.checks.length} recorded checks · ${failed} not met`));const list=node('ul');
   // Keep large evaluator records readable; all checks remain in the API/provenance.
   for(const c of m.checks.slice(0,50)){const li=node('li');li.append(node('strong',c.verdict+' · '+c.role),node('p',c.name));list.append(li);}details.append(list);
   if(m.checks.length>50)details.append(node('p','First 50 shown, unmet checks first. The full record is available below.'));section.append(details);
  }
  section.append(node('p',m.limits,'evaluation-meta'));
  const provenance=node('details');provenance.append(node('summary','Full evaluator record & source references'),node('pre',JSON.stringify(record,null,2)));section.append(provenance);return section;
 }
 function button(runId,onReady){const b=node('button','Evaluator evidence');b.type='button';b.className='evaluation-open';b.onclick=async()=>{
  b.disabled=true;b.textContent='Loading evaluator…';try{const response=await fetch('/api/reward-records/'+encodeURIComponent(runId));if(!response.ok)throw Error('Evaluator request failed ('+response.status+')');const result=await response.json();onReady(render(result));b.remove();}
  catch(error){b.disabled=false;b.textContent='Retry evaluator evidence';b.title=error.message;}
 };return b;}
 function deliveryModel(record){
  const labels={applicable_pass:'Passing evidence for delivered inputs',checked_failure:'Failure on delivered inputs',changed_inputs:'Inputs changed after the check',unresolved_check:'Check outcome unresolved',conflicting_check_results:'Checks disagree on the same captured inputs',inconsistent_check_scope:'Check input scopes differ',unknown:'Verification unresolved'};
  const witnessIds=record.conflicts?.[0]?.action_ids||[];
  const witnesses=['failed','passed'].map(result=>(record.check_history||[]).find(q=>witnessIds.includes(q.action_id)&&q.result===result)).filter(Boolean).map(q=>q.action_id);
  return {title:labels[record.status]||'Verification unresolved',criterion:record.requirement.criterion_id,witnesses,
   conflict:record.status==='conflicting_check_results'||record.status==='inconsistent_check_scope',
   coverage:record.coverage||{},history:(record.check_history||[]).map((q,i)=>({...q,index:i+1,
    label:q.availability==='pending_at_delivery'?'Pending at delivery':q.result,
    applicabilityLabel:({matching_inputs:'Matches delivered inputs',changed_inputs:'Earlier input versions',unknown:'Input comparison unresolved'})[q.applicability]||'Input comparison unresolved'}))};
 }
 function delivery(record,events=[],sourceButton){
  const m=deliveryModel(record),byId=new Map(events.map(e=>[e.id,e])),box=node('section',undefined,'evaluation-evidence');
  box.append(node('h3',m.title),node('p',m.criterion+' · delivery '+record.event_id),node('p',`${m.coverage.checks??m.history.length} checks · ${m.coverage.applicable??0} applicable · ${m.coverage.pending??0} pending at delivery`));
  if(m.conflict)box.append(node('p','Excluded from the decidable verification rate. Review the differing outcomes, input scope and uncaptured state before treating this work as verified.'));
  const checkCard=(q,open=false)=>{const row=node('details');row.open=open;row.append(node('summary','Check '+q.index+' · '+q.label+' · '+q.applicabilityLabel),node('p','Captured scope: '+(q.required_objects.join(', ')||'unrecorded')));
   if(q.issues.length)row.append(node('p',q.issues.map(s=>s.replaceAll('_',' ')).join(' · ')));
   for(const [label,id] of [['Dispatch',q.action_id],['Returned evidence',q.result_event_id]]){if(!id)continue;row.append(node('strong',label+' · '+id),node('pre',byId.get(id)?.text||'Source text unavailable in this packet.'));if(sourceButton)row.append(sourceButton(id));}return row;
  };
  if(m.witnesses.length){const counts=m.coverage.applicable_results||{};box.append(node('p',`${counts.passed||0} passing · ${counts.failed||0} failing on delivered inputs. One example of each is shown below; all checks remain in the history.`));for(const id of m.witnesses)box.append(checkCard(m.history.find(q=>q.action_id===id),true));}
  const history=node('details');history.open=!m.witnesses.length&&m.history.length<=3;history.append(node('summary','Complete check history · '+m.history.length));for(const q of m.history)history.append(checkCard(q));box.append(history);
  box.append(node('p',record.interpretation||'Captured checks do not establish full task success.'));return box;
 }
 root.EvaluationEvidence={model,render,button,deliveryModel,delivery};if(typeof module!=='undefined')module.exports=root.EvaluationEvidence;
})(typeof window!=='undefined'?window:globalThis);
