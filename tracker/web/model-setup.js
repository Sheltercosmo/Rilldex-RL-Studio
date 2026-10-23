(()=>{
 'use strict';
 const host=document.getElementById('model-setup');if(!host)return;
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),v=await r.json();if(!r.ok)throw Error(v.error||'Request failed');return v;}
 const config=el('div'),form=el('form',undefined,'model-setup-form'),output=el('div',undefined,'model-pilot-result'),run=el('select'),fields={};
 run.required=true;run.setAttribute('aria-label','Pilot rollout');
 const label=el('label','Completed rollout','full');label.append(run);form.append(label);
 for(const [key,name,value,max]of [['candidate_calls','Candidate calls',20,1000],['decision_calls','Decision calls',20,1000],['input_bytes','Input bytes',1000000,100000000]]){const label=el('label',name),input=el('input');input.type='number';input.min=0;input.max=max;input.value=value;input.required=true;fields[key]=input;label.append(input);form.append(label);}
 form.append(el('p','Extract activities, connect plans and work targets, inspect execution feedback, and compare approaches across repeated work. All stages share these lifetime limits; resume reuses saved decisions. Calls and bytes are not token or currency estimates.','full'));
 const actions=el('div',undefined,'full'),start=el('button','Start / resume pilot','primary'),refresh=el('button','Refresh setup');start.type='submit';refresh.type='button';actions.append(start,refresh);form.append(actions);
 const guide=el('details');guide.append(el('summary','Configure models or run from code'));
 guide.append(el('p','Set these variables in the environment that starts Rilldex. Keep credentials in your shell or secret manager. Restart the server after changing its environment.'));
 const preset=el('select');preset.setAttribute('aria-label','Candidate endpoint preset');for(const [value,text]of [['local','Local · vLLM / compatible server'],['ollama','Ollama'],['custom','Hosted / custom endpoint']]){const o=el('option',text);o.value=value;preset.append(o);}
 const shell=el('select');shell.setAttribute('aria-label','Setup shell');for(const [value,text]of [['bash','Bash / Linux / macOS'],['powershell','PowerShell / Windows']]){const o=el('option',text);o.value=value;shell.append(o);}
 const setup=el('pre'),commands=el('pre');guide.append(preset,shell,setup,el('p','Check configuration without a network call. Probe makes one candidate request. The pilot uses the same installed adapter and publishes a complete map when ready.'),commands);
 const docs=el('a','Model setup reference →');docs.href='/model-setup.md';guide.append(docs);
 const continuous=el('details');continuous.id='model-continuous';continuous.append(el('summary','Observe an experiment continuously'));
 continuous.append(el('p','Run this command beside the collector. It processes saved and arriving rollouts under one observer, reuses the selected pilot, and adds error, revisit, approach-change and coverage measures to the dashboard.'));
 const watchFields=el('div',undefined,'model-setup-form'),experiment=el('input'),directory=el('input'),watchLimits={},watchMode=el('select');
 const modeLabel=el('label','Worker action');watchMode.setAttribute('aria-label','Worker action');for(const [value,text]of [['start','Start with selected pilot'],['resume','Resume saved worker'],['refresh','Refresh after package update']]){const option=el('option',text);option.value=value;watchMode.append(option);}modeLabel.append(watchMode);watchFields.append(modeLabel);
 for(const [title,input,value]of [['Experiment',experiment,''],['Worker directory',directory,'./observations']]){const label=el('label',title);input.value=value;label.append(input);watchFields.append(label);}
 for(const [key,title]of [['candidate_calls','Worker candidate calls'],['decision_calls','Worker decision calls'],['input_bytes','Worker input bytes']]){const label=el('label',title),input=el('input');input.type='number';input.min=0;input.placeholder='Keep saved limit';label.append(input);watchFields.append(label);watchLimits[key]=input;}
 const watchCode=el('pre'),copy=el('button','Copy worker command');copy.type='button';
 continuous.append(watchFields,el('p','Leave limits blank to retain saved ceilings; new workers start at zero. Resume keeps the saved models and protocol. Refresh replays saved evidence offline after a package update. To resume a blocked rollout, add --retry-run with its ID from watch-status. Keep the database and worker directory on persistent storage.'),watchCode,copy);
 host.append(config,guide,form,output,continuous);
 let data=null,db='study.sqlite',restoredPilot=null;
 function code(){
  const ps=shell.value==='powershell',values={RILLDEX_LLM_PRESET:preset.value,RILLDEX_LLM_MODEL:'YOUR_MODEL_ID'};
  if(preset.value==='custom')values.RILLDEX_LLM_URL='https://YOUR_PROVIDER/v1/chat/completions';
  setup.textContent=Object.entries(values).map(([k,v])=>(ps?'$env:'+k+' = ':'export '+k+'=')+'"'+v+'"').join('\n')+'\n# Set JEV_API_KEY for decision calls; RILLDEX_LLM_API_KEY if your candidate endpoint needs it.';
  const q=v=>"'"+String(v).replaceAll("'",ps?"''":"'\"'\"'")+"'";
  const directory=data?.pilot?.run_id===run.value?data.pilot.directory:'./model-pilot';
  commands.textContent='python -m rilldex.models check\npython -m rilldex.models probe\npython -m rilldex.models pilot '+q(directory)+' --db '+q(db)+' --run-id '+q(run.value||'ROLLOUT_ID')+' --candidate-calls '+fields.candidate_calls.value+' --decision-calls '+fields.decision_calls.value+' --input-bytes '+fields.input_bytes.value;
  workerCode(q);
 }
 function workerCode(q){
  const p=data?.pilot,reuse=watchMode.value==='start'&&p?.result?.model&&p.run_id===run.value;
  watchCode.textContent='python -m rilldex.models watch '+q(directory.value||'./observations')+' --db '+q(db)+' --experiment '+q(experiment.value||'YOUR_EXPERIMENT')+(reuse?' --from-pilot '+q(p.directory):'')+Object.entries(watchLimits).filter(([,input])=>input.value!=='').map(([key,input])=>' --'+key.replaceAll('_','-')+' '+String(Math.max(0,Number(input.value)||0))).join('')+(watchMode.value==='refresh'?' --refresh-worker':'')+' --follow';
 }
 for(const input of [experiment,directory,...Object.values(watchLimits)])input.oninput=code;
 watchMode.onchange=code;
 copy.onclick=async()=>{try{await navigator.clipboard.writeText(watchCode.textContent);copy.textContent='Copied';}catch{copy.textContent='Select and copy the command above';}};
 preset.onchange=shell.onchange=run.onchange=code;for(const input of Object.values(fields))input.oninput=code;
 function render(value){
  if(value.pilot&&restoredPilot!==value.pilot.directory&&(!run.value||run.value===value.pilot.run_id)){
   run.value=value.pilot.run_id;for(const [key,input]of Object.entries(fields))if(value.pilot.limits?.[key]!=null)input.value=value.pilot.limits[key];restoredPilot=value.pilot.directory;
   if(!experiment.value)experiment.value=run.selectedOptions[0]?.dataset.experiment||'';
  }
  data=value;config.replaceChildren();const c=value.configuration.candidate,d=value.configuration.decision;
  config.append(el('p',c.state==='configured'?'Candidate: '+c.model+' · '+c.endpoint:'Candidate: '+c.detail),el('p','Decision: '+d.provider+' · '+(d.state==='configured'?'credential available':'set JEV_API_KEY in the server environment')));
  start.disabled=value.pilot?.state==='running'||c.state!=='configured'||!run.value;
  output.replaceChildren();const p=value.pilot;
  if(!p)output.append(el('p','No pilot started. Choose a rollout and set its limits.'));
  else{
   const complete=p.state==='complete_local_extraction';
   output.append(el('strong',complete?(p.result?.plan_map_available?'Pilot complete · plans and activities':p.result?.map_scope==='activities_and_work_links'?'Pilot complete · activities and work links':'Pilot complete · activities'):'Pilot · '+p.state.replaceAll('_',' ')));if(p.message)output.append(el('p',p.message));
   const providers=p.usage?.providers||{};output.append(el('p',`${providers.candidate?.attempts||0} candidate calls · ${providers.jev?.attempts||0} decision calls · ${Object.values(providers).reduce((sum,v)=>sum+v.input_bytes,0).toLocaleString()} input bytes recorded`));
   if(p.state==='budget_reached')output.append(el('p','The lifetime limit was reached. Raise the relevant limit to continue from saved requests.'));
   const links=p.work_links||p.result?.layers?.action_targets;
   const plans=p.plan_links||p.result?.layers?.plan_relations;
   const reports=p.execution_reports||p.result?.layers?.execution_reports;
   const methods=p.method_comparison||p.result?.layers?.method_comparison;
   if(plans?.coverage){const c=plans.coverage;output.append(el('p',c.plans?`Plan steps · ${c.compared_pairs} / ${c.candidate_pairs} action–step pairs inspected · ${c.pending_pairs} pending · ${c.unresolved_pairs} unresolved`:'No organized plan selected in this rollout.'));if(c.oversized_pairs)output.append(el('p',`${c.oversized_pairs} plan comparisons exceed the evidence window.`));}
   if(links?.coverage){const c=links.coverage;output.append(el('p',`Work links · ${c.compared_pairs} / ${c.candidate_pairs} action pairs inspected · ${c.pending_pairs} pending · ${c.unresolved_pairs} unresolved`));if(c.oversized_pairs)output.append(el('p',`${c.oversized_pairs} pairs exceed the evidence window. Increasing the call budget alone will not resolve them.`));}
   if(reports?.coverage){const c=reports.coverage;output.append(el('p',`Execution feedback · ${c.inspected_pairs} / ${c.response_pairs} response pairs inspected · ${c.pending_pairs} pending · ${c.error_reports} reporting errors · ${c.warning_reports} reporting warnings`));if(c.unresolved_pairs||c.incomplete_responses)output.append(el('p',`${c.unresolved_pairs} unresolved pairs · ${c.incomplete_responses} responses with unread material.`));}
   else if(reports?.status==='pending')output.append(el('p','Execution feedback inspection is pending. Uninspected responses are not counted as error-free.'));
   if(reports?.status==='not_requested'&&p.state!=='running'&&p.run_id===run.value){const add=el('button','Inspect execution feedback');add.type='button';add.onclick=()=>startPilot(true);output.append(el('p','Add errors and warnings to this saved pilot. Existing annotations are reused; current lifetime limits still apply.'),add);}
   if(methods?.coverage){const c=methods.coverage;output.append(el('p',`Approaches · ${c.inspected_pairs} / ${c.eligible_pairs} repeat pairs inspected · ${c.pending_pairs} pending · ${c.unavailable_pairs} outside evidence limits`));}
   else if(methods?.status==='pending')output.append(el('p','Approach comparisons are pending. Work links must finish first.'));
   if(methods?.status==='not_requested'&&p.result?.model?.action_target_version&&p.state!=='running'&&p.run_id===run.value){const add=el('button','Compare approaches');add.type='button';add.onclick=()=>startPilot(false,true);output.append(el('p','Compare procedures and stated reasons across repeated work. Saved annotations are reused within the current lifetime limits.'),add);}
   const last=p.result?.last_execution;if(last){const stop=last.budget_stop;if(stop)output.append(el('p','Stopped at '+stop.provider+' request · '+stop.limit.replaceAll('_',' ')+' limit.'));output.append(el('p',(last.cached_decisions_this_execution??last.exact_reused_decisions??0)+' saved decisions reused in the last pass.'));}
   if(p.result?.map_url){const a=el('a',p.result.plan_map_available?'Open plans & attempts →':p.result.map_scope==='local_activities'&&links?.status!=='not_requested'?'Open activities · work links pending →':'Open the semantic map →');a.href=p.result.map_url;output.append(a);}
   if(p.result?.work_map_url){const line=el('p'),a=el('a','Review approach comparisons →');a.href=p.result.work_map_url;line.append(a);output.append(line);}
   const receipt=el('details');receipt.append(el('summary','Saved progress & workspace'),el('pre',JSON.stringify(p,null,2)));output.append(receipt);
  }
  code();
 }
 async function load(choices=false){try{
  if(choices){const state=await api('/api/monitoring'),old=run.value;db=state.workspace.database;run.replaceChildren();const blank=el('option','Select a completed rollout');blank.value='';run.append(blank);for(const r of state.runs.filter(r=>['complete','imported_snapshot'].includes(r.state))){const o=el('option',(r.metadata.task_id||'Rollout')+(r.metadata.experiment?' · '+r.metadata.experiment:''));o.value=r.id;o.dataset.experiment=r.metadata.experiment||'';run.append(o);}run.value=old||new URLSearchParams(location.search).get('model_run')||'';if(!experiment.value)experiment.value=run.selectedOptions[0]?.dataset.experiment||'';}
  render(await api('/api/models'));
 }catch(e){output.textContent=e.message;}}
 refresh.onclick=()=>load(true);
 async function startPilot(inspectFeedback=false,inspectApproaches=false){start.disabled=true;try{render(await api('/api/models/pilot',{run_id:run.value,...Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,Number(v.value)])),...(inspectFeedback?{inspect_feedback:true}:{}),...(inspectApproaches?{inspect_approaches:true}:{})}));}catch(e){output.textContent=e.message;start.disabled=false;}}
 form.onsubmit=e=>{e.preventDefault();startPilot();};
 run.addEventListener('change',()=>{experiment.value=run.selectedOptions[0]?.dataset.experiment||'';if(data)render(data);});
 load(true);setInterval(()=>{if(!document.hidden&&data?.pilot?.state==='running')load();},2000);
})();
