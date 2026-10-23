'use strict';
window.BehaviorDistributions=(()=>{
 const initial=new URLSearchParams(location.search),n=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
 let state=Object.fromEntries(['recurrence_order','lens','grouping','observer','cohort_id','weighting','population_mode','a_start','a_end','b_start','b_end'].filter(k=>initial.has(k)).map(k=>[k,initial.get(k)]));
 if(!initial.has('lens'))state={...state,lens:'work_visits',recurrence_order:'bracketed-parallel/1'};
 let host,scope,last,sequence=0,selected=initial.get('category'),casePage=Number(initial.get('case_page')||0),casesOpen=initial.get('cases')==='1',taskDetailsOpen=false,taskPage=0;
 let caseWindow=initial.get('case_window'),caseQuery=initial.get('case_query')||'',caseTaskScope=initial.get('case_tasks')||'all';
 let caseReport=initial.get('case_report');
 let availability={scope:null,open:false,status:'missing',page:0},renderedScope=null;
 const savedId=initial.get('distribution');let savedRecord=null,saving=false,savedList=null;
 const disclosures={settings:false,coverage:false,method:false,otherApproaches:false,saved:false};
 function disclosure(key,cls){const box=n('details',undefined,cls);box.open=disclosures[key];box.ontoggle=()=>{if(box.isConnected)disclosures[key]=box.open;};return box;}
 const pct=v=>v==null?'—':(v*100).toFixed(1)+'%',pp=v=>v==null?'—':(v>0?'+':'')+v.toFixed(1)+' pp';
 const caption=m=>[m.environment||'Unknown environment',m.task_id?.startsWith('prompt-sha256:')?'Task '+m.task_id.slice(14,24):m.task_id||(m.population_basis?'Across tasks':'Unknown task'),m.model||m.policy_version||m.checkpoint].filter(Boolean).join(' · ');
 const button=(title,action,cls)=>{const b=n('button',title,cls);b.type='button';b.onclick=action;return b;};
 const link=(text,href)=>{const a=n('a',text);a.href=href;return a;};
 function select(title,items,value,action){const l=n('label',title),s=n('select');s.setAttribute('aria-label',title);for(const [id,text]of items){const o=n('option',text);o.value=id;s.append(o);}if(!items.length){const o=n('option','No saved observations available');o.value='';s.append(o);s.disabled=true;}else if(value!=null&&!items.some(([id])=>id===value)){const o=n('option','Choose '+title.toLowerCase());o.value='';s.prepend(o);}s.value=value!=null&&items.some(([id])=>id===value)?value:s.options[0]?.value||'';s.onchange=()=>action(s.value);l.append(s);return l;}
 function swatch(c){const s=n('i',undefined,'bd-swatch');s.style.background=c.color;return s;}
 function resetWindows(){for(const k of ['a_start','a_end','b_start','b_end'])delete state[k];casePage=0;caseWindow=null;caseQuery='';caseTaskScope='all';caseReport=null;}
 async function savedSelection(){
  if(!savedId)return null;
  if(!savedRecord){const response=await fetch('/api/behavior-comparisons/'+encodeURIComponent(savedId)),value=await response.json();if(!response.ok)throw Error(value.error);savedRecord=value;}
  return {experiment:savedRecord.controls.experiment||'',environment:savedRecord.controls.environment||''};
 }
 async function load(container,selection){host=container;if(!savedId&&scope&&JSON.stringify(scope)!==JSON.stringify(selection)){delete state.observer;delete state.cohort_id;resetWindows();savedList=null;}scope=selection;const token=++sequence;
  try{let d;if(savedId){
   scope=await savedSelection();if(token!==sequence)return;d=savedRecord.snapshot;state={...savedRecord.controls};delete state.experiment;delete state.environment;window.TrainingContext?.viewEvidence(scope);
  }else{const r=await fetch('/api/behavior-distributions?'+new URLSearchParams({...scope,...state}));d=await r.json();if(!r.ok)throw Error(d.error);}if(token!==sequence)return;
   last=d;state={...state,lens:d.lens,grouping:d.grouping,weighting:d.weighting,population_mode:d.population_mode||'task'};if(d.observer)state.observer=d.observer;if(d.cohort_id)state.cohort_id=d.cohort_id;
   if(!d.categories.some(c=>c.id===selected))selected=[...d.deltas].sort((a,b)=>(d.comparable?Math.abs(b.pp||0)-Math.abs(a.pp||0):0)||(d.distribution.counts[b.id]-d.distribution.counts[a.id]))[0]?.id;
   render(d);
  }catch(e){if(token===sequence){const err=n('p',e.message,'bd-error');err.setAttribute('role','alert');host.replaceChildren(err,savedId?link('Open live behavior','/?'+new URLSearchParams({view:'strategies',...scope})):button('Reset comparison',()=>{state={lens:'work_visits',recurrence_order:'bracketed-parallel/1'};load(host,scope);}));}}}
 function choose(id,window=null,taskScope='all'){selected=id;casePage=0;casesOpen=true;caseReport=null;if(window){caseWindow=window;caseTaskScope=taskScope;}render(last);host.querySelector('.bd-evidence')?.scrollIntoView({block:'start',behavior:'smooth'});}
 function chooseReport(id,window,report){selected=id;caseWindow=window;caseReport=report;caseTaskScope='all';caseQuery='';casePage=0;casesOpen=true;render(last);host.querySelector('.bd-evidence')?.scrollIntoView({block:'start',behavior:'smooth'});}
 function writeLocation(){history.replaceState(null,'','/?'+new URLSearchParams({view:'strategies',...scope,...state,...(savedId?{distribution:savedId}:{}),...evidenceControls()}));}
 const evidenceControls=()=>({...(selected?{category:selected}:{}),...(caseWindow?{case_window:caseWindow}:{}),...(casesOpen?{cases:'1'}:{}),...(caseQuery?{case_query:caseQuery}:{}),...(caseReport?{case_report:caseReport}:{}),...(caseTaskScope==='shared'?{case_tasks:'shared'}:{}),...(casePage?{case_page:casePage}:{})});
 const comparisonURL=(record,preserve=false)=>'/?'+new URLSearchParams({view:'strategies',...record.controls,distribution:record.id,...(preserve?evidenceControls():{})});
 const captureTime=value=>new Date(value).toLocaleString();
 function appliedControls(d){const value={...scope,...state};for(const [prefix,w]of [['a',d.baseline],['b',d.current]])for(const field of ['start','end'])if(w[field]!=null)value[prefix+'_'+field]=w[field];return value;}
 function comparisonActions(d){
  const bar=n('div',undefined,'bd-capture'),info=n('div'),actions=n('div',undefined,'bd-capture-actions'),error=n('p',undefined,'bd-error');error.setAttribute('role','alert');
  info.append(n('strong',savedRecord?'Saved comparison':'Live comparison'),n('span',savedRecord?d.lenses[d.lens].label+' · '+captureTime(savedRecord.captured_at)+' · fixed evidence':'Saved observations refresh with incoming data.'));
  const save=button(savedRecord?'Capture latest evidence':'Save latest comparison',async()=>{if(saving)return;saving=true;save.disabled=true;error.textContent='';try{
   const payload=savedRecord?{parent_id:savedRecord.id}:{controls:appliedControls(d)};
   const r=await fetch('/api/behavior-comparisons',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),value=await r.json();if(!r.ok)throw Error(value.error);location.href=comparisonURL(value,true);
  }catch(e){error.textContent=e.message;}finally{saving=false;save.disabled=false;}});
  save.disabled=saving||!d.cohorts.length;save.title=savedRecord?'Create a new saved comparison using the same windows and annotation version. The original stays unchanged.':'Capture the latest committed evidence for the applied comparison windows.';
  if(savedRecord){actions.append(link('Open live comparison','/?'+new URLSearchParams({view:'strategies',...savedRecord.controls,...evidenceControls()})));if(!['observer','cohort_id','a_start','a_end','b_start','b_end'].every(k=>savedRecord.controls[k]!=null))save.disabled=true;
   if(savedRecord.parent_id)actions.append(link('Original capture',comparisonURL({...savedRecord,id:savedRecord.parent_id})));
  }actions.append(save);bar.append(info,actions,error);return bar;
 }
 function savedComparisons(){
  const details=disclosure('saved','bd-saved-list');details.append(n('summary','Saved comparisons'));const list=n('div');details.append(list);
  const draw=()=>{list.replaceChildren();if(!savedList?.length){list.append(n('p','No saved comparisons in this training scope.','bd-note'));return;}
   if(savedList.length===100)list.append(n('p','Showing the 100 most recent captures in this scope.','bd-note'));
   for(const row of savedList){const item=n('div'),a=link(row.title,comparisonURL(row));if(row.id===savedId)a.setAttribute('aria-current','page');item.append(a,n('small',captureTime(row.captured_at)+' · '+(row.controls.a_start??'—')+'–'+(row.controls.a_end??'—')+' / '+(row.controls.b_start??'—')+'–'+(row.controls.b_end??'—')));list.append(item);}
  };
  details.ontoggle=async()=>{if(!details.isConnected)return;disclosures.saved=details.open;if(!details.open)return;if(savedList){draw();return;}list.replaceChildren(n('p','Loading saved comparisons…','bd-note'));try{const r=await fetch('/api/behavior-comparisons?'+new URLSearchParams(Object.entries(scope).filter(([,v])=>v))),data=await r.json();if(!r.ok)throw Error(data.error);savedList=data.comparisons;draw();}catch(e){list.replaceChildren(n('p',e.message,'bd-error'));}};if(savedList)draw();return details;
 }
 function render(d){
  const renderScope=JSON.stringify([scope,d.lens,d.observer,d.cohort_id]),oldWindows=host.querySelector('.bd-windows');
  const windowDraft=renderedScope===renderScope&&oldWindows?.open?Object.fromEntries([...oldWindows.querySelectorAll('input')].map(input=>[input.name,input.value])):null;
  renderedScope=renderScope;writeLocation();host.classList.add('behavior-distributions');host.replaceChildren();
  host.append(comparisonActions(d));
  const lenses=n('div',undefined,'bd-lenses');lenses.setAttribute('aria-label','Behavior views');const lensOrder=[...new Set(['work_visits','recurrence','revisit','procedure','work','feedback','failure','outcome',...Object.keys(d.lenses)])];for(const key of lensOrder.filter(k=>d.lenses[k])){const l=d.lenses[key];const b=button(l.label,()=>{state.lens=key;if(key==='work_visits')state.recurrence_order='bracketed-parallel/1';else delete state.recurrence_order;delete state.observer;delete state.cohort_id;selected=null;resetWindows();casesOpen=false;load(host,scope);});b.setAttribute('aria-pressed',String(d.lens===key));b.disabled=!!savedRecord;lenses.append(b);}host.append(lenses);
  const controls=n('div',undefined,'bd-controls');if(d.lens==='work')controls.append(select('Category grouping',d.groupings.map(g=>[g.id,g.name]),d.grouping,v=>{state.grouping=v;selected=null;load(host,scope);}),button('Edit grouping',()=>editor(d),'bd-configure'));
  if(d.population_mode)controls.append(select('Comparison population',[['task','One task'],['task_mix','Across tasks']],d.population_mode||'task',v=>{state.population_mode=v;delete state.cohort_id;resetWindows();load(host,scope);}));
  controls.append(select('Weighting',[['rollout','Each rollout equal'],['opportunity','Pool all opportunities']],d.weighting,v=>{state.weighting=v;load(host,scope);}));
  const context=disclosure('settings','bd-scope bd-settings'),s=n('summary');s.append(n('strong','Comparison settings'),n('span',(d.metadata?caption(d.metadata):'No task selected')+' · '+(d.population_mode==='task_mix'?'Across tasks':'One task')),n('small',(d.observers.find(o=>o.id===d.observer)?.label||'No saved observations')+' · '+(d.weighting==='opportunity'?'Pooled opportunities':'Equal rollout weights')));context.append(s,controls);
  const cp=n('div',undefined,'bd-controls');cp.append(select('Annotation version',d.observers.map(o=>[o.id,o.label+' · '+o.rollouts+' rollouts']),d.observer,v=>{state.observer=v;delete state.cohort_id;resetWindows();load(host,scope);}),select(d.population_mode==='task_mix'?'Recorded configuration':'Comparable task / configuration',d.cohorts.map(c=>[c.id,caption(c.metadata)+' · '+c.rollouts+'/'+(c.population??c.rollouts)+' observed']),d.cohort_id,v=>{state.cohort_id=v;resetWindows();load(host,scope);}));context.append(cp,n('p',(d.population_mode==='task_mix'?'Tasks are compared within one recorded configuration. Task revisions remain distinct. ':'One task and recorded configuration per comparison. ')+'Unspecified fields do not establish a configuration match.','bd-note'));if(d.metadata)context.append(n('pre',JSON.stringify(d.metadata,null,2)));host.append(context);
  if(savedRecord){lenses.hidden=true;context.replaceChildren(s,n('p','Saved settings. Open the live comparison to change them.','bd-note'));if(d.metadata)context.append(n('pre',JSON.stringify(d.metadata,null,2)));}context.append(savedComparisons());
  if(!d.cohorts.length){host.append(n('div','No imported rollouts match this selection. Use the training-run switcher to change the scope.','bd-empty'));return;}
  const methodNotes=n('div',undefined,'bd-method-notes');
  if(d.distribution.total){const stats=n('div',undefined,'bd-stats');for(const [value,label]of [[d.observed_rollouts+' / '+d.population,'cohort rollouts observed'],[d.distribution.total,d.definition.grain],d.lens==='work_visits'?[d.points.reduce((n,p)=>n+(p.switches?.unknown||0),0),'uncertain switches']:[d.bins.filter(b=>b.eligible_rollouts).length,'observed progress positions']]){const cell=n('div');cell.append(n('strong',value),n('span',label));stats.append(cell);}host.append(stats);}
  if(d.observation_readiness)host.append(coverageSummary(d));
  methodNotes.append(n('p','Experimental observations · '+caption(d.metadata)+'. This cohort contains '+d.population+' of '+d.scope_population.toLocaleString()+' imported rollouts in scope.','bd-sample'));
  if(d.metadata?.source_selection?.note)methodNotes.append(n('p','Source sampling: '+d.metadata.source_selection.note,'bd-note'));
  if(['recurrence','procedure'].includes(d.lens)){
   const coverage=d.points.reduce((a,p)=>{for(const[k,v]of Object.entries(p.work_coverage||{}))if(typeof v==='number')a[k]=(a[k]||0)+v;return a;},{});
   methodNotes.append(n('p',d.lens==='recurrence'?`${coverage.represented_actions||0}/${coverage.recorded_actions||0} actions have usable units; ${coverage.identity_reviewed||0} have recorded identity reviews. Recurrence not established includes first occurrences and missing evidence.`:`${coverage.procedure_compared||0}/${coverage.recurrences||0} recorded recurrences have usable procedure comparisons. ${coverage.procedure_unknown||0} remain unresolved; ${d.observed_rollouts-d.distribution.eligible_rollouts} observed rollouts have no recurrence opportunities.`,'bd-note'));
  }
  if(d.lens==='revisit'){
   const c=d.points.reduce((a,p)=>{for(const k of ['pairs','input_comparisons','feedback_comparisons','recorded_actions','represented_actions','identity_reviewed'])a[k]+=p.work_coverage?.[k]||0;return a;},{pairs:0,input_comparisons:0,feedback_comparisons:0,recorded_actions:0,represented_actions:0,identity_reviewed:0});
   methodNotes.append(n('p',`${c.pairs} linked pairs across ${c.recorded_actions} recorded actions · inputs comparable for ${c.input_comparisons} pairs · feedback comparable for ${c.feedback_comparisons}. ${d.observed_rollouts-d.distribution.eligible_rollouts} observed rollouts have no recorded pairs.`,'bd-note'));
  }
  if(d.lens==='work_visits'){
   if(!d.recurrence_order&&!savedRecord)host.append(n('p','This saved view uses the earlier ordering rule.'),button('Include parallel work',()=>{state.recurrence_order='bracketed-parallel/1';load(host,scope);}));
   const switches=d.points.reduce((a,p)=>{for(const k of ['numerator','denominator','unknown'])a[k]+=p.switches?.[k]||0;return a;},{numerator:0,denominator:0,unknown:0});
   methodNotes.append(n('p',`${switches.numerator} observed return${switches.numerator===1?'':'s'} across ${switches.denominator} decidable work switches; ${switches.unknown} uncertain switches. These counts cover the selected cohort. The chart counts visits, including the first visit and coverage gaps.`,'bd-note'));
   const c=d.points.reduce((a,p)=>{for(const[k,v]of Object.entries(p.work_coverage||{}))if(typeof v==='number')a[k]=(a[k]||0)+v;return a;},{});
   methodNotes.append(n('p',`${c.bound||0}/${c.contributions||0} contributions have identified work targets · ${c.source_gaps||0} source gaps. Annotation accuracy has not been independently validated.`,'bd-note'));
  }
  if(d.distribution.total){
  const panel=n('section',undefined,'bd-panel bd-result'),head=n('div',undefined,'bd-heading');head.append(n('h2',d.lenses[d.lens].label));if(d.bins.length&&!savedRecord)head.append(windows(d,windowDraft));panel.append(head);
  if(d.bins.length){const comparison=n('div',undefined,'bd-comparison');comparison.append(bar(d,d.baseline,'Earlier window','earlier'),bar(d,d.current,'Later window','later'));panel.append(comparison);if(!d.comparable)panel.append(n('p',d.comparison_reason,'bd-note'));}
  else{panel.append(bar(d,d.distribution,'Observed distribution'),n('p','Progress coordinates are not recorded for these observations. This view shows their distribution without inferring a trend.','bd-note'));}
  panel.append(n('p',d.denominator+'. Unknown categories stay in the denominator.','bd-note'),deltaTable(d));host.append(panel);
  if(d.task_mix)host.append(taskMix(d));
  if(d.bins.length)host.append(trend(d));
  if(d.approach_followup)host.append(approachFollowup(d));
  host.append(cases(d));
  }else{const empty=n('section',undefined,'bd-empty bd-no-observations'),observed=d.observation_readiness?.current??d.observed_rollouts;empty.append(n('h2',observed?'No recorded opportunities':'No saved observations'),n('p',observed?`${observed} rollouts have current inputs, but none contain ${d.definition.grain} for this view.`:`${d.population} imported rollouts; none have a current observation for ${d.lenses[d.lens].label.toLowerCase()}.`),n('p','Select another behavior view or annotation version. Missing observations are not zero behavior.'));const actions=n('div',undefined,'bd-empty-actions');actions.append(link('View rollouts','/runs?'+new URLSearchParams(scope)),link('Observation setup','/connections?'+new URLSearchParams(scope)+'#model-section'));empty.append(actions);host.append(empty);}
  const details=disclosure('method','bd-panel bd-method');details.append(n('summary','Definitions & export'),methodNotes,n('p',d.definition.limit),n('p',d.annotation_status));
  if(d.lens==='work_visits')details.append(n('p','Work ordering: '+d.ordering_label+'. Unordered actions inside a complete parallel group can establish intervening work; their mutual order remains unknown.'));
  if(d.lens==='work'){const counts=d.points.reduce((a,p)=>({records:a.records+(p.agent_records||0),covered:a.covered+(p.records_with_units||0)}),{records:0,covered:0});details.append(n('p',counts.covered+' / '+counts.records+' agent records contain selected units. This is record coverage, not span completeness or semantic accuracy.'));
   for(const c of d.categories)details.append(n('p',c.label+': '+(c.activities.length?c.activities.join(', '):'all other or missing activity labels')));}
  if(d.analysis_receipts)for(const r of d.analysis_receipts)details.append(link('Analysis receipt · rollout '+r.run_id.slice(0,10),'/api/investigation-plans/'+encodeURIComponent(r.plan_id)));
  if(d.unplaced_rollouts)details.append(n('p',d.unplaced_rollouts+' observed rollouts have no training position. They remain in the overall distribution and per-rollout evidence.'));
  details.append(n('p',d.review_note_count+' attached source-review notes. '+(savedRecord?'This capture remains fixed.':'Saved observations refresh with the dashboard.')+' Regrouping uses no model calls.'),button('Export displayed snapshot',()=>download(d)),n('small',d.snapshot_id));host.append(details);
  const intro=n('div',undefined,'bd-intro');intro.append(link('Inspect feedback and retry paths ↗','/?'+new URLSearchParams({view:'strategies',detail:'episodes',...scope})));host.append(intro);
 }
 function coverageSummary(d){
  const r=d.observation_readiness,box=disclosure('coverage','bd-coverage-summary'),summary=n('summary');
  summary.append(n('strong','Observation coverage'),n('span',`${r.current} / ${r.population} current · ${r.eligible} with opportunities`));
  if(d.bins.length){const a=d.baseline.observation_readiness,b=d.current.observation_readiness;if(a&&b)summary.append(n('small',`Earlier ${a.current}/${a.population} · Later ${b.current}/${b.population}`));}
  box.append(summary);
  // Keep gaps visible while detailed coverage tables and member filters are folded.
  const gaps=n('div',undefined,'bd-coverage-flags');for(const[key,label]of Object.entries(d.observation_statuses))if(key!=='available'&&r.statuses[key])gaps.append(n('span',`${r.statuses[key]} · ${label}`));
  for(const c of d.observation_checks||[])gaps.append(n('span',c.evidence));
  const wrapper=n('div',undefined,'bd-coverage');wrapper.append(box);if(gaps.children.length)wrapper.append(gaps);box.append(readiness(d));return wrapper;
 }
 function readiness(d){
  const r=d.observation_readiness,box=n('section',undefined,'bd-panel bd-readiness');box.setAttribute('aria-label','Observation coverage');
  const key=JSON.stringify([d.lens,d.observer,d.cohort_id]);if(availability.scope!==key)availability={scope:key,open:false,status:'missing',page:0};
  box.append(n('h2','Observation coverage'),n('p',`${r.current}/${r.population} imported rollouts have a current input for this question; ${r.eligible} contribute category opportunities.`));
  if(r.record_coverage?.inputs){const c=r.record_coverage;box.append(n('p',`${c.covered}/${c.records} agent records contain selected units across ${c.inputs} current inputs. Record coverage does not establish span completeness or semantic accuracy.`,'bd-note'));}
  const statuses=n('div',undefined,'bd-availability-status');
  for(const [key,label]of Object.entries(d.observation_statuses))if(key!=='available'&&r.statuses[key])statuses.append(n('span',`${r.statuses[key]} · ${label}`));
  box.append(statuses);
  if(d.bins.length){
   const chart=n('div',undefined,'bd-availability-chart'),svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 700 108');svg.setAttribute('role','img');svg.setAttribute('aria-label','Current annotation coverage by recorded progress coordinate');
   const add=(tag,attrs,text)=>{const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;svg.append(e);return e;};
   const lo=d.bins[0].step,hi=d.bins.at(-1).step,x=step=>lo===hi?370:48+630*(step-lo)/(hi-lo),y=v=>78-58*v;
   for(const v of [0,1]){add('line',{x1:48,x2:678,y1:y(v),y2:y(v),stroke:'#dbe2ec'});add('text',{x:2,y:y(v)+4,fill:'#53627a','font-size':12},pct(v));}
   const points=d.bins.filter(b=>b.observation_readiness?.coverage!=null);
   add('polyline',{points:points.map(b=>`${x(b.step)},${y(b.observation_readiness.coverage)}`).join(' '),fill:'none',stroke:'#365eed','stroke-width':2,'stroke-dasharray':'4 3'});
   for(const b of points){const dot=add('circle',{cx:x(b.step),cy:y(b.observation_readiness.coverage),r:4,fill:'#365eed'}),title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=`Step ${b.step} · ${b.observation_readiness.current}/${b.population} current inputs · ${b.eligible_rollouts} with opportunities`;dot.append(title);}
   add('text',{x:48,y:101,fill:'#53627a','font-size':12},String(lo));add('text',{x:678,y:101,fill:'#53627a','font-size':12,'text-anchor':'end'},String(hi));
   chart.append(svg,n('small','Recorded coordinates only; dashed links do not establish coverage between them.'));box.append(chart);
   const table=n('table'),head=n('tr');for(const label of ['Comparison window','Imported','Current inputs','With opportunities',...(r.record_coverage?.inputs?['Records with units']:[])])head.append(n('th',label));table.append(head);
   for(const [label,w]of [['Earlier',d.baseline],['Later',d.current]]){const s=w.observation_readiness;if(!s)continue;const row=n('tr');row.append(n('td',label+(w.start==null?' · no coordinate':` · ${w.start}${w.end===w.start?'':'–'+w.end}`)),n('td',s.population),n('td',`${s.current} (${pct(s.coverage)})`),n('td',s.eligible));if(r.record_coverage?.inputs){const c=s.record_coverage;row.append(n('td',c?.inputs?`${c.covered}/${c.records} (${pct(c.fraction)})`:'Unavailable'));}table.append(row);}
   const wrap=n('div',undefined,'bd-availability-table');wrap.append(table);box.append(wrap);
  }
  if(d.observation_checks?.length){const checks=n('div',undefined,'bd-availability-checks');checks.append(n('strong','Measurement coverage'));
   const list=n('ul');for(const c of d.observation_checks)list.append(n('li',c.evidence));checks.append(list);
   checks.append(n('p','Inspect missing inputs, unannotated trace sections and represented task/policy groups. Revisit the same windows after catch-up; equal coverage percentages do not establish equal selection.'));box.append(checks);
  }
  const details=n('details');details.open=availability.open;details.ontoggle=()=>{if(details.isConnected)availability.open=details.open;};details.append(n('summary','Inspect observation availability'));
  const period=n('div',undefined,'bd-availability-table'),table=n('table'),head=n('tr');for(const label of ['Window / grouping','Group','Imported','With opportunities'])head.append(n('th',label));table.append(head);
  for(const [label,w]of [['Earlier',d.baseline],['Later',d.current]])for(const selection of w.observation_readiness?.selection||[])for(const g of selection.groups){const row=n('tr');row.append(n('td',label+' · '+selection.field.replaceAll('_',' ')),n('td',g.value==null?'Not recorded':typeof g.value==='string'?g.value:JSON.stringify(g.value)),n('td',g.observed),n('td',g.measured));table.append(row);}
  period.append(table);details.append(period);
  const delay=r.delay,seconds=v=>v==null?'unavailable':v<60?v.toFixed(1)+' s':v<3600?(v/60).toFixed(1)+' min':(v/3600).toFixed(1)+' h';
  details.append(n('p',`Receipt → saved input: median ${seconds(delay.median_seconds)}; maximum ${seconds(delay.max_seconds)}. Timestamps available for ${delay.available}/${delay.current} current inputs.`,'bd-note'),n('p',delay.definition,'bd-note'));
  const rows=n('div');
  const filter=select('Availability filter',[['missing','Missing or partial input'],['partial_records','Current inputs with unannotated records'],['all','All imported rollouts'],...Object.entries(d.observation_statuses)],availability.status,v=>{availability.status=v;availability.page=0;draw();});details.append(filter,rows);
  const draw=()=>{
   const partial=m=>Number.isInteger(m.agent_records)&&Number.isInteger(m.records_with_units)&&m.records_with_units<m.agent_records;
   rows.replaceChildren();const matching=d.observation_members.filter(m=>availability.status==='all'||(availability.status==='missing'?!['available','no_opportunities'].includes(m.status)||partial(m):availability.status==='partial_records'?partial(m):m.status===availability.status));
   availability.page=Math.min(availability.page,Math.max(0,Math.ceil(matching.length/20)-1));
   rows.append(n('p',`${matching.length} matching rollouts · selected cohort, all recorded steps`,'bd-note'));
   const t=n('table'),head=n('tr');for(const label of ['Rollout / task','Coordinate','Input status',...(r.record_coverage?.inputs?['Records with units']:[])])head.append(n('th',label));t.append(head);
   for(const m of matching.slice(availability.page*20,(availability.page+1)*20)){const row=n('tr'),identity=n('td'),url='/semantic-map?'+new URLSearchParams({run:m.run_id,observer:m.graph_id?d.observer:'source',...(m.graph_id?{graph:m.graph_id}:{}),return_to:location.pathname+location.search});identity.append(link(m.task_id||'Inspect rollout',url),n('small',m.run_id));row.append(identity,n('td',m.step??'Unplaced'),n('td',d.observation_statuses[m.status]));if(r.record_coverage?.inputs)row.append(n('td',Number.isInteger(m.agent_records)&&Number.isInteger(m.records_with_units)?`${m.records_with_units}/${m.agent_records}`:'Unavailable'));t.append(row);}
   const wrap=n('div',undefined,'bd-availability-table');wrap.append(t);rows.append(wrap);
   if(matching.length>20){const pager=n('div',undefined,'pager'),back=button('Previous rollouts',()=>{availability.page--;draw();}),next=button('Next rollouts',()=>{availability.page++;draw();});back.disabled=availability.page===0;next.disabled=(availability.page+1)*20>=matching.length;pager.append(back,n('span',`${availability.page*20+1}–${Math.min((availability.page+1)*20,matching.length)} / ${matching.length}`),next);rows.append(pager);}
  };draw();box.append(details,n('p',r.boundary,'bd-note'));return box;
 }
 function bar(d,aggregate,label,window='all',taskScope='all'){const wrap=n('div',undefined,'bd-bar-block'),head=n('div',undefined,'bd-bar-label');head.append(n('strong',label),n('span',aggregate.start==null?'':('Step '+aggregate.start+(aggregate.start===aggregate.end?'':'–'+aggregate.end))));wrap.append(head);
  const track=n('div',undefined,'bd-stack');track.setAttribute('aria-label',label+' category shares');if(!aggregate.total){track.classList.add('empty');track.append(n('span','No observations'));}else for(const c of d.categories){const share=aggregate.shares[c.id];if(!share)continue;const b=button(share>=.13?pct(share):'',()=>choose(c.id,window,taskScope));b.style.width=(share*100)+'%';b.style.background=c.color;b.title=c.label+': '+pct(share);b.setAttribute('aria-label',c.label+' '+pct(share)+' in '+label);track.append(b);}wrap.append(track,n('small',aggregate.eligible_rollouts+' eligible rollouts · '+aggregate.total+' '+d.definition.grain+(aggregate.population!=null?' · '+(aggregate.population-aggregate.rollouts)+' rollouts unobserved':'')));return wrap;}
 function deltaTable(d){const wrap=n('div',undefined,'bd-deltas'),head=n('div',undefined,'bd-delta bd-column-head');['Category',d.bins.length?'Earlier':'Share',d.bins.length?'Later':'Count',d.bins.length?'Change':''].forEach(x=>head.append(n('span',x)));wrap.append(head);
  for(const c of d.categories){const delta=d.deltas.find(x=>x.id===c.id),row=button('',()=>choose(c.id),'bd-delta'+(selected===c.id?' selected':''));row.setAttribute('aria-pressed',String(selected===c.id));row.setAttribute('aria-label','Inspect '+c.label);const label=n('span',undefined,'bd-category');label.append(swatch(c),n('span',c.label));row.append(label,n('span',pct(d.bins.length?delta.before:d.distribution.shares[c.id])),n('span',d.bins.length?pct(delta.after):d.distribution.counts[c.id]),n('strong',d.bins.length?pp(delta.pp):'→'));wrap.append(row);}wrap.append(n('p','Select a category to inspect its values and contributing rollouts. A share increase is not a quality improvement.','bd-note'));return wrap;}
 function windows(d,draft=null){const details=n('details',undefined,'bd-windows');details.open=!!draft;details.append(n('summary','Change windows'));const form=n('form'),grid=n('div',undefined,'bd-window-inputs');for(const [name,label,value]of [['a_start','Earlier start',d.baseline.start],['a_end','Earlier end',d.baseline.end],['b_start','Later start',d.current.start],['b_end','Later end',d.current.end]]){const l=n('label',label),i=n('input');i.type='number';i.min=0;i.step=1;i.name=name;i.value=draft?.[name]??value??'';i.required=true;l.append(i);grid.append(l);}const apply=n('button','Apply windows');apply.type='submit';form.append(grid,apply);form.onsubmit=e=>{e.preventDefault();for(const [k,v]of new FormData(form))state[k]=v;load(host,scope);};details.append(form);return details;}
 function trend(d){const c=d.categories.find(c=>c.id===selected)||d.categories[0],section=n('section',undefined,'bd-panel bd-trend'),head=n('div',undefined,'bd-heading');head.append(n('h2',c.label+' over recorded progress'));section.append(head);
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 720 210');svg.setAttribute('role','img');svg.setAttribute('aria-label',c.label+' share at recorded training steps');const add=(tag,attrs,text)=>{const e=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;svg.append(e);return e;};
  const lo=d.bins[0].step,hi=d.bins.at(-1).step,x=step=>58+(hi===lo?.5:(step-lo)/(hi-lo))*620,y=v=>159-v*128;
  for(const v of [0,.5,1]){add('line',{x1:58,x2:678,y1:y(v),y2:y(v),stroke:'#e8eaf0'});add('text',{x:5,y:y(v)+4},Math.round(v*100)+'%');}
  let segment=[];const flush=()=>{if(segment.length>1)add('polyline',{points:segment.join(' '),stroke:c.color,fill:'none','stroke-width':2,'stroke-dasharray':'4 4',opacity:.75});segment=[];};
  for(const b of d.bins){const share=b.shares[c.id];if(share==null){flush();add('rect',{x:x(b.step)-3,y:28,width:6,height:131,fill:'#e9eaf0'});continue;}segment.push(x(b.step)+','+y(share));}flush();
  for(const p of d.points.filter(p=>p.step!=null&&p.total)){const dot=add('circle',{cx:x(p.step),cy:y(p.counts[c.id]/p.total),r:4,fill:c.color,opacity:.35,tabindex:0,role:'link'}),title=document.createElementNS(ns,'title');title.textContent='Rollout '+p.run_id+' · step '+p.step+' · '+p.counts[c.id]+'/'+p.total+' '+d.definition.grain+' · '+pct(p.counts[c.id]/p.total);dot.setAttribute('aria-label',title.textContent);dot.append(title);const item=d.cases.find(r=>r.run_id===p.run_id&&r.category===c.id)||d.cases.find(r=>r.run_id===p.run_id);if(item){const open=()=>location.href=item.map_url+'&return_to='+encodeURIComponent(location.pathname+location.search);dot.style.cursor='pointer';dot.onclick=open;dot.onkeydown=e=>{if(e.key==='Enter')open();};}}
  for(const b of d.bins){const share=b.shares[c.id];if(share!=null){const dot=add('circle',{cx:x(b.step),cy:y(share),r:6,fill:'white',stroke:c.color,'stroke-width':2});const title=document.createElementNS(ns,'title');title.textContent='Step '+b.step+': '+pct(share)+' · '+b.eligible_rollouts+'/'+b.population+' rollouts · '+b.total+' '+d.definition.grain;dot.append(title);} }
  if(d.task_mix?.available){let fixed=[];const draw=()=>{if(fixed.length>1)add('polyline',{points:fixed.join(' '),stroke:'#183f4a',fill:'none','stroke-width':3});fixed=[];};for(const b of d.task_mix.bins){const v=b.shares[c.id];if(v==null){draw();continue;}fixed.push(x(b.step)+','+y(v));const dot=add('rect',{x:x(b.step)-4,y:y(v)-4,width:8,height:8,fill:'#183f4a'}),title=document.createElementNS(ns,'title');title.textContent='Fixed tasks · step '+b.step+' · '+pct(v)+' · '+b.tasks_observed+'/'+b.tasks_required+' tasks';dot.append(title);}draw();}
  const tickSteps=[...new Set([lo,...d.bins.filter(b=>b.eligible_rollouts).map(b=>b.step),hi])].sort((a,b)=>a-b);let previous=-100;for(const step of tickSteps){const xpos=x(step);if(xpos-previous<48&&step!==hi)continue;add('text',{x:xpos,y:183,'text-anchor':step===hi?'end':'middle'},step);previous=xpos;}
  add('text',{x:678,y:205,'text-anchor':'end'},d.axis?.label||'Recorded step');section.append(svg,n('p',d.axis?.meaning||'The source defines this progress coordinate.','bd-note'),n('p','Filled dots: individual rollouts (same-step values may overlap). Rings: step shares. Dashed links guide the eye, not unobserved steps. Grey marks: imported steps without annotations.','bd-note'));
  if(d.task_mix) section.append(n('p','Dark solid line and squares: equal-weight shared tasks. A point is omitted if any shared task has no eligible observation at that step. Shared tasks are fixed by the two selected windows.','bd-note'));
  const coverage=n('details',undefined,'bd-progress-coverage');coverage.append(n('summary','Coverage at '+d.bins.length+' recorded steps'));const steps=n('div',undefined,'bd-step-coverage');for(const b of d.bins){const item=n('span','Step '+b.step+' · '+b.eligible_rollouts+'/'+b.population+' eligible',b.eligible_rollouts?'':'unobserved');steps.append(item);}coverage.append(steps);section.append(coverage);return section;}
 function approachFollowup(d){
  const f=d.approach_followup,section=n('section',undefined,'bd-panel bd-followup');section.setAttribute('aria-label','Approaches after an error');
  section.append(n('h2','After an error'),n('p','Select a response segment to inspect the attempt pairs behind it.','bd-note'));
  const legends=n('div',undefined,'bd-followup-legend');for(const status of f.statuses){const item=n('span',undefined,'bd-followup-status '+status.id);item.append(n('i'),n('span',DistributionEvidence.REPORTS[status.id]));legends.append(item);}section.append(legends);
  const windows=d.bins.length?[['earlier','Earlier',f.earlier],['later','Later',f.later]]:[['all','Whole cohort',f.overall]];
  const visible=d.categories.filter(c=>windows.some(([, ,w])=>{const r=w.rows.find(r=>r.id===c.id);return r.total+r.no_prior_error+r.prior_report_unknown+r.unavailable_pairs>0;}));
  if(!visible.length)section.append(n('p','No recorded attempt pairs in these windows. Select a different window or annotation version.','bd-followup-empty'));
  const others=disclosure('otherApproaches','bd-other-approaches');others.append(n('summary','Other approaches · '+visible.filter(c=>c.id!==selected).length));
  if(visible.length&&!visible.some(c=>c.id===selected))section.append(n('p','No linked error follow-up for the selected category in these windows.','bd-followup-empty'));
  for(const category of visible){
   const row=n('article',undefined,'bd-followup-row');row.append(n('h3',category.label));const columns=n('div',undefined,'bd-followup-columns');
   for(const [key,label,window]of windows){
    const value=window.rows.find(r=>r.id===category.id),cell=n('div',undefined,'bd-followup-window'),title=n('div',undefined,'bd-followup-caption');cell.dataset.window=key;cell.dataset.category=category.id;
    title.append(n('strong',label+(window.start!=null?' · '+(window.start===window.end?'step '+window.start:'steps '+window.start+'–'+window.end):'')),n('span',`${value.total} ${value.total===1?'pair':'pairs'} · ${value.eligible_rollouts} ${value.eligible_rollouts===1?'rollout':'rollouts'}`));cell.append(title);
    if(value.total){
     const bar=n('div',undefined,'bd-followup-bar');for(const status of f.statuses){if(!value.counts[status.id])continue;const segment=button('',()=>chooseReport(category.id,key,status.id),status.id);segment.setAttribute('aria-label',`Inspect response segment: ${category.label} · ${label} · ${DistributionEvidence.REPORTS[status.id]}`);segment.title=DistributionEvidence.REPORTS[status.id]+' · '+pct(value.shares[status.id]);segment.style.width=(value.shares[status.id]*100)+'%';bar.append(segment);}cell.append(bar);
     const choices=n('div',undefined,'bd-followup-choices');for(const status of f.statuses){const count=value.counts[status.id],b=button('',()=>chooseReport(category.id,key,status.id),'bd-followup-choice '+status.id);b.disabled=!count;b.setAttribute('aria-label',`${category.label} · ${label} · ${DistributionEvidence.REPORTS[status.id]} · ${count} of ${value.total} pairs`);b.setAttribute('aria-pressed',String(selected===category.id&&caseWindow===key&&caseReport===status.id));b.append(n('strong',pct(value.shares[status.id])),n('span',`${count} / ${value.total}`),n('small',({reported_again:'Error again',no_reported_error:'No error reported',followup_unknown:'Unresolved'})[status.id]));choices.append(b);}cell.append(choices);
    }else cell.append(n('p','No pairs with a reported earlier error.','bd-followup-empty'));
    const excluded=n('div',undefined,'bd-followup-excluded');for(const [report,count,label]of [['no_prior_error',value.no_prior_error,'without a prior reported error'],['unknown',value.prior_report_unknown,'earlier report unresolved']])if(count)excluded.append(button(`${count} ${label}`,()=>chooseReport(category.id,key,report)));
    if(value.unavailable_pairs)excluded.append(n('span',value.unavailable_pairs+' pairs unavailable'));if(excluded.childElementCount)cell.append(excluded);columns.append(cell);
   }row.append(columns);(category.id===selected?section:others).append(row);
  }
  section.append(n('p',f.denominator+'. Unresolved follow-up remains in the denominator. Counts are unweighted pairs.','bd-note'));
  if(d.population_mode==='task_mix')section.append(n('p','Observed task mix · these response shares are not adjusted for task composition.','bd-note'));
  if(d.bins.length&&!d.comparable)section.append(n('p',d.comparison_reason,'bd-note'));
  if(visible.some(c=>c.id!==selected))section.append(others);
  if(d.unplaced_rollouts)section.append(n('p',`${d.unplaced_rollouts} observed rollouts have no recorded step; their cases remain available under Whole cohort.`,'bd-note'));
  section.append(n('p','Next recorded recurrence of the same work. No error reported is not verified recovery or task success.','bd-note'));return section;
 }
 function cases(d){
  const c=d.categories.find(c=>c.id===selected)||d.categories[0],v=DistributionEvidence.select(d,{category:c.id,window:caseWindow,query:caseQuery,task_scope:caseTaskScope,report:caseReport,page:casePage});
  casePage=v.page;caseWindow=v.filters.window;caseQuery=v.filters.query;caseTaskScope=v.filters.task_scope;caseReport=v.filters.report||null;writeLocation();
  const details=n('details',undefined,'bd-panel bd-evidence');details.open=casesOpen;details.ontoggle=()=>{if(!details.isConnected)return;casesOpen=details.open;writeLocation();};
  details.append(n('summary',c.label+(caseReport?' · '+DistributionEvidence.REPORTS[caseReport]:'')+' · '+v.matching_cases+' cases in '+v.matching_rollouts+(v.matching_rollouts===1?' rollout':' rollouts')));
  details.append(button('Back to comparison',()=>host.querySelector('.bd-result')?.scrollIntoView({block:'start',behavior:'smooth'}),'bd-return-comparison'));
  const controls=n('div',undefined,'bd-controls bd-case-controls');
  const periodLabel=w=>w.start==null?'not set':w.start===w.end?'step '+w.start:'steps '+w.start+'–'+w.end;
  const periods=Number.isSafeInteger(d.baseline.start)||Number.isSafeInteger(d.current.start)?[
   ['windows','Both comparison windows'],['earlier','Earlier · '+periodLabel(d.baseline)],['later','Later · '+periodLabel(d.current)],
   ['all','Whole cohort'],['outside','Outside comparison windows'],['unplaced','No recorded step']
  ]:[['all','Whole cohort'],['unplaced','No recorded step']];
  if(!periods.some(([id])=>id===caseWindow))periods.push([caseWindow,'Saved window · no positions recorded']);
  controls.append(select('Evidence window',periods,caseWindow,value=>{caseWindow=value;casePage=0;casesOpen=true;render(last);}));
  if(d.lens==='procedure')controls.append(select('Response after attempt',[['','All reports'],...Object.entries(DistributionEvidence.REPORTS)],caseReport||'',value=>{caseReport=value||null;casePage=0;casesOpen=true;render(last);}));
  if(d.task_mix||caseTaskScope==='shared')controls.append(select('Evidence tasks',[['all','All observed tasks'],['shared','Tasks in both windows']],caseTaskScope,value=>{caseTaskScope=value;casePage=0;casesOpen=true;render(last);}));
  const form=n('form',undefined,'bd-case-search'),label=n('label','Find target, source text or rollout'),search=n('input');search.type='search';search.value=caseQuery;search.maxLength=200;search.setAttribute('aria-label','Find target, source text or rollout');label.append(search);const apply=n('button','Find cases');apply.type='submit';form.append(label,apply);form.onsubmit=e=>{e.preventDefault();caseQuery=search.value;casePage=0;casesOpen=true;render(last);};
  if(caseQuery)form.append(button('Clear search',()=>{caseQuery='';casePage=0;render(last);}));controls.append(form);details.append(controls);
  const scopeText={all:'whole cohort',windows:'both windows',earlier:'earlier window',later:'later window',outside:'outside windows',unplaced:'no recorded step'}[caseWindow];
  details.append(n('p',`${v.matching_cases} matching / ${v.available_cases} loaded category cases · ${v.matching_rollouts} ${v.matching_rollouts===1?'rollout':'rollouts'} · ${scopeText}${caseTaskScope==='shared'?' · tasks in both windows':''}. Search filters evidence only; chart shares keep their stated weighting and denominator.`,'bd-note'));
  if(v.available_cases!==v.expected_cases||v.unjoined_cases)details.append(n('p',`${v.available_cases} / ${v.expected_cases} contributing cases have matching source/projection identities. Missing cases are not zero behavior.`,'bd-error'));
  if(!v.rows.length)details.append(n('p',caseQuery?'No case text matches this search in the selected window.':'No cases in this category and window.','bd-empty'));
  const windowNames={earlier:'Earlier',later:'Later',both:'Both windows',outside:'Outside windows',unplaced:'No recorded step'};
  for(const item of v.rows){
   const preview=DistributionEvidence.preview(item),row=n('article',undefined,'bd-case bd-evidence-case'),header=n('div',undefined,'bd-case-heading');
   header.append(n('strong',preview.positions?'Actions '+preview.positions.join(' → '):(item.step==null?'Saved case':'Step '+item.step+' · '+windowNames[item.window])),n('span',c.label+' · '+item.rollout_category_count+' / '+item.rollout_total+' in this rollout'));
   row.append(header,link(preview.later?.label||item.text?.trim()||'Open selected evidence',item.map_url+'&return_to='+encodeURIComponent(location.pathname+location.search)));
   const info=n('div',undefined,'bd-case-meta');info.append(n('span','Rollout '+item.run_id.slice(0,12)));
   if(item.task?.task_id)info.append(n('span',item.task.task_id));
   const e=item.episode;if(preview.positions)info.append(n('span',item.step==null?'No recorded step':'Step '+item.step+' · '+windowNames[item.window]));else if(e?.previous_unit_id&&e?.current_unit_id)info.append(n('span','Exact earlier / later pair'));
   if(item.repeated_work)info.append(n('span','Inputs: '+item.repeated_work.dispatch.status),n('span','Feedback: '+item.repeated_work.feedback.status));
   if(item.procedure_reason)info.append(n('span',item.procedure_reason));
   if(item.correction_location&&item.correction_location!=='not_established')info.append(n('span','Correction: '+item.correction_location.replaceAll('_',' ')));
   row.append(info);
   if(item.error_followup&&item.error_followup.category!=='unknown')row.append(n('p',item.error_followup.label+' · executor diagnostics, not a task-success verdict','bd-report-state'));
   if(preview.reason){const reason=n('div',undefined,'bd-stated-reason'),text=preview.reason.text.replace(/\s+/g,' ');reason.append(n('small',"Agent's stated reason"),n('p',text.slice(0,260)+(text.length>260?'…':'')));const url=new URL(item.map_url,location.href);url.searchParams.set('level','units');url.searchParams.delete('work_episode');url.searchParams.set('focus_unit',preview.reason.node_id);url.searchParams.set('return_to',location.pathname+location.search);reason.append(link('Inspect stated reason →',url.pathname+url.search));row.append(reason);}
   if(preview.responses.length){const text=DistributionEvidence.displayText(preview.responses[0].text);if(text)row.append(n('p','Earlier response: '+text.replace(/\s+/g,' ').slice(0,200)+(text.replace(/\s+/g,' ').length>200?'…':''),'bd-response-preview'));}
   if(preview.laterResponses.length){const text=DistributionEvidence.displayText(preview.laterResponses[0].text);if(text)row.append(n('p','Later response: '+text.replace(/\s+/g,' ').slice(0,200)+(text.replace(/\s+/g,' ').length>200?'…':''),'bd-response-preview'));}
   else if(item.response_context?.current?.status==='unavailable')row.append(n('p','Later feedback unavailable · '+item.response_context.current.reasons.join('; '),'bd-note'));
   if(preview.earlier||preview.later){const source=n('details',undefined,'bd-pair-source');source.append(n('summary','Compare recorded dispatches'));source.ontoggle=()=>{if(!source.open||source.childElementCount>1)return;const pair=n('div',undefined,'bd-source-columns');for(const [name,card]of [['Earlier',preview.earlier],['Later',preview.later]]){const column=n('div');column.append(n('strong',name+(card?.event_id?' · '+card.event_id:'')),n('pre',DistributionEvidence.displayText(card?.text)||'Source text unavailable'));pair.append(column);}source.append(pair);for(const [label,responses]of [['Earlier',preview.responses],['Later',preview.laterResponses]])for(const response of responses)source.append(n('strong',label+' feedback · '+response.event_id),n('pre',DistributionEvidence.displayText(response.text)||'No recorded text'));if(item.response_context)source.append(n('small',item.response_context.scope));};row.append(source);}
   details.append(row);
  }
  const pager=n('div',undefined,'pager');if(v.pages>1)for(const [text,delta,disabled]of [['Previous cases',-1,casePage===0],['Next cases',1,casePage+1>=v.pages]]){const b=button(text,()=>{casePage+=delta;casesOpen=true;render(last);host.querySelector('.bd-evidence')?.scrollIntoView({block:'start'});});b.disabled=disabled;pager.append(b);}
  pager.append(n('span',v.matching_cases?`${casePage*v.page_size+1}–${Math.min((casePage+1)*v.page_size,v.matching_cases)} of ${v.matching_cases} cases`:'0 cases'));
  const save=button('Export matching cases',()=>{const bundle=DistributionEvidence.exportSelection(d,v);download(bundle,d.snapshot_id+'-cases');});save.disabled=!v.matching_cases;pager.append(save);details.append(pager);return details;
 }
 function taskMix(d){
  const m=d.task_mix,c=d.categories.find(c=>c.id===selected)||d.categories[0],delta=m.deltas.find(x=>x.id===c.id);
  const section=n('section',undefined,'bd-panel bd-task-mix'),head=n('div',undefined,'bd-heading');
  head.append(n('h2','Same-task comparison · '+c.label));section.append(head);
  const cards=n('div',undefined,'bd-mix-cards');for(const [value,label]of [[pp(delta.raw_pp),'All observed rollouts'],[pp(delta.fixed_pp),'Fixed tasks · equal task weights'],[m.shared_task_ids.length+' / '+m.tasks.length,'Tasks / revisions in both windows']]){const cell=n('div');cell.append(n('strong',value),n('span',label));cards.append(cell);}section.append(cards);
  if(m.available){const bars=n('div',undefined,'bd-comparison');bars.append(bar(d,{...m.earlier,start:d.baseline.start,end:d.baseline.end},'Fixed tasks · earlier','earlier','shared'),bar(d,{...m.later,start:d.current.start,end:d.current.end},'Fixed tasks · later','later','shared'));section.append(bars);}
  else section.append(n('p',m.reason,'bd-empty'));
  section.append(n('p',m.definition+' Changes are descriptive, not evidence of improvement or causation.','bd-note'));
  const coverage=n('p',`Earlier / later windows: ${m.unobserved_rollouts.join(' / ')} imported rollouts lack observations; ${m.unidentified_rollouts.join(' / ')} lack task identity. Unshared tasks are excluded from the fixed-task result. No task is imputed.`, 'bd-note');section.append(coverage);
  const details=n('details',undefined,'bd-task-details');details.open=taskDetailsOpen;details.ontoggle=()=>{taskDetailsOpen=details.open;};details.append(n('summary','Inspect task composition & per-task changes'));
  const table=n('table',undefined,'bd-task-table'),thead=n('thead'),header=n('tr');for(const label of ['Task / revision','Earlier · eligible / imported','Later · eligible / imported','Change','Comparison'])header.append(n('th',label));thead.append(header);const body=n('tbody');
  taskPage=Math.min(taskPage,Math.max(0,Math.ceil(m.tasks.length/20)-1));
  const tasks=[...m.tasks].sort((a,b)=>(a.status==='shared'?0:1)-(b.status==='shared'?0:1)||a.task.task_id.localeCompare(b.task.task_id));
  for(const row of tasks.slice(taskPage*20,taskPage*20+20)){const tr=n('tr'),task=n('td'),url='/?'+new URLSearchParams({view:'strategies',...scope,...state,population_mode:'task',cohort_id:row.cohort_id,category:c.id});task.dataset.label='Task / revision';task.append(link(row.task.task_id+(row.task.task_revision?' · '+row.task.task_revision:''),url));tr.append(task);
   for(const [label,value]of [['Earlier',pct(row.earlier.shares[c.id])+' · '+row.earlier.eligible_rollouts+' / '+row.earlier.population],['Later',pct(row.later.shares[c.id])+' · '+row.later.eligible_rollouts+' / '+row.later.population],['Change',d.comparable?pp(row.pp[c.id]):'—'],['Comparison',({shared:'Included',earlier_only:'Earlier only',later_only:'Later only',unobserved:'Unobserved'})[row.status]]]){const cell=n('td',value);cell.dataset.label=label;tr.append(cell);}body.append(tr);}
  table.append(thead,body);details.append(n('p','Each window shows the category share and eligible / imported rollout counts.','bd-note'),table);if(m.tasks.length>20){const pager=n('div',undefined,'pager');for(const [label,change,disabled]of [['Previous tasks',-1,taskPage===0],['Next tasks',1,(taskPage+1)*20>=m.tasks.length]]){const b=button(label,()=>{taskPage+=change;taskDetailsOpen=true;render(last);});b.disabled=disabled;pager.append(b);}pager.append(n('span',(taskPage*20+1)+'–'+Math.min((taskPage+1)*20,m.tasks.length)+' of '+m.tasks.length+' tasks'));details.append(pager);}details.append(n('p',m.limit,'bd-note'));section.append(details);return section;
 }
 function download(d,filename=d.snapshot_id){const a=n('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'}));a.download=filename+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
 function editor(d){const original=d.groupings.find(g=>g.id===d.grouping),groups=original.groups.map(g=>({...g,activities:[...g.activities]})),dialog=n('dialog',undefined,'bd-editor'),form=n('form');dialog.setAttribute('aria-label','Edit category grouping');const head=n('div',undefined,'dialog-head');head.append(n('h2','Group activities for analysis'),button('Close',()=>dialog.close()));form.append(head,n('p','Each activity belongs to one group. Saving creates a reusable version; the underlying unit tags stay unchanged. Empty groups are omitted.','bd-note'));
  const nameLabel=n('label','Grouping name'),name=n('input');name.value=original.name+' · custom';name.maxLength=80;name.required=true;nameLabel.append(name);form.append(nameLabel);const fields=n('div');form.append(fields);const assignment=new Map(d.activities.map(a=>[a,groups.find(g=>g.activities.includes(a))?.id||'']));
  function fieldsRender(){fields.replaceChildren();const names=n('div',undefined,'bd-group-names');for(const g of groups){const label=n('label','Group label'),input=n('input');input.value=g.label;input.required=true;input.maxLength=60;input.oninput=()=>{g.label=input.value;for(const option of fields.querySelectorAll('option'))if(option.value===g.id)option.textContent=g.label;};label.append(input);names.append(label);}fields.append(names);const add=button('+ Add group',()=>{let next=groups.length;while(groups.some(g=>g.id==='group_'+next))next++;groups.push({id:'group_'+next,label:'New group',activities:[],color:['#6b68b3','#5594a2','#b78b54','#719273','#ad7694','#7c8ba7'][groups.length%6]});fieldsRender();});add.disabled=groups.length>=8;fields.append(add);const map=n('div',undefined,'bd-assignment');for(const a of d.activities)map.append(select(a,[['','Unmapped activity'],...groups.map(g=>[g.id,g.label])],assignment.get(a),v=>assignment.set(a,v)));fields.append(map);}
  fieldsRender();const error=n('p',undefined,'bd-error');error.setAttribute('role','alert');const save=n('button','Save grouping','primary');save.type='submit';form.append(error,save);form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{const value={name:name.value,groups:groups.map(g=>({...g,activities:d.activities.filter(a=>assignment.get(a)===g.id)})).filter(g=>g.activities.length)};const response=await fetch('/api/behavior-groupings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)}),saved=await response.json();if(!response.ok)throw Error(saved.error);state.grouping=saved.id;selected=null;dialog.close();await load(host,scope);}catch(err){error.textContent=err.message;save.disabled=false;}};dialog.append(form);dialog.onclose=()=>dialog.remove();document.body.append(dialog);dialog.showModal();}
 return {load,readiness,savedSelection};
})();
