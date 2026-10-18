'use strict';
const chartCohorts=new Map();
const chartCoverage=new Map();
const WorkReturnQuery=(()=>{
 let saved=null,initialized=false,specification=null;
 const q=id=>document.getElementById(id);
 function reset(query){saved=query?.schema==='work-return-references/1'?query:null;initialized=false;}
 function configure(spec,options){
  const active=spec?.query_kind==='work_return';q('work-return-fields').hidden=!active;
  if(!active)return;specification=spec;if(initialized)return;
  const source=saved||spec.default_query;
  const types=[...new Set([...spec.supported_relations,...options.relations.filter(t=>t.startsWith('reasoningflow:backref:')),...source.relation_types])].sort();
  q('work-return-relations').replaceChildren(...types.map(type=>{
   const option=document.createElement('option');option.value=type;
   option.textContent=type.startsWith('reasoningflow:backref:')?'Native reference · '+type.slice('reasoningflow:backref:'.length):type.replaceAll('_',' ');
   option.selected=source.relation_types.includes(type);return option;
  }));
  q('work-return-scope').replaceChildren(...Object.entries(spec.referent_scopes).map(([value,label])=>{
   const option=document.createElement('option');option.value=value;option.textContent=label;return option;
  }));q('work-return-scope').value=source.referent_scope;initialized=true;
 }
 function definition(name){return {schema:specification.default_query.schema,name,
  relation_types:[...q('work-return-relations').selectedOptions].map(o=>o.value).sort(),referent_scope:q('work-return-scope').value};}
 return {reset,configure,definition};
})();
let questionCheckSequence=0,questionCheckReceipt=null,questionCheckLiveRevision=null;
function questionLiveRevision(s){return JSON.stringify([s?.source_revision,s?.analysis?.revision]);}
function monitorDefinition(){
 const d=unscopedMonitorDefinition();
 if(options?.question_setup){
  const population={};for(const key of ['experiment','environment','split']){const value=document.querySelector('#monitor-'+key).value;if(value.trim())population[key]=value;}
  if(Object.keys(population).length)d.population=population;
 }
 return d;
}
function invalidateQuestionCheck(){
 questionCheckSequence++;questionCheckReceipt=null;
 const box=document.querySelector('#question-check-result');if(box)box.replaceChildren();
 const button=document.querySelector('#check-question');if(button){button.disabled=false;button.textContent='Check evidence';}
}
function showQuestionCheck(){document.querySelector('#question-check').hidden=!options?.question_setup||!['graph','analysis'].includes(document.querySelector('#monitor-kind').value);}
function initQuestionSetup(m){
 WorkReturnQuery.reset(m?.analysis?.query);
 WorkReturnQuery.configure($('#monitor-kind').value==='analysis'?options.analysis_measures?.[$('#monitor-analysis').value]:null,options);
 invalidateQuestionCheck();const available=Boolean(options?.question_setup);
 document.querySelector('#monitor-population').hidden=!available;document.querySelector('#question-starts').hidden=!available||!!m;
 document.querySelector('#start-work-question').hidden=!options?.analysis_measures?.work_switch_return_fraction;
 document.querySelector('#start-return-reference-question').hidden=!options?.analysis_measures?.work_return_references;
 for(const key of ['experiment','environment','split'])document.querySelector('#monitor-'+key).value=m?m.population?.[key]||'':(key==='split'?'':document.querySelector('#'+key).value);
 $('#monitor-population').open=false;updatePopulationSummary();showQuestionCheck();
 $('#custom-monitor-database').value=options?.custom_setup?.database||'workspace.sqlite';
 $('#custom-monitor-experiment').value=m?.population?.experiment||($('#experiment').value==='__unassigned__'?'':$('#experiment').value);
 $('#custom-monitor-version').value=m?.custom?.version||'1';
 $('#custom-monitor-description').value=m?.custom?.description||'Count recorded agent actions; replace measure() with your analysis.';
 configureCustomMode();
}
function updatePopulationSummary(){const labels=['experiment','environment','split'].map(key=>document.querySelector('#monitor-'+key).value.trim()).filter(Boolean);document.querySelector('#population-summary').textContent='Population scope · '+(labels.join(' / ')||'All rollouts');}
for(const key of ['experiment','environment','split'])document.querySelector('#monitor-'+key).addEventListener('input',updatePopulationSummary);
async function checkQuestion(offset=0){
 const token=++questionCheckSequence,button=document.querySelector('#check-question'),box=document.querySelector('#question-check-result');
 try{
  const body={definition:monitorDefinition(),offset,limit:20};if(offset&&questionCheckReceipt)body.expected_revision=questionCheckReceipt.revision;
  button.disabled=true;button.textContent='Checking…';
  const result=await api('/api/monitoring/check',body);if(token!==questionCheckSequence)return;
  questionCheckReceipt=result;questionCheckLiveRevision=questionLiveRevision(window.trackerLive);box.replaceChildren();
  box.append(make('p',result.population?`${offset+1}–${offset+result.rows.length} of ${number(result.population)} rollouts in the saved population`:'No rollouts match this population. Future matching rollouts will be included.','question-check-summary'));
  box.append(make('p','This page checks source and observer inputs. Open a case to review meaning; save the monitor to compute its measurements.','field-note'));
  const labels={needs_source:'Source missing',needs_observer:'Observer needed',missing_inputs:'Inputs missing',presence_only:'Inputs recorded · review required',changed_evidence:'Evidence changed'};
  for(const row of result.rows){
   const card=make('details',undefined,'question-evidence-row'),summary=make('summary');summary.append(make('strong',row.task_id||row.run_id),make('span',labels[row.status]||human(row.status)));card.append(summary);
   const c=row.recorded_counts;card.append(make('p',`${c.semantic_units} selected text units · ${c.linked_text_feedback} linked text results`+(row.recorded_anchors===undefined?'':` · ${row.recorded_anchors} recorded starting units`),'field-note'));
   for(const guidance of row.guidance)card.append(make('p',guidance));
   for(const node of row.nodes)card.append(make('p',node.boundary,'field-note'));
   const link=make('a',row.graph_id?'Review this observer’s map ↗':'Review source evidence ↗');
   link.href='/semantic-map?'+new URLSearchParams({run:row.run_id,observer:row.graph_id?result.definition.observer:'source',...(row.graph_id?{graph:row.graph_id}:{})});link.target='_blank';link.rel='noopener';card.append(link);box.append(card);
  }
  if(result.next_offset!==null){const next=make('button','Check next page');next.type='button';next.onclick=()=>checkQuestion(result.next_offset);box.append(next);}
  const receipt=make('details'),heading=make('summary','Definition and evidence-check receipt');receipt.append(heading,make('pre',JSON.stringify(result,null,2)));box.append(receipt);
 }catch(error){if(token===questionCheckSequence){box.replaceChildren(make('p',error.message));questionCheckReceipt=null;}}
 finally{if(token===questionCheckSequence){button.disabled=false;button.textContent='Check evidence';}}
}
const $=s=>document.querySelector(s),make=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const number=n=>Number(n).toLocaleString(),human=s=>(s||'').replaceAll('_',' '),short=(s,n=52)=>s.length>n?s.slice(0,n)+'…':s;
let state=null,options=null,revision=null,busy=false,page=0,editing=null,caseRows=[],caseMonitor=null,caseStep=null,caseExactValue=null,casePage=0,caseCohort=null,caseRequestSequence=0,requestSequence=0;
let customGuideHashHandled=false;
const view=location.pathname==='/monitors'?'monitors':location.pathname==='/runs'?'runs':'overview';
const strategyView=view==='overview'&&new URLSearchParams(location.search).get('view')==='strategies';
const trainingView=view==='overview'&&new URLSearchParams(location.search).get('view')==='training';
const healthView=view==='overview'&&new URLSearchParams(location.search).get('view')==='health';
let healthModule=null;
function loadHealthView(){if(!document.querySelector('link[href="/training-health.css"]')){const style=make('link');style.rel='stylesheet';style.href='/training-health.css';document.head.append(style);}if(!healthModule)healthModule=new Promise((resolve,reject)=>{const script=make('script');script.src='/training-health.js';script.onload=resolve;script.onerror=()=>{healthModule=null;reject(Error('Training-health view requires the updated collector.'));};document.head.append(script);});healthModule.then(()=>TrainingHealth.load($('#health-view'),Object.fromEntries(new URLSearchParams(query())))).catch(failed);}
let trainingModule=null;
function loadTrainingView(){if(!trainingModule)trainingModule=new Promise((resolve,reject)=>{const script=make('script');script.src='/training-populations.js';script.onload=resolve;script.onerror=()=>{trainingModule=null;reject(Error('Training samples require the updated collector.'));};document.head.append(script);});trainingModule.then(()=>TrainingPopulations.load($('#training-view'),Object.fromEntries(new URLSearchParams(query())))).catch(failed);}
function trainingAvailability(s){if(s?.training_revision!==undefined)$('#training-tab').hidden=false;}
trainingAvailability(window.trackerLive);window.addEventListener('tracker-live',e=>trainingAvailability(e.detail));
if(location.hash.startsWith('#run='))location.replace('/source'+location.hash);
async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d;}
function opt(value,label){const o=make('option',label);o.value=value;return o;}
function failed(e){$('#error').hidden=false;$('#error').textContent=e.message;}
function query(){const p=new URLSearchParams();if($('#experiment').value)p.set('experiment',$('#experiment').value);if($('#environment').value)p.set('environment',$('#environment').value);return p.toString()?'?'+p:'';}
function mapLink(id,observer,valueId){if(observer?.startsWith('tool-contracts-'))return '/source#run='+encodeURIComponent(id);return '/semantic-map?run='+encodeURIComponent(id)+(observer&&observer!=='source'?'&observer='+encodeURIComponent(observer):'')+(valueId?'&value='+encodeURIComponent(valueId):'');}
function metricValue(v,m){if(v===null||v===undefined)return '—';if(m.unit==='fraction')return (v*100).toFixed(1)+'%';return Math.abs(v)>=1000?number(Math.round(v)):Number(v.toFixed(3)).toLocaleString();}
function headlineDetails(point,byStep){
 const position=byStep?'Step '+point.step:'Rollout '+point.order;
 const coverage=byStep?` · ${point.n} / ${point.n+(point.unknown||0)} rollouts measured`:'';
 const outcome=point.value==null?'No measurement at this position':point.denominator!=null?`${point.numerator} / ${point.denominator} opportunities`:byStep?'rollout mean':'recorded value';
 return position+' · '+outcome+coverage;
}
function cohortLabel(s,series){
 const c=s.cohort,parts=[c.experiment||'Unassigned'];
 for(const key of ['split','environment','environment_version','reward_definition','sampling','training_inclusion','task_revision','source_selection','adapter','training_step_basis']){
  const distinct=new Set(series.map(row=>JSON.stringify(row.cohort[key]??null)));
  if(distinct.size>1||key==='split'&&c[key])parts.push(human(key)+': '+(c[key]===null||c[key]===undefined?'not recorded':String(c[key])));
 }
 return parts.join(' · ');
}
function coverageView(m){const c=m.coverage;if(!c)return{denominator:null,label:m.enabled?'Coverage unavailable':'Paused · saved values retained',detail:null};const s=c.query_selection;return s?{denominator:s.with_dispatches,label:`${number(c.available)} / ${number(s.with_dispatches)} selected rollouts measured`,detail:`${number(s.without_dispatches)} rollouts have no selected dispatches`+(s.unavailable?` · selection unavailable for ${number(s.unavailable)}`:'')}:{denominator:c.population,label:`${number(c.available)} / ${number(c.population)} measured`,detail:m.detector_counts?Object.entries(m.detector_counts).map(([status,n])=>`${number(n)} ${status.replaceAll('_',' ')}`).join(' · '):null};}
function download(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})),a=make('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function status(s){const disconnected=window.trackerStreamConnected===false,collecting=window.trackerLive?.connections?.some(c=>c.running);$('#service-status').textContent=disconnected?'Disconnected · reconnecting':s.error?'Monitor error':s.updating||s.snapshot_stale?'Source received · updating monitors':s.running?(collecting?'Connected · watching sources':'Connected · saved data'):'Offline';$('#service-status').classList.toggle('offline',disconnected||!!s.error||!s.running);$('#service-status').title=s.error||s.inference||'';if(s.checked_at)$('#updated').textContent='Monitors checked '+new Date(s.checked_at).toLocaleTimeString();}
async function load(initial=false){const sequence=++requestSequence;try{const data=await api('/api/monitoring'+query());if(sequence!==requestSequence)return;state=data;status(data.service);$('#error').hidden=true;
 if(initial){$('#experiment').replaceChildren(opt('','All experiments'),...data.experiments.map(e=>opt(e.id,e.id==='__unassigned__'?'Unassigned / evaluation rollouts':e.id)));$('#environment').replaceChildren(opt('','All environments'),...data.environments.map(e=>opt(e,e)));
  const requested=new URLSearchParams(location.search),old=requested.get('experiment')??sessionStorage.getItem('monitor-experiment');
  for(const key of ['experiment','environment'])if(requested.has(key)&&![...$('#'+key).options].some(o=>o.value===requested.get(key)))$('#'+key).append(opt(requested.get(key),requested.get(key)+' (no source rollouts)'));
  if(requested.has('environment'))$('#environment').value=requested.get('environment');
  $('#experiment').value=old!==null&&[...$('#experiment').options].some(o=>o.value===old)?old:'';if($('#experiment').value||$('#environment').value)return load();}
 if(!initial){for(const [id,values,placeholder]of [['#experiment',data.experiments.map(e=>[e.id,e.id==='__unassigned__'?'Unassigned / evaluation rollouts':e.id]),'All experiments'],['#environment',data.environments.map(e=>[e,e]),'All environments']]){const select=$(id),old=select.value;if(old&&!values.some(v=>v[0]===old))values.push([old,old+' (no source rollouts)']);if(JSON.stringify([...select.options].map(o=>o.value))!==JSON.stringify(['',...values.map(v=>v[0])])){select.replaceChildren(opt('',placeholder),...values.map(v=>opt(...v)));select.value=old;}}}
 render();
 }catch(e){failed(e);}}
function render(){document.body.classList.toggle('measure-overview',view==='overview'&&!strategyView&&!trainingView&&!healthView);document.title='Rilldex · '+{overview:'Training overview',monitors:'Monitors',runs:'Rollouts'}[view];const active=state.monitors.filter(m=>m.enabled&&inDashboardScope(m)),steps=new Set(state.runs.map(r=>r.metadata.training_step).filter(Number.isInteger));const strip=$('#summary-strip');strip.replaceChildren();for(const[n,label]of [[state.population,'rollouts'],[steps.size,'steps in rollout metadata'],[active.length,'active monitors'],[state.runs.filter(r=>r.semantic_graphs).length,'rollouts with semantic maps']]){const x=make('div');x.append(make('strong',number(n)),make('span',label));strip.append(x);}
 renderOverviewContext();renderActiveCaptures(state.active_captures);
 const executionHost=$('#execution-context');executionHost.hidden=view!=='overview'||strategyView||trainingView||healthView;const panels=[...executionHost.children].map(e=>e.open),declared=PopulationEvidence.declaredCohorts(state.declared_populations),execution=PopulationEvidence.executionContext(state.execution_context);if(panels.length&&executionHost.firstChild.dataset.scope===declared.dataset.scope){declared.open=panels[0];execution.open=panels[1];}executionHost.replaceChildren(declared,execution);
 $('#overview-view').hidden=view!=='overview';$('#monitors-view').hidden=view!=='monitors';$('#runs-view').hidden=view!=='runs';$('#axis-label').hidden=view!=='overview';$('#page-name').textContent={overview:'Overview',monitors:'Monitors',runs:'Rollouts'}[view];$('#page-title').textContent={overview:'Training overview',monitors:'Monitor management',runs:'Rollout explorer'}[view];
 $('#page-description').textContent={overview:'Compare behavior, results and missing evidence. Select a chart point to inspect its rollout.',monitors:'Add, edit or pause monitors. Open a monitor to view its values and linked evidence.',runs:'Filter by task, training step or result. Open a rollout to trace actions, feedback and revisions.'}[view];$('#add-monitor').hidden=view==='runs';

 window.dispatchEvent(new CustomEvent('jev:scope',{detail:{experiment:$('#experiment').value,environment:$('#environment').value}}));for(const [id,panel]of [['health-tab','health'],['measures-tab',''],['strategies-tab','strategies'],['training-tab','training']]){const q=new URLSearchParams(query().slice(1));if(panel)q.set('view',panel);$('#'+id).href='/'+(q.size?'?'+q:'');}
 $('#measure-browser').hidden=view==='runs'||view==='monitors'||strategyView||trainingView;
 $('#overview-tabs').hidden=view!=='overview';$('#strategies-view').hidden=!strategyView;$('#summary-strip').hidden=strategyView;$('#overview-view').hidden=view!=='overview'||strategyView;$('#axis-label').hidden=view!=='overview'||strategyView;
 $('#training-view').hidden=!trainingView;if(trainingView){$('#overview-view').hidden=true;$('#summary-strip').hidden=true;$('#axis-label').hidden=true;}
 $('#measures-tab').setAttribute('aria-current',strategyView||trainingView?'false':'page');$('#strategies-tab').setAttribute('aria-current',strategyView?'page':'false');$('#training-tab').setAttribute('aria-current',trainingView?'page':'false');
 $('#health-tab').hidden=!state.capabilities?.training_health;$('#health-view').hidden=!healthView;$('#health-tab').setAttribute('aria-current',healthView?'page':'false');
 if(healthView){$('#overview-view').hidden=true;$('#summary-strip').hidden=true;$('#axis-label').hidden=true;$('#measure-browser').hidden=true;$('#measures-tab').setAttribute('aria-current','false');$('#page-title').textContent='Training health';$('#page-description').textContent='Follow rewards, training use and behavior under recorded RL settings.';document.title='Rilldex · Training health';if(state.capabilities?.training_health)loadHealthView();else $('#health-view').replaceChildren(make('p','This collector is running an older backend. Restart it with the updated code to enable training health diagnostics. Existing behavior measures remain available.'));return;}
 if(trainingView){document.title='Rilldex · Training samples';$('#page-title').textContent='From generated samples to training use';loadTrainingView();return;}
 if(strategyView){const episodeView=new URLSearchParams(location.search).get('detail')==='episodes';document.title='Rilldex · '+(episodeView?'Strategy profiles':'Behavior distributions');$('#page-title').textContent=episodeView?'Strategy profiles':'Behavior distributions';StrategyProfiles.load($('#strategies-view'),Object.fromEntries(new URLSearchParams(query())));}else if(view==='overview'){renderCards(active);renderResearchRail(active);}if(view==='monitors'){renderRegistry();const presets=$('#monitor-presets');presets.ontoggle=()=>{if(presets.open)renderMonitorPresets();};if(presets.open)renderMonitorPresets();}if(view==='runs')renderRuns();}
let presetOptionsSequence=0;
async function renderMonitorPresets(){
 const sequence=++presetOptionsSequence;
 try{
  const current=await api('/api/monitoring/options');if(sequence!==presetOptionsSequence)return;options=current;
  if(!$('#monitor-presets').open)return;
  return IntervalInvestigation.bundles($('#monitor-questions'),{monitors:state.monitors,observers:current.graph_observers||[],experiment:$('#experiment').value,environment:$('#environment').value},()=>load());
 }catch(e){if(sequence===presetOptionsSequence)$('#monitor-questions').textContent=e.message;}
}
function procedureCoverageText(c,scope){
 if(!c)return '';
 if(!c.observed_rollouts)return 'Procedure comparison coverage unavailable · '+scope;
 return `${c.compared} / ${c.total} recurrences compared · ${c.unresolved} unresolved · ${scope}`+(c.observed_rollouts<c.total_rollouts?` · coverage missing for ${c.total_rollouts-c.observed_rollouts} rollouts`:'');
}
function renderOverviewContext(){
 const host=$('#overview-context');host.hidden=view!=='overview';if(host.hidden)return;
 host.replaceChildren();const maps=state.runs.filter(r=>r.semantic_graphs),summary=make('div',undefined,'overview-context-summary');
 summary.append(make('strong',`${number(state.population)} rollouts · ${number(maps.length)} with semantic maps`),make('span',maps.length?'Open a saved map to inspect activities, plans and linked feedback.':'No semantic maps with relationship coverage are available in this selection. Open a rollout to inspect its source and any partial observations.'));
 const actions=make('div',undefined,'overview-context-actions');
 const browse=make('a',maps.length?'Open annotated map →':'Browse rollouts →');browse.href=maps.length?mapLink(maps[0].id):'/runs'+query();actions.append(browse);
 const defaults=make('button','Add default measures');defaults.type='button';defaults.title='Add reward, task success, response length, actions, tool errors, repeated dispatches, response coverage and first recheck. Existing or paused monitors are preserved.';
 const feedback=make('span',undefined,'overview-default-feedback');feedback.setAttribute('role','status');
 defaults.onclick=async()=>{defaults.disabled=true;try{const result=await api('/api/monitoring/starters',{});await load();const target=$('#overview-context .overview-default-feedback');target.textContent=`${result.added.length} added · ${result.existing.length} already configured`;}catch(e){failed(e);}finally{defaults.disabled=false;}};
 actions.append(defaults,feedback);host.append(summary,actions);
 const inputs=make('details',undefined,'overview-inputs');inputs.append(make('summary','Workspace & metric inputs'));
 if(state.workspace){const database=make('p');database.append(make('strong','Database: '),make('code',state.workspace.database));inputs.append(database,make('p',`${number(state.workspace.rollouts)} rollouts in this database · ${number(state.workspace.semantic_rollouts)} with semantic maps. Experiment and environment filters apply to the views above.`));}
 inputs.append(make('p','Default rollout measures use saved source records. Missing outcomes and unreported tool errors remain unavailable. Response length is in characters, not tokens.'));
 const training=make('a','Open training signals →');training.href='/?'+new URLSearchParams({...Object.fromEntries(new URLSearchParams(query())),view:'health'});
 const code=make('a','Connect trainer telemetry →');code.href='/connections#telemetry-section';
 inputs.append(make('p','Native trainer metrics appear above rollout measures when connected. Their training steps, populations, units and objective definitions remain separate from rollout counts.'),training,code);host.append(inputs);
}
function renderActiveCaptures(data){
 const host=$('#active-captures');host.hidden=view!=='overview'||strategyView||trainingView||healthView||!data?.total;
 if(host.hidden){host.replaceChildren();return;}
 host.replaceChildren();const head=make('div',undefined,'active-capture-head');head.append(make('h2',`${number(data.total)} rollouts streaming`),make('span','Current source prefixes · updates live','muted'));host.append(head);
 host.append(make('p','Inspect work while generation is still running. These received counts are separate from completed-rollout metrics; they do not measure task progress or success.','active-capture-note'));
 const list=make('div',undefined,'active-capture-list');
 for(const row of data.rows){const card=make('article',undefined,'active-capture-row'),identity=make('div'),counts=make('div'),last=make('div');identity.append(make('strong',row.task_id||'Untitled rollout'),make('small',`${row.environment||'Environment not recorded'} · source revision ${row.revision}`));
 const sample=make('small','Rollout '+row.rollout_id);sample.title='Producer: '+row.producer;identity.append(sample);
 counts.append(make('strong',`${number(row.event_count)} events · ${number(row.action_count)} actions`),make('small',`${number(row.feedback_count)} responses · ${number(row.agent_text_chars)} agent-text characters`));
 last.append(make('small','Latest recorded agent text'),make('p',row.last_agent_text||'No agent text in this prefix.'));
 const link=make('a','Inspect current trace →'),q=new URLSearchParams({run:row.run_id,observer:'source',level:'story',return_to:location.pathname+location.search+location.hash});if(row.last_agent_event_id)q.set('story_moment','event:'+row.last_agent_event_id);link.href='/semantic-map?'+q;last.append(link);
 const observations=row.semantic_observations?.rows||[];
 if(!observations.length)last.append(make('small','Semantic observations pending or not configured for this snapshot.'));
 for(const observation of observations){if(observation.status==='published'){
   const map=make('a',`Open behavior map · ${number(observation.unit_count)} units`),params=new URLSearchParams({run:row.run_id,observer:observation.observer,level:'units',return_to:location.pathname+location.search+location.hash});if(observation.graph_id)params.set('graph',observation.graph_id);map.href='/semantic-map?'+params;map.title=observation.label+' · current growing prefix';last.append(map);
  }else {
   let label={running:'observing this prefix',queued:'queued',needs_candidates:'waiting for semantic proposals',budget_reached:'budget reached',failed:'observation failed',interrupted:'observation interrupted'}[observation.status]||observation.status.replaceAll('_',' ');
   if(observation.status==='needs_candidates'&&Number.isInteger(observation.pending_proposals))label=observation.pending_proposals>0?`${number(observation.pending_proposals)} proposal files pending`:'proposal review needed';
   const status=make('small',observation.label+' · '+label),progress=observation.annotation_progress;
   if(progress&&Number.isInteger(progress.selected_units)&&progress.selected_units>=0){
    status.append(document.createTextNode(` · ${number(progress.selected_units)} units selected`));
    if(Number.isFinite(progress.eligible_source_bytes)&&progress.eligible_source_bytes>0&&Number.isFinite(progress.selected_source_bytes)&&progress.selected_source_bytes>=0&&progress.selected_source_bytes<=progress.eligible_source_bytes){
     const percent=Math.floor(100*progress.selected_source_bytes/progress.eligible_source_bytes);
     status.append(document.createTextNode(` · ${percent}% of eligible source annotated`));
    }
    status.title='Coverage of eligible text and action payloads at the last saved observation pass. This is annotation progress, not task completion, model accuracy, or feedback coverage. The map becomes available after the configured layers finish.';
   }
   last.append(status);
  }}
 card.append(identity,counts,last);list.append(card);}
 host.append(list);if(data.truncated)host.append(make('p',`Showing ${data.rows.length} most recently received prefixes of ${number(data.total)} active captures. Narrow the environment to inspect other work.`,'active-capture-note'));
}
function renderCards(monitors){monitors=filterMonitors(monitors);const host=$('#monitor-grid');for(const chart of host.querySelectorAll('.chart-host'))chart.dispose?.();host.replaceChildren();const focus=new URLSearchParams(location.search).get('monitor');host.classList.toggle('focused-monitor',Boolean(focus));if(focus){monitors=monitors.filter(m=>m.id===focus);const context=make('div',undefined,'measurement-note metric-focus-context'),all=make('a','Show all monitors');const q=new URLSearchParams(location.search);q.delete('monitor');all.href='/'+(q.size?'?'+q:'');context.append(make('p',monitors.length?'Focused monitor · population filters still apply.':'This monitor is unavailable or disabled.'),all);host.append(context);}if(!monitors.length){const empty=make('div',undefined,'empty-workspace');empty.append(make('strong',state.monitors.some(m=>m.enabled)?'No measures match these filters':'No active monitors'),make('p',state.monitors.some(m=>m.enabled)?'Try a different name, group or coverage filter.':'Use Add monitor to select a metric or register a code-defined measure.'));const action=make('button',state.monitors.some(m=>m.enabled)?'Clear filters':'Add a measure','primary');action.onclick=()=>{if(state.monitors.some(m=>m.enabled)){$('#monitor-search').value='';$('#monitor-group-filter').value='';$('#monitor-availability').value='all';const url=new URL(location.href);url.searchParams.delete('monitor');history.replaceState(null,'',url.pathname+url.search);render();}else openEditor();};empty.append(action);host.append(empty);return;}
 const priority=m=>({feedback_assessment_fraction:0,enacted_revision_completion_fraction:1,changed_retry_completion_fraction:2,plan_stage_attempt_fraction:3}[m.metric]??4);
 monitors=[...monitors].sort((a,b)=>['Behavior','Reward integrity','Training'].indexOf(a.group)-['Behavior','Reward integrity','Training'].indexOf(b.group)||priority(a)-priority(b));
 for(const m of monitors){const card=make('article',undefined,'metric-card'),top=make('div',undefined,'card-top'),titles=make('div');titles.append(make('h3',m.name),make('small',m.group+(m.metric?.startsWith('diagnostic_')?' · experimental':'')));const edit=monitorSetupAction(m,'card-menu');top.append(titles,edit);card.append(top);
 const usable=m.series.filter(s=>s.points.length),headline=make('div',undefined,'metric-headline');if(usable.length===1){const byStep=$('#axis').value==='step',latest=(byStep?usable[0].bins:usable[0].points).at(-1);headline.append(make('strong',metricValue(latest.value,m)),make('small',(byStep?'Step '+latest.step:'Rollout '+latest.order)+' · '+(latest.denominator!=null?`${latest.numerator} / ${latest.denominator} opportunities`:byStep?'rollout mean':'recorded value')));}else if(usable.length>1)headline.append(make('strong',usable.length+' cohorts'));else if(m.unplaced_points.length===1)headline.append(make('strong',metricValue(m.unplaced_points[0].value,m)),make('small',m.unplaced_points[0].denominator!=null?`${m.unplaced_points[0].numerator} / ${m.unplaced_points[0].denominator} opportunities · one rollout`:'one measured rollout'));else headline.append(make('strong',m.coverage.available?number(m.coverage.available):'—'),make('small',m.coverage.available?'measured rollouts':m.coverage.disputed_work_rollouts?'Needs evidence review':'Awaiting measurements'));if(m.analysis?.measure==='feedback_reference'){
 card.classList.add('feedback-reference-card');
 const points=[...m.series.flatMap(s=>s.points),...m.unplaced_points],n=points.reduce((sum,p)=>sum+(p.numerator||0),0),op=m.coverage.opportunities,u=m.coverage.unknown_opportunities,d=op-u;
 headline.replaceChildren(make('strong',d?number(n)+' references':op?'Review incomplete':'—'),make('small',op?`${d} decidable / ${op} captured responses · full population`:'No measured response opportunities'));
 }card.append(headline);
 const procedureNote=make('p',undefined,'measurement-note procedure-coverage');
 if(m.coverage.procedure_comparisons){procedureNote.textContent=procedureCoverageText(m.unplaced_points.length===1&&!usable.length?m.unplaced_points[0].procedure_comparisons:m.coverage.procedure_comparisons,m.unplaced_points.length===1&&!usable.length?'this rollout':'full population');card.append(procedureNote);}
 if(m.definition_notice){const note=make('div',undefined,'definition-notice'),review=make('button','Review current definition');note.append(make('strong','Historical procedure rules'),make('p',m.definition_notice.message));review.onclick=()=>openEditor(m);note.append(review);card.append(note);}
 const question={enacted_revision_completion_fraction:'After failure, does the next attempt complete when a stated change is attempted?',enacted_revision_unknown_fraction:'Are results observable after stated-change attempts?',changed_retry_completion_fraction:'After a failed operation, does a changed retry complete?',feedback_assessment_fraction:'Does the agent assess returned feedback before acting again?',plan_stage_attempt_fraction:'Does the agent act on its declared plan?',changed_retry_unknown_fraction:'How much retry evidence is still missing?',unchanged_retry_fraction:'Does the agent repeat the same dispatch after failure?'}[m.metric];const meaning=measureReading(m)||question||(m.analysis?.measure==='feedback_assessment_after_actions'?'Did other actions occur before the first saved feedback assessment?':null)||String(m.description||m.analysis_definition?.description||'').split(/(?<=[.!?])\s/)[0];if(meaning)card.append(make('p',short(meaning,200),'measurement-note metric-meaning'));
 const missingReasons=Object.entries(m.coverage.reasons||{}).filter(([,n])=>n>0).sort((a,b)=>b[1]-a[1]);if(missingReasons.length){const gaps=make('details',undefined,'metric-gaps');gaps.open=!m.coverage.available;gaps.append(make('summary',number(missingReasons.reduce((sum,row)=>sum+row[1],0))+' missing measurements · reasons'));const list=make('dl');for(const [reason,count]of missingReasons)list.append(make('dt',reason),make('dd',number(count)+(count===1?' rollout':' rollouts')));const inspect=make('button','Inspect missing measurements');inspect.onclick=()=>openCases(m,null,null,'unknown');gaps.append(list,inspect);card.append(gaps);}
 const definition=make('details',undefined,'metric-definition');definition.append(make('summary','Definition & interpretation'),make('p',m.kind==='analysis'?m.analysis_definition.description:m.description));card.append(definition);
 if(['work_visits','work_return_references'].includes(m.analysis_definition?.operation)&&!m.analysis_definition.scope_consistency){definition.firstChild.textContent='Definition · historical rules';definition.classList.add('historical-definition');titles.querySelector('small').textContent+=' · historical rules';definition.append(make('p','Conflicting work assignments are not excluded by this saved definition. Use a current work measure for consistency-aware results.'));}
 if(m.coverage.disputed_work_rollouts)card.append(make('p',m.coverage.disputed_work_rollouts+(m.coverage.disputed_work_rollouts===1?' rollout contains':' rollouts contain')+' disputed work identities. Affected switches are unknown; counts are withheld. Open rollouts to review the conflicting evidence.','measurement-note'));
 if(m.kind==='analysis'){if(m.aggregation==='opportunity_ratio'&&!m.coverage.procedure_comparisons)card.append(make('p',m.coverage.unknown_opportunities+' unknown / '+m.coverage.opportunities+' recorded opportunities','measurement-note'));}
 if(m.kind==='graph')card.append(make('p','Matches in saved links · incomplete annotations can hide matches','measurement-note'));
 if(usable.length){
 const chart=make('div',undefined,'metric-cohort-chart'),select=make('select'),cohortKey=s=>JSON.stringify(s.cohort);
 select.setAttribute('aria-label','Cohort for '+m.name);
 for(const [i,s]of usable.entries()){const label=cohortLabel(s,usable),option=make('option',label);option.value=String(i);option.title=label;select.append(option);}
 const remembered=usable.findIndex(s=>cohortKey(s)===chartCohorts.get(m.id));select.value=String(Math.max(0,remembered));
 if(usable.length>1){const label=make('label',undefined,'metric-cohort-picker');label.append(make('span',usable.length+' separate cohorts'),select);card.append(label);}
 let coverageMode=chartCoverage.get(m.id)||false;
 function showCohort(){const s=usable[Number(select.value)];chartCohorts.set(m.id,cohortKey(s));chart.querySelector('.chart-host')?.dispose?.();chart.replaceChildren();
  const byStep=$('#axis').value==='step',latest=(byStep?s.bins:s.points).at(-1);
  if(m.analysis?.measure!=='feedback_reference')headline.replaceChildren(make('strong',metricValue(latest.value,m)),make('small',headlineDetails(latest,byStep)+(usable.length>1?' · selected cohort':'')));
  if(m.coverage.procedure_comparisons)procedureNote.textContent=procedureCoverageText(latest.procedure_comparisons,byStep?'this step':'this rollout');
  const info=make('details',undefined,'chart-cohort-definition'),fields=make('dl');info.append(make('summary',`${s.points.length} rollouts · cohort definition`));
  for(const [key,value]of Object.entries(s.cohort)){if(value==null)continue;fields.append(make('dt',human(key)),make('dd',typeof value==='object'?JSON.stringify(value):String(value)));}info.append(fields);
  const controls=make('div',undefined,'population-chart-controls'),mode=make('button',coverageMode?'Show metric':'Show measurement coverage');mode.type='button';mode.setAttribute('aria-pressed',String(coverageMode));mode.onclick=()=>{coverageMode=!coverageMode;chartCoverage.set(m.id,coverageMode);showCohort();};const investigate=make('button','Investigate interval');investigate.type='button';investigate.onclick=()=>IntervalInvestigation.open({monitors:state.monitors,experiment:s.cohort.experiment,environment:s.cohort.environment});controls.append(mode,investigate);
  const current=s.bins.at(-1)?.readiness;if(current)chart.append(make('p','Step '+s.bins.at(-1).step+' · '+PopulationEvidence.readinessText(current),'measurement-note'));
  chart.append(info,controls,plot(m,s,coverageMode));if(coverageMode)chart.append(make('p','Measured ÷ observed sources at each step; individual rollouts show 1 when measured and 0 when missing. Select a point to inspect the original evidence. Unreported jobs are outside this denominator.','field-note'));
 }
 select.onchange=showCohort;card.append(chart);showCohort();
 }
 else if(m.unplaced_points.length){card.append(distribution(m));}
 else{const empty=make('div',undefined,'chart-empty');empty.append(make('span',m.coverage.available?'∿':'○'),make('p',m.coverage.available?'Measured values have no logged training coordinates.':m.coverage.disputed_work_rollouts?'Work identity needs review.':m.analysis?.measure==='feedback_reference'&&m.coverage.opportunities?'Captured responses need complete reference review.':'No values for this population yet.'));empty.append(make('small',m.coverage.disputed_work_rollouts?'Saved evidence conflicts; no model recalculation is needed to inspect it.':m.analysis?.measure==='feedback_reference'&&m.coverage.opportunities?'Open rollouts to inspect coverage gaps.':m.kind==='graph'?'Waiting for semantic observations':'Waiting for '+(m.observer==='source'?'compatible source records':'the selected detector')));card.append(empty);}
 const readingDetails=make('div',undefined,'metric-card-details');for(const detail of card.querySelectorAll(':scope > .metric-definition,:scope > .metric-gaps'))readingDetails.append(detail);card.append(readingDetails);
 const cv=coverageView(m);if(cv.detail)readingDetails.append(make('p',cv.detail,'measurement-note'));const foot=make('div',undefined,'card-foot'),coverage=make('span',cv.label+' · population');coverage.title=Object.entries(m.coverage.reasons).map(([r,n])=>n+' · '+r).join('\n');const cases=make('button','Inspect rollouts →');cases.onclick=()=>openCases(m);const compare=make('button','Compare windows');compare.onclick=()=>openWindowComparison(m);foot.append(coverage,compare,cases);card.append(foot);const track=make('div',undefined,'coverage-track'),fill=make('span');fill.style.width=(100*m.coverage.available/(cv.denominator||1))+'%';track.append(fill);card.append(track);card.title=m.description;
 const intro=make('div',undefined,'metric-intro'),body=card.querySelector(':scope > .metric-cohort-chart,:scope > .value-distribution,:scope > .chart-empty');
 if(body){for(const child of [...card.children]){if(child===body)break;intro.append(child);}card.prepend(intro);}
 host.append(card);}}
function measureReading(m){
 const spec=m.analysis_definition||{},key=spec.operation+':'+spec.key;
 const descriptions={
  'work_visits:returned':'Count of returns to earlier work after working on another bound subject.',
  'work_visits:switch_returns':'Returns to earlier work ÷ work switches with sufficient evidence.',
  'declared_plans:initial_completed':'Items already reported complete in the first captured task list ÷ decidable items.',
  'feedback_timing:after_actions':'Did other actions occur before the first saved feedback assessment?'
 };
 if(spec.operation==='work_return_references'){
  const query=m.analysis?.query||{},relations=query.relation_types||[];
  const names={revises:'revision',uses_evidence:'evidence use',assesses:'assessment',responds_to:'response'};
  const scopes={same_work_history:'earlier visits to the same work',intervening_work:'the intervening work',all_prior_work:'any earlier work'};
  if(relations.length&&scopes[query.referent_scope])return 'Return visits with '+relations.map(r=>names[r]||(r.startsWith('reasoningflow:backref:')?r.slice('reasoningflow:backref:'.length).replaceAll(':',' / ')+' (native)':human(r))).join(' / ')+' links to '+scopes[query.referent_scope]+'.';
 }
 return descriptions[key]||{actions:'Recorded agent actions, excluding copied history.',agent_text_chars:'Recorded agent prose length, in characters.'}[m.metric]||null;
}
function filterMonitors(monitors){
 if(view==='overview')monitors=monitors.filter(inDashboardScope);
 const term=(view==='monitors'?$('#registry-search')?.value:$('#monitor-search').value||'').trim().toLowerCase(),group=$('#monitor-group-filter').value,availability=$('#monitor-availability').value;
 const rows=monitors.filter(m=>{const c=m.coverage,denominator=coverageView(m).denominator;const hasGap=!c||c.available<denominator||c.unknown_opportunities>0||c.procedure_comparisons?.unresolved>0||c.procedure_comparisons?.observed_rollouts<c.procedure_comparisons?.total_rollouts;return(!term||[m.name,m.description,m.metric,m.kind,m.group,customDefinition(m)?.description].filter(Boolean).join(' ').toLowerCase().includes(term))&&(!group||m.group===group)&&(availability==='all'||availability==='measured'&&(c?.available||0)>0||availability==='missing'&&hasGap);});
 $('#measure-count').textContent=rows.length+' / '+monitors.length+' measures';return rows;
}
function inDashboardScope(m){return ['experiment','environment'].every(k=>!$('#'+k).value||!m.population?.[k]||m.population[k]===$('#'+k).value);}
for(const id of ['monitor-search','monitor-group-filter','monitor-availability'])$('#'+id).addEventListener(id==='monitor-search'?'input':'change',()=>{if(state)view==='monitors'?renderRegistry():renderCards(state.monitors.filter(m=>m.enabled));});
function distribution(m){
 // This is an unordered distribution of saved per-rollout values, never a training curve.
 const points=m.unplaced_points.filter(p=>typeof p.value==='number'&&Number.isFinite(p.value)),host=make('div',undefined,'value-distribution');
 if(points.length===1){host.classList.add('single-rollout-value');const open=make('button','Open measured rollout →');open.onclick=()=>openCases(m,null,points[0].value);host.append(make('span','No training coordinates recorded'),open);return host;}
 const head=make('div',undefined,'distribution-head');head.append(make('strong','Recorded values'),make('span','No training coordinates'));host.append(head);
 if(!points.length){host.append(make('p','No finite values are available.'));return host;}
 const groups=new Map();for(const p of points){if(!groups.has(p.value))groups.set(p.value,[]);groups.get(p.value).push(p);}
 const ordered=[...groups].sort((a,b)=>a[0]-b[0]),peak=Math.max(...ordered.map(([,rows])=>rows.length)),list=make('div',undefined,'distribution-bars');
 for(const [value,rows]of ordered.slice(0,8)){const row=make('button',undefined,'distribution-row');row.type='button';row.setAttribute('aria-label',metricValue(value,m)+' · '+rows.length+' rollouts · inspect values');const bar=make('i');bar.style.setProperty('--value-width',(rows.length/peak*100)+'%');row.append(make('span',metricValue(value,m)),bar,make('small',String(rows.length)));row.onclick=()=>openCases(m,null,value);list.append(row);}
 host.append(list,make('p',ordered.length>8?ordered.length+' distinct values · open rollouts for the full distribution':points.length+' measured rollouts · unordered distribution','distribution-note'));return host;
}
function renderResearchRail(monitors){
 const host=$('#research-rail');host.replaceChildren();const checks=make('div',undefined,'research-rail-group');checks.append(make('h2','Data status'));
 const noStep=state.runs.filter(r=>!Number.isInteger(r.metadata.training_step)).length;
 if(noStep){const item=make('a',undefined,'research-check');item.href='/connections';item.append(make('span','DATA CONTEXT','rail-kicker'),make('strong','Training coordinates missing'),make('p',noStep+' loaded rollouts have no recorded training step. Their values are available on the rollout axis.'),make('span','Review capture setup ↗','rail-action'));checks.append(item);}
 const incomplete=monitors.filter(m=>m.coverage.available<coverageView(m).denominator||m.coverage.unknown_opportunities>0||m.coverage.procedure_comparisons?.unresolved>0||m.coverage.procedure_comparisons?.observed_rollouts<m.coverage.procedure_comparisons?.total_rollouts);
 if(incomplete.length){const item=make('button',undefined,'research-check');item.type='button';item.append(make('span','COVERAGE','rail-kicker'),make('strong',incomplete.length+' measures have evidence gaps'),make('p','Missing annotations and unresolved opportunities remain unknown.'),make('span','Show coverage gaps →','rail-action'));item.onclick=()=>{$('#monitor-availability').value='missing';$('#monitor-search').value='';$('#monitor-group-filter').value='';renderCards(monitors);$('#monitor-availability').focus();};checks.append(item);}
 const declared=state.declared_populations,cohorts=declared?.cohorts||[],unsettled=cohorts.filter(c=>!c.generation_settled||c.complete_captures<c.declared||c.source_conflicts).length;
 if(unsettled||declared?.truncated){const item=make('button',undefined,'research-check');item.type='button';item.append(make('span','POPULATION','rail-kicker'),make('strong',unsettled+' declared cohorts remain incomplete'),make('p',`${declared.distinct_delivered_rollouts}/${declared.distinct_declared_rollouts} declared rollout identities linked to sources${declared.truncated?' in this bounded view':''}. Open the cohort list for pending and missing rollouts.`),make('span','Inspect declared workload →','rail-action'));item.onclick=()=>{const panel=$('#execution-context .declared-cohorts');panel.open=true;panel.scrollIntoView({block:'start',behavior:'smooth'});};checks.append(item);}
 if(!noStep&&!incomplete.length&&!unsettled&&!declared?.truncated)checks.append(make('p',cohorts.length?'Received sources have training coordinates and current measurements. Declared cohorts are complete.':'Received sources have training coordinates and current measurements. Scheduled workload has not been declared.','rail-note'));
 host.append(checks);const recent=make('div',undefined,'research-rail-group'),head=make('div',undefined,'rail-heading');head.append(make('h2','Recent rollouts'));const all=make('a','View all ↗');all.href='/runs'+query();head.append(all);recent.append(head);
 for(const r of [...state.runs].sort((a,b)=>String(b.imported_at||'').localeCompare(String(a.imported_at||''))).slice(0,4)){const a=make('a',undefined,'rail-run');a.href='/investigate?run='+encodeURIComponent(r.id);a.append(make('strong',short(r.metadata.task_id||r.id,46)),make('small',(r.metadata.environment||'Environment unspecified')+' · '+(r.semantic_graphs?'Semantic map':'Source only')),make('span','Investigate →'));recent.append(a);}host.append(recent);

}
function plot(m,s,coverage=false){
 const host=make('div',undefined,'chart-host'),svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
 svg.setAttribute('role','button');svg.setAttribute('tabindex','0');
 const mode=$('#axis').value,display=coverage?PopulationEvidence.coverageSeries(s):s,points=mode==='step'?display.bins:display.points,known=points.filter(p=>p.value!==null);
 svg.setAttribute('aria-label',(coverage?'Measurement coverage for '+m.name:m.name)+' chart. '+(mode==='step'?'Arrow keys select a training step; Enter opens contributing rollouts.':'Arrow keys select a rollout; Enter opens its map.'));
 const min=Math.min(0,...known.map(p=>p.value)),max=Math.max(...known.map(p=>p.value));
 const low=coverage||m.unit==='fraction'?0:min,top=coverage||m.unit==='fraction'?1:Math.max(max,min+.001);
 const xval=p=>mode==='step'?p.step:p.order,xmin=Math.min(...points.map(xval)),xmax=Math.max(...points.map(xval));
 let width=320,height=160,selected=known.at(-1),cursor;
 const x=v=>48+(width-64)*(v-xmin)/(xmax-xmin||1),y=v=>height-32-(height-46)*(v-low)/(top-low||1);
 const tip=make('div',undefined,'chart-tip');tip.hidden=true;
 const add=(tag,attrs,text)=>{const n=document.createElementNS(svg.namespaceURI,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;svg.append(n);return n;};
 function show(p){selected=p;tip.hidden=false;tip.textContent=(mode==='step'?'Step '+p.step+' · '+p.n+' / '+(p.n+(p.unknown||0))+' rollouts measured':'Rollout '+p.order+' · step '+p.step)+' · '+metricValue(p.value,coverage?{unit:'fraction'}:m)+(!coverage&&m.analysis?.measure==='feedback_reference'?` of decidable responses · ${p.unknown_opportunities||0} unknown / ${p.opportunities||0} captured`:'');cursor.setAttribute('x1',x(xval(p)));cursor.setAttribute('x2',x(xval(p)));cursor.setAttribute('visibility','visible');}
 const open=()=>{if(!selected)return;if(mode==='step')openCases(m,selected.step,null,coverage?'all':null,s);else location.href=mapLink(selected.run_id,m.observer,selected.value_id);};
 function draw(){
  svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.replaceChildren();
  for(const v of [low,(low+top)/2,top]){add('line',{x1:48,x2:width-16,y1:y(v),y2:y(v),class:'grid-line'});add('text',{x:40,y:y(v)+4,'text-anchor':'end'},coverage||m.unit==='fraction'?Math.round(v*100)+'%':v>=1000?(v/1000).toFixed(1)+'k':Number(v.toFixed(2)));}
  let path='',prior=null,rolling=[],smooth='';
  for(const p of points){const gap=prior&&p.step>prior.step+1;if(p.value===null){prior=null;rolling=[];continue;}const command=!prior||gap?'M':'L';if(gap)rolling=[];path+=command+x(xval(p)).toFixed(2)+','+y(p.value).toFixed(2);rolling.push(p.value);if(rolling.length>32)rolling.shift();smooth+=command+x(xval(p)).toFixed(2)+','+y(rolling.reduce((a,b)=>a+b,0)/rolling.length).toFixed(2);prior=p;}
  add('path',{d:path,class:mode==='rollout'?'raw-line':'trend-line'});
  if(mode==='rollout')add('path',{d:smooth,class:'trend-line'});else for(const p of known)add('circle',{cx:x(xval(p)),cy:y(p.value),r:3,fill:'#5b55d6'});
  const ticks=[...new Set((width>600?[0,.25,.5,.75,1]:[0,.5,1]).map(f=>Math.round(xmin+(xmax-xmin)*f)))];
  for(const v of ticks)add('text',{x:x(v),y:height-9,'text-anchor':v===xmin?'start':v===xmax?'end':'middle'},(mode==='step'?'Step ':'#')+v);
  cursor=add('line',{x1:48,x2:48,y1:8,y2:height-30,class:'chart-cursor',visibility:'hidden'});
  const hit=add('rect',{x:45,y:0,width:width-57,height:height-27,class:'hit-area'});
  let drag=null,suppressClick=false,band=null;
  const nearest=e=>{const rect=svg.getBoundingClientRect(),px=(e.clientX-rect.left)/rect.width*width;return points.reduce((best,p)=>Math.abs(x(xval(p))-px)<Math.abs(x(xval(best))-px)?p:best,points[0]);};
  hit.onpointerdown=e=>{if(!e.shiftKey||!points.length)return;e.preventDefault();drag=nearest(e);hit.setPointerCapture(e.pointerId);band=add('rect',{x:x(xval(drag)),y:8,width:0,height:height-38,class:'ii-chart-selection'});};
  hit.onpointermove=e=>{if(!points.length)return;const best=nearest(e);show(best);if(drag&&band){band.setAttribute('x',Math.min(x(xval(drag)),x(xval(best))));band.setAttribute('width',Math.abs(x(xval(drag))-x(xval(best))));}};
  hit.onpointerup=e=>{if(!drag)return;const end=nearest(e),ranges=IntervalInvestigation.range(drag.step,end.step);drag=null;suppressClick=true;band?.remove();hit.releasePointerCapture(e.pointerId);IntervalInvestigation.open({monitors:state.monitors,experiment:s.cohort.experiment,environment:s.cohort.environment,...ranges});};
  hit.onpointercancel=()=>{drag=null;band?.remove();};hit.onclick=()=>{if(suppressClick){suppressClick=false;return;}open();};
  if(!tip.hidden&&selected)show(selected);
 }
 svg.onpointerleave=()=>{tip.hidden=true;cursor.setAttribute('visibility','hidden');};
 svg.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open();}if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const i=points.indexOf(selected),next=e.key==='Home'?0:e.key==='End'?points.length-1:Math.max(0,Math.min(points.length-1,i+(e.key==='ArrowRight'?1:-1)));show(points[next]);}};
 host.append(tip,svg);draw();
 // Match the SVG coordinate system to its rendered box; labels and points must
 // not stretch when a long-run chart occupies a wider card or the window resizes.
 if(typeof ResizeObserver!=='undefined'){
  const resize=new ResizeObserver(entries=>{const r=entries[0].contentRect;if(r.width<100||r.height<60)return;const w=Math.round(r.width),h=Math.round(r.height);if(w===width&&h===height)return;width=w;height=h;draw();});
  resize.observe(svg);host.dispose=()=>resize.disconnect();
 }
 const key=make('div',undefined,'chart-key');key.append(make('span',coverage?'Measured / observed sources · unreported work is unknown':mode==='rollout'?'Rollouts by step · mean of up to 32 display points':['anchor_ratio','opportunity_ratio'].includes(m.aggregation)?'Pooled opportunities per step · gaps remain unknown':'Rollout mean per step · gaps remain unknown'));host.append(key,make('p','Shift-drag to select an interval.','ii-brush-note'));
 host.title=coverage?'Measurement availability, not task outcome. Missing observations are 0 here; they remain missing on the metric curve.':mode==='rollout'?'Rollouts ordered by generation step; within-step order is not completion time. Dark line averages up to 32 display points. Use Training step for order-independent aggregates.':'Select a training step to inspect its contributing rollouts. Fractions use a fixed 0–100% scale. Missing measurements remain gaps.';
 return host;
}
function table(headers){const t=make('table'),head=make('tr');headers.forEach(h=>head.append(make('th',h)));t.append(head);return t;}
function customDefinition(m){return m.custom||m.definition?.custom||(m.kind==='custom'?{description:m.description}:null);}
function observerLabel(m){if(!m.observer||m.observer==='source')return 'Recorded source';if(m.observer_label)return m.observer_label;const lists=[...(options?.observers||[]),...(options?.graph_observers||[])],entry=lists.find(o=>o.id===m.observer);if(entry?.label)return entry.label;return 'Observer not available';}
function monitorDetail(m){const custom=customDefinition(m);return m.description||custom?.description||(m.kind==='analysis'?m.analysis_definition?.label:m.kind==='graph'?m.requirement?.question:options?.metrics?.[m.metric]?.description||options?.metrics?.[m.metric]?.label)||m.metric||human(m.kind||'monitor');}
async function openCustomCodeGuide(){if(view!=='monitors'){location.href='/monitors#custom-code';return;}await openEditor();$('#monitor-kind').value='custom';$('#monitor-group').value='Behavior';configureKind();}
function monitorSetupAction(m,className=''){const custom=customDefinition(m),button=make('button',custom?'Code setup':'Edit',className);button.setAttribute('aria-label',(custom?'Code setup for ':'Edit ')+m.name);button.onclick=()=>custom?openCustomCodeGuide():openEditor(m);return button;}
function renderRegistry(){const host=$('#monitor-table'),priority=m=>!m.enabled?3:(m.feedback_counts?.warning||m.feedback_counts?.critical)?0:m.coverage?.available>0?1:2,rows=filterMonitors(state.monitors).sort((a,b)=>priority(a)-priority(b));$('#registry-count').textContent=`${rows.length} of ${state.monitors.length} monitors`;host.replaceChildren();if(!rows.length){host.append(make('div',$('#registry-search').value?'No monitors match this search.':'No monitors yet.','registry-empty'));return;}
 for(const m of rows){const card=make('article',undefined,'registry-monitor'),identity=make('div',undefined,'registry-monitor-identity'),heading=make('div',undefined,'registry-monitor-heading'),detail=make('p',monitorDetail(m),'registry-monitor-description'),tags=make('div',undefined,'registry-monitor-tags'),coverage=coverageView(m),coverageBox=make('div',undefined,'registry-monitor-coverage'),actions=make('div',undefined,'registry-monitor-actions'),custom=customDefinition(m);
  heading.append(make('h3',m.name));heading.append(make('span',m.enabled?'Enabled':'Paused','status-pill'+(m.enabled?'':' waiting')));identity.append(heading,detail);
  tags.append(make('span',m.group||human(m.kind||'Monitor'),'registry-tag'),make('span',observerLabel(m),'registry-tag'));if(custom)tags.append(make('span','Custom Python','registry-tag registry-tag-custom'));if(m.definition_notice)tags.append(make('span','Historical definition · review rules','registry-tag registry-tag-warning'));identity.append(tags);
  coverageBox.append(make('span',coverage.label,'registry-coverage-label'));if(coverage.denominator!==null&&m.coverage){const denominator=coverage.denominator||0,available=Number.isFinite(m.coverage.available)?m.coverage.available:0,fill=make('span');fill.style.width=(denominator?Math.max(0,Math.min(100,100*available/denominator)):0)+'%';const track=make('div',undefined,'registry-coverage-track');track.append(fill);coverageBox.append(track);}if(coverage.detail)coverageBox.append(make('small',coverage.detail));if(custom&&m.feedback_counts){const counts=['warning','critical'].filter(severity=>Number.isFinite(m.feedback_counts[severity])&&m.feedback_counts[severity]>0).map(severity=>`${m.feedback_counts[severity]} ${severity}`);if(counts.length)coverageBox.append(make('small','Feedback · '+counts.join(' · '),'registry-feedback-counts'));}
  const values=make('button','View values');values.type='button';values.onclick=()=>openCases(m);actions.append(values);
  if(m.enabled){const chart=make('a','Show chart');const q=new URLSearchParams(location.search);q.set('monitor',m.id);chart.href='/?'+q.toString();chart.className='registry-action-link';actions.append(chart);}else{const chart=make('button','Show chart');chart.type='button';chart.disabled=true;chart.title='Resume this monitor to show its chart.';actions.append(chart);}
  const edit=monitorSetupAction(m);actions.append(edit);
  const pause=make('button',m.enabled?'Pause':'Resume');pause.type='button';pause.className=m.enabled?'registry-secondary-action':'';pause.onclick=async()=>{pause.disabled=true;try{await api('/api/monitoring/monitors/'+m.id+'/state',{enabled:!m.enabled});await load();}catch(e){pause.disabled=false;failed(e);}};actions.append(pause);
  card.append(identity,coverageBox,actions);host.append(card);
 }
 if(location.hash==='#custom-code'&&!customGuideHashHandled){customGuideHashHandled=true;openCustomCodeGuide();history.replaceState(null,'',location.pathname+location.search);}
}
const retiredMetricChoices=new Set(['exploration_rate','plan_deviation_rate','recovery_rate','plan_completion_rate']);
function metricChoices(existing=null){return Object.entries(options?.metrics||{}).filter(([id])=>!retiredMetricChoices.has(id)||existing?.metric===id).map(([id,item])=>[id,`${retiredMetricChoices.has(id)?'Earlier definition · ':id==='criterion_recovery'?'Earlier definition · ':''}${item.label||id}`]);}
function catalogEntries(){const found=[];for(const [id,item]of Object.entries(options?.metrics||{}))if(!retiredMetricChoices.has(id))found.push({id,name:item.label||id,description:item.description||'',kind:'metric',item});for(const [id,item]of Object.entries(options?.analysis_measures||{}))found.push({id,name:item.label||id,description:item.description||'',kind:'analysis',item});return found;}
function starterEntries(){const values=options?.starter_catalog||options?.starters||[];return Array.isArray(values)?values:Object.values(values);}
function renderMonitorDiscovery(){const starterHost=$('#monitor-starters'),catalogHost=$('#metric-catalog-results');if(!starterHost||!catalogHost)return;starterHost.replaceChildren();const starters=starterEntries();if(!starters.length)starterHost.append(make('p','No templates available. Select a measure from the catalog below.','field-note'));for(const recipe of starters){const button=make('button',undefined,'starter-recipe'),title=make('strong',recipe.name||recipe.id||'Starter recipe'),description=make('span',recipe.use||recipe.evidence_requirement||'Fills the monitor fields below');button.type='button';button.append(title,description);button.onclick=()=>applyStarterRecipe(recipe);starterHost.append(button);}
 const term=$('#metric-catalog-search').value.trim().toLowerCase(),items=catalogEntries().filter(item=>!term||(item.name+' '+item.id+' '+item.description).toLowerCase().includes(term));catalogHost.replaceChildren();if(!items.length){catalogHost.append(make('p','No measures match this search.','field-note'));return;}for(const item of items){const button=make('button',undefined,'catalog-entry');button.type='button';button.append(make('strong',item.name),make('span',item.description||item.id),make('small',item.kind==='metric'?'Recorded metric':'Analysis measure'));button.onclick=()=>selectCatalogEntry(item);catalogHost.append(button);}
}
function selectCatalogEntry(item){$('#monitor-kind').value=item.kind;$('#monitor-group').value=item.item.group||'Training';configureKind();if(item.kind==='metric'){$('#monitor-metric').value=item.id;$('#metric-description').textContent=item.description;}else{$('#monitor-analysis').value=item.id;configureKind();}if(!editing)$('#monitor-name').value=item.name;}
function applyStarterRecipe(recipe){const definition=recipe.definition||recipe,kind=definition.kind||recipe.kind;if(!['metric','graph','analysis'].includes(kind)){failed(Error('This starter recipe is not supported by the current monitor editor.'));return;}$('#editor-error').hidden=true;$('#editor-error').textContent='';const needsObserver=recipe.observer_requirement==='explicit_observer',requestedObserver=definition.observer||recipe.observer,semanticObservers=(options?.graph_observers||[]).filter(observer=>observer.id&&observer.id!=='source'),selectedObserver=requestedObserver&&requestedObserver!=='source'&&semanticObservers.some(observer=>observer.id===requestedObserver)?requestedObserver:null;$('#monitor-kind').value=kind;$('#monitor-group').value=definition.group||recipe.group||'Behavior';configureKind(selectedObserver);if(definition.name||recipe.name)$('#monitor-name').value=definition.name||recipe.name;
 if(kind==='metric'){const id=definition.metric||recipe.metric;if(id&&options.metrics?.[id]){$('#monitor-metric').value=id;$('#metric-description').textContent=options.metrics[id].description||'';}}
 if(kind==='analysis'){const analysis=definition.analysis?.measure||definition.measure||recipe.measure||recipe.analysis;if(analysis&&options.analysis_measures?.[analysis])$('#monitor-analysis').value=analysis;configureKind(definition.observer||recipe.observer);}
 if(kind==='graph'){const requirement=definition.requirement||definition;if(requirement.question&&requirement.anchor_activity)applyPattern(requirement);}
 if(needsObserver){if(!semanticObservers.length){$('#monitor-observer').replaceChildren(opt('','No saved semantic observer available'));$('#monitor-observer').value='';$('#editor-error').hidden=false;$('#editor-error').textContent='This recipe needs a saved semantic observer, but none is available in this workspace. Choose an observer with saved observations before saving; recorded source cannot satisfy this recipe.';}else if(!$('#monitor-observer').value||$('#monitor-observer').value==='source'){const select=$('#monitor-observer');if(![...select.options].some(option=>option.value===''))select.prepend(opt('','Choose a saved semantic observer'));select.value='';$('#editor-error').hidden=false;$('#editor-error').textContent='This recipe needs a saved semantic observer. Choose one with saved observations before saving.';}}else if(selectedObserver&&[...$('#monitor-observer').options].some(option=>option.value===selectedObserver))$('#monitor-observer').value=selectedObserver;
 const recipePanel=$('#monitor-starters').closest?.('details');if(recipePanel)recipePanel.open=false;
}
function renderRuns(){const search=$('#run-search').value.toLowerCase(),runs=state.runs.filter(r=>(r.id+' '+r.metadata.task_id+' '+r.metadata.environment).toLowerCase().includes(search)).sort((a,b)=>(a.metadata.training_step??Infinity)-(b.metadata.training_step??Infinity)||(a.metadata.source_line??0)-(b.metadata.source_line??0));const size=40;page=Math.min(page,Math.max(0,Math.ceil(runs.length/size)-1));const t=table(['Rollout / task','State','Step','Environment','Map','']);for(const r of runs.slice(page*size,(page+1)*size)){const tr=make('tr'),name=make('td',undefined,'name-cell');name.append(make('strong',short(r.metadata.task_id||r.id,43)),make('small',r.id));tr.append(name,make('td',human(r.state==='imported_snapshot'?'imported':r.state)),make('td',r.metadata.training_step??'—'),make('td',r.metadata.environment||'—'));const maps=make('td');maps.append(make('span',r.semantic_graphs?'Semantic units':'Source only','status-pill'+(r.semantic_graphs?'':' waiting')));const open=make('td'),a=make('a','Open rollout ↗');a.href=mapLink(r.id);const investigate=make('a','Investigate');investigate.href='/investigate?run='+encodeURIComponent(r.id);investigate.style.display='block';investigate.style.marginTop='8px';open.append(a,investigate);tr.append(maps,open);t.append(tr);}$('#run-table').replaceChildren(t);$('#runs-count').textContent=number(runs.length)+' rollouts · '+number(state.runs.filter(r=>r.semantic_graphs).length)+' have semantic maps';$('#prev-runs').disabled=page===0;$('#next-runs').disabled=(page+1)*size>=runs.length;}
async function openCases(m,step=null,exactValue=null,initialFilter=null,series=null){
 const request=++caseRequestSequence;
 caseMonitor=m;caseStep=step;caseExactValue=exactValue;caseCohort=series?.cohort??null;casePage=0;caseRows=[];
 $('#cases-review').hidden=true;$('#cases-export').disabled=true;$('#cases-title').textContent=m.name;
 const scope=exactValue!==null?'Rollouts with value '+metricValue(exactValue,m):step===null?'Per-rollout values and coverage':'Rollouts contributing at training step '+step;
 $('#cases-note').textContent=scope+(series?' · '+cohortLabel(series,m.series):'');
 $('#clear-case-value').hidden=exactValue===null;$('#case-table').textContent='Loading values…';$('#cases-dialog').showModal();
 try{
  const rows=(await api('/api/monitoring/cases/'+m.id+query())).rows;
  if(request!==caseRequestSequence)return;
  // Keep exactly the selected chart cohort, including its unknown measurements.
  // Reviews retain all outcomes in this cohort and step, even when the table is filtered.
  const ids=series?new Set(series.points.map(p=>p.run_id)):null;
  caseRows=ids?rows.filter(r=>ids.has(r.run.id)):rows;
  $('#cases-filter').value=initialFilter||((m.coverage?.available||0)>0?'available':'all');renderCases();$('#cases-export').disabled=false;
  if(m.kind==='analysis'&&m.analysis_definition?.aggregation==='opportunity_ratio'||m.kind==='custom'&&m.custom?.aggregation==='incidence'){
   if(!options)options=await api('/api/monitoring/options');
   if(request===caseRequestSequence){const button=$('#cases-review');button.hidden=!(m.kind==='custom'?options.measurement_review?.custom_aggregation==='incidence':['measurement-review-sample/1','measurement-review-sample/2','measurement-review-sample/3'].includes(options.measurement_review?.version));button.textContent='Review all outcomes';button.title='Sample this cohort and training step, including clear and unresolved results. Value filters do not restrict the review sample.';}
  }
 }catch(e){if(request===caseRequestSequence)$('#case-table').textContent=e.message;}
}
function filteredCases(){return caseRows.filter(r=>(caseExactValue===null||r.measurement?.value===caseExactValue)&&(caseStep===null||r.run.metadata.training_step===caseStep)&&($('#cases-filter').value==='all'||$('#cases-filter').value==='unknown'&&r.measurement?.value==null||$('#cases-filter').value==='available'&&r.measurement?.value!=null||$('#cases-filter').value==='positive'&&r.measurement?.value>0));}
function reviewCases(){return caseRows.filter(r=>caseStep===null||r.run.metadata.training_step===caseStep);}
function addToolEvidence(cell,runId){
 if(!caseMonitor.metric?.startsWith('tool_contract_'))return;
 const observer=caseMonitor.observer,source=cell.querySelector('a');source.textContent='Source rollout ↗';source.href='/source#run='+encodeURIComponent(runId);
 const button=make('button','Schema evidence');button.style.display='block';button.style.marginTop='8px';cell.append(button);
 button.onclick=async()=>{button.disabled=true;try{const check=await api('/api/tool-contracts/'+encodeURIComponent(runId)+'?observer='+encodeURIComponent(observer));const detail=ToolContractEvidence.render(check);detail.open=true;cell.append(detail);button.remove();}catch(error){button.disabled=false;const message=make('p',error.message);message.setAttribute('role','alert');cell.append(message);}};
}
function renderCases(){const rows=filteredCases();casePage=Math.min(casePage,Math.max(0,Math.ceil(rows.length/40)-1));const t=table(['Rollout / task','Step','Value','Evidence / coverage','']);for(const r of rows.slice(casePage*40,(casePage+1)*40)){const tr=make('tr'),name=make('td',undefined,'name-cell');name.append(make('strong',short(r.run.metadata.task_id||r.run.id,43)),make('small',r.run.id));const v=r.measurement,custom=customDefinition(caseMonitor);tr.append(name,make('td',r.run.metadata.training_step??'—'),make('td',custom&&v?.details?.detector?.schema==='reward-detector/1'?({flagged:'Flagged',clear:'Clear',unknown:'Unknown',not_applicable:'Not applicable'}[v.details.detector.status]||'Pending'):metricValue(v?.value,caseMonitor)),make('td',v?.denominator!=null?`${v.numerator} / ${v.denominator} ${caseMonitor.kind==='graph'?'anchors':'decidable opportunities'}${v.unknown!=null?' · '+v.unknown+' unknown':''}`:v?.value!=null?'Source-linked observation':v?.reason||'Materialization pending'));const evidence=tr.children[3],feedback=v?.feedback||v?.details?.feedback||r.feedback;if(custom&&feedback){if(v?.value==null&&evidence.textContent===feedback.summary)evidence.textContent='';const severity=['info','warning','critical'].includes(feedback.severity)?feedback.severity:'info',box=make('section',undefined,'custom-feedback custom-feedback-'+severity);box.append(make('strong',(severity[0].toUpperCase()+severity.slice(1))+': '+(feedback.summary||'Custom monitor feedback')));if(feedback.next_check)box.append(make('p','Next check · '+feedback.next_check));evidence.append(box);}const details=custom?(v?.details??r.details):null;if(details!==null&&details!==undefined){const disclosure=make('details',undefined,'custom-result-details');disclosure.append(make('summary','Result details'),make('pre',typeof details==='string'?details:JSON.stringify(details,null,2)));evidence.append(disclosure);}const cell=make('td'),a=make('a','Open map ↗');a.href=mapLink(r.run.id,caseMonitor.observer,v?.id);const investigate=make('a','Investigate');const investigationQuery=new URLSearchParams({run:r.run.id,observer:caseMonitor.observer,signal:custom?'monitor:'+caseMonitor.id:caseMonitor.kind!=='metric'?'monitor:'+caseMonitor.id:((caseMonitor.metric?.startsWith('reward_')||caseMonitor.metric?.startsWith('environment_')||['actions','agent_text_chars','feedback_link_rate','exact_dispatch_repeat_rate','recorded_success','recorded_reward'].includes(caseMonitor.metric))?'source:':'observation:')+caseMonitor.metric});if(v?.value!=null){investigationQuery.set('operator','eq');investigationQuery.set('threshold',v.value);}investigate.href='/investigate?'+investigationQuery;investigate.style.display='block';investigate.style.marginTop='8px';cell.append(a,investigate);addToolEvidence(cell,r.run.id);if(caseMonitor.metric?.startsWith('reward_')||caseMonitor.metric?.startsWith('environment_tool_error'))cell.append(EvaluationEvidence.button(r.run.id,section=>{const detail=make('tr'),slot=make('td');slot.colSpan=5;slot.append(section);detail.append(slot);tr.after(detail);}));tr.append(cell);t.append(tr);}$('#case-table').replaceChildren(t);$('#case-count').textContent=number(rows.length)+' rollouts';$('#prev-cases').disabled=casePage===0;$('#next-cases').disabled=(casePage+1)*40>=rows.length;}
function configureKind(observer){
 const kind=$('#monitor-kind').value,analysis=kind==='analysis',graph=kind==='graph',spec=options.analysis_measures?.[$('#monitor-analysis').value];
 $('#graph-fields').hidden=!graph;$('#metric-fields').hidden=kind!=='metric';$('#analysis-fields').hidden=!analysis;
 $('#history-query-fields').hidden=!analysis||!spec?.requires_query||spec?.query_kind==='work_return';
 WorkReturnQuery.configure(analysis?spec:null,options);
 const contract=analysis?options.analysis_inputs?.operations?.[spec?.operation]:null;
 const accepted=contract?.accepted||['source','observed'];
 const entries=kind==='custom'?(options.custom_observers||[{id:'source',label:'Recorded source'},...options.graph_observers]):graph?options.graph_observers:analysis?[
  ...(accepted.includes('source')?[{id:'source',label:'Recorded source'}]:[]),
  ...(accepted.includes('observed')?options.graph_observers:[])]:options.observers;
 const preferred=contract?.preferred==='source'?'source':entries.filter(o=>o.id!=='source').length===1?entries.find(o=>o.id!=='source').id:'';
 const selected=entries.some(o=>o.id===observer)?observer:analysis||graph?preferred:entries.some(o=>o.id==='source')?'source':entries[0]?.id||'';
 $('#monitor-observer').replaceChildren(...(!selected?[opt('',entries.length?'Choose evidence observer':'No saved observer available')]:[]),...ChoiceLabels.choices(entries).map(ChoiceLabels.option));
 $('#monitor-observer').value=selected;
 if(analysis&&spec){$('#analysis-description').textContent=spec.description+' '+(contract?.guidance||'This collector does not advertise observer requirements. Choose explicitly; compatibility is checked when saving.');$('#analysis-version').textContent='Pinned definition · '+spec.version+' · saved observations only';}
 configureCustomMode();
}
let previousBuiltInKind='metric';
function selectMonitorMode(mode){
 const current=$('#monitor-kind').value;
 if(mode==='custom'&&current!=='custom')previousBuiltInKind=current;
 $('#monitor-kind').value=mode==='custom'?'custom':previousBuiltInKind;
 configureKind($('#monitor-observer').value);
 showQuestionCheck();
}
function updateCustomScript(){
 const template=$('#custom-monitor-template')?.value||'metric',evaluations=template==='evaluations',reward=template==='reward'||evaluations;
 if($('#custom-reward-fields'))$('#custom-reward-fields').hidden=!reward;
 if($('#custom-recorded-check-fields'))$('#custom-recorded-check-fields').hidden=evaluations;
 if($('#custom-evaluation-fields'))$('#custom-evaluation-fields').hidden=!evaluations;
 if($('#custom-reward-help'))$('#custom-reward-help').textContent=evaluations?'Compare saved evaluator reports for the same rollout and declared inputs. Late reports trigger recalculation. Multiple matches stay unresolved; use producer or code filters to select the intended check.':'Bind the rule to a recorded reward definition. Input paths refer to the normalized rollout. The starter compares reward with a check on the same versioned subject; edit detect() for other rules.';
 const descriptions={metric:'Count recorded agent actions; replace measure() with your analysis.',reward:'Reward crosses the configured threshold while a matched recorded check fails.',evaluations:'Compare reward and evaluator reports on matching task, criterion, artifact and output inputs.'};
 if(Object.values(descriptions).includes($('#custom-monitor-description').value))$('#custom-monitor-description').value=descriptions[template]||descriptions.metric;
 if(reward)$('#monitor-group').value='Reward integrity';
 if($('#custom-callback-help'))$('#custom-callback-help').textContent=evaluations?'Edit detect() to use ctx.evaluations and ctx.compare_evaluations(). Return a status, summary and cited evaluation_ids. Missing or ambiguous comparisons stay unknown.':reward?'Edit detect() for your reward. Return flagged, clear, unknown or not_applicable, a summary, and the input names or graph IDs supporting the finding.':'Replace measure() with your metric; return value or numerator/denominator, evidence IDs, and optional feedback.';
 try{
 $('#custom-monitor-script').textContent=CustomMonitorSetup.script({
  database:$('#custom-monitor-database').value,name:$('#monitor-name').value,
  observer:$('#monitor-observer').value,experiment:$('#custom-monitor-experiment').value,
  version:$('#custom-monitor-version').value,description:$('#custom-monitor-description').value,
  group:$('#monitor-group').value,
  template,rewardDefinition:$('#custom-reward-definition')?.value,definitionPath:$('#custom-reward-definition-path')?.value,
  rewardPath:$('#custom-reward-path')?.value,checkPath:$('#custom-reward-check')?.value,subjectPath:$('#custom-reward-subject')?.value,
  threshold:$('#custom-reward-threshold')?.value,direction:$('#custom-reward-direction')?.value,
  rewardProducer:$('#custom-reward-producer')?.value,checkProducer:$('#custom-check-producer')?.value,
 });
 $('#custom-monitor-status').textContent='';
 $('#copy-custom-monitor').disabled=$('#download-custom-monitor').disabled=false;
 }catch(error){$('#custom-monitor-script').textContent='';$('#custom-monitor-status').textContent=error.message;$('#copy-custom-monitor').disabled=$('#download-custom-monitor').disabled=true;}
}
function configureCustomMode(){
 const custom=$('#monitor-kind').value==='custom';
 if(!custom)previousBuiltInKind=$('#monitor-kind').value;
 $('#monitor-mode-builtin').setAttribute('aria-pressed',String(!custom));
 $('#monitor-mode-code').setAttribute('aria-pressed',String(custom));
 $('#monitor-kind-field').hidden=custom;
 $('#monitor-type-fields').classList.toggle('code-mode',custom);
 $('#editor-custom-guide').hidden=!custom;$('#monitor-discovery').hidden=custom;
 $('#save-monitor').hidden=custom;$('#save-monitor').disabled=custom;
 $('#monitor-population').hidden=custom||!options?.question_setup;
 $('#question-starts').hidden=custom||!options?.question_setup||!!editing;
 $('#monitor-save-note').textContent=custom?'Run the Python script to register and publish this monitor.':'Saved in the workspace database';
 if(custom){
  if(!$('#custom-monitor-database').value)$('#custom-monitor-database').value=options?.custom_setup?.database||'workspace.sqlite';
  updateCustomScript();
 }
}
async function copyCustomMonitor(){
 try{await navigator.clipboard.writeText($('#custom-monitor-script').textContent);$('#custom-monitor-status').textContent='Python copied';}
 catch{$('#custom-monitor-status').textContent='Clipboard unavailable. Download the script or select the code.';}
}
function downloadCustomMonitor(){
 const url=URL.createObjectURL(new Blob([$('#custom-monitor-script').textContent],{type:'text/x-python;charset=utf-8'}));
 const link=make('a');link.href=url;link.download='custom_monitor.py';link.click();
 setTimeout(()=>URL.revokeObjectURL(url),1000);$('#custom-monitor-status').textContent='Script downloaded. Run it to register the monitor.';
}
$('#copy-custom-monitor').onclick=copyCustomMonitor;$('#download-custom-monitor').onclick=downloadCustomMonitor;
$('#monitor-mode-builtin').onclick=()=>selectMonitorMode('builtin');
$('#monitor-mode-code').onclick=()=>selectMonitorMode('custom');
$('#monitor-form').addEventListener('input',()=>{if($('#monitor-kind').value==='custom')updateCustomScript();});
$('#monitor-form').addEventListener('change',()=>{if($('#monitor-kind').value==='custom')updateCustomScript();});
function applyPattern(q){$('#monitor-question').value=q.question;$('#monitor-anchor').value=q.anchor_activity;$('#monitor-relation').value=q.relation;$('#monitor-window').value=q.within_units;$('#monitor-novelty').checked=q.require_new_exploration;const p=q.evidence_path;$('#monitor-connection').value=p?.start==='relation_target'?'feedback':p?.hops?.length===2?'used-feedback':p||q.require_evidence_link?'direct':'none';}
async function openEditor(m=null){if(!options)options=await api('/api/monitoring/options');editing=m;$('#editor-error').hidden=true;$('#editor-title').textContent=m?'Edit monitor':'Add monitor';$('#custom-monitor-template').value='metric';$('#monitor-name').value=m?.name||'';$('#monitor-kind').value=m?.kind||'metric';$('#monitor-group').value=m?.group||'Training';$('#monitor-analysis').replaceChildren(...Object.entries(options.analysis_measures||{}).map(([id,v])=>opt(id,(id==='criterion_recovery'?'Earlier definition · ':'')+v.label)));$('#monitor-analysis').value=m?.analysis?.measure||'returns';$('#monitor-history-query').value=m?.analysis?.query?JSON.stringify(m.analysis.query,null,2):'';configureKind(m?.observer);$('#monitor-metric').replaceChildren(...metricChoices(m).map(([id,label])=>opt(id,label)));$('#monitor-metric').value=m?.metric||'recorded_reward';$('#metric-description').textContent=options.metrics[$('#monitor-metric').value]?.description||'';
 $('#monitor-preset').replaceChildren(...Object.entries(options.presets).map(([id,q])=>opt(id,q.question)));$('#monitor-preset').value='assessment_of_inspection_feedback';$('#monitor-anchor').replaceChildren(...[...new Set(['inspect',...options.activities])].map(v=>opt(v,human(v))));$('#monitor-relation').replaceChildren(...[...new Set(['assesses','revises',...options.relations])].map(v=>opt(v,human(v))));applyPattern(m?.requirement||options.presets.assessment_of_inspection_feedback);initQuestionSetup(m);renderMonitorDiscovery();let notice=$('#editor-definition-notice');if(!notice){notice=make('p',undefined,'definition-notice');notice.id='editor-definition-notice';$('#editor-title').after(notice);}notice.hidden=!m?.definition_notice;notice.textContent=m?.definition_notice?'Saving uses the current comparison rules and pauses this historical monitor. Its saved values and evidence remain available.':'';$('#monitor-dialog').showModal();$('#monitor-dialog').scrollTop=0;}
