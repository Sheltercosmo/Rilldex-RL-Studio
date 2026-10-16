'use strict';
(()=>{
 const $=s=>document.querySelector(s),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 let rendered=null;
 const relocationDrafts=new Map();
 const time=t=>t?new Date(t).toLocaleTimeString():'not yet';
 async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d;}
 function error(e){$('#error').hidden=false;$('#error').textContent=e.message;}
 for(const example of document.querySelectorAll('#capture-example,#telemetry-example')){
  example.textContent=example.textContent.replace('http://127.0.0.1:8765',location.origin);
 }
 let inputs=null;
 function recordFormats(select,mode){
  if(!inputs)return;
  const value=select.value,groups=new Map();select.replaceChildren();
  for(const f of inputs.formats.filter(f=>!mode||f.collection_modes.includes(mode))){
   let group=select;if(f.group){if(!groups.has(f.group)){const g=el('optgroup');g.label=f.group;groups.set(f.group,g);select.append(g);}group=groups.get(f.group);}
   const option=el('option',f.label);option.value=f.id;group.append(option);
  }
  select.value=[...select.options].some(o=>o.value===value)?value:'auto';
 }
 function collectionMode(resetPattern=true){
  const mode=$('#collection-mode').value,portable=mode!=='native';
  recordFormats($('#format'),mode);
  $('#export-pattern-label').hidden=!portable;$('#snapshot-state-label').hidden=mode!=='snapshots';$('#collection-experiment').required=portable;
  if(resetPattern)$('#export-pattern').value=mode==='snapshots'?'*.json':'*.jsonl';
  $('#export-pattern').placeholder=mode==='snapshots'?'rollout-*.json':'worker-*.jsonl';
  $('#collection-help').textContent=inputs?.modes.find(m=>m.id===mode)?.detail||'Choose the file layout, then check a sample. The record schema is independent of your training framework.';
 }
 $('#collection-mode').onchange=collectionMode;
 function deploymentFormats(){recordFormats($('#deploy-format'),$('#deploy-case').value==='offline'?undefined:$('#deploy-mode').value);}
 $('#deploy-mode').addEventListener('change',deploymentFormats);
 $('#deploy-case').addEventListener('change',deploymentFormats);
 function definition(){
  let metadata;try{metadata=JSON.parse($('#metadata').value);}catch{throw Error('Metadata must be valid JSON');}
  if(!metadata||typeof metadata!=='object'||Array.isArray(metadata))throw Error('Metadata must be an object');
  const experiment=$('#collection-experiment').value.trim();
  if(experiment){if(metadata.experiment&&metadata.experiment!==experiment)throw Error('Experiment field conflicts with metadata JSON');metadata.experiment=experiment;}
  const config={root:$('#root').value.trim(),producer:$('#producer').value.trim(),format:$('#format').value,interval:Number($('#interval').value),max_files:Number($('#max-files').value),metadata};
  const mode=$('#collection-mode').value;
  if(mode!=='native')Object.assign(config,{mode,pattern:$('#export-pattern').value.trim()});
  if(mode==='snapshots')config.snapshot_state=$('#snapshot-state').value;
  return config;
 }
 function directoryCheck(p){
  const host=$('#preview-result');host.replaceChildren();if(p.cloud){host.append(el('p',p.cloud.copied+' cloud objects checked · '+p.cloud.pending+' beyond this preview'));for(const e of p.cloud.errors||[])host.append(el('p',e.path+': '+e.error));if(p.cloud.errors?.length&&!p.files)return;}
  if(!p.files){host.append(el('h3','Ready to connect an empty directory'),el('p','No matching output yet. Connect now to collect files as the job writes them. If output already exists, check the route, directory and filename pattern.'));return;}
  const valid=p.samples.filter(s=>s.status==='valid').length,issues=p.samples.filter(s=>s.status==='deferred'),waiting=p.samples.filter(s=>s.status==='waiting'),limited=p.samples.filter(s=>s.status==='limited');
  host.append(el('h3',valid?`${valid} sampled records decoded`:'No usable records in this sample'),el('p',`${p.checked_files} of ${p.files} matching files checked · ${issues.length} errors · ${waiting.length} waiting${limited.length?' · '+limited.length+' preview limits reached':''}`,'muted'));
  const c=p.coverage;
  if(c){
   const n=c.total_records,facts=el('div',undefined,'intake-coverage');
   const reward=c.metric_coverage.recorded_reward?.available||0,linked=c.runs.filter(r=>r.linked_responses>0).length;
   for(const [title,value,detail] of [
    ['Source maps',`${n} / ${n}`,'Recorded events and available native connections.'],
    ['Action / feedback',String(c.recorded_actions)+' actions',`${linked} of ${c.runs.length} preview records contain linked responses.`],
    ['Recorded reward',`${reward} / ${n}`,'Missing scores remain unavailable, never zero.'],
    ['Training coordinates',`${c.declared_training_coordinates} / ${n}`,'Requires experiment, step and what that step measures.']
   ]){const item=el('div');item.append(el('span',title),el('strong',value),el('small',detail));facts.append(item);}
   host.append(facts,el('p','Plans, strategies and revision analysis require saved semantic observations. Source capture does not run an observer.','intake-boundary'));
   if(c.declared_training_coordinates<n)host.append(el('p','For training trends, include training_step and training_step_basis with each rollout. Do not use arrival time as a training step.','intake-next'));
  }
  const details=el('details');details.open=!!(issues.length||limited.length);details.append(el('summary','Sample files and validation results'));
  for(const sample of p.samples){const row=el('div',undefined,'intake-sample');row.dataset.status=sample.status;row.append(el('strong',sample.path+(sample.line?' · line '+sample.line:'')),el('span',sample.status==='valid'?'Decoded · '+sample.adapter:sample.detail));details.append(row);}
  host.append(details,el('small',p.note,'muted'));
 }
 let previewSequence=0;
 $('#connection-form').addEventListener('input',()=>{previewSequence++;if($('#preview-result').textContent)$('#preview-result').textContent='Settings changed. Check the directory again to update this preview.';});
 function locationEditor(c,open){
  if(c.enabled||c.stopping||c.running||c.waiting_for_owner)return null;
  const details=el('details',undefined,'connection-location');details.dataset.connection=c.id;details.open=open;
  details.append(el('summary','Change output location'));
  const draft=relocationDrafts.get(c.id)||{root:c.config.root,task_root:c.config.task_root||''};
  const label=el('label','Output directory or cloud prefix'),input=el('input');input.id='location-'+c.id;input.value=draft.root;input.oninput=()=>{draft.root=input.value;relocationDrafts.set(c.id,draft);};label.append(input);details.append(label);
  if(c.config.task_root){const taskLabel=el('label','Task files directory (optional)'),task=el('input');task.id='task-location-'+c.id;task.value=draft.task_root;task.oninput=()=>{draft.task_root=task.value;relocationDrafts.set(c.id,draft);};taskLabel.append(task);details.append(taskLabel);}
  details.append(el('p','Keep the same relative filenames. Producer identity and accepted rows stay attached; resume after saving the new location.','muted'));
  const actions=el('div',undefined,'form-actions'),button=el('button','Save location'),status=el('p');button.type='button';status.setAttribute('role','status');actions.append(button);details.append(actions,status);
  button.onclick=async()=>{button.disabled=true;status.textContent='Checking the new directory…';try{const body={root:input.value.trim()};if(c.config.task_root)body.task_root=draft.task_root.trim()||null;await api('/api/connections/'+c.id+'/location',body);relocationDrafts.delete(c.id);render(await api('/api/connections'));}catch(e){status.textContent=e.message;button.disabled=false;}};
  return details;
 }
 function producers(rows){
  const host=$('#producer-health');host.replaceChildren();$('#worker-section').dataset.empty=String(!rows.length);
  if(!rows.length){host.append(el('p','No workers have reported or delivered snapshots yet.','muted'));return;}
  const labels={current:'Queue clear at last report',pending:'Delivery pending',blocked:'Blocked delivery',stale:'Report overdue',stopped:'Sender stopped',unreported:'Queue not reported'};
  for(const row of rows){const report=row.report,card=el('article',undefined,'producer-card');card.dataset.producer=row.producer;card.dataset.status=row.status;
   const head=el('div',undefined,'connection-head');head.append(el('h3',row.producer),el('span',labels[row.status],'health'+(['blocked','stale'].includes(row.status)||report?.phase==='stopped'&&(report.pending||report.blocked)?' issue':'')));card.append(head);
   const facts=el('div',undefined,'producer-facts');for(const [value,label] of [[report?.pending,'Pending snapshots'],[report?.blocked,'Blocked snapshots'],[row.received_revisions,'Received revisions'],[row.received_rollouts,'Received rollouts']]){const fact=el('div');fact.append(el('strong',value===undefined?'—':value.toLocaleString()),el('small',label));facts.append(fact);}card.append(facts);
   if(report){const bytes=n=>(n/1048576).toFixed(2)+' MiB';card.append(el('p',`${bytes(report.pending_bytes)} / ${bytes(report.max_pending_bytes)} pending capacity · oldest queued ${report.oldest_pending_seconds===null?'none':report.oldest_pending_seconds+'s at report'}`));
    const capacity=el('progress');capacity.max=report.max_pending_bytes;capacity.value=Math.min(report.pending_bytes,report.max_pending_bytes);capacity.setAttribute('aria-label','Pending outbox capacity');card.append(capacity,el('p',`Report received ${time(row.reported_at)} · ${row.report_age_seconds}s ago · report #${report.sequence}`,'muted'));
   }else card.append(el('p','Enable .start(report_status=True) on this worker to see its queue. No zero-backlog assumption is made.','muted'));
   if(report?.blocked)card.append(el('p','Inspect this worker’s outbox for the server/schema error. Correct it before retrying blocked revisions.','producer-help'));
   if(row.status==='stale')card.append(el('p','The report may be delayed, disconnected or stopped. Last queue values may no longer be current.','producer-help'));
   host.append(card);
  }
 }
 function connectionState(c){
  if(c.stopping||(!c.enabled&&(c.running||c.waiting_for_owner)))return c.enabled?'Waiting to resume':'Pausing · finishing current read';
  if(!c.enabled)return 'Paused';
  if(c.waiting_for_owner)return 'Another collector is active';
  if(c.collector_error||c.status.error)return 'Collection error';
  if(c.status.cloud?.state==='cached_only')return 'Cloud unavailable · using cached output';
  if(c.status.cloud?.state==='partial')return 'Retrying cloud downloads';
  if(c.status.deferred)return 'Retrying incomplete or invalid files';
  return c.running?(!c.status.checked_at?'Checking source':c.status.backlog?'Catching up':c.status.waiting?'Waiting for the last newline':c.status.files?'Watching':'Waiting for output files'):'Starting…';
 }
 function render(s){if(s.error)error(Error(s.error));const rows=s.connections||[],active=rows.filter(c=>c.running),problems=rows.filter(c=>c.enabled&&(c.status.error||c.status.deferred));
  $('#capture-state').textContent=active.length?`${active.length} watching${problems.length?' · '+problems.length+' need attention':''}`:rows.some(c=>c.stopping)?'Collection stopping':rows.some(c=>c.waiting_for_owner)?'Another collector is active':rows.some(c=>c.enabled)?'Starting collection':rows.length?'Sources paused':'No source connected';
  $('#source-state').textContent=s.recent_rollouts?.length?'Last received '+time(s.recent_rollouts[0].created_at):'Waiting for a rollout';
  $('#analysis-state').textContent=s.analysis?.error?'Monitor error':s.analysis?.updating?'Updating monitors':s.analysis?.checked_at?'Checked '+time(s.analysis.checked_at):'Waiting for analysis';
  const fileProducers=new Set(rows.map(c=>c.producer));producers((s.producers||[]).filter(p=>p.report||!fileProducers.has(p.producer)));
  const signature=JSON.stringify([rows,s.recent_rollouts]);if(signature===rendered)return;rendered=signature;
  const focusedInput=document.activeElement?.id,openedLocations=new Set([...document.querySelectorAll('.connection-location[open]')].map(d=>d.dataset.connection));const opened=new Set([...document.querySelectorAll('.connection')].filter(d=>d.querySelector('details')?.open).map(d=>d.dataset.connection)),focused=document.activeElement?.closest('.connection')?.dataset.connection;const host=$('#connections');host.replaceChildren();if(!rows.length)host.append(el('p','No sources connected. Use the form above to watch a job, or send snapshots from training code.','muted'));
  for(const c of rows){const d=el('article',undefined,'connection'),h=el('div',undefined,'connection-head'),title=el('div');d.dataset.connection=c.id;title.append(el('h3',c.producer),el('span',connectionState(c),'health'+(c.collector_error||c.status.error||c.status.deferred?' issue':c.stopping||c.waiting_for_owner?' pending':!c.enabled?' paused':'')));const button=el('button',c.enabled?'Pause':'Resume');button.onclick=async()=>{button.disabled=true;try{await api('/api/connections/'+c.id+'/state',{enabled:!c.enabled});render(await api('/api/connections'));}catch(e){error(e);button.disabled=false;}};h.append(title,button);d.append(h,el('p',c.config.root));if(c.stopping)d.append(el('p','The current read is still finishing. Collection will '+(c.enabled?'resume after it stops.':'stay paused once it returns. You can change the output location after it stops.'),'producer-help'));if(c.waiting_for_owner)d.append(el('p','This producer is already being collected by another tracker or watch process using this workspace. This connection waits and takes over when that reader stops. Other producers can continue.','producer-help'));if(c.collector_error)d.append(el('pre',c.collector_error));if(c.status.cloud){d.append(el('p',c.status.cloud.state==='cached_only'?'Cloud check failed. Processing downloaded records; new remote output cannot be checked yet.':`${c.status.cloud.copied} objects fetched · ${c.status.cloud.unchanged} unchanged · ${c.status.cloud.pending} waiting for download`,'muted'));d.append(el('p','Last complete cloud sync '+(c.status.last_cloud_sync_at?time(c.status.last_cloud_sync_at):'not recorded'),'muted'));}const facts=el('p',undefined,'facts');for(const text of [`${c.status.files||0} files scanned`,`${c.received?.received_rollouts??'—'} rollouts recorded`,`${c.received?.received_revisions??'—'} revisions recorded`,`check every ${c.config.interval}s`,`scan ${c.status.scan_seconds??'—'}s`,`last receipt ${time(c.received?.last_receipt_at)}`])facts.append(el('span',text));d.append(facts);if(c.status.backlog)d.append(el('p',c.status.cloud?`${c.status.backlog} sources have pending downloads or records; collection continues.`:`${c.status.backlog} files have queued rows; continuing on the next poll.`));if(c.status.waiting)d.append(el('p',`${c.status.waiting} files have an unfinished last line. Append a newline when the record is complete.`));if(c.status.error)d.append(el('pre',c.status.error));if(c.status.errors?.length){const details=el('details'),summary=el('summary',`${c.status.deferred} collection issues · automatically retried`);details.open=opened.has(c.id);details.append(summary);for(const x of c.status.errors)details.append(el('pre',x.path+'\n'+x.error));d.append(details);}const location=locationEditor(c,openedLocations.has(c.id));if(location)d.append(location);host.append(d);if(focused===c.id)(document.getElementById(focusedInput)||button).focus({preventScroll:true});}
  const table=el('table'),head=el('tr');for(const x of ['Rollout / producer','Revision','State','Training step','Received'])head.append(el('th',x));table.append(head);
  for(const r of s.recent_rollouts||[]){const tr=el('tr'),td=el('td'),a=el('a',r.export_path?`${r.export_path} · line ${r.source_line}`:r.rollout_id);a.href='/semantic-map?run='+encodeURIComponent(r.run_id)+'&observer=source';td.append(a,el('small',r.producer));tr.append(td,el('td',r.revision),el('td',r.state.replaceAll('_',' ')),el('td',r.training_step??'Not recorded'),el('td',time(r.created_at)));table.append(tr);}$('#recent').replaceChildren(...((s.recent_rollouts||[]).length?[table]:[el('p','No live deliveries yet. Imported snapshots are available in Rollouts.','muted')]));
 }
 $('#preview').onclick=async()=>{const sequence=++previewSequence;$('#preview').disabled=true;try{$('#error').hidden=true;$('#preview-result').textContent='Decoding a bounded sample…';const p=await api('/api/connections/preview',definition());if(sequence===previewSequence)directoryCheck(p);}catch(e){if(sequence===previewSequence){$('#preview-result').replaceChildren();error(e);}}finally{$('#preview').disabled=false;}};
 $('#connection-form').onsubmit=async e=>{e.preventDefault();$('#connect').disabled=true;try{$('#error').hidden=true;await api('/api/connections',definition());$('#preview-result').textContent='Connected. Collection continues in the background and resumes when the server restarts.';render(await api('/api/connections'));}catch(e){error(e);}finally{$('#connect').disabled=false;}};
 function routes(c){
  inputs=c.inputs;
  for(const select of [$('#collection-mode'),$('#deploy-mode')]){const value=select.value;select.replaceChildren(...inputs.modes.map(m=>{const o=el('option',m.label);o.value=m.id;return o;}));select.value=value||inputs.default_collection_mode;}
  collectionMode(false);recordFormats($('#upload-format'));deploymentFormats();
  $('#integration-scope').textContent=c.scope+' Reviewed '+c.reviewed_at+'.';const table=el('table'),head=el('tr');for(const label of ['Framework / environment','Capture route','Validation / boundary'])head.append(el('th',label));table.append(head);for(const route of c.routes){const tr=el('tr'),name=el('td'),detail=el('td');name.append(el('strong',route.name));for(const [label,url]of route.sources){const a=el('a',label);a.href=url;a.target='_blank';a.rel='noopener';name.append(el('br'),a);}detail.append(el('strong',route.validation),el('p',route.boundary));tr.append(name,el('td',route.route),detail);table.append(tr);}$('#integration-routes').replaceChildren(table);
 }
 function preflight(name,result){const card=el('article',undefined,'preflight-card');card.append(el('h3',name));for(const run of result.runs){card.append(el('p',`${run.adapter_version} · ${run.trajectory_count} source timelines · ${run.linked_responses} linked responses · ${run.unlinked_responses} unlinked`));sourceUnit(card,run.source_unit);const functions=el('div',undefined,'function-grid');for(const f of run.functions){const box=el('div');box.append(el('strong',f.name),el('small',f.state.replaceAll('_',' ')),el('p',f.detail));functions.append(box);}card.append(functions);const details=el('details');details.open=true;details.append(el('summary','Source measurements for this snapshot'));const table=el('table'),head=el('tr');for(const t of ['Measure','Value','Meaning / missing evidence'])head.append(el('th',t));table.append(head);for(const metric of run.metrics){const tr=el('tr');tr.dataset.metric=metric.id;tr.append(el('td',metric.label),el('td',metric.value===null?'Unavailable':String(Number(metric.value.toFixed(4)))),el('td',metric.reason||metric.definition));table.append(tr);}const wrap=el('div',undefined,'table-wrap');wrap.append(table);details.append(wrap);card.append(details);const warnings=el('details');warnings.append(el('summary','Source boundaries and supplied clocks'),el('pre',JSON.stringify(run.clocks,null,2)));for(const w of run.warnings)warnings.append(el('p',w));card.append(warnings,el('p',run.note,'muted'));}$('#preflight').append(card);}
 function sourceUnit(host,unit){if(unit){const line=el('p',undefined,'producer-help');line.append(el('strong',unit.label+(unit.records!==undefined?' · '+unit.records+' records':'')),el('br'),document.createTextNode(unit.detail));host.append(line);}}
 function batchPreflight(name,result){
  if(result.total_rollouts<=1){preflight(name,result);return;}
  const card=el('article',undefined,'preflight-card batch-preflight');card.append(el('h3',name));
  const stats=el('div',undefined,'capture-contracts');for(const [value,label]of [[result.total_records??result.total_rollouts,'records validated'],[result.recorded_actions,'recorded agent actions'],[result.declared_training_coordinates,'records with declared training coordinates']]){const box=el('div');box.append(el('strong',value.toLocaleString()),el('small',label));stats.append(box);}card.append(stats,el('p',result.note,'muted'));
  for(const unit of result.source_units||[])sourceUnit(card,unit);
  const table=el('table'),head=el('tr');for(const text of ['Source format','Records'])head.append(el('th',text));table.append(head);for(const [format,n]of Object.entries(result.formats)){const tr=el('tr');tr.append(el('td',format),el('td',n));table.append(tr);}card.append(table);
  const details=el('details');details.append(el('summary','Measurement coverage across all records'));for(const key of ['recorded_reward','recorded_success','feedback_link_rate','environment_episode_return']){const c=result.metric_coverage[key];if(c)details.append(el('p',key.replaceAll('_',' ')+': '+c.available+' available · '+c.missing+' unavailable'));}for(const row of result.warning_counts)details.append(el('p',row.rollouts+' records · '+row.warning));card.append(details);
  const label=el('label','Inspect a preview record'),select=el('select'),empty=el('option','Choose a record');empty.value='';select.append(empty);for(const [i,run]of result.runs.entries()){const option=el('option',(i+1)+' · '+(run.clocks.sample_id||run.source_id));option.value=i;select.append(option);}label.append(select);card.append(label,el('small',`First ${result.preview_rollouts} of ${result.total_records??result.total_rollouts} shown here. Import to browse every record.`));
  const preview=el('div');select.onchange=()=>{preview.replaceChildren();if(select.value!==''){preflight('Record '+(Number(select.value)+1),{runs:[result.runs[Number(select.value)]]});preview.append($('#preflight').lastElementChild);}};card.append(preview);$('#preflight').append(card);
 }
 function base64(bytes){let text='';for(let i=0;i<bytes.length;i+=32768)text+=String.fromCharCode(...bytes.subarray(i,i+32768));return btoa(text);}
 async function snapshots(save){
  $('#check-snapshot').disabled=true;$('#import-snapshot').disabled=true;const report=[];$('#preflight').replaceChildren();$('#import-links').replaceChildren();
  try{
   if(!$('#upload-files').files.length)throw Error('Choose at least one snapshot.');let metadata;
   try{metadata=JSON.parse($('#upload-metadata').value);}catch{throw Error('Snapshot metadata must be valid JSON');}
   if(!metadata||Array.isArray(metadata)||typeof metadata!=='object')throw Error('Snapshot metadata must be an object');
   const experiment=$('#upload-experiment').value.trim();if(experiment){if(metadata.experiment&&metadata.experiment!==experiment)throw Error('Experiment field conflicts with metadata JSON');metadata.experiment=experiment;}
   for(const file of $('#upload-files').files){
    try{
     if(file.size>14*1024*1024)throw Error('Browser uploads allow 14 MiB of source data. Use python -m rilldex import for larger files (up to 100 MB), or a live producer connection.');
     $('#upload-result').textContent=report.concat(file.name+': validating every record…').join('\n');
     const body={file:{name:file.name,base64:base64(new Uint8Array(await file.arrayBuffer()))},format:$('#upload-format').value,metadata};
     const checked=await api('/api/import-file/check',body);batchPreflight(file.name,checked);
     if(save){$('#upload-result').textContent=report.concat(file.name+': saving '+(checked.total_records??checked.total_rollouts)+' records…').join('\n');const r=await api('/api/import-file',body);report.push(file.name+': '+r.runs.filter(x=>x.imported).length+' imported, '+r.runs.filter(x=>!x.imported).length+' already present');const a=el('a','Browse imported records from '+file.name);a.href='/runs'+(metadata.experiment?'?experiment='+encodeURIComponent(metadata.experiment):'');$('#import-links').append(a,el('br'));for(const row of r.runs.slice(0,3)){const link=el('a','Open '+row.id);link.href='/semantic-map?run='+encodeURIComponent(row.id)+'&observer=source';$('#import-links').append(link,el('br'));}}
     else report.push(file.name+': checked, nothing saved');
    }catch(err){report.push(file.name+': '+err.message);}
    $('#upload-result').textContent=report.join('\n');
   }
  }catch(e){$('#upload-result').textContent=e.message;}finally{$('#check-snapshot').disabled=false;$('#import-snapshot').disabled=false;}
 }
 const fileInput=$('#upload-files');
 function fileSelection(){const files=[...fileInput.files];$('#file-selection').textContent=files.length?files.map(f=>f.name).join(', '):'No files selected';$('#clear-files').hidden=!files.length;$('#upload-result').textContent='';$('#preflight').replaceChildren();$('#import-links').replaceChildren();}
 $('#choose-files').onclick=()=>fileInput.click();fileInput.addEventListener('change',fileSelection);
 $('#clear-files').onclick=()=>{fileInput.value='';fileSelection();$('#choose-files').focus();};
 $('#check-snapshot').onclick=()=>snapshots(false);
 $('#upload-form').onsubmit=e=>{e.preventDefault();snapshots(true);};
 window.addEventListener('tracker-live',e=>{render(e.detail);$('#stream-state').textContent='Connected · updates pushed by server';});
 window.addEventListener('tracker-disconnected',()=>{$('#stream-state').textContent='Disconnected · reconnecting';});
 api('/api/connections').then(render).catch(error);
 api('/api/integrations').then(routes).catch(error);
 async function investigationChecks(){
  const form=$('#readiness-form');if(!form)return;
  const status=$('#question-status'),results=$('#readiness-results'),requested=new URLSearchParams(location.search);
  let config,receipt,requestSequence=0,liveRevision=null;
  const names={available:'Current value',choose_measure:'Choose a measure',source_missing:'Source missing',outside_measure_population:'Outside measure scope',incomplete_source:'Source unfinished',source_graph_missing:'Source graph missing',observation_missing:'Observation missing',not_materialized:'Calculation pending',stale_measurement:'Calculation outdated',unresolved_followup:'Follow-up unresolved',no_recorded_opportunities:'No recorded opportunities',unavailable:'Value unavailable',error:'Calculation error',waiting:'Awaiting observation'};
  function choices(select,rows,current,placeholder){select.replaceChildren();if(placeholder||!rows.length){const o=el('option',!rows.length?(select.id==='readiness-filter'?'No recorded selection rules':select.id==='readiness-monitor'?'No saved measures for this analysis':placeholder||'No choices available'):placeholder);o.value='';select.append(o);}for(const [id,label] of rows){select.append(ChoiceLabels.option({id,label}));}select.value=rows.some(([id])=>id===current)?current:placeholder||!rows.length?'':rows[0][0];select.disabled=!rows.length;}
  function measures(){const recipe=$('#readiness-recipe').value,prior=$('#readiness-monitor').value;choices($('#readiness-monitor'),ChoiceLabels.choices(config.monitors.filter(m=>m.recipes.includes(recipe)).map(m=>({id:m.id,label:m.name,suffix:m.enabled?'':'paused'})),{noun:'Monitor',fallback:'Saved monitor'}).map(m=>[m.id,m.label]),prior,'Choose a measure');$('#readiness-filter-label').hidden=recipe!=='selection';}
  function body(){const value={recipe:$('#readiness-recipe').value,experiment:$('#readiness-experiment').value};if($('#readiness-monitor').value)value.monitor=$('#readiness-monitor').value;if(value.recipe==='selection'&&$('#readiness-filter').value)value.selection=$('#readiness-filter').value;return value;}
  function persist(value){const url=new URL(location.href);for(const k of ['recipe','experiment','monitor','selection']){if(value[k])url.searchParams.set(k,value[k]);else url.searchParams.delete(k);}history.replaceState(null,'',url);}
  function render(data){
   results.replaceChildren();const cards=el('div',undefined,'readiness-requirements');
   for(const row of data.requirements){const card=el('article');card.dataset.requirement=row.id;card.append(el('strong',row.label),el('small',row.state.replaceAll('_',' ')),el('p',row.detail));cards.append(card);}results.append(cards);
   const summary=el('p',`${data.total_rows} ${data.recipe.grain} records · ${data.summary.distinct_sources} distinct joined source rollouts`);summary.id='readiness-summary';results.append(summary);
   const counts=el('div',undefined,'readiness-counts');for(const [state,n]of Object.entries(data.summary.row_statuses)){const item=el('span',`${n} ${names[state]||state}`);item.dataset.state=state;counts.append(item);}results.append(counts);
   if(data.recipe.opportunity_label){const o=data.summary.opportunity_totals;results.append(el('p',o.opportunities==null?'Opportunity counts are unavailable until a current calculation is recorded.':`${o.opportunities} ${data.recipe.opportunity_label} · ${o.denominator} decidable · ${o.unknown} unresolved, across distinct source rollouts with current calculations.`));}
   if(data.selection){const p=el('p',data.selection.cohorts_with_measured_sides+' cohorts have current values on both sides of the selected rule. Counts above include all recorded splits; comparisons keep the following cohorts separate.');p.id='readiness-selection-overlap';results.append(p);const table=el('table'),head=el('tr');for(const text of ['Split / environment / clock','Samples','Decisions','Both sides measured','Sources shared across sides'])head.append(el('th',text));table.append(head);for(const c of data.selection.cohorts){const row=el('tr'),context=el('td');context.append(el('strong',c.cohort.split),el('small',c.cohort.environment||'Environment not recorded'),el('small',c.cohort.step_basis||'Clock not recorded'));const details=el('details');details.append(el('summary','Cohort definition'),el('pre',JSON.stringify(c.cohort,null,2)));context.append(details);row.append(context,el('td',c.samples),el('td',Object.entries(c.decisions).map(([key,n])=>n+' '+key.replaceAll('_',' ')).join(' · ')),el('td',c.both_sides_measured?'Recorded':'Not established'),el('td',c.shared_source_rollouts));table.append(row);}const wrap=el('div',undefined,'table-wrap readiness-table');wrap.id='readiness-cohorts';wrap.append(table);results.append(wrap);if(data.selection.orphans||data.selection.conflicting_declarations)results.append(el('p',`${data.selection.orphans} sample identities have facts without a declaration; ${data.selection.conflicting_declarations} have conflicting declarations. They are excluded from the declared population.`,'readiness-warning'));}
   const health=el('details'),h=data.training_health;health.append(el('summary','Training evidence and score status'),el('p',h.capture_status==='schema_unavailable'?'Training capture is unavailable in this database.':`${h.declared_samples} declared samples · ${h.samples_without_score_records} without score records · ${h.samples_with_optimizer_membership} with recorded optimizer membership`));for(const [key,n]of Object.entries(h.score_record_statuses))health.append(el('p',`${n} score component records: ${key}`));health.append(el('p',h.detail));results.append(health);
   const table=el('table'),head=el('tr');for(const label of [data.scope.recipe==='selection'?'Sample / source':'Rollout','Evidence status','Recorded value','Inspect'])head.append(el('th',label));table.append(head);
   for(const row of data.rows){const tr=el('tr'),identity=el('td'),m=row.measurement;identity.append(el('strong',row.sample_id||row.task_id||row.run_id||'Unmapped source'));if(row.producer)identity.append(el('small',row.producer));if(row.sample_id)identity.append(el('small',row.run_id?'Source '+row.run_id:row.join_status));const detail=el('td',names[m.status]||m.status);if(row.decision)detail.append(el('small','Selection: '+row.decision.replaceAll('_',' ')));if(m.reason)detail.append(el('small',m.reason));const value=el('td',m.value==null?'—':String(m.value));if(m.unknown!=null)value.append(el('small',m.unknown+' unresolved opportunities'));const evidence=el('td');if(row.evidence_url){const link=el('a','Open evidence');link.href=row.evidence_url;evidence.append(link);}else evidence.append(el('span','Deliver the pinned source'));tr.append(identity,detail,value,evidence);table.append(tr);}const wrap=el('div',undefined,'table-wrap readiness-table');wrap.tabIndex=0;wrap.setAttribute('aria-label','Investigation evidence cases');wrap.append(table);results.append(wrap);
   const pager=el('div',undefined,'form-actions');for(const [label,offset]of [['Previous',data.offset-data.limit],['Next',data.next_offset]]){const b=el('button',label);b.type='button';b.disabled=offset==null||offset<0;b.onclick=()=>load(offset);pager.append(b);}pager.append(el('span',data.total_rows?`${data.offset+1}–${Math.min(data.offset+data.rows.length,data.total_rows)} of ${data.total_rows}`:'No declared records'));results.append(pager,el('p',data.notice,'muted'));
   const validation=el('details');validation.append(el('summary','Definition and validation boundary'),el('p',data.validation.detail),el('p',data.validation.boundary||''),el('pre',JSON.stringify({revision:data.revision,scope:data.scope,monitor:data.monitor},null,2)));results.append(validation);
   $('#question-configure').href=data.configure_url;const next=$('#readiness-continue');next.href=data.continue_url;next.hidden=false;next.textContent=data.scope.recipe==='selection'?'Open selection comparison →':'Open selected monitor →';
  }
  async function load(offset=0){
   if(!$('#readiness-experiment').value){status.textContent='Import data with an experiment identity or connect a producer to begin.';return;}
   const sequence=++requestSequence,value=body();if(offset){value.offset=offset;value.expected_revision=receipt.revision;}
   $('#readiness-check').disabled=true;status.textContent='Checking recorded evidence…';$('#readiness-continue').hidden=true;results.replaceChildren();
   try{const data=await api('/api/investigation-readiness',value);if(sequence!==requestSequence)return;receipt=data;choices($('#readiness-filter'),ChoiceLabels.choices(data.selection_options.map(f=>({id:f.id,label:f.filter,detail:f.definition+' · '+f.producer})),{noun:'Rule',fallback:'Selection rule'}).map(f=>[f.id,f.label]),value.selection,'Choose a recorded rule');render(data);persist(data.scope);status.textContent='Evidence checked · saved measurements only · no model calls';}
   catch(e){if(sequence!==requestSequence)return;receipt=null;results.replaceChildren();status.textContent=e.message;}
   finally{if(sequence===requestSequence)$('#readiness-check').disabled=false;}
  }
  try{const response=await fetch('/api/investigation-readiness/options');if(response.status===404){status.textContent='This running collector does not yet provide investigation evidence checks. Existing imports remain available.';return;}if(!response.ok)throw Error('Investigation checks are unavailable');config=await response.json();choices($('#readiness-experiment'),config.experiments.map(e=>[e,e]),requested.get('experiment'),'Choose an experiment');choices($('#readiness-recipe'),config.recipes.map(r=>[r.id,r.label]),requested.get('recipe')||'selection');if(!$('#readiness-recipe').value)$('#readiness-recipe').value='selection';measures();if([...$('#readiness-monitor').options].some(o=>o.value===requested.get('monitor')))$('#readiness-monitor').value=requested.get('monitor');if(requested.get('selection'))choices($('#readiness-filter'),[[requested.get('selection'),'Requested rule']],requested.get('selection'));form.hidden=false;status.textContent='Select an experiment to inspect its evidence.';if($('#readiness-experiment').value)await load();}
  catch(e){status.textContent=e.message;return;}
  async function refreshChoices(){const next=await api('/api/investigation-readiness/options');config=next;choices($('#readiness-experiment'),config.experiments.map(e=>[e,e]),$('#readiness-experiment').value,'Choose an experiment');measures();}
  form.onsubmit=async e=>{e.preventDefault();try{await refreshChoices();await load();}catch(err){status.textContent=err.message;}};$('#readiness-experiment').onchange=()=>{choices($('#readiness-filter'),[],null,'Choose an experiment first');load();};$('#readiness-recipe').onchange=()=>{measures();choices($('#readiness-filter'),[],null,'Choose an experiment first');load();};$('#readiness-monitor').onchange=()=>load();$('#readiness-filter').onchange=()=>load();
  window.addEventListener('tracker-live',e=>{const revision=JSON.stringify([e.detail.source_revision,e.detail.training_revision,e.detail.analysis?.revision]);if(liveRevision!==null&&revision!==liveRevision){if(receipt)status.textContent='New data available. Use Refresh inputs to update this view.';refreshChoices().catch(err=>{status.textContent=err.message;});}liveRevision=revision;});
 }
 investigationChecks();
})();

