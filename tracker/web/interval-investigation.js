'use strict';
/* Shared interval selection, pinned evidence and monitor presets. */
const IntervalInvestigation=(()=>{
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 const button=(text,fn)=>{const n=el('button',text);n.type='button';n.onclick=fn;return n;};
 const link=(text,url)=>{const n=el('a',text);n.href=url;return n;};
 const fmt=(v,unit)=>typeof v==='number'&&Number.isFinite(v)?unit==='fraction'?(v*100).toFixed(1)+'%':Number(v.toFixed(3)).toLocaleString():'Unavailable';
 async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);const d=await r.json();if(!r.ok)throw Error(d.error||r.statusText);return d;}
 const details=(title,value)=>{const d=el('details');d.append(el('summary',title),el('pre',typeof value==='string'?value:JSON.stringify(value,null,2)));return d;};
 const table=(heads,rows)=>{const wrap=el('div',null,'ii-table'),t=el('table'),h=el('tr');heads.forEach(s=>h.append(el('th',s)));const thead=el('thead');thead.append(h);t.append(thead);const body=el('tbody');for(const row of rows){const tr=el('tr');for(const value of row){const td=el('td');td.append(value instanceof Node?value:document.createTextNode(String(value??'Unavailable')));tr.append(td);}body.append(tr);}t.append(body);wrap.append(t);return wrap;};
 function field(form,label,value='',type='text'){const l=el('label',label),i=el('input');i.type=type;i.value=value??'';i.required=true;if(type==='number'){i.min='0';i.step='1';}l.append(i);form.append(l);return i;}
 function modal(title){const d=el('dialog',null,'ii-dialog'),h=el('div',null,'ii-head'),body=el('div');h.append(el('h2',title),button('Close',()=>d.close()));d.append(h,body);document.body.append(d);d.addEventListener('close',()=>d.remove());d.showModal();return {d,body};}
 function range(a,b){const lo=Math.min(a,b),hi=Math.max(a,b),width=hi-lo+1;return {current:[lo,hi],baseline:lo>0?[Math.max(0,lo-width),lo-1]:null};}
 async function open(context={}){
  const {d,body}=modal('Investigate a training interval'),form=el('form',null,'ii-form');body.append(form);
  form.append(el('p','One selection freezes outcome, task mix, pending work, training use, behavior and measurement reliability. Later arrivals require a new comparison.','field-note'));
  const exp=field(form,'Experiment',context.experiment),env=field(form,'Environment (optional)',context.environment);env.required=false;
  const controls=el('div',null,'ii-ranges'),a=el('fieldset'),b=el('fieldset');a.append(el('legend','Reference interval'));b.append(el('legend','Selected interval'));
  const steps=[...new Set((context.monitors||[]).flatMap(m=>(m.series||[]).filter(s=>!context.experiment||s.cohort.experiment===context.experiment).flatMap(s=>s.points.map(p=>p.step))))].sort((a,b)=>a-b);
  const last=steps.at(-1),defaults=Number.isInteger(last)?range(Math.max(1,last-3),last):{baseline:null,current:null};
  const startA=field(a,'Reference first step',context.baseline?.[0]??defaults.baseline?.[0],'number'),endA=field(a,'Reference last step',context.baseline?.[1]??defaults.baseline?.[1],'number');
  const startB=field(b,'Selected first step',context.current?.[0]??defaults.current?.[0],'number'),endB=field(b,'Selected last step',context.current?.[1]??defaults.current?.[1],'number');controls.append(a,b);form.append(controls);
  let monitors=context.monitors;
  if(!monitors){try{monitors=(await api('/api/monitoring')).monitors;}catch(e){form.append(el('p',e.message));return;}}
  const choose=el('details'),list=el('div',null,'ii-monitors');choose.append(el('summary','Measures in this investigation (up to 24)'),list);
  const inputs=[];for(const m of monitors){const label=el('label'),input=el('input');input.type='checkbox';input.value=m.id;input.checked=(context.monitor_ids?context.monitor_ids.includes(m.id):m.enabled)&&inputs.filter(i=>i.checked).length<24;label.append(input,document.createTextNode(m.name));list.append(label);inputs.push(input);}form.append(choose);
  const title=field(form,'Investigation title',context.title||'Training interval review'),hyp=field(form,'Hypothesis or question (optional)',context.hypothesis||'');hyp.required=false;
  const error=el('p',null,'ii-error');error.setAttribute('role','alert');const submit=el('button','Capture synchronized investigation','primary');submit.type='submit';form.append(submit,error);
  form.onsubmit=async e=>{e.preventDefault();submit.disabled=true;error.textContent='';try{
   const result=await api('/api/investigations/interval',{experiment:exp.value,environment:env.value||null,baseline:[+startA.value,+endA.value],current:[+startB.value,+endB.value],monitor_ids:inputs.filter(i=>i.checked).map(i=>i.value),title:title.value,hypothesis:hyp.value,...(context.parent_id?{parent_id:context.parent_id}:{})});
   location.href='/investigate?'+new URLSearchParams({saved:result.id});
  }catch(e){error.textContent=e.message;submit.disabled=false;}};
 }
 function chart(cohort,scope,unit,events=[]){
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 640 140');svg.setAttribute('role','img');svg.setAttribute('aria-label','Reference and selected interval; raw saved per-step values. Gaps are not interpolated.');svg.classList.add('ii-chart');
  const add=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text!=null)n.textContent=text;svg.append(n);return n;};
  const all=[...cohort.points.baseline,...cohort.points.current],steps=[...new Set(all.map(p=>p.step))].sort((a,b)=>a-b),points=steps.map(step=>{const ps=all.filter(p=>p.step===step),known=ps.filter(p=>p.value!==null);const ratio=known.some(p=>p.denominator!=null);const denom=known.reduce((s,p)=>s+(p.denominator||0),0);return {step,value:ratio?(denom?known.reduce((s,p)=>s+(p.numerator||0),0)/denom:null):known.length?known.reduce((s,p)=>s+p.value,0)/known.length:null};});
  const valid=points.filter(p=>p.value!==null);if(!valid.length)return el('p','No measured values in these windows.','field-note');
  const lo=Math.min(0,...valid.map(p=>p.value)),hi=unit==='fraction'?1:Math.max(...valid.map(p=>p.value),lo+0.01),xmin=scope.baseline[0],xmax=scope.current[1],x=v=>52+(v-xmin)/(xmax-xmin||1)*568,y=v=>105-(v-lo)/(hi-lo)*86;
  add('rect',{x:x(scope.current[0]),y:9,width:620-x(scope.current[0]),height:101,fill:'#edf3ff'});
  for(const v of [lo,hi]){add('line',{x1:52,x2:620,y1:y(v),y2:y(v),stroke:'#dfe5ee'});add('text',{x:46,y:y(v)+4,'text-anchor':'end'},fmt(v,unit));}
  let previous=null,path='';for(const p of points){if(p.value===null){previous=null;continue;}path+=(previous&&p.step===previous.step+1?'L':'M')+x(p.step)+','+y(p.value);add('circle',{cx:x(p.step),cy:y(p.value),r:3,fill:'#3864d9'});previous=p;}add('path',{d:path,fill:'none',stroke:'#3864d9','stroke-width':2});
  for(const v of [scope.baseline[0],scope.baseline[1],scope.current[0],scope.current[1]].filter((v,i,a)=>a.indexOf(v)===i))add('text',{x:x(v),y:132,'text-anchor':v===xmin?'start':v===xmax?'end':'middle'},'Step '+v);
  const retired=new Set(events.map(e=>e.supersedes).filter(Boolean));for(const e of events.filter(e=>!retired.has(e.id)&&(!e.environment||e.environment===cohort.cohort.environment)&&e.clock===cohort.cohort.training_clock&&e.basis===cohort.cohort.training_step_basis&&e.step>=xmin&&e.step<=xmax)){const mark=add('line',{x1:x(e.step),x2:x(e.step),y1:8,y2:111,stroke:'#94653d','stroke-dasharray':'3 3'});const t=document.createElementNS(ns,'title');t.textContent=e.kind+': '+e.title;mark.append(t);}
  return svg;
 }
 function evidenceCases(explanation){return [...(explanation.analysis_cases||[]),...(explanation.cases||[])];}
 function receiptLabel(p,unit){
  if(typeof p.value==='number'&&Number.isFinite(p.value))return fmt(p.value,unit);
  if(p.status==='error')return 'Measurement error';
  if(!p.value_id)return 'No receipt at capture';
  if(p.unknown_opportunities>0)return `Unresolved evidence · ${p.unknown_opportunities} opportunities`;
  if(p.opportunities===0)return 'No eligible opportunities';
  return 'Recorded observation · no numeric value';
 }
 async function cases(panel,cohort,side){const {body}=modal(panel.monitor.name+' · '+(side==='current'?'selected':'reference')+' cases');
  let page=0;const rows=cohort.points[side];function draw(){body.replaceChildren();body.append(el('p',`${Math.min(page*30+1,rows.length)}–${Math.min((page+1)*30,rows.length)} of ${rows.length} rollout receipts`));
  body.append(el('p','Exact receipts from the frozen comparison. Missing measurements stay missing even if new results have arrived.','field-note'));
  for(const p of rows.slice(page*30,(page+1)*30)){const row=el('details');row.append(el('summary',`Step ${p.step} · ${p.task_id||'Task unspecified'} · ${receiptLabel(p,panel.unit)}`));
   if(!p.value_id){row.append(el('p','No receipt at capture.'));body.append(row);continue;}
   row.append(link('Open pinned rollout map','/semantic-map?'+new URLSearchParams({run:p.run_id,value:p.value_id,observer:panel.monitor.observer,return_to:location.pathname+location.search})));
   const load=button('Inspect saved evidence',async()=>{load.disabled=true;try{const d=await api('/api/monitoring/values/'+encodeURIComponent(p.value_id));const explanation=d.explanation||{};for(const [index,c] of evidenceCases(explanation).entries()){const block=el('details');block.open=index===0;block.append(el('summary',c.label||c.status||'Evidence case'),el('p','Result: '+(c.status||'Recorded relationship').replaceAll('_',' ')));const record=c.record;if(record?.check_history){block.append(EvaluationEvidence.delivery(record,d.run.events));}else if(record?.failure_action_id){const events=new Map(d.run.events.map(e=>[e.id,e]));const stages=[['Failed attempt',[record.failure_action_id,record.failure_result_event_id]],...(record.attempts||[]).map((a,i)=>['Follow-up '+(i+1)+' · '+a.result,[...(a.changes||[]).flatMap(change=>[change.action_id,change.result_event_id]),a.action_id,a.result_event_id]])];for(const [title,ids]of stages){const stage=el('section',null,'ii-witness');stage.append(el('strong',title));for(const id of [...new Set(ids.filter(Boolean))]){const event=events.get(id);stage.append(el('small',id+' · '+(event?.kind||'record')),el('pre',event?.text||JSON.stringify(event?.arguments||{},null,2)));}block.append(stage);}}else{const nodes=new Map((d.graph?.nodes||[]).map(n=>[n.id,n]));for(const id of c.node_ids||[]){const n=nodes.get(id);const text=n?.properties?.text||n?.label;if(text)block.append(el('p',text));}}block.append(details('Full case record',c));row.append(block);}row.append(details('Exact evidence and limits',explanation));}catch(e){row.append(el('p',e.message));load.disabled=false;}});row.append(load);body.append(row);
  }
  const paging=el('div',null,'ii-actions'),prev=button('Previous',()=>{page--;draw();}),next=button('Next',()=>{page++;draw();});prev.disabled=page===0;next.disabled=(page+1)*30>=rows.length;paging.append(prev,next);body.append(paging);
  }draw();
 }
 function section(host,title){const s=el('section',null,'iv-panel ii-panel');s.id='ii-'+title.toLowerCase().replace(/[^a-z0-9]+/g,'-');s.append(el('h2',title));host.append(s);return s;}
 function render(host,doc,onRevision){
  const s=doc.snapshot;host.replaceChildren();const pinned=el('div',null,'ii-pinned');pinned.append(el('strong',doc.title),el('span',`Captured ${new Date(s.captured_at).toLocaleString()} · immutable`),button('Compare with latest arrivals',()=>open({...doc.controls,title:doc.title,hypothesis:doc.hypothesis,parent_id:doc.id})));host.append(pinned);
  const scope=section(host,'One interval · shared evidence');scope.append(el('p',`${s.scope.experiment} · ${s.scope.environment||'all environments'} · reference ${s.scope.baseline.join('–')} → selected ${s.scope.current.join('–')}`),el('p','Source intervals stay separate from native learner steps. Related records are joined by exact identity.','field-note'),details('Coordinate definitions and alignment',s.clock_boundary));
  if(s.excluded.missing_coordinates)scope.append(el('p',`${s.excluded.missing_coordinates} sources excluded: no recorded training coordinate.`,'ii-warning'));
  const jump=el('nav',null,'ii-jumps');jump.setAttribute('aria-label','Interval evidence');for(const [label,id]of [['Population','ii-outcome-context-task-composition'],['Learning signals','ii-recorded-learning-signals'],['Behavior','ii-behavior-outcome-measures'],['Run history','ii-run-history-candidate-explanations'],['Follow-up','ii-hypothesis-follow-up']])jump.append(link(label,'#'+id));scope.append(jump);
  if(s.excluded.unselected_monitors)scope.append(el('p',`${s.excluded.unselected_monitors} registered monitors are outside this capture. Change the measure selection when creating a new comparison.`,'field-note'));
  const composition=section(host,'Outcome context & task composition');
  const mix=new Map();for(const r of s.source_rows){const side=s.population.baseline.includes(r.id)?'baseline':'current';const key=JSON.stringify([r.adapter,...['environment','environment_version','split','task_id','task_revision','training_clock','training_step_basis','sampling','reward_definition','source_selection','training_inclusion'].map(k=>r.metadata[k])]);if(!mix.has(key))mix.set(key,{label:[r.metadata.environment||'Environment unspecified',r.metadata.split||'split unspecified',r.metadata.task_id||'Task unspecified',r.metadata.training_clock||'clock unspecified',r.metadata.training_step_basis||'basis unspecified',...['sampling','reward_definition','task_revision'].filter(k=>r.metadata[k]).map(k=>k.replaceAll('_',' ')+': '+JSON.stringify(r.metadata[k]))].join(' · '),baseline:[],current:[]});mix.get(key)[side].push(r);}
  const outcome=rows=>{const known=rows.filter(r=>typeof r.outcome.verified_success==='boolean');return `${known.filter(r=>r.outcome.verified_success).length}/${known.length} reported successes · ${rows.length-known.length} unknown · ${rows.filter(r=>r.state==='in_progress').length} in progress`;};
  composition.append(table(['Recorded task / context','Reference','Selected'],[...mix.values()].map(r=>[r.label,outcome(r.baseline),outcome(r.current)])),el('p','Reported success is not necessarily an independent evaluator. Task matching does not control unrecorded difficulty or budget changes.','field-note'));
  const grid=el('div',null,'ii-grid');host.append(grid);const pending=section(grid,'Pending generation & capture');
  if(!s.declared_populations.available)pending.append(el('p','Generation membership unavailable. Observed traces cannot establish how many rollouts are still outstanding.','ii-warning'));
  if(s.declared_populations.available){const d=s.declared_populations;pending.append(el('p',`${d.distinct_declared_rollouts} distinct rollouts declared · ${d.distinct_delivered_rollouts} delivered · ${d.distinct_declared_rollouts-d.distinct_delivered_rollouts} not delivered`));
   const unsettled=d.cohorts.filter(c=>!c.selected_generation_settled||c.delivered<c.declared||c.source_conflicts);
   for(const c of unsettled){pending.append(el('h3',`${c.label} · ${c.coordinate.clock} / ${c.coordinate.basis} ${c.coordinate.index}`),el('p',`${c.declared} declared · ${c.delivered} delivered · ${c.selected_generation_settled?'generation settled':'generation not settled'} · ${c.sealed?'membership sealed':'membership open'}`),details('Missing members and clock alignment',c));}
   const all=el('details');all.append(el('summary',`All ${d.cohorts.length} generation cohorts`),table(['Cohort / coordinate','Declared / delivered','Generation states'],d.cohorts.map(c=>[`${c.label} · ${c.coordinate.clock} / ${c.coordinate.basis} ${c.coordinate.index}`,`${c.declared} / ${c.delivered}`,Object.entries(c.generation_states).filter(([,n])=>n).map(([k,n])=>n+' '+k).join(' · ')])));pending.append(all);
  }
  if(s.declared_populations.truncated)pending.append(el('p','Generation declarations truncated. Narrow the interval.','ii-warning'));
  pending.append(el('p',s.declared_populations.clock_boundary,'field-note'));
  const training=section(grid,'Selection & learner use');const windows=s.training_lineage.windows;
  training.append(table(['Observed stage','Reference','Selected'],['generated','scored','admitted','backward','optimizer'].map(k=>[k==='optimizer'?'Optimizer membership':k.replaceAll('_',' '),...['baseline','current'].map(side=>{const r=windows[side].stages[k];return `${r.member_rollouts}/${windows[side].source_rollouts} source rollouts · ${r.unknown_rollouts} unknown`;})])),el('p',s.training_lineage.membership_boundary,'field-note'));
  for(const side of ['baseline','current'])training.append(details(side+' · named filters, objective/recipe records and learner coordinates',windows[side]));
  const signals=section(host,'Recorded learning signals');
  const contextLabel=c=>[c.component,c.filter,c.stage?.replaceAll('_',' '),c.environment,c.split].filter(Boolean).join(' · ');
  let hasSignals=false;
  for(const family of ['scores','filters','uses']){
   const groups=new Map();for(const side of ['baseline','current'])for(const g of s.learning_context?.windows[side]?.[family]||[]){const key=JSON.stringify(g.context);if(!groups.has(key))groups.set(key,{context:g.context});groups.get(key)[side]=g;}
   for(const pair of groups.values()){hasSignals=true;signals.append(el('h3',contextLabel(pair.context)),details('Exact producer, definition and recipe',pair.context));
    const values=fn=>['baseline','current'].map(side=>pair[side]?fn(pair[side]):'No recorded evidence');
    if(family==='scores')signals.append(table(['Score population','Reference mean / coverage','Selected mean / coverage'],['generated','admitted','optimizer'].map(stage=>[stage==='optimizer'?'Optimizer membership':stage,...values(g=>{const v=g.stages[stage];return `${fmt(v.mean)} · ${v.scored}/${v.members} scored · ${v.ambiguous} ambiguous`;})])));
    if(family==='filters')signals.append(table(['Filter decision','Reference samples','Selected samples'],['admitted','rejected','unknown','conflicting'].map(state=>[state,...values(g=>g[state])])));
    if(family==='uses')signals.append(table(['Recorded use signal','Reference','Selected'],[
     ['Use receipts',...values(g=>g.uses)],['Native learner steps',...values(g=>`${g.learner_steps[0]}–${g.learner_steps.at(-1)} · ${g.learner_steps.length} distinct steps`)],
     ['Masked-token fraction',...values(g=>fmt(g.masked_fraction,'fraction'))],['Token evidence',...values(g=>`${g.paired_token_uses}/${g.uses} uses · ${g.loss_tokens}/${g.model_tokens} loss/model tokens`)],['Mean recorded advantage',...values(g=>`${fmt(g.advantage_mean)} · ${g.advantage_observed_uses}/${g.uses} uses`)]]));
   }
  }
  if(!hasSignals)signals.append(el('p','No exact-joined score, filter or learner-use records. Missing telemetry is not no learning.','ii-warning'));
  signals.append(el('p',s.learning_context?.boundary,'field-note'),el('p','GPU-hour learning efficiency needs timestamped resource allocations and comparable evaluations. Action counts and masked-token fractions cannot substitute.','field-note'));
  const measures=section(host,'Behavior & outcome measures');measures.append(el('p','Raw per-step values. Shading marks the selected interval. Different configurations remain separate; no universal “healthy” direction is assigned.','field-note'));
  if(!s.panels.length)measures.append(link('Configure measures in Monitor management','/monitors'));
  for(const panel of s.panels){const card=el('article',null,'ii-measure');card.append(el('h3',panel.monitor.name),el('p',panel.monitor.analysis_definition?.description||panel.monitor.custom?.description||panel.limits.at(-1),'field-note'));
   const rel=panel.reliability;card.append(el('p',`Protocol: ${rel.observer} · definition ${rel.definition_version}`,'ii-version'),el('p',['anchor_ratio','opportunity_ratio'].includes(panel.aggregation)?'Aggregation: pooled decidable opportunities.':'Aggregation: mean per measured rollout.','field-note'));
   const versions=rel.graph_versions||[];if(versions.length>1)card.append(el('p','Multiple annotation or adapter definitions are included. Version membership is listed below.','ii-warning'));
   if(panel.monitor.observer!=='source'){
    const coverage=side=>{const rows=s.population[side].map(id=>rel.action_coverage?.[id]).filter(Boolean),known=rows.filter(r=>r.denominator!=null);if(!known.length)return `Unavailable · 0/${s.population[side].length} source rollouts have coverage records`;return `${known.reduce((n,r)=>n+(r.numerator||0),0)}/${known.reduce((n,r)=>n+(r.denominator||0),0)} actions annotated · ${rows.length}/${s.population[side].length} source rollouts have coverage records`;};
    card.append(table(['Annotation coverage · reference','Annotation coverage · selected'],[[coverage('baseline'),coverage('current')]]));
   }
   if(panel.monitor.population)card.append(el('p','Additional monitor scope: '+Object.entries(panel.monitor.population).map(([k,v])=>k+' = '+v).join(' · '),'field-note'));
   for(const c of panel.cohorts){const info=Object.entries(c.cohort).filter(([,v])=>v!=null).map(([k,v])=>k.replaceAll('_',' ')+': '+(typeof v==='object'?JSON.stringify(v):v)).join(' · ');card.append(el('p',info,'ii-cohort'),chart(c,s.scope,panel.unit,s.history));
    const summary=v=>`${fmt(v.value,panel.unit)} · ${v.measured}/${v.total} measured`+(v.denominator!=null?` · ${v.numerator}/${v.denominator} decidable opportunities`:v.opportunities?` · ${v.opportunities} recorded opportunities`:'')+` · ${v.unknown_opportunities} unresolved opportunities`;
    card.append(table(['Reference','Selected','Difference'],[[summary(c.baseline),summary(c.current),c.delta==null?'Unavailable':(c.delta>0?'+':'')+(panel.unit==='fraction'?(100*c.delta).toFixed(1)+' pp':fmt(c.delta))]]));
    if(c.coverage_change)card.append(el('p',`Numeric-value coverage changed by ${(100*c.coverage_change).toFixed(1)} percentage points. This can alter the apparent behavior trend.`,'ii-warning'));
    if(c.task_mix.recorded_task_mix_distance>0)card.append(el('p','Task composition differs between these intervals. Open the task breakdown for per-task values.','ii-warning'));
    const actions=el('div',null,'ii-actions');actions.append(button('Reference evidence',()=>cases(panel,c,'baseline')),button('Selected evidence',()=>cases(panel,c,'current')));card.append(actions);
   }
   if(!panel.cohorts.length)card.append(el('p','No eligible source rollouts in the selected intervals.','field-note'));
   card.append(el('p',rel.audits.length?`${rel.audits.length} reviewer reports match these exact receipts.`:panel.monitor.observer==='source'?'Uses recorded source evidence; no independent audit results match these receipts.':'No matching audit results. Semantic accuracy is unestablished.','ii-warning'),details('Measurement coverage, versions & audit results',rel));
   for(const review of panel.review)card.append(details(review.title,review.evidence+'\nNext check: '+review.next_check));measures.append(card);
  }
  const events=section(host,'Run history & candidate explanations');events.append(el('p','Events use explicit native clocks. Only matching clock/basis events are marked on a curve; other events remain listed as context.','field-note'));
  const superseded=new Set(s.history.map(e=>e.supersedes).filter(Boolean));for(const e of s.history){const row=el('details');row.append(el('summary',`${e.clock} / ${e.basis} ${e.step} · ${e.title}${superseded.has(e.id)?' (superseded)':''}`),el('p',e.detail),el('p',e.attribution,'field-note'));if(e.investigation_id)row.append(link('Linked hypothesis & follow-up','/investigate?saved='+encodeURIComponent(e.investigation_id)));events.append(row);}
  if(!s.history.length)events.append(el('p','No run events recorded at capture. Missing history does not mean settings stayed unchanged.','field-note'));
  events.append(button('Record a run event',()=>eventForm(doc)));
  const notes=section(host,'Hypothesis & follow-up');notes.append(el('p',doc.hypothesis||'No hypothesis recorded.'),el('p','A coincident event is a candidate explanation, not an established cause.','field-note'));
  if(typeof InvestigationFollowups!=='undefined')notes.append(InvestigationFollowups.render(doc,onRevision,()=>{}));
  host.append(details('Definitions & limitations',doc.limits));
 }
 function eventForm(doc){const {body}=modal('Record a run event'),form=el('form',null,'ii-form');body.append(form);const label=el('label','Event type'),kind=el('select');for(const value of ['curriculum','reward_grader','sampling','budget_phase','restart','infrastructure','other']){const o=el('option',value.replaceAll('_',' '));o.value=value;kind.append(o);}label.append(kind);form.append(label);
  const title=field(form,'Event title'),detail=field(form,'What changed and supporting evidence'),step=field(form,'Native coordinate',doc.scope.current[0],'number'),clock=field(form,'Clock (exact recorded name)'),basis=field(form,'Coordinate basis (exact recorded name)');const error=el('p',null,'ii-error'),save=el('button','Record event','primary');form.append(save,error);
  form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await api('/api/experiment-history',{experiment:doc.scope.experiment,environment:doc.scope.environment,kind:kind.value,title:title.value,detail:detail.value,step:+step.value,clock:clock.value,basis:basis.value,investigation_id:doc.id});error.textContent='Recorded. This frozen investigation remains unchanged. Capture a new comparison to include the event.';}catch(e){error.textContent=e.message;save.disabled=false;}};
 }
 let bundleSequence=0;
 const presetStates=new Map();
 async function bundles(host,context,onUpdate){
  const seq=++bundleSequence,scope=JSON.stringify([context.experiment||'',context.environment||'']);
  try{
   const data=await api('/api/monitoring/questions?'+new URLSearchParams(Object.fromEntries(Object.entries({experiment:context.experiment,environment:context.environment}).filter(([,v])=>v))));
   if(seq!==bundleSequence)return;
   const grid=el('div',null,'ii-question-grid');
   host.replaceChildren(el('p','Add a set of monitors to the selected experiment and environment. Existing definitions are reused.','field-note'),grid);
   for(const q of data.questions){
    const key=scope+q.id,state=presetStates.get(key)||{open:false,observer:'',monitor:'',status:'',busy:false,inputs:false,attach:false};presetStates.set(key,state);
    const card=el('details',null,'ii-question'),summary=el('summary'),name=el('span',null,'ii-preset-name');
    card.dataset.question=q.id;card.open=state.open;card.ontoggle=()=>{state.open=card.open;};
    name.append(el('strong',q.title),el('span',q.description||'Saved monitor definitions'));
    summary.append(name,el('span',`${q.monitors.filter(m=>m.enabled).length} active`,'ii-preset-count'));
    const body=el('div',null,'ii-preset-body');card.append(summary,body);
    const row=el('div',null,'ii-preset-controls'),label=el('label','Observation source'),observer=el('select');
    observer.setAttribute('aria-label','Observation source for '+q.title);observer.append(el('option','Source measures only'));observer.firstChild.value='';
    for(const o of context.observers||[]){if(o.id==='source')continue;const opt=el('option',o.label||o.id);opt.value=o.id;observer.append(opt);}
    observer.value=state.observer;if(observer.selectedIndex<0)observer.value='';observer.onchange=()=>{state.observer=observer.value;};label.append(observer);
    const status=el('p',state.status,'ii-preset-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    const mutate=async(path,payload,message)=>{
     if(state.busy)return;state.busy=true;add.disabled=true;attach.disabled=true;
     try{const result=await api(path,payload);state.status=message(result);status.textContent=state.status;await onUpdate();}
     catch(e){state.status=e.message;status.textContent=state.status;}
     finally{state.busy=false;for(const current of host.querySelectorAll('.ii-question'))if(current.dataset.question===q.id){for(const b of current.querySelectorAll('[data-preset-write]'))b.disabled=false;const note=current.querySelector('.ii-preset-status');if(note)note.textContent=state.status;}}
    };
    const add=button('Add preset',()=>mutate('/api/monitoring/questions/activate',{
     question_id:q.id,observer:observer.value||null,...(context.experiment?{experiment:context.experiment}:{}),...(context.environment?{environment:context.environment}:{})
    },r=>`${r.monitor_ids.length} monitors ready.${r.skipped.length?' '+r.skipped.length+' require a semantic observation source.':''} No model calls.`));
    add.dataset.presetWrite='';add.disabled=state.busy;row.append(label,add);body.append(row);
    const attachDetails=el('details',null,'ii-preset-extra');attachDetails.open=state.attach;attachDetails.ontoggle=()=>{state.attach=attachDetails.open;};attachDetails.append(el('summary','Attach an existing monitor'));
    const attachRow=el('div',null,'ii-preset-controls'),customLabel=el('label','Saved monitor'),custom=el('select');custom.setAttribute('aria-label','Saved monitor for '+q.title);
    const initial=el('option','Choose a monitor…');initial.value='';custom.append(initial);
    for(const m of context.monitors||[]){const opt=el('option',m.name+(m.kind==='custom'?' · custom code':''));opt.value=m.id;custom.append(opt);}
    custom.value=state.monitor;if(custom.selectedIndex<0)custom.value='';custom.onchange=()=>{state.monitor=custom.value;};customLabel.append(custom);
    const attach=button('Attach monitor',()=>{if(!custom.value){status.textContent=state.status='Choose a saved monitor to attach.';return;}return mutate('/api/monitoring/questions/bind',{question_id:q.id,monitor_id:custom.value},()=> 'Monitor attached.');});
    attach.dataset.presetWrite='';attach.disabled=state.busy;attachRow.append(customLabel,attach);attachDetails.append(attachRow);body.append(attachDetails,status);
    if(q.monitors.length){const saved=el('div',null,'ii-preset-monitors');saved.append(el('h3','Saved monitors'));
     for(const m of q.monitors)saved.append(link(m.name+(m.enabled?'':' (paused)')+` · ${q.measurement_coverage[m.id]?.measured||0}/${q.measurement_coverage[m.id]?.eligible||0} measured`, '/?'+new URLSearchParams({monitor:m.id,...(context.experiment?{experiment:context.experiment}:{}),...(context.environment?{environment:context.environment}:{})})));
     saved.append(button('Compare intervals',()=>open({...context,monitor_ids:q.monitors.map(m=>m.id)})));body.append(saved);
    }
    const inputs=el('details',null,'ii-preset-extra');inputs.open=state.inputs;inputs.ontoggle=()=>{state.inputs=inputs.open;};inputs.append(el('summary','Input coverage & definitions'));
    if(q.missing_measure_labels?.length)inputs.append(el('p','Not configured: '+q.missing_measure_labels.join(' · '),'field-note'));
    inputs.append(table(['Input','Recorded coverage'],q.readiness.map(r=>[r.label,r.status||(r.total==null?String(r.observed)+' recorded revisions':`${r.observed}/${r.total} recorded`)])));
    const list=el('ul');for(const need of q.needs)list.append(el('li',need));inputs.append(el('h3','Required inputs'),list,el('p',q.reading,'field-note'));body.append(inputs);grid.append(card);
   }
  }catch(e){if(seq===bundleSequence)host.textContent=e.message;}
 }
 return {open,render,bundles,range,evidenceCases,receiptLabel};
})();
if(typeof module!=='undefined')module.exports=IntervalInvestigation;