function unscopedMonitorDefinition(){if($('#monitor-kind').value==='custom')throw Error('Run the generated Python script to register and publish this code monitor.');const d={name:$('#monitor-name').value,kind:$('#monitor-kind').value,observer:$('#monitor-observer').value,group:$('#monitor-group').value};if(d.kind==='metric')d.metric=$('#monitor-metric').value;else if(d.kind==='analysis'){const spec=options.analysis_measures[$('#monitor-analysis').value];d.analysis={measure:$('#monitor-analysis').value,version:spec.version};if(spec.query_kind==='work_return'){d.analysis.query=WorkReturnQuery.definition(d.name);}else if(spec.requires_query){try{d.analysis.query=JSON.parse($('#monitor-history-query').value);}catch{throw Error('Provide a valid JSON history query, or load the example and adapt its fields.');}}}else{const connection=$('#monitor-connection').value,hop=(...relations)=>({direction:'outgoing',relations});const evidence_path=connection==='none'?null:connection==='feedback'?{start:'relation_target',hops:[hop('feedback_for')]}:connection==='used-feedback'?{start:'relation_source',hops:[hop('uses_evidence','responds_to'),hop('feedback_for')]}:{start:'relation_source',hops:[hop('uses_evidence','responds_to')]};d.requirement={schema:'graph-requirement/2',question:$('#monitor-question').value,anchor_activity:$('#monitor-anchor').value,relation:$('#monitor-relation').value,within_units:Number($('#monitor-window').value),require_new_exploration:$('#monitor-novelty').checked,evidence_path};}return d;}
$('#monitor-form').onsubmit=async e=>{e.preventDefault();try{const saved=await api('/api/monitoring/monitors',{definition:monitorDefinition(),replace:editing?.id});const url=new URL(location.href);if(editing&&url.searchParams.get('monitor')===editing.id&&saved.id){url.searchParams.set('monitor',saved.id);}url.searchParams.delete('create_measure');history.replaceState(null,'',url.pathname+url.search);$('#monitor-dialog').close();await load();}catch(error){$('#editor-error').hidden=false;$('#editor-error').textContent=error.message;}};
$('#monitor-kind').onchange=()=>{configureKind();if(['graph','analysis'].includes($('#monitor-kind').value)){$('#monitor-group').value='Behavior';if(!$('#monitor-name').value)$('#monitor-name').value=$('#monitor-kind').value==='analysis'?options.analysis_measures[$('#monitor-analysis').value].label:'Inspection feedback assessed';}};
$('#monitor-analysis').onchange=()=>{configureKind($('#monitor-observer').value);if(!editing)$('#monitor-name').value=options.analysis_measures[$('#monitor-analysis').value].label;};
$('#history-query-example').onclick=()=>{const q={schema:'history-evidence-query/1',name:'Exchanged order was recorded as delivered',target:{tools:['exchange_delivered_order_items'],values:'/order_id'},history:{tools:['get_order_details'],bindings:[{target:'/order_id',history:'/order_id'}],result_bindings:[{target:'/order_id',result:'/order_id'}]},rows:'',key:'/order_id',checks:[{pointer:'/status',equals:'delivered'}],quantifier:'all',invalidate_on:[]};$('#monitor-history-query').value=JSON.stringify(q,null,2);if(!editing)$('#monitor-name').value=q.name;};
$('#monitor-preset').onchange=()=>applyPattern(options.presets[$('#monitor-preset').value]);$('#monitor-metric').onchange=()=>{$('#metric-description').textContent=options.metrics[$('#monitor-metric').value].description;if(!$('#monitor-name').value)$('#monitor-name').value=options.metrics[$('#monitor-metric').value].label;};
$('#reward-checks').ontoggle=()=>{if($('#reward-checks').open)RewardChecks.render($('#reward-check-options'),{
 api,scope:()=>{const population={};for(const key of ['experiment','environment','split']){const value=$('#'+key)?.value;if(value)population[key]=value;}return population;},
 onChange:()=>load(),onCustom:async()=>{await openEditor();$('#custom-monitor-template').value='reward';$('#monitor-name').value='Reward / check disagreement';$('#custom-monitor-description').value='Reward crosses the configured threshold while a matched recorded check fails.';$('#monitor-group').value='Reward integrity';selectMonitorMode('custom');}
});};
$('#registry-search').oninput=()=>{if(state)renderRegistry();};$('#metric-catalog-search').oninput=renderMonitorDiscovery;$('#registry-code-help').onclick=openCustomCodeGuide;
$('#monitor-observer').onchange=()=>{const error=$('#editor-error');if($('#monitor-observer').value&&$('#monitor-observer').value!=='source'&&error.textContent.startsWith('This recipe needs a saved semantic observer')){error.hidden=true;error.textContent='';}};
async function addCoreMonitors(){const button=$('#add-core-monitors');button.disabled=true;$('#registry-feedback').textContent='Adding source-backed core monitors…';try{const result=await api('/api/monitoring/starters',{});await load();$('#registry-feedback').textContent=`${number(result.added?.length||0)} added · ${number(result.existing?.length||0)} already present`;}catch(error){$('#registry-feedback').textContent='';failed(error);}finally{button.disabled=false;}}
$('#add-core-monitors').onclick=addCoreMonitors;
$('#clear-case-value').onclick=()=>{caseExactValue=null;casePage=0;$('#clear-case-value').hidden=true;$('#cases-note').textContent='Per-rollout values and coverage';renderCases();};
function openWindowComparison(monitor){MonitorComparisons.open({monitors:state.monitors,experiments:state.experiments,experiment:$('#experiment').value,environment:$('#environment').value,monitor});}
$('#compare-windows').onclick=()=>openWindowComparison();
$('#add-monitor').onclick=()=>openEditor();$('#close-editor').onclick=()=>$('#monitor-dialog').close();$('#monitor-dialog').addEventListener('close',()=>pulse());$('#close-cases').onclick=()=>$('#cases-dialog').close();$('#cases-filter').onchange=()=>{casePage=0;renderCases();};$('#prev-cases').onclick=()=>{casePage--;renderCases();};$('#next-cases').onclick=()=>{casePage++;renderCases();};$('#cases-export').onclick=()=>download({monitor:caseMonitor,scope:{experiment:$('#experiment').value,environment:$('#environment').value,step:caseStep,cohort:caseCohort,exact_value:caseExactValue,filter:$('#cases-filter').value},rows:filteredCases()},'monitor-values.json');
$('#experiment').onchange=()=>{sessionStorage.setItem('monitor-experiment',$('#experiment').value);page=0;load();};$('#environment').onchange=()=>{page=0;load();};$('#axis').onchange=()=>{if(state)renderCards(state.monitors.filter(m=>m.enabled));};$('#refresh').onclick=()=>load();$('#run-search').oninput=()=>{page=0;renderRuns();};$('#prev-runs').onclick=()=>{page--;renderRuns();};$('#next-runs').onclick=()=>{page++;renderRuns();};
async function pulse(){if(busy||document.hidden)return;busy=true;try{const s=await api('/api/monitoring/status');status(s);if((s.revision!==revision||state?.service?.snapshot_stale)&&!$('#monitor-dialog').open){await load();revision=state?.service?.revision;}}catch(e){status({running:false});}finally{busy=false;}}
(async()=>{await load(true);const savedComparison=new URLSearchParams(location.search).get('comparison');if(savedComparison)MonitorComparisons.openSaved(savedComparison,{monitors:state.monitors,experiments:state.experiments,experiment:$('#experiment').value,environment:$('#environment').value});const draft=new URLSearchParams(location.search);if(view==='monitors'&&draft.has('create_measure')){const key=draft.get('create_measure');if(!options)options=await api('/api/monitoring/options');if(options.analysis_measures?.[key]){await openEditor();$('#monitor-kind').value='analysis';$('#monitor-group').value='Behavior';$('#monitor-analysis').value=key;configureKind(draft.get('observer')||undefined);$('#monitor-name').value=options.analysis_measures[key].label;}}revision=state?.service?.revision;let trainingRevision=window.trackerLive?.training_revision,source=window.trackerLive?.source_revision,execution=window.trackerLive?.execution_revision,cohort=window.trackerLive?.cohort_revision,semantic=window.trackerLive?.semantic_revision,observedRevision=revision,wasUpdating=false;window.addEventListener('tracker-live',async e=>{const s=e.detail,a=s.analysis;if(!a)return;status(a);const changed=s.training_revision!==trainingRevision||s.source_revision!==source||s.execution_revision!==execution||s.cohort_revision!==cohort||s.semantic_revision!==semantic||a.revision!==observedRevision||wasUpdating&&!a.updating;wasUpdating=a.updating;if(!changed||busy||document.hidden||$('#monitor-dialog').open)return;trainingRevision=s.training_revision;source=s.source_revision;execution=s.execution_revision;cohort=s.cohort_revision;semantic=s.semantic_revision;observedRevision=a.revision;busy=true;try{await load();revision=state?.service?.revision;}finally{busy=false;}});window.addEventListener('tracker-disconnected',()=>status(state?.service||{}));setInterval(pulse,30000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)pulse();});})();