// Presentation-only capture routes. Forms retain their values when switching.
(()=>{
 const groups={setup:'setup',import:'sources',watch:'sources',code:'sources',config:'sources',readiness:'health',workers:'health',outputs:'outputs'};
 const target=()=>{try{return document.getElementById(decodeURIComponent(location.hash.slice(1)));}catch{return null;}};
 function show(){
  const anchor=target(),views=anchor?.closest('[data-capture-view]')?.dataset.captureView.split(' ')||[];
  const view=WorkspaceNavigation.captureView(location.hash,views,new URLSearchParams(location.search).has('recipe'));
  document.body.dataset.captureMode=view;
  for(const node of document.querySelectorAll('[data-capture-view]'))node.hidden=!node.dataset.captureView.split(' ').includes(view);
  for(const a of document.querySelectorAll('[data-capture-tab]'))a.setAttribute('aria-current',a.dataset.captureTab===view?'page':'false');
  for(const a of document.querySelectorAll('[data-capture-group]'))a.setAttribute('aria-current',a.dataset.captureGroup===groups[view]?'page':'false');
  for(let node=anchor;node;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;
  return anchor;
 }
 let positioning=false,frame=0,currentEntry=location.href;
 const positions=new Map();
 function remember(){
  const point={x:scrollX,y:scrollY};positions.set(currentEntry,point);
  if(currentEntry===location.href)history.replaceState({...history.state,rilldexScroll:point},'');
 }
 function position({tabs=false,restore=false}={}){
  positioning=true;const anchor=show(),saved=restore?(history.state?.rilldexScroll||positions.get(location.href)):null;
  currentEntry=location.href;
  cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{
   if(saved)scrollTo({left:saved.x,top:saved.y,behavior:'instant'});
   else if(!WorkspaceNavigation.restore?.()){
    if(tabs||!location.hash)scrollTo({top:0,left:0,behavior:'instant'});
    else anchor?.scrollIntoView({block:'start',behavior:'instant'});
   }
   requestAnimationFrame(()=>{positioning=false;remember();});
  });
  window.dispatchEvent(new Event('rilldex:navigation'));
 }
 document.addEventListener('click',event=>{
  const a=event.target.closest?.('a[href]');if(!a||event.defaultPrevented||event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey||a.target||a.hasAttribute('download'))return;
  const url=new URL(a.href);if(url.origin!==location.origin||url.pathname!==location.pathname||url.search!==location.search||!url.hash)return;
  let anchor;try{anchor=document.getElementById(decodeURIComponent(url.hash.slice(1)));}catch{return;}
  if(!anchor?.closest('[data-capture-view]')&&!a.matches('[data-capture-group],[data-capture-tab]'))return;
  event.preventDefault();remember();WorkspaceNavigation.remember?.();
  const previous=location.pathname+location.search+location.hash,next=url.pathname+url.search+url.hash;
  if(next!==previous)history.pushState({rilldexBack:previous,rilldexOrigin:history.state?.rilldexOrigin},'',next);
  position({tabs:a.matches('[data-capture-group],[data-capture-tab]')});
 });
 // Reveal the destination before scrolling, including nested disclosures and Back/Forward.
 history.scrollRestoration='manual';
 window.addEventListener('scroll',()=>{if(!positioning)remember();},{passive:true});
 window.addEventListener('hashchange',()=>{if(currentEntry!==location.href)position({restore:true});});
 window.addEventListener('popstate',()=>position({restore:true}));
 show();window.addEventListener('load',()=>position({restore:true}),{once:true});
})();
