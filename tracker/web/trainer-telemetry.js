/* Native trainer coordinates remain separate from rollout measurements. */
(() => {
 'use strict';
 const names={reward:'Outcome',mismatch:'Policy mismatch',clipping:'Clipping & masking',entropy:'Entropy',throughput:'Throughput',gradients:'Gradient norms',loss:'Loss',kl:'KL divergence',tokens:'Token usage',systems:'Systems',other:'Additional native metrics'};
 function comparable(a,b){
  const objectiveSensitive=['loss','entropy','kl','clipping','gradients','other'].includes(a.group);
  return ['native_key','unit','reduction','definition','group'].every(k=>a[k]===b[k])&&
   ['clock','split','population','environment','framework'].every(k=>a.context[k]===b.context[k])&&
   (!objectiveSensitive||a.context.objective===b.context.objective);
 }
 function expectedGroups(series){
  const contexts=series.map(s=>s.context).filter(Boolean);
  if(contexts.length&&contexts.every(c=>c.framework==='stable-baselines3')){
   return ['reward','throughput','loss',...(contexts.some(c=>c.objective==='ppo')?['entropy','clipping','kl']:[])];
  }
  return ['reward','mismatch','throughput'];
 }
 function captureSessions(series){
  const groups=new Map();
  for(const s of series){const id=JSON.stringify([s.context.producer,s.context.session]),first=s.full_range?.first_received_record??0;
   if(!groups.has(id))groups.set(id,{id,producer:s.context.producer,first,series:[]});const g=groups.get(id);g.first=Math.min(g.first,first);g.series.push(s);
  }
  return [...groups.values()].sort((a,b)=>a.first-b.first||a.id.localeCompare(b.id)).map((g,i)=>{
   const steps=g.series.flatMap(s=>s.full_range?[s.full_range.start,s.full_range.end].filter(v=>v!=null):s.points.map(p=>p.step));
   return {...g,label:`Session ${i+1} · ${g.producer}${steps.length?' · steps '+Math.min(...steps)+'–'+Math.max(...steps):''}`};
  });
 }
 function selectSession(series,choice=''){
  const sessions=captureSessions(series);return choice==='*'?series:(choice?sessions.find(s=>s.id===choice):sessions.at(-1))?.series||[];
 }
 function sessionLabel(s,series){return captureSessions(series).find(g=>g.id===JSON.stringify([s.context.producer,s.context.session]))?.label||s.context.producer;}
 function sessionParams(choice=''){
  if(!choice)return {session_mode:'latest'};if(choice==='*')return {session_mode:'all'};
  let value;try{value=JSON.parse(choice);}catch{}
  if(!Array.isArray(value)||value.length!==2||value.some(v=>typeof v!=='string'||!v||v.length>1000))throw Error('Invalid saved worker/session selection. Choose a session again.');
  return {session_mode:'all',producer:value[0],session:value[1]};
 }
 function knownSessions(dataset){
  if(!dataset.session_inventory)return captureSessions(dataset.series||[]);
  const rows=[...dataset.session_inventory.rows],selected=dataset.session_selection?.selected;
  if(selected&&!rows.some(r=>r.producer===selected.producer&&r.session===selected.session))rows.push(selected);
  return rows.sort((a,b)=>a.ordinal-b.ordinal).map(r=>({...r,id:JSON.stringify([r.producer,r.session]),label:`Session ${r.ordinal} · ${r.producer} · steps ${r.start}–${r.end}`}));
 }
 function smoothPoints(points,halfLife){
  let value=null,last=null;
  return points.map(p=>{
   if(p.value==null||!Number.isFinite(p.value)){value=null;last=null;return {...p,value:null};}
   const alpha=halfLife>0&&last!=null?-Math.expm1(-Math.LN2*Math.max(0,p.step-last)/halfLife):1;
   value=value==null?p.value:alpha*p.value+(1-alpha)*value;last=p.step;return {...p,value};
  });
 }
 function intervalStats(points,range){
  const rows=points.filter(p=>!range||p.step>=range[0]&&p.step<=range[1]),finite=rows.filter(p=>p.value!=null&&Number.isFinite(p.value));
  return {rows,finite,first:finite[0],last:finite.at(-1),delta:finite.length>1?finite.at(-1).value-finite[0].value:null};
 }
 function seriesStats(series,range){
  if(series.stats)return {...series.stats,measured:series.stats.recorded,total:series.stats.coordinates};
  const stats=intervalStats(series.points,range);return {...stats,measured:stats.finite.length,total:stats.rows.length};
 }
 function trendPoints(series,halfLife){return series.representation?series.trend_points:smoothPoints(series.points,halfLife);}
 function defaultSeries(series){
  const defaults={reward:['reward','critic/score/mean','critic/rewards/mean','objective/rlhf_reward','rollout/ep_rew_mean','eval/mean_reward'],entropy:['entropy','entropy/mean','actor/entropy','policy/entropy_avg','objective/entropy','entropy_loss'],clipping:['clip_ratio/region_mean','actor/pg_clipfrac','policy/clipfrac_avg','cispo_clip_ratio','clip_ratio','clip_fraction'],tokens:['completions/mean_length','response_length/mean','num_tokens','perf/total_num_tokens'],other:['rollout/exploration_rate','explained_variance','rollout/ep_len_mean']};
  const priority=s=>{
   const key=s.native_key.replace(/^eval_/, '').replace(/^train\//, ''),preferred=defaults[s.group];
   if(preferred){const index=preferred.indexOf(key);return index<0?100:index;}
   return key==='comparison/mean_probability_gap'?0:key.includes('mismatch_kl')?1:key==='comparison/mean_absolute_gap'?2:5;
  };
  // A fraction is not intrinsically a better headline than reward or mean entropy.
  // Keep the user's selection; this only chooses the initial chart in each group.
  return [...series].sort((a,b)=>Number(b.recorded>0)-Number(a.recorded>0)||priority(a)-priority(b)||b.recorded-a.recorded)[0];
 }
 function compactValue(v){return v!==0&&Math.abs(v)<0.0001?Number(v).toExponential(2):Number(v).toLocaleString(undefined,{maximumSignificantDigits:5});}
 function previewSignals(series,limit=6){
  const order=[...new Set([...expectedGroups(series),'entropy','loss','kl','clipping','tokens','gradients','systems','other'])];
  return order.map(group=>defaultSeries(series.filter(s=>s.group===group))).filter(Boolean).slice(0,limit);
 }
 if(typeof module!=='undefined'&&module.exports){module.exports={comparable,smoothPoints,intervalStats,defaultSeries,seriesStats,trendPoints,expectedGroups,captureSessions,selectSession,sessionParams,knownSessions,previewSignals,compactValue};return;}
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const ns='http://www.w3.org/2000/svg';
 const svg=(tag,attrs={})=>{const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;};
 let scope={},seq=0,saved='',data=null,selection=new Map(),datasets=[],failure='',paused=false,checked=null,dragging=false,openedSignal='';
 const query=()=>new URLSearchParams(location.search),colors=['#355cdb','#009b82','#dc6637'];
 document.addEventListener('pointerdown',event=>{for(const menu of document.querySelectorAll('.telemetry-card-options[open]'))if(!menu.contains(event.target))menu.open=false;});
 let cutoffs={};try{const value=JSON.parse(query().get('signals_cutoffs')||'{}');if(value&&typeof value==='object')cutoffs=Object.fromEntries(Object.entries(value).filter(([k,v])=>k&&Number.isSafeInteger(v)&&v>=0));}catch{}paused=Object.keys(cutoffs).length>0;
 let comparisons=query().getAll('signals_compare').slice(0,2),halfLife=Number(query().get('signals_smooth'))||0;
 if(![0,10,50,100].includes(halfLife))halfLife=0;
 let clock=query().get('signals_clock')||'',range=null;
 let sessionChoice=query().get('signals_session')||'';
 let comparisonSessions=new Map();try{comparisonSessions=new Map(Object.entries(JSON.parse(query().get('signals_sessions')||'{}')).filter(([k,v])=>typeof v==='string'));}catch{}
 const from=query().get('signals_from'),to=query().get('signals_to');
 if(from!==null&&to!==null&&Number.isFinite(Number(from))&&Number.isFinite(Number(to))&&Number(from)<=Number(to))range=[Number(from),Number(to)];
 const logarithmic=new Set((query().get('signals_log')||'').split(',').filter(Boolean));
 let layout=query().get('signals_layout')||'';
 const extraMetrics=new Set(query().getAll('signals_extra').slice(0,6));
 try{selection=new Map(Object.entries(JSON.parse(query().get('signals_picks')||'{}')));}catch{}
 function persist(){const u=new URL(location.href);if(paused){for(const d of datasets)if(d.as_of!=null)cutoffs[d.experiment]=d.as_of;}else cutoffs={};for(const key of [...u.searchParams.keys()])if(key.startsWith('signals_'))u.searchParams.delete(key);for(const run of comparisons)u.searchParams.append('signals_compare',run);for(const id of extraMetrics)u.searchParams.append('signals_extra',id);for(const[k,v]of Object.entries({clock,session:sessionChoice,sessions:comparisonSessions.size?JSON.stringify(Object.fromEntries(comparisonSessions)):null,smooth:halfLife||null,layout,from:range?.[0],to:range?.[1],cutoffs:paused?JSON.stringify(cutoffs):null,log:[...logarithmic].join(','),picks:selection.size?JSON.stringify(Object.fromEntries(selection)):null}))if(v!=null&&v!=='')u.searchParams.set('signals_'+k,v);history.replaceState(history.state,'',u);}
 function choiceFor(experiment){return experiment===scope.experiment?sessionChoice:comparisonSessions.get(experiment)||'';}
 function chooseSession(experiment,value){if(experiment===scope.experiment)sessionChoice=value;else comparisonSessions.set(experiment,value);range=null;selection.clear();extraMetrics.clear();persist();load(true);}
 function labelFor(s,dataset=data){return knownSessions(dataset).find(r=>r.id===JSON.stringify([s.context.producer,s.context.session]))?.label||s.context.producer+' · saved session';}
 function sessionControls(dataset,label){
  const known=knownSessions(dataset),choice=choiceFor(dataset.experiment),options=[['','Latest received session'],...known.map(s=>[s.id,s.label]),['*','All sessions · choose per chart']];
  if(choice&&choice!=='*'&&!known.some(s=>s.id===choice))options.splice(1,0,[choice,'Selected session · unavailable']);
  const result=[choose(label,options,choice,v=>chooseSession(dataset.experiment,v))];
  const selected=dataset.session_selection?.selected;
  if(selected&&window.ExperimentDetails)result.push(button('Session details',()=>ExperimentDetails.openTrainer(dataset.experiment,selected.producer,selected.session)));
  if((dataset.session_inventory?.total||0)>20)result.push(button('Browse all '+dataset.session_inventory.total+' sessions',()=>browseSessions(dataset)));
  return result;
 }
 function browseSessions(dataset){
  const d=el('dialog',undefined,'telemetry-dialog');d.setAttribute('aria-label','Trainer sessions');
  const form=el('form',undefined,'telemetry-interval'),input=el('input'),label=el('label','Search sessions','telemetry-control'),submit=button('Search'),status=el('p'),rows=el('div');
  input.type='search';input.placeholder='Worker, session name or number';input.setAttribute('aria-label','Search sessions');label.append(input);submit.type='submit';form.append(label,submit);
  d.append(el('h2','Trainer sessions'),el('p',dataset.experiment+' · '+dataset.clock+' · ordered by first receipt'),button('Close',()=>d.close()),form,status,rows);let request=0;
  async function page(offset=0){const ticket=++request;submit.disabled=true;status.textContent='Loading sessions…';
   try{const q=new URLSearchParams({experiment:dataset.experiment,clock:dataset.clock,as_of:dataset.as_of,search:input.value,limit:20,offset});if(scope.environment)q.set('environment',scope.environment);
    const r=await fetch('/api/trainer-telemetry/sessions?'+q),value=await r.json();if(ticket!==request||!d.isConnected)return;if(!r.ok)throw Error(value.error||'Could not load sessions');
    rows.replaceChildren();status.textContent=`${value.total} matching sessions · ${value.rows.length} shown`;
    for(const s of value.rows){const row=el('div',undefined,'telemetry-catalog-row'),text=el('div');text.append(el('strong',`Session ${s.ordinal} · ${s.producer}`),el('small',`Steps ${s.start}–${s.end} · ${s.records} native logs · first received ${new Date(s.first_received_at).toLocaleString()}`));
     const details=el('details');details.append(el('summary','Recorded identity'),el('code',s.session));text.append(details);row.append(text,button('Use session',()=>{d.close();chooseSession(dataset.experiment,JSON.stringify([s.producer,s.session]));}));rows.append(row);}
    const nav=el('div',undefined,'telemetry-actions');if(offset)nav.append(button('Previous',()=>page(Math.max(0,offset-20))));if(value.next_offset!=null)nav.append(button('Next',()=>page(value.next_offset)));rows.append(nav);
   }catch(e){if(ticket===request)status.textContent=e.message;}finally{if(ticket===request)submit.disabled=false;}
  }
  form.onsubmit=e=>{e.preventDefault();page();};d.onclose=()=>{++request;d.remove();};showTelemetryDialog(d);input.focus();page();
 }
 function link(text,view,extra={}){const a=el('a',text);a.href='/?'+new URLSearchParams({view,...(scope.experiment?{experiment:scope.experiment}:{}),...(scope.environment?{environment:scope.environment}:{}),...extra});return a;}
 function button(text,action){const b=el('button',text);b.type='button';b.onclick=action;return b;}
 function showTelemetryDialog(dialog){
  const title=dialog.querySelector(':scope > h2'),close=[...dialog.children].find(n=>n.tagName==='BUTTON'&&n.textContent==='Close');
  if(title&&close){const head=el('div',undefined,'dialog-head');close.setAttribute('aria-label','Close');head.append(title,close);dialog.prepend(head);}
  document.body.append(dialog);window.WorkspaceDialog?.prepare(dialog);dialog.showModal();
 }
 function choose(label,items,value,onchange){const l=el('label',undefined,'telemetry-control'),s=el('select');l.append(el('span',label),s);s.setAttribute('aria-label',label);s.dataset.telemetryControl=label;for(const[v,t]of items){const o=el('option',t);o.value=v;s.append(o);}s.value=value;s.onchange=()=>onchange(s.value);return l;}
 function exportView(){const a=el('a'),url=URL.createObjectURL(new Blob([JSON.stringify({schema:'training-signals-view/1',captured_at:checked,selection:{experiment:scope.experiment,environment:scope.environment,comparisons,clock,session:sessionChoice,sessions:Object.fromEntries(comparisonSessions),range,halfLife,log:[...logarithmic],metrics:Object.fromEntries(selection),extra:[...extraMetrics]},datasets},null,2)],{type:'application/json'}));a.href=url;a.download='rilldex-training-signals.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 function dataParams(dataset,interval=range){
  const q=new URLSearchParams();if(dataset.experiment)q.set('experiment',dataset.experiment);if(scope.environment)q.set('environment',scope.environment);
  if(clock)q.set('clock',clock);if(dataset.as_of!=null)q.set('as_of',dataset.as_of);
  const selection=dataset.session_selection;if(selection){const selected=selection.selected;if(selected){q.set('producer',selected.producer);q.set('session',selected.session);}else for(const k of ['producer','session'])if(selection[k]!=null)q.set(k,selection[k]);}
  if(interval){q.set('start',interval[0]);q.set('end',interval[1]);}return q;
 }
 function exportDialog(){
  const d=el('dialog',undefined,'telemetry-dialog');d.setAttribute('aria-label','Export training signals');
  d.append(el('h2','Export training signals'),el('p','Original JSONL follows each run’s selected worker, session, clock and interval. Chart JSON also retains plotted representatives, exact statistics and capture cutoffs.'),button('Close',()=>d.close()));
  for(const dataset of datasets){const a=el('a','Download original JSONL · '+dataset.experiment);a.href='/api/trainer-telemetry/export?'+dataParams(dataset);a.download='rilldex-telemetry.jsonl';const p=el('p');p.append(a);d.append(p);}
  d.append(button('Download chart JSON',exportView));d.onclose=()=>d.remove();showTelemetryDialog(d);
 }
 function browseMetrics(){
  const d=el('dialog',undefined,'telemetry-dialog');d.setAttribute('aria-label','Metric catalog');
  const form=el('form',undefined,'telemetry-interval'),input=el('input'),label=el('label','Search metrics','telemetry-control'),search=button('Search'),results=el('div'),status=el('p');
  input.type='search';input.placeholder='Metric name or native key';input.setAttribute('aria-label','Search metrics');label.append(input);search.type='submit';form.append(label,search);
  d.append(el('h2','Metric catalog'),el('p','Search every metric in the selected run, session and clock.'),button('Close',()=>d.close()),form,status,results);
  let request=0;
  async function page(offset=0){
   const ticket=++request;search.disabled=true;status.textContent='Loading metrics…';
   try{const params=dataParams(data,null);params.set('search',input.value);params.set('offset',offset);params.set('limit',30);
    const r=await fetch('/api/trainer-telemetry/catalog?'+params);if(!r.ok)throw Error('Could not load the metric catalog.');const value=await r.json();if(ticket!==request||!d.isConnected)return;
    results.replaceChildren();status.textContent=`${value.total_series} matching series · ${clock}`;
    for(const s of value.series){const row=el('div',undefined,'telemetry-catalog-row'),text=el('div');text.append(el('strong',s.label),el('small',`${s.native_key} · ${s.context.split} · ${labelFor(s)}`));
     const add=button(extraMetrics.has(s.id)?'Added':'Add chart',()=>{extraMetrics.add(s.id);persist();d.close();load(true);});add.disabled=extraMetrics.has(s.id)||extraMetrics.size>=6;row.append(text,add);results.append(row);}
    const nav=el('div',undefined,'telemetry-actions');if(offset)nav.append(button('Previous',()=>page(Math.max(0,offset-30))));if(value.next_offset!=null)nav.append(button('Next',()=>page(value.next_offset)));results.append(nav);
    if(extraMetrics.size>=6)status.append(' Remove an extra chart to add another.');
   }catch(e){if(ticket===request)status.textContent=e.message;}finally{if(ticket===request)search.disabled=false;}
  }
  form.onsubmit=e=>{e.preventDefault();page();};d.onclose=()=>{++request;d.remove();};showTelemetryDialog(d);input.focus();page();
 }
 const fmt=v=>v===null?'Unavailable':Number.isInteger(v)?Number(v).toLocaleString():compactValue(v);
 async function showRecord(s,p){
  const d=el('dialog',undefined,'telemetry-dialog'),close=el('button','Close');d.setAttribute('aria-label',s.label);close.type='button';close.onclick=()=>d.close();
  const links=el('div','Loading linked rollout evidence…'),raw=el('details');raw.append(el('summary','Native point & definition'),el('pre',JSON.stringify({context:s.context,native_key:s.native_key,unit:s.unit,reduction:s.reduction,...p},null,2)));
  d.append(el('h2',s.label),el('p',`${fmt(p.value)} ${s.unit} · ${s.context.clock} ${p.step} · ${p.status}`),el('p',s.definition),links,raw,close);
  if(window.ExperimentDetails)d.append(button('Captured logs & settings',()=>ExperimentDetails.openTrainer(s.context.experiment,s.context.producer,s.context.session)));
  d.addEventListener('close',()=>d.remove());showTelemetryDialog(d);
  try{
   const records=await Promise.all(p.record_ids.map(async record_id=>{const q=new URLSearchParams({producer:s.context.producer,experiment:s.context.experiment,record_id});const r=await fetch('/api/trainer-telemetry/evidence?'+q);if(!r.ok)throw Error('Linked evidence is unavailable.');return r.json();}));
   if(!links.isConnected)return;links.replaceChildren();
   if(!p.record_ids.length)links.append(el('p','This metric was not recorded at this coordinate. Export original JSONL to inspect the other logged fields.'));
   if(p.omitted_record_ids)links.append(el('p',`${p.omitted_record_ids} additional conflicting records are available in the original JSONL export.`));
   for(const record of records){
    if(window.ExperimentDetails)links.append(ExperimentDetails.pointContext(record.executions,s.context.experiment));
    links.append(el('h3','Linked rollout evidence'),el('p',record.declared_uses?`${record.matched_uses} / ${record.declared_uses} declared training uses have exact source links · ${record.declared_coverage} reference inventory`:'No training-use references recorded. Add references in TrainerTelemetry.log() to enable rollout drill-down.'));
    const list=el('ul');for(const [index,id] of record.run_ids.slice(0,100).entries()){const item=el('li'),a=el('a',`Open rollout ${index+1}`);a.href='/semantic-map?'+new URLSearchParams({run:id,observer:'source',return_to:location.pathname+location.search});item.append(a);list.append(item);}links.append(list);
    if(record.run_ids.length>100)links.append(el('p',`${record.run_ids.length-100} further rollout links are retained in the full evidence record.`));
    const detail=el('details');detail.append(el('summary','Training-use receipts & attribution'),el('p',record.boundary),el('pre',JSON.stringify(record.references,null,2)));links.append(detail);
   }
  }catch(e){if(links.isConnected)links.textContent=e.message;}
 }
 function compareLinked(streams){
  const u=new URL(location.href);u.searchParams.set('signals_cutoffs',JSON.stringify(Object.fromEntries(datasets.map(d=>[d.experiment,d.as_of]))));
  CaseComparisonsView.openTrainer({streams:streams.map(({series})=>({series,as_of:(datasets.find(d=>d.experiment===series.context.experiment)||data).as_of})),range:range?.slice(),return_to:u.pathname+u.search});
 }
 function inspectInterval(streams){
  const d=el('dialog',undefined,'telemetry-dialog'),close=button('Close',()=>d.close());d.setAttribute('aria-label','Recorded updates in interval');
  d.append(el('h2','Recorded updates'),el('p',range?`${clock} ${range[0]}–${range[1]}`:'Full recorded range'),close);
  if(window.CaseComparisonsView)d.append(button('Compare linked rollouts',()=>{d.close();compareLinked(streams);}));
  for(const {series:s} of streams){
   const stats=seriesStats(s,range),section=el('section');section.append(el('h3',s.context.experiment),el('p',`${stats.measured}/${stats.total} measured coordinates · ${s.context.population} · ${s.context.split}`));
   let after=null;const list=el('div',undefined,'telemetry-log-list'),status=el('p'),more=button('Show more updates',append);
   const params=dataParams(datasets.find(x=>x.experiment===s.context.experiment)||data);params.set('series',s.id);params.set('limit',50);
   async function append(){more.disabled=true;status.textContent='Loading original coordinates…';
    try{if(after!=null)params.set('after',after);const r=await fetch('/api/trainer-telemetry/points?'+params);if(!r.ok)throw Error('Could not load recorded updates.');const page=await r.json();if(!d.isConnected)return;
     for(const p of page.points){const b=button(`${s.context.clock} ${p.step} · ${p.value==null?p.status:fmt(p.value)+' '+s.unit}`,()=>showRecord(s,p));list.append(b);}
     after=page.next_after;more.hidden=after==null;status.textContent=page.points.length?'Every coordinate is available, including missing and conflicting values.':'No recorded coordinates in this interval.';
    }catch(e){status.textContent=e.message;}finally{more.disabled=false;}
   }
   section.append(list,status,more);d.append(section);queueMicrotask(append);
  }
  d.onclose=()=>d.remove();showTelemetryDialog(d);
 }
 function chart(streams,bounds,group){
  const compact=(layout||(comparisons.length?'stacked':'compact'))==='compact';
  const log=logarithmic.has(group),width=innerWidth<700?360:compact?440:innerWidth<1100?540:760,left=58,right=18,bottom=147,top=18;
  const box=el('div',undefined,'telemetry-plot'),g=svg('svg',{viewBox:`0 0 ${width} 185`,role:'group','aria-label':`${names[group]||streams[0].series.label} · aligned ${clock}${log?' · logarithmic scale':''}`});
  const prepared=streams.map(s=>({...s,raw:intervalStats(s.series.points,bounds).rows,trend:intervalStats(trendPoints(s.series,halfLife)||[],bounds).rows}));
  const transform=v=>log?Math.log10(v):v,valid=p=>p.value!=null&&Number.isFinite(p.value)&&(!log||p.value>0),values=prepared.flatMap(s=>[...s.raw,...(halfLife?s.trend:[])].filter(valid).map(p=>transform(p.value)));
  const excluded=prepared.reduce((n,s)=>n+s.raw.filter(p=>p.value!=null&&p.value<=0).length,0);
  if(log&&excluded)box.append(el('p',`${excluded} nonpositive values omitted on Log; switch to Linear to include them.`,'telemetry-warning'));
  if(!values.length){box.append(el('p','No plottable values in this interval.','telemetry-empty'));return box;}
  let lo=Math.min(...values),hi=Math.max(...values);if(lo===hi){if(!log&&lo>=0&&hi<=1&&streams.every(s=>s.series.unit==='fraction')){lo=0;hi=1;}else{const pad=log ? .25 : Math.abs(lo)*.05||1;lo-=pad;hi+=pad;}}
  const x=v=>left+(width-left-right)*(v-bounds[0])/(bounds[1]-bounds[0]||1),y=v=>bottom-(bottom-top)*(transform(v)-lo)/(hi-lo);
  for(let i=0;i<=2;i++){const v=lo+(hi-lo)*i/2,t=svg('text',{x:left-8,y:bottom-(bottom-top)*i/2+4,'text-anchor':'end'});t.textContent=fmt(log?10**v:v);g.append(svg('line',{x1:left,x2:width-right,y1:bottom-(bottom-top)*i/2,y2:bottom-(bottom-top)*i/2,class:'telemetry-gridline'}),t);}
  for(let i=0;i<=4;i++){const value=bounds[0]+(bounds[1]-bounds[0])*i/4,t=svg('text',{x:x(value),y:173,'text-anchor':i===0?'start':i===4?'end':'middle'});t.textContent=fmt(value);g.append(svg('line',{x1:x(value),x2:x(value),y1:top,y2:bottom,class:'telemetry-gridline'}),t);}
  const highlight=svg('rect',{x:left,y:top,width:0,height:bottom-top,class:'telemetry-brush'}),cursor=svg('line',{x1:left,x2:left,y1:top,y2:bottom,class:'telemetry-cursor',visibility:'hidden'});g.append(highlight,cursor);
  g.dataset.min=bounds[0];g.dataset.max=bounds[1];g.dataset.left=left;g.dataset.right=width-right;
  const path=(points,color,trend)=>{let d='',open=false,segment;for(const p of points){if(!valid(p)){open=false;continue;}if(segment!==p.segment)open=false;d+=`${open?'L':'M'}${x(p.step)} ${y(p.value)} `;open=true;segment=p.segment;}g.append(svg('path',{d,fill:'none',stroke:color,'stroke-width':trend?2.7:halfLife?1:2,'stroke-opacity':!trend&&halfLife?.25:1,class:trend?'telemetry-trend':'telemetry-raw'}));};
  for(const {series:s,color,raw,trend}of prepared){
   path(raw,color,false);if(halfLife)path(trend,color,true);
   for(const [i,p]of raw.filter(valid).entries()){
    const dot=svg('circle',{cx:x(p.step),cy:y(p.value),r:3,tabindex:i===0?0:-1,role:'button',style:`fill:${color}`,'aria-label':`${s.context.experiment} · ${clock} ${p.step}: ${fmt(p.value)} ${s.unit}`});
    const title=svg('title');title.textContent=`${s.context.experiment} · ${clock} ${p.step}\n${fmt(p.value)} ${s.unit} · raw`;dot.append(title);dot.onclick=()=>showRecord(s,p);
    dot.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();showRecord(s,p);}if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();const dots=[...g.querySelectorAll('circle')],next=dots[dots.indexOf(dot)+(e.key==='ArrowLeft'?-1:1)];next?.focus();}};g.append(dot);
   }
  }
  const at=e=>{const r=g.getBoundingClientRect();return Math.max(bounds[0],Math.min(bounds[1],bounds[0]+((e.clientX-r.left)/r.width*width-left)/(width-left-right)*(bounds[1]-bounds[0])));};
  let start=null;
  const sync=(value,end)=>{for(const plot of document.querySelectorAll('#trainer-telemetry .telemetry-plot svg')){const coordinate=v=>Number(plot.dataset.left)+(Number(plot.dataset.right)-Number(plot.dataset.left))*(v-Number(plot.dataset.min))/(Number(plot.dataset.max)-Number(plot.dataset.min)||1);const line=plot.querySelector('.telemetry-cursor');line.setAttribute('x1',coordinate(value));line.setAttribute('x2',coordinate(value));line.setAttribute('visibility','visible');const area=plot.querySelector('.telemetry-brush');area.setAttribute('x',coordinate(Math.min(value,end??value)));area.setAttribute('width',end==null?0:Math.abs(coordinate(end)-coordinate(value)));}};
  g.onpointermove=e=>{const value=at(e);sync(start??value,start==null?null:value);};
  g.onpointerdown=e=>{if(e.button!==0||e.target.closest('circle'))return;e.preventDefault();start=at(e);dragging=true;g.setPointerCapture(e.pointerId);};
  const clear=()=>{start=null;dragging=false;for(const plot of document.querySelectorAll('#trainer-telemetry .telemetry-plot svg')){plot.querySelector('.telemetry-brush').setAttribute('width',0);plot.querySelector('.telemetry-cursor').setAttribute('visibility','hidden');}};
  g.onpointerup=e=>{if(start==null)return;const a=start,b=at(e);clear();if(Math.abs(a-b)>(bounds[1]-bounds[0])*.004){range=[Math.min(a,b),Math.max(a,b)];paused=true;++seq;persist();load(true);}};
  g.onpointercancel=clear;g.onlostpointercapture=()=>{if(start!=null)clear();};g.onpointerleave=()=>{if(start==null)clear();};box.append(g);return box;
 }
 function render(){
  const host=document.querySelector('#trainer-telemetry');if(!host||!data)return;
  const summaryView=typeof OverviewLayout!=='undefined'&&OverviewLayout.mode(location.search).section==='summary';
  if(summaryView&&!scope.experiment){host.hidden=true;host.replaceChildren();return;}
  const focused=document.activeElement?.dataset.telemetryControl,displayOpen=!!host.querySelector('.telemetry-options[open]'),openOptions=new Set([...host.querySelectorAll('.telemetry-card-options[open]')].map(e=>e.dataset.group));host.hidden=false;host.replaceChildren();
  const heading=el('div',undefined,'telemetry-heading'),title=el('div');title.append(el('h2','Training signals'),el('p','Compare runs on recorded steps. Select an interval or point to inspect its updates and rollouts.'));
  const actions=el('div',undefined,'telemetry-actions');actions.append(link(summaryView?'Open training comparison →':'Execution timeline →',summaryView?'health':'execution'));
  if(scope.experiment&&comparisons.length&&window.ConfigurationComparison)actions.append(button('Compare settings',()=>{let sources={};try{const value=JSON.parse(query().get('settings_sources')||'{}');if(value&&typeof value==='object'&&!Array.isArray(value))sources=Object.fromEntries([scope.experiment,...comparisons].filter(e=>Object.hasOwn(value,e)).map(e=>[e,value[e]]));}catch(_){}ConfigurationComparison.open([scope.experiment,...comparisons],scope.environment||null,sources);}));
  const setup=el('a',data.records?'Capture settings':'Connect training data');setup.href='/connections#telemetry-section';actions.append(setup);heading.append(title,actions);host.append(heading);
  if(failure)host.append(el('p',failure+' Displayed data is unchanged.','telemetry-warning'));
  if(!scope.experiment){
   if(document.getElementById('experiment-browser')){host.hidden=true;return;}
   host.append(el('p','Select a training run to align its signals. Add another run to compare it.','telemetry-note'));
   const runs=el('div',undefined,'telemetry-run-choices'),ids=[...new Set(data.series.map(s=>s.context.experiment))];
   for(const id of ids)runs.append(link(id,'health',{experiment:id}));host.append(runs);
   if(!ids.length)host.append(el('p','No trainer logs received. Connect a running trainer or import existing logs. Rollout-only data is available in Behavior measures.','telemetry-empty'),link('Open behavior measures →','measures'));
   return;
  }
  const controls=el('div',undefined,'telemetry-board-controls'),available=[...document.querySelector('#experiment').options].map(o=>[o.value,o.textContent]).filter(([v])=>v&&v!==scope.experiment&&!comparisons.includes(v));
  if(!summaryView&&comparisons.length<2)controls.append(choose('Compare run',[['','Add a run…'],...available],'',value=>{if(value){comparisons.push(value);paused=false;persist();load(true);}}));
  const clocks=data.clocks||[...new Set(data.series.map(s=>s.context.clock))];if(!clocks.includes(clock))clock=data.clock||'learner_update';
  const clockControl=clocks.length>1?choose('Step clock',clocks.map(c=>[c,c]),clock,v=>{clock=v;sessionChoice='';range=null;selection.clear();persist();load(true);}):null;
  const clockSeries=data.series.filter(s=>s.context.clock===clock),sessions=knownSessions(data),visible=clockSeries;
  const sessionOptions=(data.session_inventory?.total||sessions.length)>1||sessionChoice?sessionControls(data,'Session'):[];
  const display=el('details',undefined,'telemetry-options'),displayTitle=el('summary','Chart options'),displayBody=el('div',undefined,'telemetry-options-body');
  if(clockControl)displayBody.append(clockControl);displayBody.append(...sessionOptions);
  displayTitle.append(el('span',(halfLife?'EMA · '+halfLife+' steps':'Raw')+' · '+(layout||(comparisons.length?'stacked':'compact'))));
  displayBody.append(choose('Trend',[[0,'Raw'],[10,'EMA · 10-step half-life'],[50,'EMA · 50-step half-life'],[100,'EMA · 100-step half-life']],halfLife,v=>{halfLife=Number(v);persist();load(true);}),choose('Chart layout',[['stacked','Stacked'],['compact','Compact']],layout||(comparisons.length?'stacked':'compact'),v=>{layout=v;persist();render();}),button('Export comparison',exportDialog));
  display.open=displayOpen;display.append(displayTitle,displayBody);controls.append(display,button(paused?'Resume updates':'Pause updates',()=>{paused=!paused;++seq;persist();render();if(!paused)load(true);}),button('Browse metrics',browseMetrics));host.append(controls);
  const legend=el('div',undefined,'telemetry-run-legend');
  datasets.forEach((d,i)=>{const item=el('span',undefined,'telemetry-run-chip'),swatch=el('i');swatch.style.background=colors[i];item.append(swatch,el('strong',d.experiment),el('span',`${fmt(d.records)}${range?' / '+fmt(d.total_records??d.records):''} logs${range?' in interval':''}`));if(i){if((d.session_inventory?.total||0)>0||choiceFor(d.experiment))item.append(...sessionControls(d,'Session · '+d.experiment));item.append(button('Remove',()=>{comparisons=comparisons.filter(x=>x!==d.experiment);comparisonSessions.delete(d.experiment);paused=false;persist();load(true);}));}legend.append(item);});host.append(legend);
  if(typeof CaseComparisonsView!=='undefined')controls.append(button('Compare rollout cases',()=>CaseComparisonsView.open({selected:{experiment:scope.experiment,...(scope.environment?{environment:scope.environment}:{})},...(comparisons[0]?{reference:{experiment:comparisons[0]}}:{})})));
  host.append(el('p',`${paused?'Paused · selected data held':'Live · refreshes every 10 seconds'}${checked?' · captured '+new Date(checked).toLocaleTimeString():''}. X: ${clock||'unavailable'}${halfLife?' · faint raw, bold EMA; computed before interval selection':''}.`,'telemetry-note'));
  const active=data.session_selection?.selected;
  if((data.session_inventory?.total||sessions.length)>1)host.append(el('p',sessionChoice==='*'?'Sessions are selected separately for each chart.':active?`Session ${active.ordinal} · ${active.producer} · steps ${active.start}–${active.end} · shared across charts; sessions ordered by first receipt.`:'The selected worker/session has no records in this clock. Choose another session.','telemetry-note'));
  for(const d of datasets)if(d.total_series>d.series.length)host.append(el('p',`${d.experiment}: ${d.series.length} of ${d.total_series} metric series loaded. Use Browse metrics to find another signal.`,'telemetry-note'));
  if(!data.records&&!data.series.length){host.append(el('p','No native logs for this selection. Import existing logs or connect your trainer; execution instrumentation is optional.','telemetry-empty'));return;}
  const panels=[];
  const addPanel=(group,label,candidates,extra=false)=>{
   const primary=candidates.find(s=>s.id===selection.get(group))||defaultSeries(candidates);selection.set(group,primary.id);
   const streams=[{series:primary,color:colors[0]}],pending=[];
   datasets.slice(1).forEach((d,i)=>{const matches=d.series.filter(s=>comparable(primary,s)),key=group+'/'+d.experiment;const chosen=matches.find(s=>s.id===selection.get(key))||(matches.length===1?matches[0]:null);if(chosen){selection.set(key,chosen.id);streams.push({series:chosen,color:colors[i+1]});}else pending.push({dataset:d,matches,key});});
   panels.push({group,label,candidates,primary,streams,pending,extra});
  };
  const groups=summaryView?previewSignals(visible).map(s=>[s.group,names[s.group]]):Object.entries(names);
  for(const [group,label]of groups){const candidates=visible.filter(s=>s.group===group);if(candidates.length)addPanel(group,label,candidates);}
  for(const id of extraMetrics){const s=visible.find(s=>s.id===id);if(s&&!panels.some(p=>p.primary.id===id))addPanel('extra/'+id,s.label,[s],true);}
  if(!summaryView&&extraMetrics.size<6){const unused=visible.filter(s=>!panels.some(p=>p.primary.id===s.id));if(unused.length)host.append(choose('Add metric',[['','Add another signal…'],...unused.map(s=>[s.id,s.label+' · '+s.context.split])],'',id=>{if(id){extraMetrics.add(id);persist();render();}}));}
  const steps=panels.flatMap(p=>p.streams.flatMap(({series:s})=>s.full_range?[s.full_range.start,s.full_range.end].filter(v=>v!=null):s.points.map(p=>p.step))),full=steps.length?[Math.min(...steps),Math.max(...steps)]:[0,1],bounds=range||full;
  const interval=el('form',undefined,'telemetry-interval'),a=el('input'),b=el('input');
  for(const[input,label,value]of [[a,'From step',bounds[0]],[b,'To step',bounds[1]]]){const l=el('label',label,'telemetry-control');input.type='number';input.step='any';input.required=true;input.value=value;input.setAttribute('aria-label',label);l.append(input);interval.append(l);}
  const apply=button('Select interval');apply.type='submit';interval.append(apply,button('Full range',()=>{range=null;persist();load(true);}));interval.onsubmit=e=>{e.preventDefault();b.setCustomValidity(Number(b.value)<Number(a.value)?'End must follow start.':'');if(interval.reportValidity()){range=[Number(a.value),Number(b.value)];paused=true;++seq;persist();load(true);}};a.oninput=b.oninput=()=>b.setCustomValidity('');if(summaryView&&!range)displayBody.append(interval);else host.append(interval);
  const grid=el('div',undefined,'telemetry-grid telemetry-aligned telemetry-'+(layout||(comparisons.length?'stacked':'compact')));
  for(const {group,label,candidates,primary,streams,pending,extra}of panels){
   const card=el('article',undefined,'telemetry-card');card.dataset.signalGroup=group;card.id='training-signal-'+group;const head=el('div',undefined,'telemetry-card-heading');head.append(el('h3',label));
   const options=el('details',undefined,'telemetry-card-options'),optionTitle=el('summary',logarithmic.has(group)?'Options · log':'Options'),optionBody=el('div',undefined,'telemetry-card-options-body');options.dataset.group=group;options.open=openOptions.has(group);optionTitle.setAttribute('aria-label',label+' chart options');options.append(optionTitle,optionBody);optionBody.append(choose(label+' scale',[['linear','Linear'],['log','Log']],logarithmic.has(group)?'log':'linear',v=>{v==='log'?logarithmic.add(group):logarithmic.delete(group);persist();render();}));
   if(candidates.length>1)optionBody.append(choose(label+' metric',candidates.map(s=>[s.id,s.label+' · '+s.context.split+(candidates.filter(c=>c.label===s.label&&c.context.split===s.context.split).length>1?' · '+labelFor(s):'')]),primary.id,v=>{selection.set(group,v);persist();render();}));
   if(extra)optionBody.append(button('Remove chart',()=>{extraMetrics.delete(primary.id);selection.delete(group);persist();render();}));options.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();options.open=false;optionTitle.focus();}};head.append(options);card.append(head,el('p',primary.label,'telemetry-series-name'));
   for(const {dataset:d,matches,key}of pending){
    if(matches.length>1)card.append(choose('Stream · '+d.experiment,[['','Choose a session…'],...matches.map(s=>[s.id,labelFor(s,d)])],'',v=>{selection.set(key,v);persist();render();}));
    else card.append(el('p',`${d.experiment}: no matching series loaded for this definition, clock and population.`,'telemetry-empty'));
   }
   const values=el('div',undefined,'telemetry-window-values');for(const {series:s,color}of streams){const stat=seriesStats(s,bounds),item=el('div');item.style.borderColor=color;item.append(el('strong',stat.last?fmt(stat.last.value):'—'),el('span',`${s.context.experiment} · ${primary.unit}`),el('small',stat.last?`${fmt(stat.measured)}/${fmt(stat.total)} measured · latest at ${stat.last.step}${stat.delta!=null?' · Δ '+fmt(stat.delta):''}`:'No measured update in this interval'));if(stat.minimum&&stat.maximum)item.append(el('small',`Range ${fmt(stat.minimum.value)}–${fmt(stat.maximum.value)}`));values.append(item);}card.append(values,chart(streams,bounds,group));
   if(streams.some(({series:s})=>s.representation?.reduced))card.append(el('p','Plot retains first, last and extreme points per bucket. Counts and EMA use every coordinate; inspect updates for the full sequence.','telemetry-note'));
   const footer=el('div',undefined,'telemetry-card-footer');footer.append(button('Inspect updates',()=>inspectInterval(streams)));if(window.CaseComparisonsView)footer.append(button('Compare linked rollouts',()=>compareLinked(streams)));footer.append(el('span',primary.context.split+' · '+primary.context.population));card.append(footer);
   const detail=el('details');detail.append(el('summary','Definition & sources'),el('p',primary.definition),el('p',`${primary.unit} · ${primary.reduction}. Native key: ${primary.native_key}.`));for(const {series:s}of streams)detail.append(el('p',`${s.context.experiment}: ${s.context.framework} ${s.context.framework_version} · ${s.context.objective} · ${s.context.session} · ${s.context.producer}`));card.append(detail);grid.append(card);
  }
  host.append(grid);if(location.hash.startsWith('#training-signal-')&&openedSignal!==location.hash){const target=document.getElementById(location.hash.slice(1));if(target){openedSignal=location.hash;requestAnimationFrame(()=>target.scrollIntoView({block:'start'}));}}
  const missing=expectedGroups(data.series.filter(s=>s.context.clock===clock)).filter(g=>!panels.some(p=>p.group===g));if(missing.length){const p=el('p',`Not recorded in this clock: ${missing.map(g=>names[g]).join(', ')}. `,'telemetry-empty');const guide=el('a','Add these signals');guide.href='/connections#telemetry-section';p.append(guide);host.append(p);}
  const next=el('div',undefined,'telemetry-next');next.append(link('Inspect execution timing →','execution'),link('Compare rollout behavior →','measures'),link('Inspect training samples →','training'));host.append(next);
  if(focused)host.querySelector('[data-telemetry-control="'+CSS.escape(focused)+'"]')?.focus({preventScroll:true});
 }
 async function load(force=false){
  const host=document.querySelector('#trainer-telemetry');if(!host||document.hidden)return;
  const mode=query().get('view'),route=typeof OverviewLayout!=='undefined'?OverviewLayout.mode(location.search):null;
  if(location.pathname!=='/'||(route?route.section!=='summary'&&!(route.section==='training'&&route.panel==='signals'):mode&&mode!=='health')){host.hidden=true;return;}
  if(window.TrainingContext&&!scope.experiment){++seq;host.hidden=false;host.replaceChildren(el('p','Trainer signals are shown per run. Choose a run to inspect its updates; add comparisons in Training.','telemetry-note'),button('Choose a training run',()=>TrainingContext.open()));return;}
  if(!force&&(paused&&data||dragging||document.querySelector('.telemetry-dialog[open]')||host.querySelector('.telemetry-options[open],.telemetry-card-options[open]')||host.contains(document.activeElement)&&document.activeElement?.matches('input,select')))return;
  comparisons=[...new Set(comparisons)].filter(x=>x!==scope.experiment).slice(0,2);
  const ticket=++seq,runs=[scope.experiment||'',...(route?.section==='summary'?[]:comparisons)];
  try{
   host.setAttribute('aria-busy','true');
   const values=await Promise.all(runs.map(async experiment=>{const prior=datasets.find(d=>d.experiment===experiment),q=dataParams({experiment,as_of:paused?(prior?.as_of??cutoffs[experiment]):null},range);if(experiment)for(const[k,v]of Object.entries(sessionParams(choiceFor(experiment))))q.set(k,v);q.set('half_life',halfLife);for(const id of [...new Set([...selection.values(),...extraMetrics])].slice(0,40))q.append('series',id);const r=await fetch('/api/trainer-telemetry/query?'+q);if(!r.ok)throw Error('Trainer telemetry is unavailable.');return {...await r.json(),experiment};}));
   if(ticket!==seq)return;host.hidden=route?.section==='summary'&&!scope.experiment;checked=new Date().toISOString();failure='';const signature=JSON.stringify(values.map(({captured_at,...d})=>d));data=values[0];datasets=values;
   const count=document.getElementById('summary-native-count');if(count){count.textContent=Number(data.total_records??data.records).toLocaleString();count.title='Native trainer logs in the selected clock and session scope';}
   if(signature!==saved||force){saved=signature;render();}
  }catch(e){if(ticket===seq){failure=e.message;saved='';if(data){range=data.range?.every(v=>v!=null)?data.range:null;clock=data.clock||clock;halfLife=data.series[0]?.representation?.half_life??halfLife;persist();render();}else{host.hidden=false;host.replaceChildren(el('p',e.message),button('Use latest session',()=>{sessionChoice='';comparisonSessions.clear();persist();load(true);}));}}}finally{if(ticket===seq)host.removeAttribute('aria-busy');}
 }
  window.addEventListener('jev:scope',e=>{const initialized=Object.hasOwn(scope,'experiment'),changed=scope.experiment!==e.detail.experiment||scope.environment!==e.detail.environment;scope=e.detail;if(changed){++seq;data=null;datasets=[];saved='';if(initialized){paused=false;range=null;clock='';sessionChoice='';comparisonSessions.clear();selection.clear();extraMetrics.clear();persist();}}load();});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
 document.getElementById('refresh')?.addEventListener('click',()=>{paused=false;persist();load(true);});
 let screenBand=innerWidth<700?0:innerWidth<1100?1:2;
 window.addEventListener('resize',()=>{const next=innerWidth<700?0:innerWidth<1100?1:2;if(next!==screenBand){screenBand=next;if(data&&!document.querySelector('#trainer-telemetry')?.hidden)render();}});
 setInterval(load,10000);
})();
