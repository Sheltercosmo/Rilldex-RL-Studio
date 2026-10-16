'use strict';
(()=>{
 const $=id=>document.getElementById(id),el=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
 const status=$('analysis-data-status'),host=$('analysis-data-preview');let sequence=0,optionSequence=0,optionTimer;
 const observerTables=new Set(['graphs','nodes','edges','measurements','monitor_values','monitor_definitions']);
 const scopeFields=['experiment','observer','table','history','profile','format','publish_interval'];
 function restoreScope(){const q=new URLSearchParams(location.search);for(const name of scopeFields){const value=q.has('analysis_'+name)?q.get('analysis_'+name):(name==='experiment'?q.get('experiment'):null),control=$('analysis-'+name);if(value===null)continue;if(name==='observer'&&value&&!Array.from(control.options).some(o=>o.value===value)){control.append(ChoiceLabels.option({id:value,label:ChoiceLabels.name(value)}));}if(name==='experiment'||Array.from(control.options).some(o=>o.value===value))control.value=value;}}
 function saveScope(){const url=new URL(location.href);for(const name of scopeFields){const value=$('analysis-'+name).value;(value||name==='experiment')?url.searchParams.set('analysis_'+name,value):url.searchParams.delete('analysis_'+name);}history.replaceState(null,'',url);}
 for(const name of scopeFields)$('analysis-'+name).addEventListener('input',saveScope);
 document.querySelectorAll('a[href="#analysis-code"]').forEach(a=>a.addEventListener('click',()=>{$('analysis-code').open=true;}));
 if(location.hash==='#analysis-code')$('analysis-code').open=true;
 function scope(withObserver=false){const q=new URLSearchParams({history:$('analysis-history').value});const experiment=$('analysis-experiment').value.trim(),observer=$('analysis-observer').value;if(experiment)q.set('experiment',experiment);if(withObserver&&observer)q.set('observer',observer);return q;}
 async function options(){
  clearTimeout(optionTimer);
  const request=++optionSequence,notice=$('analysis-options-status');notice.textContent='Reading saved scopes…';
  try{
   const response=await fetch('/api/analysis/options?'+scope()),r=await response.json();if(request!==optionSequence)return;if(!response.ok)throw Error(r.error||'Could not read saved scopes');
   $('analysis-experiments').replaceChildren(...r.experiments.filter(e=>e.experiment!==null).map(row=>{const option=el('option');option.value=row.experiment;option.label=`${row.experiment} · ${row.snapshots} snapshots${row.execution_attempts?' · '+row.execution_attempts+' execution attempts':''}`;return option;}));
   const selected=$('analysis-observer').value,items=[el('option','All saved sets')];items[0].value='';
   const rows=r.observers.filter(r=>r.observer!==null).map(row=>({id:row.observer,label:row.label,suffix:`${row.snapshots} snapshot${row.snapshots===1?'':'s'}`}));
   items.push(...ChoiceLabels.choices(rows).map(ChoiceLabels.option));
   if(selected&&!items.some(o=>o.value===selected))items.push(ChoiceLabels.option({id:selected,label:ChoiceLabels.name(selected)+' · no saved records in scope'}));
   $('analysis-observer').replaceChildren(...items);$('analysis-observer').value=selected;
   notice.textContent=`${r.experiments.filter(e=>e.experiment!==null).length} recorded experiments · ${r.observers.length} observation sets${r.truncated?' · list limited':''}. Counts describe saved records, not coverage.`;
  }catch(e){if(request===optionSequence)notice.textContent=e.message;}
 }
 $('analysis-refresh').onclick=options;
 $('analysis-experiment').addEventListener('input',()=>{clearTimeout(optionTimer);optionSequence++;$('analysis-options-status').textContent='Updating saved scopes…';optionTimer=setTimeout(options,300);});
 for(const id of ['analysis-experiment','analysis-history'])$(id).addEventListener('change',options);
 for(const id of ['analysis-table','analysis-experiment','analysis-history','analysis-observer'])$(id).addEventListener('input',()=>{sequence++;host.replaceChildren();status.textContent='Scope changed. Preview again to see the selected data.';});
 $('analysis-data-form').onsubmit=async event=>{
  event.preventDefault();options();const request=++sequence,q=scope(observerTables.has($('analysis-table').value));q.set('limit','50');status.textContent='Reading saved data…';host.replaceChildren();
  try{
   const response=await fetch('/api/analysis/tables/'+$('analysis-table').value+'?'+q),r=await response.json();
   if(request!==sequence)return;if(!response.ok)throw Error(r.error||'Could not read saved data');
   if(r.available===false){status.textContent='This table was not captured in this workspace or dataset. Upgrade the collector before recording it; absence is not zero workload.';return;}
   status.textContent=`${r.rows.length} rows shown${r.truncated?' · more rows available through Python or SQL':''} · snapshot ${new Date(r.captured_at).toLocaleTimeString()}. ${r.grain}`;
   if(!r.rows.length){host.append(el('p','No saved rows in this scope. Choose another table or experiment; missing analysis is not a zero measurement.'));return;}
   const priorities=r.table==='executions'?['kind','state','environment','backend','model','record_id']:r.table==='rollouts'?['experiment','adapter','generation_step','training_step','verified_success','run_id']:r.table==='measurements'?['metric','value','status','reason','observer','run_id']:r.table==='training_records'?['experiment','record_schema','kind','sample_id','rollout_id','record_id']:['monitor_name','activity','kind','type','value','status','reason','source','target','observer','state','revision','graph_id','monitor_id','producer','run_id'];
   const columns=priorities.filter(c=>r.columns.includes(c)).slice(0,6);if(!columns.length)columns.push(...r.columns.slice(0,5));
   const wrap=el('div');wrap.className='analysis-table-scroll';wrap.tabIndex=0;wrap.setAttribute('aria-label','Saved data preview; scroll horizontally for more columns');
   const table=el('table'),head=el('thead'),tr=el('tr'),body=el('tbody'),evidence=r.columns.includes('run_id');for(const col of columns)tr.append(el('th',col.replaceAll('_',' ')));if(evidence)tr.append(el('th','Evidence'));head.append(tr);
   for(const row of r.rows){const tr=el('tr');for(const col of columns){const value=row[col]===null?'—':String(row[col]),td=el('td',value.length>100?value.slice(0,97)+'…':value);td.title=value;tr.append(td);}if(evidence){const td=el('td'),a=el('a',row.graph_id?'Open saved graph':'Open source'),q=new URLSearchParams({run:row.run_id,observer:row.graph_id?(row.observer||'source'):'source',level:'units'});if(row.graph_id)q.set('graph',row.graph_id);a.href='/semantic-map?'+q;td.append(a);tr.append(td);}body.append(tr);}
   table.append(head,body);wrap.append(table);host.append(wrap,el('small','Preview shows selected columns. Workspace.table(...) exposes all fields, evidence references and missing-value reasons without exporting.'));
  }catch(e){if(request===sequence)status.textContent=e.message;}
 };
 $('analysis-export').onclick=async()=>{
  const button=$('analysis-export'),notice=$('analysis-export-status'),q=scope(true),profile=$('analysis-profile').value;q.set('format',$('analysis-format').value);if(profile==='table')q.set('table',$('analysis-table').value);else q.set('profile',profile);
  const label=`${q.get('experiment')||'all experiments'} · ${q.get('observer')||'all saved sets'} · ${profile==='table'?q.get('table'):profile}`;button.disabled=true;notice.textContent='Preparing '+label+'…';
  try{const r=await fetch('/api/analysis/export?'+q);if(!r.ok){const error=await r.json();throw Error(error.error||'Export failed');}
   const url=URL.createObjectURL(await r.blob()),a=el('a');a.href=url;a.download='research-data-'+(profile==='table'?q.get('table'):profile)+'.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
   notice.textContent='Export prepared: '+label+'. Includes snapshot scope and integrity manifest.';
  }catch(e){notice.textContent=e.message;}finally{button.disabled=false;}
 };
 $('analysis-workflow').onclick=async()=>{
  const button=$('analysis-workflow'),notice=$('analysis-workflow-status');
  const analysis={experiment:$('analysis-experiment').value.trim()||null,observer:$('analysis-observer').value||null,history:$('analysis-history').value==='1',profile:$('analysis-profile').value,table:$('analysis-table').value,format:$('analysis-format').value,publish_interval:Number($('analysis-publish_interval').value)};
  button.disabled=true;notice.textContent='Packaging your selection and the local runtime…';
  try{
   const r=await fetch('/api/workflows/package',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({analysis})});
   if(!r.ok){const error=await r.json();throw Error(error.error||'Could not package workflow');}
   const url=URL.createObjectURL(await r.blob()),a=el('a');a.href=url;a.download='rilldex-analysis-workflow.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
   notice.textContent='Ready: '+(analysis.experiment||'all experiments')+' · '+(analysis.observer||'all saved sets')+'. Unzip on the database host, review rilldex.json, then run run.py. No data has been exported or analysis started.';
  }catch(e){notice.textContent=e.message;}finally{button.disabled=false;}
 };
 // Browser history may restore form fields after scripts run.
 window.addEventListener('pageshow',()=>{clearTimeout(optionTimer);optionTimer=setTimeout(()=>{restoreScope();options();},0);});
})();
