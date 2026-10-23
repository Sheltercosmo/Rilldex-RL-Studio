'use strict';
const InvestigationTrials=(()=>{
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 const button=(text,fn)=>{const n=el('button',text);n.type='button';n.onclick=fn;return n;};
 async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d;}
 function input(root,label,value='',multiline=false){const wrap=el('label',label),n=el(multiline?'textarea':'input');n.setAttribute('aria-label',label);n.value=value;if(multiline)n.rows=3;wrap.append(n);root.append(wrap);return n;}
 function select(root,label,options){const wrap=el('label',label),n=el('select');n.setAttribute('aria-label',label);for(const [value,text]of options){const o=el('option',text);o.value=value;n.append(o);}wrap.append(n);root.append(wrap);return n;}
 function dialog(title){const d=el('dialog',null,'if-dialog'),head=el('div',null,'if-dialog-head'),body=el('div',null,'if-dialog-body');head.append(el('h2',title),button('Close',()=>d.close()));d.setAttribute('aria-label',title);d.append(head,body);d.addEventListener('close',()=>d.remove());document.body.append(d);d.showModal();return{d,body};}
 const labels={replay:'Replay a rollout prefix',evaluate:'Rescore the captured rollout',train:'Train from a checkpoint'};
 async function editor(root,doc){
  const box=el('div',null,'if-form if-trial-editor');root.append(box);
  box.append(el('p','Runs in your Python environment. Export the design, connect your runner, then import its results here.','if-muted'));
  let data=await api('/api/investigation-trials/options?'+new URLSearchParams({investigation:doc.id}));
  if(!data.selected)throw Error('No retained rollout is available in this saved comparison.');
  const mode=select(box,'Trial action',Object.entries(labels));
  const rollout=select(box,'Source rollout',data.rollouts.map((r,i)=>[r.run_id,`${i+1}. ${r.metadata.task_id||'Rollout'} · ${r.cohort} · ${r.metadata.checkpoint||r.metadata.experiment||'Captured source'}`]));rollout.value=data.selected;
  const through=select(box,'Include events through',[]),config=select(box,'Base configuration',[]),base=input(box,'Base settings (JSON)','{}',true);
  const configNote=el('p','Select the configuration used for this check. A recorded snapshot is not automatically the configuration at the selected rollout step.','if-muted');box.append(configNote);
  const restore=el('details');restore.append(el('summary','Checkpoint & restore state'));const restoreBody=el('div',null,'if-form');restore.append(restoreBody);box.append(restore);
  const checkpoint=input(restoreBody,'Checkpoint or environment snapshot reference');
  restoreBody.append(el('p','A checkpoint label in the rollout is not a restorable snapshot. Supply a reference your runner can load.','if-muted'));
  const states=el('div',null,'if-trial-states');restoreBody.append(states);const stateInputs=[];
  for(const key of ['model','optimizer','scheduler','rng','data','environment','agent']){const c=select(states,key==='rng'?'RNG':key[0].toUpperCase()+key.slice(1),[['','Unspecified'],['restore','Restore checkpoint state'],['reset','Start fresh']]);c.dataset.state=key;stateInputs.push(c);}
  restoreBody.append(el('p','Choose Restore for checkpoint state or Start fresh for an intentional reset, such as seeded environments and new rollout collection. Your runner reports what it actually did.','if-muted'));
  const modeNote=el('p',null,'if-muted');box.append(modeNote);
  const variants=el('div',null,'if-trial-variants');box.append(el('strong','Variants'),el('p','The unchanged Reference arm is included. Overrides merge JSON objects; arrays and null replace values.','if-muted'),variants);const arms=[];
  function add(){if(arms.length>=8)return;const card=el('fieldset');card.append(el('legend','Variant '+(arms.length+1)));const name=input(card,'Variant name','Variant '+(arms.length+1)),parameters=input(card,'Parameter overrides (JSON)','{}',true),context=input(card,'Append context after selected event','',true);const item={card,name,parameters,context};arms.push(item);card.append(button('Remove variant',()=>{arms.splice(arms.indexOf(item),1);card.remove();}));variants.append(card);context.closest('label').hidden=mode.value!=='replay';}
  add();box.append(button('Add variant',add));
  const limits=el('div',null,'if-trial-grid');box.append(limits);
  const seeds=input(limits,'Seeds (comma separated)','0, 1, 2'),maxTrials=input(limits,'Maximum trials','9'),maxSteps=input(limits,'Steps per trial','64'),maxTokens=input(limits,'Tokens per trial','32768');
  for(const n of [maxTrials,maxSteps,maxTokens]){n.type='number';n.min='1';}
  const metric=input(limits,'Result metric key','success'),metricLabel=input(limits,'Result metric label','Task success'),unit=input(limits,'Result unit','0–1');
  const count=el('p',null,'if-muted');box.append(count);
  function populate(){through.replaceChildren();for(const e of data.events){const o=el('option',e.id+' · '+e.label);o.value=e.id;through.append(o);}through.value=data.events.at(-1)?.id||'';config.replaceChildren();for(const [value,text]of [['','Provide settings'],...data.configurations.map((c,i)=>[c.id,`${i+1}. ${c.kind} · ${c.producer} · ${c.recorded_at||c.received_at||''}`])]){const o=el('option',text);o.value=value;config.append(o);}config.value='';base.value='{}';config.onchange();}
  config.onchange=()=>{const chosen=data.configurations.find(c=>c.id===config.value);base.value=JSON.stringify(chosen?.config||{},null,2);base.readOnly=!!chosen;};
  let loading=false,loadError=null,request=0;
  rollout.onchange=async()=>{const version=++request;loading=true;loadError=null;through.disabled=config.disabled=true;try{const next=await api('/api/investigation-trials/options?'+new URLSearchParams({investigation:doc.id,run:rollout.value}));if(version!==request)return;data=next;populate();}catch(e){if(version===request){loadError=e;count.textContent=e.message;}}finally{if(version===request){loading=false;config.disabled=false;update();}}};
  function update(){through.disabled=loading||mode.value==='evaluate';if(mode.value==='evaluate')through.value=data.events.at(-1)?.id||'';modeNote.textContent=mode.value==='replay'?'Only events through this point are passed to your adapter. Later events and recorded outcomes are excluded. Context is appended to this prefix.':mode.value==='evaluate'?'The adapter evaluates the fixed captured rollout; no policy generation is requested.':'The rollout is diagnostic evidence, not a training dataset. Your runner must restore the checkpoint and enforce step/token limits.';for(const a of arms)a.context.closest('label').hidden=mode.value!=='replay';if(!loadError)count.textContent=`${arms.length+1} arms × ${seeds.value.split(',').filter(s=>s.trim()).length} seeds. The runner must enforce per-trial limits.`;}
  mode.onchange=()=>{restore.open=mode.value==='train';update();};box.addEventListener('input',update);box.addEventListener('click',update);populate();update();
  return {read(){if(loading)throw Error('Wait for the selected rollout to load.');if(loadError)throw loadError;const seedTexts=seeds.value.split(',').map(s=>s.trim());if(seedTexts.some(s=>!/^\d+$/.test(s)))throw Error('Enter comma-separated integer seeds.');return {mode:mode.value,run_id:rollout.value,through_event_id:through.value,configuration:config.value?{source_id:config.value}:{values:JSON.parse(base.value)},checkpoint:{reference:checkpoint.value,available_state:stateInputs.filter(c=>c.value==='restore').map(c=>c.dataset.state),reset_state:stateInputs.filter(c=>c.value==='reset').map(c=>c.dataset.state)},variants:arms.map(a=>({name:a.name.value,parameters:JSON.parse(a.parameters.value),context_append:mode.value==='replay'?a.context.value:''})),seeds:seedTexts.map(Number),budget:{max_trials:Number(maxTrials.value),max_steps:Number(maxSteps.value),max_tokens:Number(maxTokens.value)},measure:{key:metric.value,label:metricLabel.value,unit:unit.value}};}};
 }
 async function prepare(doc,check,onSaved){const {d,body}=dialog('Prepare trial · '+check.title),form=el('form',null,'if-form'),error=el('p',null,'if-error');error.setAttribute('role','alert');body.append(form);try{const edit=await editor(form,doc);const save=el('button','Save trial design','primary');save.type='submit';form.append(error,save);form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{const result=await api('/api/investigations/follow-ups',{parent_id:doc.id,action:'trial',check:{id:check.id,trial:edit.read()}});d.close();await onSaved(result);}catch(e){error.textContent=e.message;save.disabled=false;}};}catch(e){body.append(error);error.textContent=e.message;}}
 function download(name,data){const a=el('a');a.download=name;a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
 function appendRollouts(root,binding,doc,checkId){
  if(!binding?.rollouts.length)return;
  const list=el('div',null,'if-trial-links');
  for(const [i,r]of binding.rollouts.entries()){
   const row=el('div');
   if(r.status!=='available'){row.append(el('span',`Rollout ${i+1}: ${r.status==='unavailable'?'trace not received':r.reasons.join(', ')}`));}
   else{
    const g=r.graphs.find(g=>g.observer!=='source'&&g.coverage?.semantic_relations&&g.coverage.semantic_relations!=='unavailable')||r.graphs.find(g=>g.observer==='source');
    const name=r.source.metadata.task_id||`Rollout ${i+1}`;row.append(el('small',name+' · '+r.source.state));
    if(g){const a=el('a','Open behavior map');a.href='/semantic-map?'+new URLSearchParams({run:r.run_id,observer:g.observer,graph:g.id,level:'units',return_to:'/investigate?'+new URLSearchParams({saved:doc.id,panel:'checks'})+'#'+checkId});row.append(a);}
    else row.append(el('span','Map not available in this snapshot'));
   }list.append(row);
  }root.append(list);
 }
 function returnedBehavior(root,doc,check,onSaved){
  if(!check.trial_results?.length)return;
  const box=el('section',null,'if-trial-behavior'),evidence=check.trial_evidence,error=el('p',null,'if-error');error.setAttribute('role','alert');box.append(el('h4','Returned behavior'));
  box.append(el('p',evidence?.declared?`${evidence.available} / ${evidence.declared} declared rollout sources available`:'Return rollout_ids in your callback output to connect trial scores to behavior maps and saved measures.','if-muted'));
  const refresh=button('Refresh rollout evidence',async()=>{refresh.disabled=true;try{const saved=await api('/api/investigations/follow-ups',{parent_id:doc.id,action:'trial_evidence',check:{id:check.id}});if(saved.id===doc.id){error.textContent='No new rollout sources or maps received.';refresh.disabled=false;}else await onSaved(saved);}catch(e){error.textContent=e.message;refresh.disabled=false;}});box.append(refresh);
  if(evidence?.declared){const controls=el('div',null,'if-form if-trial-grid');box.append(controls);
   const arm=select(controls,'Compare variant',check.trial.arms.slice(1).map(a=>[a.name,a.name]));
   const selection=select(controls,'Trial evidence selection',[['paired','Paired completed trials'],['returned','All returned evidence']]);
   const compare=button('Compare returned behavior',async()=>{compare.disabled=true;error.textContent='';try{const saved=await api('/api/investigations/trial-cases',{investigation_id:doc.id,check_id:check.id,arm:arm.value,selection:selection.value});location.href='/investigate?'+new URLSearchParams({saved:saved.id});}catch(e){error.textContent=e.message;compare.disabled=false;}});box.append(compare);
  }box.append(error);root.append(box);
 }
 function render(root,doc,check,onSaved){
  if(!check.trial){root.append(button('Prepare trial',()=>prepare(doc,check,onSaved)));return;}
  const trial=check.trial,box=el('section',null,'if-trial');box.append(el('h4',labels[trial.mode]),el('p',`${trial.arms.length} arms · ${trial.seeds.length} seeds · ${trial.source.event_count} source events · ${trial.measure.label} (${trial.measure.unit})`));
  const details=el('details');details.append(el('summary','Trial settings & Python runner'));
  const table=el('div',null,'if-trial-settings');for(const arm of trial.arms){const row=el('div');row.append(el('strong',arm.name),el('pre',JSON.stringify(arm.parameters,null,2)));if(arm.context_append)row.append(el('p','Additional context: '+arm.context_append));table.append(row);}details.append(table,el('p',`Base settings: ${trial.configuration.origin}. Restore point: ${trial.checkpoint.reference||'None — text replay / evaluation'}.`),el('p',`Limits per trial: ${trial.budget.max_steps} steps · ${trial.budget.max_tokens} tokens.`));
  details.append(el('pre',`from rilldex import TrialStudy\nfrom my_runner import run_trial\n\nstudy = TrialStudy.load("trial.json")\nstudy.run(run_trial, output="trial-results.json")`),el('p','Your callback receives the prefix, seed, merged configuration, added context, restore point and limits. Return status, metrics and applied settings. Import the result file below; completed jobs are skipped on restart.','if-muted'));
  if(trial.checkpoint.reference)details.append(el('p',`Restore: ${trial.checkpoint.available_state.join(', ')||'Unspecified'}. Start fresh: ${(trial.checkpoint.reset_state||[]).join(', ')||'None declared'}.`));
  const help=el('a','Adapter example & result format');help.href='/integration-guide#investigation-trials';details.append(help);box.append(details);
  const summary=check.trial_comparison,results=el('div',null,'if-trial-results');
  if(summary){for(const contrast of summary.contrasts){const delta=contrast.mean_difference;results.append(el('p',`${contrast.arm}: ${delta==null?'No comparable pairs':(delta>0?'+':'')+Number(delta.toPrecision(4))+' vs Reference'} · ${contrast.paired}/${contrast.planned} paired seeds${contrast.unrepresentable_differences?' · '+contrast.unrepresentable_differences+' differences exceed numeric range':''}`));}
   const rows=el('details'),entries=el('div',null,'if-trial-rows');rows.append(el('summary','Results, pending trials & applied settings'),entries);for(const row of summary.rows){const item=el('div',null,'if-trial-result');item.append(el('strong',`${row.arm} · seed ${row.seed}`),el('p',`${row.status} · ${row.value==null?'No measurement':row.value+' ('+summary.measure.unit+')'}`));for(const issue of row.issues)item.append(el('p',issue,'if-warning'));if(row.result?.note)item.append(el('p',row.result.note));if(row.result?.experiment){const link=el('a','Open returned run');link.href='/?'+new URLSearchParams({experiment:row.result.experiment});item.append(link);}if(row.result){const applied=el('details');applied.append(el('summary','Applied configuration'),el('pre',JSON.stringify(row.result.applied,null,2)));item.append(applied);}appendRollouts(item,check.trial_evidence?.jobs.find(j=>j.job_id===row.job_id),doc,check.id);const prior=(check.trial_results||[]).filter(r=>r.job_id===row.job_id&&r.id!==row.result?.id);if(prior.length){const history=el('details');history.append(el('summary',prior.length+' earlier '+(prior.length===1?'attempt':'attempts')));for(const r of prior)history.append(el('p',r.status+' · '+(r.metrics[trial.measure.key]??'No measurement')+(r.note?' · '+r.note:'')));item.append(history);}entries.append(item);}rows.append(el('p',summary.interpretation,'if-muted'));results.append(rows);if(trial.mode==='replay')results.append(el('p',summary.replay_scope,'if-muted'));
  }else results.append(el('p','No results returned yet. Export the trial to run it.','if-muted'));
  box.append(results);returnedBehavior(box,doc,check,onSaved);const actions=el('div',null,'if-actions'),error=el('p',null,'if-error');error.setAttribute('role','alert');
  actions.append(button('Export trial',async()=>{try{download('trial.json',await api('/api/investigation-trials/manifest?'+new URLSearchParams({investigation:doc.id,check:check.id})));}catch(e){error.textContent=e.message;}}));
  const file=el('input');file.type='file';file.accept='.json,application/json';file.hidden=true;file.setAttribute('aria-label','Trial result file');
  file.onchange=async()=>{try{if(!file.files[0])return;const returned=JSON.parse(await file.files[0].text());if(returned.schema!=='trial-results/1'||returned.trial_id!==trial.id||returned.check_id!==check.id)throw Error('This result file belongs to another trial.');const saved=await api('/api/investigations/follow-ups',{parent_id:doc.id,action:'trial_results',check:{id:check.id,results:returned.results.map(({id,...r})=>r)}});await onSaved(saved);}catch(e){error.textContent=e.message;}finally{file.value='';}};
  actions.append(button('Import results',()=>file.click()),file);box.append(actions,error);root.append(box);
 }
 return{editor,render,prepare};
})();
