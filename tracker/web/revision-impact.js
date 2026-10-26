(function(root){
 'use strict';
 const LABELS={gain:'Improved',harm:'Regressed',retained:'Still passing',still_failed:'Still failing',unknown:'Unresolved',mixed:'Gain + regression',unchanged:'No result change'};
 const METHODS={alternative_procedure:'Different method',reconfigured_procedure:'Method adjusted',same_procedure:'Same method',not_established:'Method comparison unavailable'};
 const CHANGES={procedure:'Procedure change',prerequisite:'Prerequisite repair',local_adjustment:'Local adjustment',revision:'Revision',plan_replacement:'Plan replaced'};
 function checkRows(episodes){const seen=new Set();return episodes.flatMap(e=>e.impact?.checks||[]).filter(r=>{const key=r.pair_id||r.id;if(!key)return true;if(seen.has(key))return false;seen.add(key);return true;});}
 function summary(episodes,scope='operations'){
  const rows=scope==='checks'?checkRows(episodes):episodes.map(e=>e.impact?.operation||{status:'unknown'});
  const counts=Object.fromEntries(['gain','harm','retained','still_failed','unknown'].map(k=>[k,rows.filter(r=>r.status===k).length]));
  return {...counts,total:rows.length,unmeasured:scope==='checks'?episodes.filter(e=>!e.impact?.checks?.length).length:0};
 }
 function matches(episode,filter){if(!filter)return true;const [scope,status]=filter.split(':');return (scope==='checks'?episode.impact?.checks||[]:[episode.impact?.operation||{status:'unknown'}]).some(r=>r.status===status);}
 function badge(episode){const p=episode.impact;return p?.checks?.length?p.check_status:p?.operation?.status||'unknown';}
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 function overview(episodes,onFilter,selected=''){
  const host=el('section',null,'ri-overview');host.setAttribute('aria-label','Revision benefits and harms');
  const head=el('div',null,'ri-heading');head.append(el('h4','What changed after revision'),el('small',`${episodes.length} recorded episodes`));host.append(head);
  for(const [scope,label]of [['operations','Operations'],['checks','Criterion checks']]){
   const counts=summary(episodes,scope),row=el('div',null,'ri-summary-row');row.append(el('strong',label));
   if(!counts.total){row.append(el('span','Before/after checks not captured','ri-muted'));host.append(row);continue;}
   for(const key of ['gain','harm','still_failed','retained','unknown']){const b=el('button',null,'ri-stat '+key);b.type='button';b.setAttribute('aria-pressed',String(selected===scope+':'+key));b.append(el('strong',String(counts[key])),el('span',LABELS[key]));b.onclick=()=>onFilter(selected===scope+':'+key?'':scope+':'+key);row.append(b);}host.append(row);
   if(scope==='checks'&&counts.unmeasured)host.append(el('small',`${counts.unmeasured} episodes have no comparable check capture.`,'ri-muted'));
  }
  host.append(el('p','First follow-up · operation completion and check quality stay separate. Select a result to inspect its changes.','ri-muted'));
  return host;
 }
 function detail(host,episode,inspect,{showTags=true}={}){
  const p=episode.impact;if(!p)return;
  if(showTags){const chips=el('div',null,'ri-tags');for(const key of episode.change_kinds)chips.append(el('span',CHANGES[key]||key));
   if(episode.kind!=='plan_replacement')chips.append(el('span',METHODS[episode.method_change]||METHODS.not_established));host.append(chips);}
  const heading=el('h4','Benefit & harm');host.append(heading);
  if(p.checks.length){const unknown=p.checks.filter(c=>c.status==='unknown').length;host.append(el('p',`${p.checks.length-unknown} / ${p.checks.length} check pairs measured${unknown?' · '+unknown+' unresolved':''}`,'ri-muted'));}
  const rows=[{...p.operation,criterion:'Operation completion'},...p.checks],table=el('table',null,'ri-results'),thead=el('thead'),header=el('tr');
  for(const text of ['Measure','Before','First follow-up','Change'])header.append(el('th',text));thead.append(header);table.append(thead);const body=el('tbody');
  for(const row of rows){const tr=el('tr'),label=el('td',row.criterion);if(rows.filter(r=>r.criterion===row.criterion).length>1)label.append(el('small',(row.required_objects||row.changed_objects||[]).join(', '),'ri-muted'));if(row.reason)label.append(el('small',row.reason,'ri-muted'));tr.append(label);
   for(const phase of ['before','after']){const cell=el('td'),ids=row[phase+'_node_ids']||[],text=row[phase]==='not_established'?'Unknown':row[phase];if(ids.length){const b=el('button',text+' ↗','ri-evidence');b.type='button';b.setAttribute('aria-label',`${row.criterion} · ${phase==='before'?'before':'first follow-up'} · ${text}`);b.onclick=()=>inspect(ids);cell.append(b);}else cell.textContent=text;tr.append(cell);}
   tr.append(el('td',LABELS[row.status],'ri-status '+row.status));body.append(tr);}table.append(body);const scroll=el('div',null,'ri-table-scroll');scroll.append(table);host.append(scroll);
  if(!p.checks.length){const note=el('p','Task-quality changes are unmeasured. Add versioned checks around the implemented change. ','ri-muted'),a=el('a','Capture guide ↗');a.href='/integration-guide#revision-impact';note.append(a);host.append(note);}
  host.append(el('p',`${p.implementation_dispatches} implementing ${p.implementation_dispatches===1?'dispatch':'dispatches'} · ${p.followup_dispatches} linked ${p.followup_dispatches===1?'follow-up':'follow-ups'}`,'ri-muted'));
  if(p.later_results.length)host.append(el('p','Later results: '+p.later_results.map(r=>r.outcome.replaceAll('_',' ')).join(' → ')+'. The first result remains the comparison.','ri-muted'));
 }
 const api={LABELS,METHODS,CHANGES,checkRows,summary,matches,badge,overview,detail};if(typeof module==='object')module.exports=api;else root.RevisionImpact=api;
})(typeof window==='object'?window:globalThis);