// Setup reuses the ordinary monitor definition and frozen observer selection.
$('#check-question').onclick=()=>checkQuestion();
$('#monitor-form').addEventListener('input',()=>{invalidateQuestionCheck();showQuestionCheck();});
$('#monitor-form').addEventListener('change',()=>{invalidateQuestionCheck();showQuestionCheck();});
$('#close-editor').addEventListener('click',invalidateQuestionCheck);
$('#history-query-example').addEventListener('click',invalidateQuestionCheck);
function startFeedbackQuestion(all){
 $('#monitor-kind').value=all?'analysis':'graph';$('#monitor-group').value='Behavior';
 $('#monitor-analysis').value='feedback_reference';configureKind();
 if(!all)applyPattern(options.presets.assessment_of_inspection_feedback);
 $('#monitor-name').value=all?'Explicit feedback reference':'Inspection feedback assessed';
 invalidateQuestionCheck();showQuestionCheck();
}
$('#start-inspection-question').onclick=()=>startFeedbackQuestion(false);
$('#start-feedback-question').onclick=()=>startFeedbackQuestion(true);
$('#start-work-question').onclick=()=>{
 $('#monitor-kind').value='analysis';$('#monitor-group').value='Behavior';$('#monitor-analysis').value='work_switch_return_fraction_parallel';
 configureKind(options.graph_observers.find(o=>o.id.startsWith('work-subjects-'))?.id);
 $('#monitor-name').value='Return share among observed work switches';invalidateQuestionCheck();showQuestionCheck();
};
$('#start-return-reference-question').onclick=()=>{
 $('#monitor-kind').value='analysis';$('#monitor-group').value='Behavior';$('#monitor-analysis').value='work_return_references_parallel';
 WorkReturnQuery.reset(null);configureKind(options.graph_observers.find(o=>o.id.startsWith('work-subjects-'))?.id);
 $('#monitor-name').value='Returns revising earlier work';invalidateQuestionCheck();showQuestionCheck();
};
window.addEventListener('tracker-live',e=>{if($('#monitor-dialog').open&&questionCheckReceipt&&questionCheckLiveRevision!==questionLiveRevision(e.detail)){invalidateQuestionCheck();$('#question-check-result').textContent='Source or analysis state changed. Check evidence again for a current receipt.';}});

$('#cases-review').onclick=async()=>{const b=$('#cases-review');b.disabled=true;try{const run_ids=reviewCases().map(r=>r.run.id);const result=await api('/api/measurement-reviews',{monitor_id:caseMonitor.id,run_ids,size:20,seed:'initial-review'});location.href='/measurement-review?sample='+encodeURIComponent(result.id);}catch(e){$('#cases-note').textContent=e.message;}finally{b.disabled=false;}};
