'use strict';
const $=s=>document.querySelector(s),el=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};let report=null,loadSequence=0,rowPage=0,evidenceSequence=0;const pageSize=50;
const display=v=>v===null?'Unavailable':Number.isInteger(v)?String(v):v.toFixed(3);
const initial=new URLSearchParams(location.search);
const isIndicator=metric=>report?.definitions[metric]?.aggregation==='incidence';
let binMeasurementIds=null;
function clearBin(){binMeasurementIds=null;$('#bin-selection').hidden=true;$('#clear-bin').hidden=true;rowPage=0;}
function selectBin(cohort,b){binMeasurementIds=new Set(cohort.points.filter(p=>p.training_step>=b.start&&p.training_step<=b.end).map(p=>p.measurement_id));rowPage=0;$('#bin-selection').textContent='Selected steps '+b.start+'–'+b.end+' · '+binMeasurementIds.size+' contributing measured rollouts. Search applies within this selection. Export measurements retains the full report.';$('#bin-selection').hidden=false;$('#clear-bin').hidden=false;rows();$('#row-status').scrollIntoView({block:'center',behavior:'smooth'});}
function rewardEvidence(row,open=false){
 const detail=el('details'),body=el('div');detail.className='operation-evidence';detail.append(el('summary','Recorded reward feedback and rubric components'),body);let loaded=false;
 detail.ontoggle=async()=>{if(!detail.open||loaded)return;loaded=true;body.textContent='Loading evaluator feedback…';try{
  const response=await fetch('/api/reward-records/'+encodeURIComponent(row.run_id)),data=await response.json();if(!response.ok)throw Error(data.error||'Cannot load reward feedback');
  if(data.source_hash!==row.source_hash)throw Error('Source changed; refresh measurements before inspecting feedback.');
  body.replaceChildren(el('p',data.limits),el('small',data.protocol+' · '+data.status));
  if(data.counts)body.append(el('p',data.counts.known_verdicts+' known judgments / '+data.counts.criteria+' criteria · '+data.counts.unknown_verdicts+' unknown'));
  for(const issue of data.issues)body.append(el('p',issue.code.replaceAll('_',' ')+': '+issue.note+' ('+issue.pointer+')'));
  for(const [key,m]of Object.entries(data.metrics)){if(m.value!==null)body.append(el('p',report.definitions[key].label+': '+display(m.value)+(m.denominator!==null?' ('+m.numerator+' / '+m.denominator+')':'')));}
  if(data.calculation)body.append(el('p','Unclipped signed rubric score: '+display(data.calculation.rubric_score)+'. Producer reward transformations are not inferred.'));
  for(const category of data.categories){const box=el('details');box.append(el('summary',category.category+' · '+category.criteria+' criteria'),el('p','Positive credit: '+display(category.positive_met_weight)+' / '+category.positive_weight+' · Penalty weight: '+display(category.penalty_met_weight)));
   for(const criterion of data.criteria.filter(c=>(c.category||'Uncategorized')===category.category)){const item=el('details');item.append(el('summary',criterion.id+' · weight '+criterion.weight+' · '+(criterion.met===null?'Unknown':criterion.met?'Recorded met':'Recorded not met')),el('p',criterion.description),el('small',criterion.source_reference+' · '+(criterion.verdict_reference||'No recorded verdict')));box.append(item);}body.append(box);}
  const raw=el('details');raw.append(el('summary','Original evaluator fields · outside agent-visible trace'),el('pre',JSON.stringify(data.source_fields,null,2)));body.append(raw);
 }catch(e){body.textContent=e.message;loaded=false;}};
 detail.open=open;return detail;
}
function diagnosticEvidence(result){
 const detail=el('details');detail.className='operation-evidence';detail.append(el('summary','Diagnostic evidence · experimental source monitor'));
 detail.append(el('p','Raw Jev maximum selections; no confidence threshold. These are behavior indicators, not confirmed reward hacking.'),el('small',result.protocol.id+' · source '+result.source_hash));
 for(const [key,m] of Object.entries(result.metrics)){
  const item=el('details');item.append(el('summary',result.protocol.detectors[key][0]+': '+display(m.value)));
  item.append(el('p','Selected: '+m.selection+' · '+(m.reason||'Evidence available')),el('p',result.protocol.detectors[key][1]));
  if(m.evidence_verdict)item.append(el('p','Evidence-chain check: '+m.evidence_verdict.replaceAll('_',' ')));
  if(m.mechanism_selection)item.append(el('p','Evaluation mechanism: '+m.mechanism_selection.replaceAll('_',' ')));
  if(m.source_order_established!==null&&m.source_order_established!==undefined)item.append(el('p','Returned material precedes incorporation: '+(m.source_order_established?'yes':'not established')));
  if(m.evidence_roles){
   const chain=el('div');chain.className='diagnostic-chain';
   const roles=Object.entries(m.evidence_roles).sort((a,b)=>{const x=a[1],y=b[1];if(!x||!y)return Number(!x)-Number(!y);if(x.origin!==y.origin)return x.origin==='task'?-1:1;return x.start-y.start;});
   if(roles.length>1)item.append(el('p',roles.map(([role])=>role.replaceAll('_',' ')).join(' → ')));
   for(const [role,reference]of roles){
    const card=el('div');card.className='diagnostic-evidence-card';card.append(el('strong',role.replaceAll('_',' ')));
    if(reference){card.append(el('small',reference.origin+' · characters '+reference.start+'–'+reference.end+' · '+reference.id+(reference.event_id?' · event '+reference.event_id:'')),el('pre',reference.text));}
    else card.append(el('p','No adequate source anchor selected.'));
    chain.append(card);
   }item.append(chain);
  }
  if(m.evidence)item.append(el('small','Supplied trace characters '+m.evidence.start+'–'+m.evidence.end+' · '+m.evidence.id),el('pre',m.evidence.text));
  item.append(el('small','Decision '+result.request_hash+' · evidence decision '+(result.roles_request_hash||result.anchor_request_hash||'none')+(result.validation_request_hash?' · validation '+result.validation_request_hash:'')));detail.append(item);
 }
 detail.append(el('p',result.confirmed_reward_hacking.reason));return detail;
}
function operationEvidence(id){
 const detail=el('details'),body=el('div');detail.className='operation-evidence';detail.append(el('summary','Recorded operation outcomes'),body);let loaded=false;
 detail.ontoggle=async()=>{if(!detail.open||loaded)return;loaded=true;body.textContent='Loading recorded evidence…';try{
  const response=await fetch('/api/operation-observations/'+encodeURIComponent(id)),data=await response.json();if(!response.ok)throw Error(data.error||'Unable to load operation evidence');body.replaceChildren();
  body.append(el('p',data.validation),el('small','Protocol '+data.protocol.id));
  if(data.actions_without_observed_response?.length)body.append(el('p','Actions without an inspected source-bound response: '+data.actions_without_observed_response.join(', ')+'. These actions are outside the operation-outcome denominator.'));
  if(data.projection_note)body.append(el('p',data.projection_note));
  for(const [aid,aggregate]of Object.entries(data.action_outcomes).sort(([a],[b])=>data.actions[a].index-data.actions[b].index)){
   const action=data.actions[aid],card=el('details');card.append(el('summary',aid+' · '+aggregate.outcome.replaceAll('_',' ')));
   card.append(el('p','Dispatch · '+(action.tool||'operation')),el('pre',action.text));
   for(const observation of aggregate.observations){
    card.append(el('p',observation.response_event_id+' · selected '+observation.selected_option+' · '+(observation.complete_readable_response&&observation.complete_readable_dispatch?'Complete readable dispatch and response':'Incomplete readable evidence; excluded from whole-call outcome')));
    for(const evidence of observation.evidence){card.append(el('small',evidence.event_id+' · source offsets '+evidence.start+'–'+evidence.end),el('pre',evidence.text));}
    card.append(el('small','Decision '+observation.request_hash));
   }body.append(card);
  }
 }catch(e){body.textContent=e.message;loaded=false;}};return detail;
}
function updateURL(){const p=new URLSearchParams({observer:$('#observer').value,metric:$('#metric').value,bin_width:$('#bin-width').value});if($('#search').value)p.set('run',$('#search').value);history.replaceState(null,'','/rollouts?'+p);}
function monitoringCoverage(observer){
 const populations=(report.diagnostic_monitoring||[]).filter(p=>p.observer===observer),host=$('#monitoring-populations');$('#monitoring').hidden=!populations.length;host.replaceChildren();
 for(const p of populations){
  const card=el('div');card.className='monitor-population';const selection=p.selection;
  card.append(el('h3',selection.kind==='explicit_latest'?'Selected rollouts':'Latest rollout imports'),el('p',p.population+' sources in scope · '+p.eligible+' eligible for inspection'));
  if(selection.experiment||selection.adapters?.length)card.append(el('p',[selection.experiment,...(selection.adapters||[])].filter(Boolean).join(' · ')));
  card.append(el('p',Object.entries(p.counts).map(([k,n])=>n+' '+k.replaceAll('_',' ')).join(' · ')),el('small','Last scan '+p.last_scanned_at+' · '+p.worker_id));
  const reasons=new Map();for(const r of p.rows){if(r.reason)reasons.set(r.reason,(reasons.get(r.reason)||0)+1);}for(const [reason,n]of reasons)card.append(el('p',n+' · '+reason));
  const unresolved=p.rows.filter(r=>r.eligibility==='ready'&&r.status!=='complete');
  if(unresolved.length){const details=el('details');details.append(el('summary','Pending or failed inspections ('+unresolved.length+')'));
   for(const r of unresolved.slice(0,30)){const row=el('p'),a=el('a',r.task_id||r.run_id);a.href='/#run='+encodeURIComponent(r.run_id);row.append(a,document.createTextNode(' · '+r.status+(r.attempt?.http_status?' · HTTP '+r.attempt.http_status:r.attempt?.error_type?' · '+r.attempt.error_type:'')));details.append(row);}
   if(unresolved.length>30)details.append(el('small','First 30 shown; export measurements for the full population.'));card.append(details);
  }host.append(card);
 }
}
async function inspectRollout(r){
 const sequence=++evidenceSequence,host=$('#selected-rollout');host.hidden=false;host.replaceChildren(el('h2','Selected rollout'),el('p','Loading source…'));host.scrollIntoView({block:'start'});
 try{const response=await fetch('/api/runs/'+encodeURIComponent(r.run_id)),data=await response.json();if(sequence!==evidenceSequence)return;if(!response.ok)throw Error(data.error||'Cannot load rollout');const run=data.run;host.replaceChildren(el('h2','Selected rollout'));
  const close=el('button','Close');close.onclick=()=>{evidenceSequence++;host.hidden=true;};host.append(close,el('p',r.rollout_id+' · logged iteration '+(r.metadata.training_step??'unrecorded')),el('p','Generating policy: '+(r.metadata.policy_version||r.metadata.checkpoint||'not recorded')));
  const selectedMetric=$('#metric').value;host.append(el('p',report.definitions[selectedMetric].label+': '+display(r.metrics[selectedMetric].value)));
  if(r.metadata.source_line)host.append(el('p','Source line '+r.metadata.source_line+' · file SHA-256 '+r.metadata.source_file_sha256));
  host.append(el('small','Normalized source hash '+r.source_hash));
  if(r.metadata.source_uri){const link=el('a','Published source file');if(/^https?:\/\//.test(r.metadata.source_uri)){link.href=r.metadata.source_uri;host.append(link);}}
  if(r.metadata.reward_definition)host.append(el('p','Reward: '+r.metadata.reward_definition));
  const graphLink=el('a','Inspect stored rollout relationships →');graphLink.href='/relations?run='+encodeURIComponent(r.run_id);host.append(graphLink);
  if(r.diagnostic_result)host.append(diagnosticEvidence(r.diagnostic_result));
  if(r.reward_inspection_protocol)host.append(rewardEvidence(r,selectedMetric.startsWith('reward_')));
  for(const e of run.events){const item=el('details');item.open=e.actor==='agent';item.append(el('summary',e.actor+' · '+e.kind+' · '+e.source_pointer),el('pre',e.text));host.append(item);}
  for(const warning of run.warnings||[])host.append(el('small',warning));
 }catch(e){if(sequence===evidenceSequence)host.append(el('p',e.message));}
}
function chart(cohort,metric){
 const host=el('div');host.className='cohort';const c=cohort.cohort;host.append(el('h3',[c.experiment,c.environment,c.environment_version,c.split].filter(Boolean).join(' · ')));
 if(c.source_selection){const s=c.source_selection;host.append(el('p',`${s.kind||'Source selection'}${s.steps?' · iterations '+s.steps.join(', '):''}. ${s.note||''}`));}
 if(c.training_step_basis==='source_logged_iteration')host.append(el('small','X axis: source-logged training iteration. Exact generating-policy version is unrecorded.'));
 host.append(el('h4',report.definitions[metric].label));
 const ns='http://www.w3.org/2000/svg',make=(t,a={})=>{const e=document.createElementNS(ns,t);for(const[k,v]of Object.entries(a))e.setAttribute(k,v);return e;};
 const svg=make('svg',{viewBox:'0 0 1020 340',class:'trend-plot',role:'img','aria-label':'Individual rollout measurements over training steps'}),pts=cohort.points;
 const showIndividuals=$('#show-rollouts').checked,rateOnly=isIndicator(metric)&&!showIndividuals,ys=rateOnly?cohort.bins.map(b=>b.mean):pts.map(p=>p.value);
 const xmin=Math.min(...pts.map(p=>p.training_step)),xmax=Math.max(...pts.map(p=>p.training_step)),ymin=Math.min(0,...ys),ymax=rateOnly?Math.max(.05,...ys.map(v=>v*1.15)):Math.max(1,...ys);
 const x=v=>70+(v-xmin)/(xmax-xmin||1)*890,y=v=>280-(v-ymin)/(ymax-ymin||1)*240;
 for(let i=0;i<=4;i++){const value=ymin+(ymax-ymin)*i/4,Y=y(value);svg.append(make('line',{x1:70,x2:960,y1:Y,y2:Y,stroke:'#e3eaed'}));const t=make('text',{x:58,y:Y+4,'text-anchor':'end'});t.textContent=rateOnly?(value*100).toFixed(1)+'%':display(value);svg.append(t);}
 for(const [value,anchor]of [[xmin,'start'],[xmax,'end']]){const t=make('text',{x:x(value),y:307,'text-anchor':anchor});t.textContent='Step '+value;svg.append(t);}
 let lastTick=xmin;for(const step of [...new Set(pts.map(p=>p.training_step))].sort((a,b)=>a-b)){if(x(step)-x(lastTick)>=65&&x(xmax)-x(step)>=65){const t=make('text',{x:x(step),y:307,'text-anchor':'middle'});t.textContent='Step '+step;svg.append(t);lastTick=step;}}
 const bins=cohort.bins;const center=b=>Math.min(xmax,Math.max(xmin,(b.start+b.end)/2)),diagnostic=isIndicator(metric),stat=b=>diagnostic?b.mean:b.median;
 const segments=[];for(const b of bins){if(!segments.length||b.start>segments.at(-1).at(-1).end+1)segments.push([]);segments.at(-1).push(b);}
 for(const segment of segments){if(segment.length>1){if(!diagnostic){const top=segment.map(b=>`${x(center(b))},${y(b.p90)}`),bottom=[...segment].reverse().map(b=>`${x(center(b))},${y(b.p10)}`);svg.append(make('polygon',{points:top.concat(bottom).join(' '),fill:'#dceeee'}));}svg.append(make('polyline',{points:segment.map(b=>`${x(center(b))},${y(stat(b))}`).join(' '),fill:'none',stroke:'#215e65','stroke-width':2}));}}
 if(showIndividuals)for(const p of pts){const dot=make('circle',{cx:x(p.training_step),cy:y(p.value),r:3,tabindex:0,role:'button','aria-label':`${p.task_id||p.rollout_id}, training step ${p.training_step}, ${metric}: ${display(p.value)}`});const title=make('title');title.textContent=`${p.rollout_id}\nStep ${p.training_step} · ${display(p.value)}\nTask ${p.task_id||'missing'}`;dot.append(title);dot.onclick=()=>{const r=report.rows.find(r=>r.measurement_id===p.measurement_id);if(r)inspectRollout(r);};dot.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();dot.onclick();}};svg.append(dot);}
 for(const b of bins){const X=x(center(b));if(!diagnostic)svg.append(make('line',{x1:X,x2:X,y1:y(b.p10),y2:y(b.p90),stroke:'#193d47','stroke-width':2,'pointer-events':'none'}));const mark=make('circle',{cx:X,cy:y(stat(b)),r:5,tabindex:0,role:'button','aria-label':'Inspect contributing rollouts at steps '+b.start+'–'+b.end});mark.style.fill='#b7711c';mark.style.opacity='1';const tip=make('title');tip.textContent='Steps '+b.start+'–'+b.end+' · '+(diagnostic?b.positive+' / '+b.n+' = '+(100*b.mean).toFixed(1)+'%':'median '+display(b.median))+' · '+b.unknown+' unknown';mark.append(tip);mark.onclick=()=>selectBin(cohort,b);mark.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();mark.onclick();}};svg.append(mark);}
 host.append(svg);const stats=el('p',`${pts.length} rollouts · ${bins.length} bins · bin counts ${bins.map(b=>b.n).join(', ')}. ${diagnostic?'Orange marks show positive / decidable incidence. Unknown counts in these bins: '+bins.map(b=>b.unknown).join(', ')+'. ':''}Task mix is included in the exported bin records.`);stats.className='muted';host.append(stats);
 if(diagnostic){const table=el('table'),head=el('tr');for(const label of ['Training steps','Positive','Decidable','Unknown','Incidence'])head.append(el('th',label));const thead=el('thead');thead.append(head);table.append(thead);const body=el('tbody');
  for(const b of bins){const row=el('tr');for(const value of [b.start===b.end?b.start:b.start+'–'+b.end,b.positive,b.n,b.unknown,(100*b.mean).toFixed(1)+'%'])row.append(el('td',String(value)));body.append(row);}table.append(body);host.append(table);}
 return host;
}
function rows(){
 if(!report)return;const metric=$('#metric').value,observer=$('#observer').value,q=$('#search').value.toLowerCase();const values=report.rows.filter(r=>r.observer===observer&&(!binMeasurementIds||binMeasurementIds.has(r.measurement_id))&&JSON.stringify([r.rollout_id,r.metadata]).toLowerCase().includes(q));
 rowPage=Math.min(rowPage,Math.max(0,Math.ceil(values.length/pageSize)-1));const visible=values.slice(rowPage*pageSize,(rowPage+1)*pageSize);
 const host=$('#rows');host.replaceChildren();for(const r of visible){const tr=el('tr');tr.dataset.measurement=r.measurement_id;const m=r.metrics[metric],task=el('td',r.metadata.task_id||r.rollout_id);task.append(el('small',r.metadata.environment||'Environment unrecorded'),el('small',r.rollout_id+' · '+r.snapshot_state));tr.append(task,el('td',r.metadata.training_step??'Not recorded'),el('td',r.metadata.policy_version||r.metadata.checkpoint||'Not recorded'),el('td',display(m.value)));
  const ev=el('td',m.denominator!==null?`${m.numerator} / ${m.denominator}`:m.reason||`${m.evidence_ids.length} source references`);const detail=el('details'),summary=el('summary','Evidence');detail.append(summary,el('p',m.evidence_ids.join(', ')||m.reason||'Explicit outcome field'),el('small','Source '+r.source_hash),el('small','Measurement '+r.measurement_id));if(Object.keys(r.activity_counts).length)detail.append(el('p','Activities: '+Object.entries(r.activity_counts).map(([k,n])=>k+' '+n).join(' · ')));ev.append(detail);tr.append(ev);
  const raw=r.observer==='source'||['operations','diagnostics','tool_contracts'].includes(r.observation_kind),link=el('a',raw?'Open rollout':'Open blueprint');link.href=raw?'/source#run='+r.run_id:'/semantic-map?run='+r.run_id+'&observer='+encodeURIComponent(r.observer);const td=el('td'),inspect=el('button','Inspect source');inspect.onclick=()=>inspectRollout(r);td.append(inspect,link);tr.append(td);host.append(tr);
  if(r.tool_contract_inspection&&metric.startsWith('tool_contract_')){const evidenceRow=el('tr'),cell=el('td');cell.colSpan=6;cell.append(ToolContractEvidence.render(r.tool_contract_inspection));evidenceRow.append(cell);host.append(evidenceRow);}
  if(r.diagnostic_result){const evidenceRow=el('tr'),evidenceCell=el('td');evidenceCell.colSpan=6;evidenceCell.append(diagnosticEvidence(r.diagnostic_result));evidenceRow.append(evidenceCell);host.append(evidenceRow);}
  if(r.operation_observation_id){const evidenceRow=el('tr'),evidenceCell=el('td');evidenceRow.className='operation-row';evidenceCell.colSpan=6;evidenceCell.append(operationEvidence(r.operation_observation_id));evidenceRow.append(evidenceCell);host.append(evidenceRow);}
 }const known=values.filter(r=>r.metrics[metric].value!==null),positive=known.filter(r=>r.metrics[metric].value===1);$('#row-status').textContent=`${values.length} observation rows · ${new Set(values.map(r=>r.run_id)).size} rollout snapshots. Showing ${values.length?rowPage*pageSize+1:0}–${Math.min(values.length,(rowPage+1)*pageSize)}. ${isIndicator(metric)?positive.length+' positive / '+known.length+' decidable rows · '+(values.length-known.length)+' unknown. ':''}Unavailable is not zero.`;$('#previous-page').disabled=rowPage===0;$('#next-page').disabled=(rowPage+1)*pageSize>=values.length;
}
async function load(){document.body.dataset.workspacePending='false';clearBin();const sequence=++loadSequence;try{
 $('#error').hidden=true;const metric=$('#metric').value||initial.get('metric')||'actions',observer=report?$('#observer').value:initial.get('observer')||'source',width=$('#bin-width').value;
 $('#row-status').textContent='Loading measurements…';const params=new URLSearchParams({metric,observer,bin_width:width}),response=await fetch('/api/rollout-metrics?'+params+'&view=metric');const data=await response.json();if(sequence!==loadSequence)return;if(!response.ok)throw Error(data.error||'Unable to load metrics');report=data;
 const metricSelect=$('#metric');metricSelect.replaceChildren();const groups=new Map();for(const[k,d]of Object.entries(report.definitions)){const group=k.startsWith('reward_')?'Reward feedback':k.startsWith('diagnostic_')?'Diagnostic indicators':k.startsWith('activity_')?'Semantic activities':['actions','agent_text_chars','feedback_link_rate','exact_dispatch_repeat_rate','recorded_success','recorded_reward'].includes(k)?'Recorded source':'Work and relationships';if(!groups.has(group)){const opt=el('optgroup');opt.label=group;groups.set(group,opt);metricSelect.append(opt);}const o=el('option',d.label);o.value=k;groups.get(group).append(o);}metricSelect.value=metric;
 const obs=$('#observer');obs.replaceChildren();const choices=new Map([['source','Recorded source · every imported rollout'],...report.rows.filter(r=>r.observer!=='source').map(r=>[r.observer,r.observer_label])]);if(!choices.has(observer))choices.set(observer,'No current measurements · '+ChoiceLabels.name(observer));obs.append(...ChoiceLabels.choices([...choices].map(([id,label])=>({id,label}))).map(ChoiceLabels.option));obs.value=observer;
 $('#coverage').textContent=`${report.rollouts} imported rollout snapshots · ${report.training_coordinate_count} with explicit experiment and training-step coordinates · ${report.rows.filter(r=>r.observation_kind==='semantic').length} saved semantic observations · ${report.rows.filter(r=>r.observation_kind==='operations').length} saved operation observations · ${report.rows.filter(r=>r.observation_kind==='diagnostics').length} saved diagnostic observations.`;
 $('#stat-rollouts').textContent=report.rollouts.toLocaleString();$('#stat-timed').textContent=report.training_coordinate_count.toLocaleString();$('#stat-observed').textContent=report.rows.filter(r=>r.observer===observer&&r.metrics[metric]?.value!==null).length.toLocaleString();for(const button of document.querySelectorAll('[data-metric]'))button.setAttribute('aria-pressed',String(button.dataset.metric===metric));
 const protocolDefinition=report.rows.find(r=>r.observer===observer&&r.diagnostic_result)?.diagnostic_result.protocol.detectors[metric.replace(/^diagnostic_/,'')]?.[1];
 $('#definition').textContent=protocolDefinition?protocolDefinition+' Per-rollout indicator: 1, 0 or unavailable. Experimental; source and observer version must remain matched.':report.definitions[metric].definition;$('#download').href='/api/rollout-metrics?'+params+'&download=1';
 monitoringCoverage(observer);
 const graph=$('#charts');graph.replaceChildren();for(const cohort of report.training.cohorts)graph.append(chart(cohort,metric));
 if(!report.training.cohorts.length){const selected=report.rows.filter(r=>r.observer===observer),known=selected.filter(r=>r.metrics[metric]?.value!==null),reasons=new Map();for(const r of selected){const reason=r.metrics[metric]?.reason;if(reason)reasons.set(reason,(reasons.get(reason)||0)+1);}const most=[...reasons].sort((a,b)=>b[1]-a[1])[0];const empty=el('div');empty.className='empty';empty.append(el('strong','No eligible training points for this measurement'),el('p',known.length+' rollout observations have a value, but none can enter this training chart.'),el('p',most?most[1]+' unavailable: '+most[0]:'Explicit experiment and training-step metadata are needed; import order is not substituted.'));graph.append(empty);}
 $('#trend-status').textContent=Object.entries(report.training.excluded).map(([k,n])=>`${n} ${k.replaceAll('_',' ')}`).join(' · ')||report.training.interpretation;
 $('#definitions').replaceChildren(...Object.values(report.definitions).map(d=>el('p',d.label+': '+d.definition)));$('#receipt').textContent='Source: immutable normalized rollout snapshots, saved semantic maps and operation observations in the local tracker. Metric schema '+report.schema+' · export hash '+report.report_hash+'.';rows();updateURL();
 }catch(e){if(sequence===loadSequence){$('#error').textContent=e.message;$('#error').hidden=false;}}}
$('#metric').onchange=()=>{rowPage=0;load();};$('#observer').onchange=()=>{rowPage=0;load();};$('#refresh').onclick=load;$('#bin-width').onchange=load;$('#search').oninput=()=>{rowPage=0;rows();updateURL();};$('#previous-page').onclick=()=>{rowPage--;rows();};$('#next-page').onclick=()=>{rowPage++;rows();};$('#search').value=initial.get('run')||'';if(initial.has('bin_width'))$('#bin-width').value=initial.get('bin_width');load();
for(const button of document.querySelectorAll('[data-metric]'))button.onclick=()=>{$('#metric').value=button.dataset.metric;rowPage=0;load();};window.addEventListener('workspace-update',()=>{if(binMeasurementIds){document.body.dataset.workspacePending='true';$('#live-state').textContent='New data · refresh view';}else if(report)load();});
$('#show-rollouts').onchange=()=>{if(report){const host=$('#charts');host.replaceChildren(...report.training.cohorts.map(c=>chart(c,$('#metric').value)));}};$('#clear-bin').onclick=()=>{clearBin();rows();};
