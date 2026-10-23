(function(root){
 'use strict';
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 const button=(name,fn)=>{const b=el('button',name);b.type='button';b.onclick=fn;return b;};
 const fmt=(v,unit)=>typeof v==='number'&&Number.isFinite(v)?unit==='fraction'?(v*100).toFixed(1)+'%':v.toLocaleString('en',{maximumFractionDigits:3}):'Not measured';
 const delta=(v,unit)=>v==null?'—':(v>0?'+':'')+(unit==='fraction'?(v*100).toFixed(1)+' pp':v.toLocaleString('en',{maximumFractionDigits:3}));
 async function recapture(doc,ids){
  const trial=!!doc.snapshot.trial_selection;
  const response=await fetch('/api/investigations/'+(trial?'trial-cases':doc.snapshot.trainer_selection?'trainer-cases':'cases'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...doc.controls,...(trial?{}:{title:doc.title,hypothesis:doc.hypothesis}),parent_id:doc.id,monitor_ids:ids})});
  const next=await response.json();if(!response.ok)throw Error(next.error||'Could not save comparison');location.href='/investigate?'+new URLSearchParams({saved:next.id});
 }
 function chooseMeasures(doc){
  const d=el('dialog',null,'case-dialog case-setup'),head=el('div',null,'case-dialog-head'),body=el('div',null,'case-dialog-body'),prior=document.activeElement;
  d.setAttribute('aria-label','Comparison measures');head.append(el('h2','Comparison measures'),button('Close',()=>d.close()));d.append(head,body);document.body.append(d);d.onclose=()=>{d.remove();prior?.focus();};d.showModal();
  body.append(el('p','Select up to 24 saved monitors. Applying saves a new comparison; the earlier one remains available.','case-note'));
  const inputs=[],data=doc.snapshot.behavior,list=el('div'),status=el('p','Loading saved monitors…','case-note');body.append(status,list);
  const error=el('p',null,'case-error'),apply=button('Save with these measures',async()=>{error.textContent='';const ids=inputs.filter(i=>i.checked).map(i=>i.value);if(ids.length>24){error.textContent='Select at most 24 measures.';return;}apply.disabled=true;try{await recapture(doc,ids);}catch(e){error.textContent=e.message;apply.disabled=false;}});error.setAttribute('role','alert');apply.disabled=true;body.append(apply,error);
  async function load(){
   status.textContent='Loading saved monitors…';error.textContent='';
   try{const response=await fetch('/api/investigations/'+encodeURIComponent(doc.id)+'/measures'),latest=await response.json();if(!response.ok)throw Error(latest.error||'Could not load monitors');if(!d.isConnected)return;
    for(const m of latest.choices){const label=el('label',null,'case-measure-choice'),input=el('input');input.type='checkbox';input.value=m.id;input.checked=data.monitor_ids.includes(m.id);label.append(input,el('span',m.name+(m.enabled?'':' · paused')));list.append(label);inputs.push(input);}
    status.textContent=latest.choices.length?'':'No monitors cover these rollouts.';apply.disabled=false;
   }catch(e){if(!d.isConnected)return;status.textContent='';error.textContent=e.message;const retry=button('Retry loading monitors',()=>{retry.remove();load();});body.append(retry);}
  }load();
 }
 function taskCoverage(details,p){
  let shown=0,loaded=false;const list=el('div',null,'case-task-list'),more=button('Show more tasks',append);
  function append(){
   more.remove();
   for(const t of p.same_tasks.tasks.slice(shown,shown+20)){
    const row=el('div',null,'case-task-row'),name=el('div');name.append(el('strong',t.context.task_id),el('small',[t.context.environment+' '+t.context.environment_version,'task '+t.context.task_revision,t.context.split,t.context.reward_definition].join(' · ')));row.append(name);
    for(const [side,label]of [['baseline','Reference'],['current','Selected']]){
     const cell=el('div'),value=button(label+': '+fmt(t[side].value,p.unit),()=>IntervalInvestigation.cases(p,t,side));
     value.setAttribute('aria-label','Inspect '+label.toLowerCase()+' '+p.monitor.name+' for '+t.context.task_id);
     cell.append(value,el('small',t[side].measured+' / '+t[side].total+' rollouts measured'));
     if(t[side].unknown_opportunities)cell.append(el('small',t[side].unknown_opportunities+' unresolved opportunities'));
     row.append(cell);
    }
    if(!t.measured_on_both)row.append(el('small','Excluded from the equal-task value: measurements missing on one or both sides.','case-task-gap'));
    list.append(row);
   }
   shown+=20;if(shown<p.same_tasks.tasks.length)list.append(more);
  }
  details.append(list);details.addEventListener('toggle',()=>{if(details.open&&!loaded){loaded=true;append();}});
 }
 function render(host,doc){
  const data=doc.snapshot.behavior;if(!data)return;
  const section=el('section',null,'iv-panel case-behavior'),head=el('div',null,'case-behavior-head');section.id='case-behavior';head.append(el('h2','Behavior & outcomes'),button('Change measures',()=>chooseMeasures(doc)));section.append(head);host.append(section);
  if(!data.panels.length){section.append(el('p',data.choices.length?'No measures selected. Use Change measures to include saved monitor values.':'No saved monitors cover these rollouts. Add monitors to collect behavior measures.','case-note'),Object.assign(el('a','Open Monitor management'),{href:'/monitors'}));return;}
  const controls=el('div',null,'case-behavior-controls'),mode=el('select');mode.setAttribute('aria-label','Behavior comparison population');
  for(const [value,text]of [['all','All selected rollouts'],['matched','Same tasks · equal weight']])mode.append(Object.assign(el('option',text),{value}));
  mode.value=new URLSearchParams(location.search).get('case_measure_view')==='matched'?'matched':'all';controls.append(mode);const note=el('p',null,'case-note'),table=el('div',null,'case-measure-table');section.append(controls,note,table);
  function draw(){
   const matched=mode.value==='matched';note.textContent=matched?'Each fully recorded task context with measurements on both sides has equal weight. Open a measure to inspect its task coverage.':'Each monitor keeps its own aggregation. Coverage and unresolved opportunities appear beside the values.';
   table.replaceChildren();const labels=el('div',null,'case-measure-labels');for(const text of ['Measure','Reference','Selected','Change'])labels.append(el('span',text));table.append(labels);
   for(const p of data.panels){
    const row=el('article',null,'case-measure-row');row.dataset.monitorId=p.monitor.id;
    const name=el('div',null,'case-measure-name');name.append(el('strong',p.monitor.name),el('small',p.monitor.group||'Monitor'));row.append(name);
    for(const [side,label]of [['baseline','Reference'],['current','Selected']]){
     const summary=p[side],cell=el('div',null,'case-measure-value');cell.dataset.label=label;
     const relevant=matched?p.same_tasks.tasks.filter(t=>t.measured_on_both).flatMap(t=>t.points[side]):p.points[side];
     const value=matched?p.same_tasks[side]:summary.value;
     const inspect=button(fmt(value,p.unit),()=>IntervalInvestigation.cases(p,{points:{[side]:relevant}},side,{scope:matched?'matched':'all'}));inspect.setAttribute('aria-label','Inspect '+label.toLowerCase()+' '+p.monitor.name);inspect.disabled=!relevant.length;cell.append(inspect);
     cell.append(el('small',matched?p.same_tasks.measured_contexts+' / '+p.same_tasks.contexts+' shared tasks measured':summary.measured+' / '+summary.total+' rollouts measured'));
     if(!matched&&summary.denominator!=null)cell.append(el('small',summary.numerator+' / '+summary.denominator+' resolved opportunities'));
     if(!matched&&summary.unknown_opportunities)cell.append(el('small',summary.unknown_opportunities+' unresolved opportunities'));
     if(p.excluded[side])cell.append(el('small',p.excluded[side]+' outside monitor scope'));
     row.append(cell);
    }
    const change=el('div',null,'case-measure-delta');change.dataset.label='Change';change.append(el('strong',delta(matched?p.same_tasks.delta:p.delta,p.unit)));row.append(change);
    const details=el('details',null,'case-measure-detail');details.append(el('summary','Task coverage & measurement versions'));
    details.append(el('p',p.same_tasks.contexts+' shared complete task contexts · '+p.same_tasks.measured_contexts+' measured on both sides.','case-note'));
    for(const [side,label]of [['baseline','Reference'],['current','Selected']])details.append(el('p',label+': '+p.same_tasks.incomplete_context_rollouts[side]+' rollouts with incomplete task context · '+p.same_tasks.without_counterpart[side]+' without a task counterpart.','case-note'));
    if(p.versions.same_recorded_versions===false)name.append(el('small','Observation versions differ','case-measure-version'));
    taskCoverage(details,p);
    const raw=el('details');raw.append(el('summary','Saved definition & versions'),el('pre',JSON.stringify({monitor:p.monitor,aggregation:p.aggregation,versions:p.versions},null,2)));details.append(raw);row.append(details);table.append(row);
   }
  }
  mode.onchange=()=>{const u=new URL(location.href);u.searchParams.set('case_measure_view',mode.value);history.replaceState(history.state,'',u);draw();};draw();
  if(data.not_selected)section.append(el('p',data.not_selected+' other saved monitors available in Change measures.','case-note'));
 }
 root.CaseBehaviorView={render,fmt,delta};
 if(typeof module!=='undefined')module.exports={fmt,delta};
})(globalThis);
