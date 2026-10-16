'use strict';
(() => {
 const states=new Map();
 const stages={generated:'Generated',scored:'Scored',admitted:'Any recorded admission',backward:'Backward recorded',positive_mask_backward:'Backward with positive mask',optimizer:'Optimizer recorded'};
 const decisions={admitted:'Filter admitted',rejected:'Filter rejected',unknown:'Decision unknown',conflicting:'Conflicting decision',varies_by_batch:'Varies across batches',not_recorded:'No decision recorded'};
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const fmt=(v,m)=>v==null?'—':m?.unit==='fraction'?(100*v).toFixed(1)+'%':Number(v.toFixed(3)).toLocaleString();
 const coverage=s=>s.weighting==='unique_source_rollout'?`${s.source_measured} / ${s.source_rollouts} source rollouts · ${s.measured} / ${s.population} samples`:s.measured+' / '+s.population+' measured';
 const delta=(v,m)=>v==null?'—':m?.unit==='fraction'?(100*v).toFixed(1)+' pp':fmt(v,m);
 async function api(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined),v=await r.json();if(!r.ok)throw Error(v.error||'Comparison unavailable');return v;}
 function select(label,choices,value,change){const field=el('label',label),s=el('select');s.setAttribute('aria-label',label);for(const [k,v]of choices){const o=el('option',v);o.value=k;s.append(o);}s.value=value;s.onchange=()=>change(s.value);field.append(s);return field;}
 function selected(value){const at=value.indexOf(':');return {kind:value.slice(0,at),value:value.slice(at+1)};}
 function selectorText(s,parent){return s.kind==='reward_pattern'?parent.reward_comparison?.pattern_options.find(p=>p.value===s.value)?.label||s.value:(s.kind==='filter'?decisions:stages)[s.value];}
 const same=(a,b)=>a===b||(a!=null&&b!=null&&typeof a==='object'&&typeof b==='object'&&Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(k=>Object.hasOwn(b,k)&&same(a[k],b[k])));
 function cohortName(c,parent){const r=c.recipe,recipe=r?(parent.snapshot.recipes||[]).find(x=>x.experiment===c.experiment&&x.producer===r.producer&&x.id===r.id&&x.revision===r.revision):null;return [c.split==='train'?'Training':c.split==='evaluation'?'Evaluation':c.split,recipe?.label,c.environment,recipe?'Settings r'+r.revision:c.experiment].filter(x=>x!=null).join(' · ');}
 function draw(state){
  const {parent,host}=state;host.replaceChildren();host.className='iv-panel training-measure-comparison';host.id='training-measure-comparison';
  host.append(el('h2','Compare behavior on the same samples'),el('p','Keep this saved training population fixed while comparing existing monitors. Original measurements stay pinned; added monitors use current saved observations on those source identities. No model calls.','iv-note'));
  if(!state.options&&!state.result){host.append(el('p',state.error||'Loading available monitors…','iv-note'));return;}
  const choices=state.options||{monitors:state.result.metrics.map(m=>({...m.monitor,enabled:null}))};
  const setup=el('details');setup.open=!state.result;setup.append(el('summary','Choose populations and measures'));
  const form=el('form'),fields=el('div',undefined,'training-comparison-fields'),spec=state.spec;
  fields.append(select('Comparison cohort',parent.snapshot.cohorts.map((c,i)=>[String(i),cohortName(c.cohort,parent)]),String(state.cohort),v=>{state.cohort=Number(v);spec.cohort=parent.snapshot.cohorts[state.cohort].cohort;delete spec.step;if([spec.focus,spec.reference].some(s=>s.kind==='reward_pattern')){spec.focus={kind:'stage',value:'generated'};spec.reference={kind:'stage',value:'optimizer'};}draw(state);}));
  const rows=parent.snapshot.samples.filter(r=>Object.entries(spec.cohort).every(([k,v])=>same(r[k]??null,v)));
  const steps=[...new Set(rows.filter(r=>Number.isInteger(r.step)).map(r=>r.step))].sort((a,b)=>a-b);
  fields.append(select('Recorded coordinate',[['','All saved coordinates'],...steps.map(n=>[String(n),String(n)])],spec.step==null?'':String(spec.step),v=>{if(v==='')delete spec.step;else spec.step=Number(v);}));
  const rewardChoices=parent.reward_comparison&&same(parent.reward_comparison.cohort,spec.cohort)?parent.reward_comparison.pattern_options.map(p=>['reward_pattern:'+p.value,p.label]):[];
  const populations=[...rewardChoices,...(parent.snapshot.selection?Object.entries(decisions).map(([k,v])=>['filter:'+k,v]):[]),...Object.entries(stages).map(([k,v])=>['stage:'+k,v])];
  for(const [key,label]of [['focus','Focus population'],['reference','Reference population']])fields.append(select(label,populations,spec[key].kind+':'+spec[key].value,v=>{spec[key]=selected(v);}));
  form.append(fields);
  const measures=el('fieldset',undefined,'training-comparison-monitors');measures.append(el('legend','Existing monitors · select up to eight'));
  for(const m of choices.monitors){const label=el('label'),box=el('input');box.type='checkbox';box.value=m.id;box.checked=spec.monitors.includes(m.id);box.setAttribute('aria-label',m.name+' · '+m.observer);box.onchange=()=>{spec.monitors=box.checked?[...spec.monitors,m.id]:spec.monitors.filter(k=>k!==m.id);};label.append(box,el('span',m.name+' · '+m.observer+(m.enabled===false?' · paused':'')));measures.append(label);}form.append(measures);
  const preview=el('button','Preview comparison','primary');preview.type='submit';preview.disabled=state.busy;form.append(preview);form.onsubmit=async e=>{e.preventDefault();state.busy=true;state.error='';draw(state);try{state.result=await api('/api/training-comparisons/preview',{parent_id:parent.id,spec:structuredClone(spec)});state.pinned=false;state.caseMonitor=state.result.metrics[0].monitor.id;state.casePage=0;}catch(e){state.error=e.message;}finally{state.busy=false;draw(state);}};
  setup.append(form);host.append(setup);if(state.error){const error=el('p',state.error,'iv-error');error.setAttribute('role','alert');host.append(error);}
  if(!state.result)return;
  const result=state.result,labels=selectorText(result.spec.focus,parent)+' versus '+selectorText(result.spec.reference,parent);
  host.append(el('h3',labels),el('p',`${result.focus_ids.length} focus · ${result.reference_ids.length} reference · ${result.overlap_ids.length} shared samples · ${result.common_support_ids.length} measured by every selected monitor. ${state.pinned?'Saved comparison.':'Preview; save to retain this comparison and inspect exact cases.'}`,'iv-note'));
  if(result.reward_context)host.append(el('p',result.reward_context.boundary,'iv-note'));
  if(result.source_coverage){const s=result.source_coverage;host.append(el('p',`${s.sample_members} declared samples refer to ${s.unique_source_rollouts} distinct rollout sources; ${s.samples_without_source} have no saved source join. ${s.shared_sources.length} sources are shared by multiple samples. Measures describe associated rollout evidence; they do not establish which tokens received training credit.`,'iv-note'));}
  if(result.overlap_ids.length)host.append(el('p','These populations overlap. Their counts are not additive, and they are not independent groups.','iv-warning'));
  const wrap=el('div',undefined,'training-comparison-table'),table=el('table'),head=el('tr');
  for(const label of ['Measure','Focus mean','Reference mean','Difference','Common samples Δ','Within groups Δ'])head.append(el('th',label));table.append(head);
  for(const m of result.metrics){const row=el('tr'),name=el('td'),choose=el('button',m.monitor.name);choose.type='button';choose.title=m.description;choose.onclick=()=>{state.caseMonitor=m.monitor.id;state.casePage=0;draw(state);host.querySelector('.training-comparison-cases').scrollIntoView({block:'nearest'});};name.append(choose,el('small',m.monitor.observer));row.append(name);
   for(const key of ['focus','reference']){const td=el('td');td.append(el('strong',fmt(m[key].mean_per_rollout,m)),el('small',coverage(m[key])));row.append(td);}
   row.append(el('td',delta(m.difference,m)));const common=el('td');common.append(el('strong',delta(m.common_support.difference,m)),el('small',m.common_support.focus.measured+' focus / '+m.common_support.reference.measured+' reference'));row.append(common);
   const group=el('td');group.append(el('strong',delta(m.within_group.mean_group_difference,m)),el('small',m.within_group.compared_groups+' / '+m.within_group.groups+' groups'));row.append(group);table.append(row);
  }wrap.append(table);host.append(wrap,el('p',(result.weighting==='unique_source_rollout'?'Means weight each distinct source rollout once in each population. Source-rollout behavior is context, not sample-span behavior. ':'Means weight each declared sample once. ')+'Common-sample differences use only samples measured by every selected monitor. Within-group differences weight each comparable recorded group equally. These summaries answer different questions.','iv-note'));
  if(!state.pinned){const save=el('button','Save comparison & inspect cases','primary');save.disabled=state.busy;save.onclick=async()=>{save.disabled=true;try{const next=await api('/api/training-comparisons',{parent_id:parent.id,spec:result.spec,preview_id:result.id});location.href='/investigate?'+new URLSearchParams({saved:next.id});}catch(e){state.error=e.message;draw(state);}};host.append(save);}
  renderCases(state);
  const associations=el('details');associations.append(el('summary','Pairwise associations · exploratory'));
  for(const pair of result.associations){const a=result.metrics.find(m=>m.monitor.id===pair.x),b=result.metrics.find(m=>m.monitor.id===pair.y);associations.append(el('p',`${a.monitor.name} × ${b.monitor.name}: ${pair.rho==null?'unavailable':pair.rho.toFixed(2)} · ${pair.n} paired ${pair.weighting==='unique_source_rollout'?'source rollouts':'samples'}${pair.reason?' · '+pair.reason:''}`,'iv-note'));}
  associations.append(el('p','Spearman rank associations are unadjusted and can reflect group dependence or shared definitions. Paired sample sets can differ by pair. No significance or causal explanation is asserted.','iv-note'));host.append(associations);
  const definition=el('details');definition.append(el('summary','Comparison definitions and evidence'));for(const limit of result.limits)definition.append(el('p',limit,'iv-note'));definition.append(el('pre',JSON.stringify({id:result.id,spec:result.spec,observation_origins:result.metrics.map(m=>({monitor:m.monitor.id,origin:m.observation_origin}))},null,2)));host.append(definition);
 }
 function renderCases(state){
  const {parent,result,host}=state,m=result.metrics.find(m=>m.monitor.id===state.caseMonitor)||result.metrics[0];state.caseMonitor=m.monitor.id;
  const box=el('section',undefined,'training-comparison-cases');box.append(select('Inspect measure',result.metrics.map(m=>[m.monitor.id,m.monitor.name]),m.monitor.id,v=>{state.caseMonitor=v;state.casePage=0;draw(state);}),el('p',m.description,'iv-note'));
  for(const side of ['focus','reference']){const s=m[side],pooled=s.pooled_opportunities;box.append(el('p',`${side==='focus'?'Focus':'Reference'}: ${coverage(s)}${pooled?` · pooled opportunities ${pooled.numerator}/${pooled.denominator} · ${pooled.unknown} unknown · ${pooled.rollouts_without_counts} ${s.weighting==='unique_source_rollout'?'source rollouts':'samples'} without complete counts`:''}`,'iv-note'));
   if(Object.keys(s.missing_statuses).length)box.append(el('p','Missing: '+Object.entries(s.missing_statuses).map(([k,v])=>k.replaceAll('_',' ')+' '+v).join(' · '),'iv-note'));
  }
  if(m.shared_source_rollouts)box.append(el('p',`${m.shared_source_rollouts} source rollouts appear on both sides through different samples. These populations share episode evidence.`,'iv-warning'));
  const groups=el('details');groups.append(el('summary','Group matching and common-sample contrast'),el('p',m.within_group.definition,'iv-note'),el('p',`${m.within_group.missing_group_samples} samples without group IDs · ${m.within_group.groups_with_unrecorded_context} compared groups with incomplete context`,'iv-note'));
  for(const [reason,n]of Object.entries(m.within_group.excluded_groups))groups.append(el('p',reason.replaceAll('_',' ')+': '+n,'iv-note'));
  groups.append(el('p','Within-group difference on common measured samples: '+delta(m.common_within_group.mean_group_difference,m)+' · '+m.common_within_group.compared_groups+' groups','iv-note'));box.append(groups);
  const union=new Set([...result.focus_ids,...result.reference_ids]),samples=result.samples.filter(s=>union.has(s.id)),wrap=el('div',undefined,'training-comparison-table'),table=el('table'),head=el('tr');
  ['Sample / group','Population','Value / coverage','Exact evidence'].forEach(t=>head.append(el('th',t)));table.append(head);
  for(const s of samples.slice(state.casePage*20,state.casePage*20+20)){const v=m.values[s.id],row=el('tr'),name=el('td');name.append(el('strong',s.task_id||s.sample_id||s.rollout_id),el('small',s.sample_id?'Sample '+s.sample_id+' · source '+(s.rollout_id||'unavailable'):s.rollout_id),el('small',(s.group_id||'Group unavailable')+' · '+s.producer));row.append(name,el('td',[result.focus_ids.includes(s.id)?'Focus':null,result.reference_ids.includes(s.id)?'Reference':null].filter(Boolean).join(' + ')));
   const value=el('td');value.append(el('strong',fmt(v.value,m)),el('small',v.status.replaceAll('_',' ')));if(v.reason)value.append(el('small',v.reason));row.append(value);const evidence=el('td');
   if(state.pinned&&s.run_id&&(v.id||parent.source_graphs[s.run_id])){const a=el('a','Inspect case'),q=new URLSearchParams({run:s.run_id,observer:v.id?m.monitor.observer:'source',return_to:'/investigate?'+new URLSearchParams({saved:parent.id})});if(v.id)q.set('value',v.id);else q.set('graph',parent.source_graphs[s.run_id].id);a.href='/semantic-map?'+q;evidence.append(a);}else evidence.append(el('span',state.pinned?'Source not captured in this population':'Save comparison to inspect'));
   if(s.reward_evidence){const reward=el('details');reward.append(el('summary','Reward selection evidence'),el('pre',JSON.stringify(s.reward_evidence,null,2)));evidence.append(reward);}
   const raw=el('details');raw.append(el('summary','Measurement record'),el('pre',JSON.stringify(s.sample_id?{sample_id:s.sample_id,source:s.source||null,interaction_ids:s.interaction_ids||[],measurement_grain:s.measurement_grain,episode:s.episode||null,token_context_summary:s.token_context_summary||null,measurement:v}:v,null,2)));evidence.append(raw);row.append(evidence);table.append(row);
  }wrap.append(table);box.append(wrap);const pager=el('div',undefined,'pager');for(const [d,label]of [[-1,'Previous cases'],[1,'Next cases']]){const b=el('button',label);b.disabled=d<0?state.casePage===0:(state.casePage+1)*20>=samples.length;b.onclick=()=>{state.casePage+=d;draw(state);};pager.append(b);}box.append(pager);host.append(box);
 }
 window.renderTrainingMeasureComparison=parent=>{
  let state=states.get(parent.id);
  if(!state){const result=parent.measure_comparison||null,cohort=parent.snapshot.cohorts.findIndex(c=>same(c.cohort,parent.view.selection?.cohort)),index=Math.max(0,cohort);
   state={parent,cohort:index,options:null,result,pinned:!!result,casePage:0,error:'',busy:false,
    spec:result?structuredClone(result.spec):{cohort:parent.snapshot.cohorts[index].cohort,focus:{kind:parent.snapshot.selection?'filter':'stage',value:parent.snapshot.selection?'admitted':'generated'},reference:{kind:parent.snapshot.selection?'filter':'stage',value:parent.snapshot.selection?'rejected':'optimizer'},monitors:parent.snapshot.monitor?[parent.snapshot.monitor.id]:[]}};
   if(result)state.cohort=parent.snapshot.cohorts.findIndex(c=>same(c.cohort,result.spec.cohort));
   else if(parent.reward_comparison){
    if(Number.isInteger(parent.view.selection?.step))state.spec.step=parent.view.selection.step;
    const rows=parent.reward_comparison.evidence.records.filter(r=>state.spec.step===undefined||r.step===state.spec.step);
    const ordered=parent.reward_comparison.pattern_options.filter(p=>p.value!=='unavailable').map(p=>({...p,count:rows.filter(r=>r.reward_pattern===p.value).length})).sort((a,b)=>b.count-a.count);
    const present=ordered.filter(p=>p.count);if(present.length>=2){state.spec.focus={kind:'reward_pattern',value:present[0].value};state.spec.reference={kind:'reward_pattern',value:present[1].value};}
   }states.set(parent.id,state);
   api('/api/training-comparisons/options').then(data=>{state.options=data;draw(state);}).catch(e=>{state.error=e.message;draw(state);});
  }
  state.host=el('section');draw(state);return state.host;
 };
})();
