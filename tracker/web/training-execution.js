/* One captured population for the timeline, curves and evidence drawer. */
(() => {
 'use strict';
 const key=(p,id)=>JSON.stringify([p,id]), human=s=>String(s||'Unknown').replaceAll('_',' ');
 function model(data){
  const lanes=new Map(), positions=new Map(), series=new Map(), coordinates=new Map();
  const clocks=new Set((data.executions||[]).map(e=>e.record.timing?.clock).filter(Boolean));
  const clock=data.selection?.clock||(clocks.size===1?[...clocks][0]:null);
  for(const e of data.executions||[]){
   const r=e.record,t=r.timing;if(!t||t.clock!==clock)continue;
   const lane=key(e.producer,r.context.worker||r.context.server||r.kind);
   if(!lanes.has(lane))lanes.set(lane,{id:lane,label:r.context.worker||r.context.server||human(r.kind),producer:e.producer,rows:[]});
   lanes.get(lane).rows.push(e);
   for(const ref of r.telemetry||[]){const id=key(ref.producer,ref.id);if(!positions.has(id))positions.set(id,[]);positions.get(id).push(e);}
  }
  let unplaced=0;
  for(const log of data.logs||[]){
   const matches=positions.get(log.id)||[];
   if(matches.length!==1||matches[0].record.timing?.end==null){unplaced++;continue;}
   const execution=matches[0],r=log.record,time=execution.record.timing.end;
   const context=JSON.stringify([log.producer,r.session,r.clock,r.split,r.objective,r.population,r.framework,r.framework_version]);
   if(!coordinates.has(context))coordinates.set(context,[]);
   coordinates.get(context).push({time,log:log.id,execution:execution.id,step:r.step});
   function add(id,spec,value,status){
    const signature=context+'|'+id+'|'+JSON.stringify(spec);
    if(!series.has(signature))series.set(signature,{id:signature,context,...spec,producer:log.producer,session:r.session,population:r.population,points:[]});
    series.get(signature).points.push({time,value,status,log:log.id,execution:execution.id,step:r.step});
   }
   for(const [name,m] of Object.entries(r.metrics)){
    const {value,status,...spec}=m;add(name,spec,value,status);
   }
   for(const age of log.policy_age?.clocks||[])add('policy-age/'+age.clock+'/'+age.unit,
    {label:'Policy age',group:'age',unit:human(age.unit)+'s',definition:'Token-weighted policy lag across referenced training uses; only tokens with a matching policy clock contribute. Clock: '+age.clock,reduction:'known-token weighted mean'},age.mean_age,age.mean_age===null?'missing':'recorded');
  }
  return {lanes:[...lanes.values()].map(l=>({...l,rows:l.rows.sort((a,b)=>a.record.timing.start-b.record.timing.start)})),
   series:[...series.values()].map(s=>{
    // Separate native and comparison receipts can share one update boundary.
    // An absent metric in the other receipt is not a missing measurement here.
    const present=new Set(s.points.map(p=>p.time)),missing=[];
    for(const p of coordinates.get(s.context))if(!present.has(p.time)){present.add(p.time);missing.push({...p,value:null,status:'missing'});}
    return {...s,points:[...s.points,...missing].sort((a,b)=>a.time-b.time)};
   }),unplaced};
 }
 function boundsFor(data){
  const clock=data.clocks?.find(c=>c.clock===data.selection?.clock),timings=(data.executions||[]).map(e=>e.record.timing).filter(t=>t&&(!data.selection?.clock||t.clock===data.selection.clock));
  const origin=clock?.start??0,fullLo=clock?.start??Math.min(...timings.map(t=>t.start)),fullHi=clock?.end??Math.max(...timings.map(t=>t.end??t.start));
  const lo=data.selection?.start??(Number.isFinite(fullLo)?fullLo:0),hi=data.selection?.end??(Number.isFinite(fullHi)?fullHi:lo+1);
  return {origin,lo,hi,fullLo:Number.isFinite(fullLo)?fullLo:lo,fullHi:Number.isFinite(fullHi)?fullHi:hi};
 }
 function zoomRange(bounds,factor,center=(bounds.lo+bounds.hi)/2){
  const available=bounds.fullHi-bounds.fullLo;if(available<=0)return {start:bounds.fullLo,end:bounds.fullHi};
  const width=Math.min(available,Math.max((bounds.hi-bounds.lo)*factor,available/10000));
  const start=Math.max(bounds.fullLo,Math.min(bounds.fullHi-width,center-width/2));return {start,end:start+width};
 }
 function readout(series,selection){
  const points=series.points,eligible=selection?points.filter(p=>p.execution===selection):points;
  const point=eligible.at(-1),finite=point?.value!=null&&Number.isFinite(point.value);
  const previous=point?points.filter(p=>p.time<point.time&&p.value!=null&&Number.isFinite(p.value)).at(-1):null;
  return {point:finite?point:null,previous,delta:finite&&previous?point.value-previous.value:null,
   measured:points.filter(p=>p.value!=null&&Number.isFinite(p.value)).length,total:points.length};
 }
 function plotData(points,{alpha=0,log=false}={}){
  if(!Number.isFinite(alpha)||alpha<0||alpha>1)throw Error('EMA alpha must be between zero and one');
  let average=null,omitted=0;
  const raw=[],trend=[];
  for(const p of points){
   const finite=p.value!=null&&Number.isFinite(p.value),valid=finite&&(!log||p.value>0);
   if(finite&&!valid)omitted++;
   if(!valid){average=null;raw.push({...p,value:null});trend.push({...p,value:null});continue;}
   average=average==null||!alpha?p.value:alpha*p.value+(1-alpha)*average;
   raw.push(p);trend.push({...p,value:average});
  }
  const transform=v=>log?Math.log10(v):v,values=raw.filter(p=>p.value!=null).map(p=>transform(p.value));
  let lo=values.length?Math.min(...values):0,hi=values.length?Math.max(...values):1;
  if(lo===hi){const pad=log ? .25 : Math.abs(lo)*.05||1;lo-=pad;hi+=pad;}
  return {raw,trend,lo,hi,omitted};
 }
 if(typeof module!=='undefined'&&module.exports){module.exports={model,boundsFor,zoomRange,readout,plotData};return;}
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const svg=(tag,attrs={})=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;};
 const fmt=v=>v==null?'Unavailable':v!==0&&(Math.abs(v)<.001||Math.abs(v)>=1e6)?Number(v).toExponential(2):Number(v).toLocaleString(undefined,{maximumFractionDigits:3});
 const sourceMessage=value=>({source_revision_not_declared:'A rollout revision is needed to open its behavior map.',source_not_delivered:'The linked rollout has not arrived yet.',experiment_conflict:'The linked source belongs to a different experiment.',invalid_source_spans:'The recorded sample text does not match its source.'}[value]||human(value));
 const time=v=>Math.abs(v)<60?fmt(v)+'s':Math.abs(v)<3600?Math.floor(v/60)+'m '+fmt(v%60)+'s':Math.floor(v/3600)+'h '+Math.floor(v%3600/60)+'m';
 const params=()=>new URLSearchParams(location.search),active=()=>location.pathname==='/'&&params().get('view')==='execution';
 let scope={},data=null,request=0,selected=params().get('execution_focus'),signature='',error='',dragging=false,checkedAt=null;
 let paused=params().get('execution_paused')==='1',search=params().get('execution_search')||'',stateFilter=params().get('execution_state')||'',kindFilter=params().get('execution_kind')||'';
 let lastFocus=selected?'span:'+selected:'',drawer=null,small=innerWidth<=1280;
 let sampleFocus=null,sampleSearch='',samplePage=0;
 let smoothing=Number(params().get('execution_ema'))||0;
 if(![0,.1,.3,.6].includes(smoothing))smoothing=0;
 const logGroups=new Set((params().get('execution_log')||'').split(',').filter(Boolean));
 const picks=new Map(),rangeHistory=[];
 function button(label,action,cls){const b=el('button',label,cls);b.type='button';b.onclick=action;return b;}
 function writeURL(values){const u=new URL(location.href);for(const[k,v]of Object.entries(values))v==null||v===''?u.searchParams.delete('execution_'+k):u.searchParams.set('execution_'+k,v);history.replaceState(history.state,'',u);}
 function options(){const p=params(),q={experiment:scope.experiment};if(scope.environment)q.environment=scope.environment;for(const k of ['clock','start','end','limit']){const v=p.get('execution_'+k);if(v!==null)q[k]=k==='clock'?v:Number(v);}return q;}
 function change(values,remember=false){
  if(remember){const p=params();rangeHistory.push(Object.fromEntries(['start','end'].map(k=>[k,p.get('execution_'+k)])));if(rangeHistory.length>25)rangeHistory.shift();}
  writeURL(values);signature='';load(true);
 }
 function download(value){const a=el('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));a.download='rilldex-execution-view.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
 function filterRows(rows){return rows.filter(e=>{
  const r=e.record,state=stateFilter==='active'?['queued','running','suspended'].includes(r.state):!stateFilter||r.state===stateFilter;
  return state&&(!kindFilter||r.kind===kindFilter)&&(!search||[r.id,e.producer,...Object.values(r.context||{}),r.rollout?.id].join(' ').toLowerCase().includes(search.toLowerCase()));
 });}
 async function load(force=false){
  const host=document.getElementById('training-execution');
  if(!active()||!host||document.hidden||!force&&(paused&&data||dragging||host.contains(document.activeElement)&&document.activeElement?.matches('input,select')||drawer?.open))return;
  host.hidden=false;
  if(!scope.experiment&&!params().get('execution_saved')){host.replaceChildren(el('p','Choose an experiment above to view execution and training signals.','ex-empty'));return;}
  const seq=++request,p=params(),q=p.has('execution_saved')?{saved:p.get('execution_saved')}:options();
  try{
   const r=await fetch('/api/training-execution?'+new URLSearchParams(q));const value=await r.json();if(seq!==request)return;if(!r.ok)throw Error(value.error||'Execution view is unavailable');
   checkedAt=new Date();
   if(!q.saved&&!q.clock){const clocks=(value.clocks||[]).filter(c=>c.clock).sort((a,b)=>b.records-a.records);if(clocks.length){change({clock:clocks[0].clock});return;}}
   if(signature!==value.snapshot_id||data?.saved!==value.saved){data=value;signature=value.snapshot_id;error='';render();}else refreshStatus();
  }catch(e){if(seq===request){error=e.message;signature='';if(data)render();else host.replaceChildren(el('p',error,'ex-error'));}}
 }
 function refreshStatus(){
  const status=document.getElementById('execution-status');if(!status)return;
  const mode=data.saved?'Saved':paused?'Paused':drawer?.open?'Inspecting':'Live';status.dataset.mode=mode.toLowerCase();
  status.replaceChildren(el('span',mode,'ex-live-label'),el('span',data.saved?'Captured '+new Date(data.captured_at).toLocaleString():paused?'Displayed data held':drawer?.open?'Refresh resumes when details close':checkedAt?'Checked '+checkedAt.toLocaleTimeString()+' · every 5s':'Refreshes every 5s','ex-muted'));
 }
 function focus(id,origin){
  if(origin)lastFocus=origin;selected=id;writeURL({focus:id});render();
  if(!drawer?.open&&(origin||!id&&lastFocus))document.querySelector('[data-focus-key="'+CSS.escape(origin||lastFocus)+'"]')?.focus({preventScroll:true});
 }
 function mapLink(id,label='Open behavior map'){const a=el('a',label);a.href='/semantic-map?'+new URLSearchParams({run:id,observer:'source',return_to:location.pathname+location.search});return a;}
 function ordered(kind){return filterRows(data.executions).filter(e=>(!kind||e.record.kind===kind)&&e.record.timing?.clock===data.selection.clock).sort((a,b)=>a.record.timing.start-b.record.timing.start||a.id.localeCompare(b.id));}
 function navigateExecution(direction,keyboard=false){const current=data.executions.find(e=>e.id===selected),rows=ordered(current?.record.kind),i=rows.findIndex(e=>e.id===selected),next=rows[i+direction];if(next)focus(next.id,keyboard?'span:'+next.id:undefined);}
 function detail(){
  const aside=el('aside',undefined,'ex-detail');aside.id='execution-detail';aside.setAttribute('aria-label','Selected execution');
  const execution=data.executions.find(e=>e.id===selected),head=el('div',undefined,'ex-detail-heading');
  head.append(el('span','Selected operation','ex-kicker'),button('Close',()=>focus(null),'ex-close'));aside.append(head);
  if(!execution){aside.append(el('h3','Selection outside this interval'),el('p','Use Undo interval or Full range to return to the selected operation.','ex-muted'));return aside;}
  const r=execution.record,logs=data.logs.filter(l=>(r.telemetry||[]).some(ref=>key(ref.producer,ref.id)===l.id)),bounds=boundsFor(data);
  const ids=new Set([...execution.sample_ids,...logs.flatMap(l=>l.sample_ids)]),samples=data.samples.filter(s=>ids.has(s.id));
  const kindLabel={inference:'Model inference',rollout:'Rollout',environment:'Environment step',verification:'Verification',learner_update:'Learner update',weight_sync:'Weight sync',configuration:'Configuration change'}[r.kind]||human(r.kind);
  aside.append(el('h3',r.kind==='learner_update'&&logs.length?'Update '+[...new Set(logs.map(l=>l.record.step))].join(', '):kindLabel),el('p',r.context.worker||r.context.server||execution.producer,'ex-muted'),el('span',human(r.state),'ex-state ex-'+r.state));
  if(r.timing){const timing=el('p',time(r.timing.start-bounds.origin)+' → '+(r.timing.end==null?'End not reported':time(r.timing.end-bounds.origin)),'ex-timing');aside.append(timing);}
  const nav=el('div',undefined,'ex-detail-actions'),rows=ordered(r.kind),i=rows.findIndex(e=>e.id===selected);
  const prev=button('← Previous',()=>navigateExecution(-1)),next=button('Next →',()=>navigateExecution(1));prev.dataset.control='previous-operation';next.dataset.control='next-operation';prev.setAttribute('aria-label','Previous operation');next.setAttribute('aria-label','Next operation');prev.disabled=i<=0;next.disabled=i<0||i===rows.length-1;nav.append(prev,next);
  const zoom=button('Zoom to operation',()=>{if(!r.timing)return;const width=Math.max((r.timing.end??r.timing.start)-r.timing.start,(bounds.fullHi-bounds.fullLo)/40),range=zoomRange({...bounds,lo:0,hi:width},2,(r.timing.start+(r.timing.end??r.timing.start))/2);if(small)focus(null);change(range,true);});zoom.disabled=!!data.saved||!r.timing;nav.append(zoom);aside.append(nav);
  const facts=el('dl');for(const[k,v]of Object.entries({...r.context,...r.configuration})){if(v==null)continue;facts.append(el('dt',human(k)),el('dd',typeof v==='object'?JSON.stringify(v):String(v)));}aside.append(facts);
  if(r.policy)aside.append(el('p',`Policy ${r.policy.index} · ${human(r.policy.unit)}`));
  if(execution.run_id)aside.append(mapLink(execution.run_id));
  if(r.rollout&&!execution.run_id)aside.append(el('p',sourceMessage(execution.source_status),'ex-muted'));
  for(const log of logs){
   aside.append(el('h4','Update '+log.record.step),el('p',`${log.declared_uses-log.unresolved_uses.length} / ${log.declared_uses} training-use links resolved · ${human(log.coverage)} batch coverage`,'ex-muted'));
   for(const age of log.policy_age.clocks)aside.append(el('p',`Policy age ${fmt(age.mean_age)} · ${age.known_tokens} / ${age.recorded_target_tokens} target tokens mapped`));
  }
  aside.append(el('h4',samples.length+' linked samples'));
  if(sampleFocus!==selected){sampleFocus=selected;sampleSearch='';samplePage=0;}
  if(samples.length>8){const searchBox=el('input');searchBox.type='search';searchBox.placeholder='Find linked sample…';searchBox.setAttribute('aria-label','Find linked sample');searchBox.dataset.control='sample-search';searchBox.value=sampleSearch;searchBox.oninput=()=>{sampleSearch=searchBox.value;samplePage=0;render();};aside.append(searchBox);}
  const visibleSamples=samples.filter(s=>[s.sample_id,s.producer,s.split].join(' ').toLowerCase().includes(sampleSearch.toLowerCase()));
  const pageSize=20;samplePage=Math.max(0,Math.min(samplePage,Math.ceil(visibleSamples.length/pageSize)-1));
  if(!visibleSamples.length&&samples.length)aside.append(el('p','No linked samples match this search.','ex-muted'));
  for(const s of visibleSamples.slice(samplePage*pageSize,(samplePage+1)*pageSize)){
   const card=el('div',undefined,'ex-sample');card.append(el('strong',s.sample_id),el('span',s.split,'ex-muted'));
   for(const score of s.scores)card.append(el('p',`${score.data.component||'Reward'}: ${fmt(score.data.value)} · ${human(score.data.status)}`));
   for(const selection of s.selections)card.append(el('p',`${selection.data.filter||'Selection'}: ${human(selection.data.decision)}`));
   card.append(el('p',s.uses.length?`${s.uses.length} recorded training use${s.uses.length===1?'':'s'}`:'Training use not recorded','ex-muted'));
   if(s.run_id)card.append(mapLink(s.run_id));else card.append(el('p',sourceMessage(s.source_status),'ex-muted'));aside.append(card);
  }
  if(visibleSamples.length>pageSize){const pages=el('div',undefined,'ex-detail-actions'),prevPage=button('← Samples',()=>{samplePage--;render();}),nextPage=button('Samples →',()=>{samplePage++;render();});prevPage.setAttribute('aria-label','Previous sample page');nextPage.setAttribute('aria-label','Next sample page');prevPage.dataset.control='sample-previous';nextPage.dataset.control='sample-next';prevPage.disabled=samplePage===0;nextPage.disabled=(samplePage+1)*pageSize>=visibleSamples.length;pages.append(prevPage,el('span',`${samplePage*pageSize+1}–${Math.min((samplePage+1)*pageSize,visibleSamples.length)} of ${visibleSamples.length}`,'ex-muted'),nextPage);aside.append(pages);}
  const raw=el('details');raw.dataset.disclosure='execution-raw';raw.append(el('summary','Recorded IDs & evidence'),el('pre',JSON.stringify({execution,logs},null,2)));aside.append(raw);return aside;
 }
 function brush(g,bounds,at,x,y,height){
  let begin=null,selection=null;
  const clear=()=>{begin=null;dragging=false;selection?.remove();selection=null;};
  g.onpointerdown=e=>{if(data.saved||e.button!==0||e.target.closest('.ex-block,circle'))return;e.preventDefault();begin=at(e);dragging=true;selection=svg('rect',{x:x(begin),y,width:0,height,class:'ex-selection'});g.append(selection);g.setPointerCapture(e.pointerId);};
  g.onpointermove=e=>{if(begin===null)return;const end=at(e);selection.setAttribute('x',Math.min(x(begin),x(end)));selection.setAttribute('width',Math.abs(x(end)-x(begin)));};
  g.onpointerup=e=>{if(begin===null)return;const end=at(e),start=begin;clear();if(Math.abs(end-start)>(bounds.hi-bounds.lo)*.005)change({start:Math.min(start,end),end:Math.max(start,end)},true);};
  g.onpointercancel=clear;g.onlostpointercapture=clear;
 }
 function timeline(view,bounds){
  const box=el('div',undefined,'ex-timeline'),width=1000,left=160,right=20,rowHeight=40,range=bounds.hi-bounds.lo||1,x=v=>left+(width-left-right)*(v-bounds.lo)/range;
  let rows=[];for(const lane of view.lanes){const tracks=[];for(const e of filterRows(lane.rows)){let i=tracks.findIndex(t=>t.end<=e.record.timing.start);if(i<0){i=tracks.length;tracks.push({end:-Infinity,rows:[]});}tracks[i].rows.push(e);tracks[i].end=e.record.timing.end??Infinity;}for(const [i,t]of tracks.entries())rows.push({label:lane.label+(i?' · '+(i+1):''),producer:lane.producer,rows:t.rows});}
  if(!rows.length){box.append(el('p','No operations match these timeline filters.','ex-empty'),button('Clear filters',()=>setFilters({search:'',state:'',kind:''})));return box;}
  const g=svg('svg',{viewBox:`0 0 ${width} ${Math.max(100,rows.length*rowHeight+52)}`,role:'group','aria-label':'Sampler and learner timeline. Select a block or drag a time interval.'});
  for(let tick=0;tick<=4;tick++){const value=bounds.lo+range*tick/4;g.append(svg('line',{x1:x(value),x2:x(value),y1:28,y2:rows.length*rowHeight+35,class:'ex-gridline'}));const label=svg('text',{x:x(value),y:18,'text-anchor':tick===4?'end':'start'});label.textContent=time(value-bounds.origin);g.append(label);}
  const picked=data.executions.find(e=>e.id===selected),related=new Set(picked?.sample_ids||[]);
  if(picked)for(const log of data.logs)if((picked.record.telemetry||[]).some(ref=>key(ref.producer,ref.id)===log.id))for(const id of log.sample_ids)related.add(id);
  let first=true;
  rows.forEach((lane,index)=>{const y=index*rowHeight+34,label=svg('text',{x:8,y:y+18,class:'ex-lane-label'});label.textContent=lane.label.length>23?lane.label.slice(0,21)+'…':lane.label;const title=svg('title');title.textContent=lane.producer+' · '+lane.label;label.append(title);g.append(label);
   for(const e of lane.rows){const r=e.record,t=r.timing;if(t.start>bounds.hi||(t.end!=null&&t.end<bounds.lo))continue;
    const focusKey='span:'+e.id,rect=svg('rect',{x:x(Math.max(t.start,bounds.lo)),y,width:Math.max(5,x(Math.min(t.end??t.start,bounds.hi))-x(Math.max(t.start,bounds.lo))),height:25,rx:4,tabindex:e.id===selected||first?0:-1,role:'button','data-focus-key':focusKey,
     class:'ex-block ex-'+r.state+' ex-kind-'+r.kind+(e.id===selected?' ex-selected':'')+(e.sample_ids.some(id=>related.has(id))?' ex-related':''),
     'aria-label':`${human(r.kind)} · ${lane.label} · ${human(r.state)} · ${fmt(t.start-bounds.origin)} seconds`,'aria-pressed':String(e.id===selected)});first=false;
    const tip=svg('title');tip.textContent=`${human(r.kind)} · ${human(r.state)}\n${time(t.start-bounds.origin)}–${t.end==null?'end not reported':time(t.end-bounds.origin)}`;rect.append(tip);
    rect.onclick=()=>focus(e.id,focusKey);rect.onkeydown=ev=>{if(['Enter',' '].includes(ev.key)){ev.preventDefault();focus(e.id,focusKey);}else if(['ArrowLeft','ArrowRight'].includes(ev.key)){ev.preventDefault();selected=e.id;navigateExecution(ev.key==='ArrowLeft'?-1:1,true);}};g.append(rect);
   }
  });
  const at=event=>{const rect=g.getBoundingClientRect();return Math.max(bounds.lo,Math.min(bounds.hi,bounds.lo+((event.clientX-rect.left)/rect.width*width-left)/(width-left-right)*range));};brush(g,bounds,at,x,28,rows.length*rowHeight+7);box.append(g);return box;
 }
 function curve(series,bounds){
  const log=logGroups.has(series.group),g=svg('svg',{viewBox:'0 0 360 155',role:'group','aria-label':series.label+' on the selected execution clock'+(log?' · logarithmic scale':'')});
  const plot=plotData(series.points.filter(p=>p.time>=bounds.lo&&p.time<=bounds.hi),{alpha:smoothing,log}),points=plot.raw,valid=points.filter(p=>p.value!=null);
  const box=el('div',undefined,'ex-plot');
  if(plot.omitted)box.append(el('p',`${plot.omitted} nonpositive point${plot.omitted===1?'':'s'} not plotted on log scale. Switch to Linear to see all values.`,'ex-scale-note'));
  if(!valid.length){box.append(el('p',log?'No positive point in this interval.':'No finite point in this interval.','ex-muted'));return box;}
  const {lo,hi}=plot,transform=v=>log?Math.log10(v):v;
  const x=v=>44+300*(v-bounds.lo)/(bounds.hi-bounds.lo||1),y=v=>115-95*(transform(v)-lo)/(hi-lo);
  const ticks=log?[lo,(lo+hi)/2,hi]:[lo,hi];
  for(const t of ticks){const v=log?10**t:t;g.append(svg('line',{x1:44,x2:344,y1:y(v),y2:y(v),class:'ex-gridline'}));const label=svg('text',{x:40,y:y(v)+4,'text-anchor':'end'});label.textContent=log?v.toExponential(1):fmt(v);g.append(label);}
  const selectedTime=data.executions.find(e=>e.id===selected)?.record.timing?.end;if(selectedTime!=null&&selectedTime>=bounds.lo&&selectedTime<=bounds.hi)g.append(svg('line',{x1:x(selectedTime),x2:x(selectedTime),y1:15,y2:120,class:'ex-selected-time'}));
  const path=(items,cls)=>{let d='',open=false;for(const p of items){if(p.value==null){open=false;continue;}d+=`${open?'L':'M'}${x(p.time)} ${y(p.value)} `;open=true;}g.append(svg('path',{d,fill:'none',class:cls}));};
  path(points,'ex-curve'+(smoothing?' ex-raw':''));if(smoothing)path(plot.trend,'ex-curve ex-ema');
  for(const [i,p]of valid.entries()){const focusKey='point:'+series.id+':'+p.log,dot=svg('circle',{cx:x(p.time),cy:y(p.value),r:p.execution===selected?5:3,tabindex:p.execution===selected||i===0?0:-1,role:'button','data-focus-key':focusKey,'aria-label':`Update ${p.step}: ${fmt(p.value)} ${series.unit}`});dot.onclick=()=>focus(p.execution,focusKey);dot.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();focus(p.execution,focusKey);}else if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();const next=valid[i+(e.key==='ArrowLeft'?-1:1)];if(next)focus(next.execution,'point:'+series.id+':'+next.log);}};const title=svg('title');title.textContent=`Update ${p.step} · ${time(p.time-bounds.origin)} · ${fmt(p.value)} ${series.unit}`;dot.append(title);g.append(dot);}
  for(const [v,anchor]of [[bounds.lo,'start'],[bounds.hi,'end']]){const label=svg('text',{x:x(v),y:140,'text-anchor':anchor});label.textContent=time(v-bounds.origin);g.append(label);}
  const at=e=>{const rect=g.getBoundingClientRect();return Math.max(bounds.lo,Math.min(bounds.hi,bounds.lo+((e.clientX-rect.left)/rect.width*360-44)/300*(bounds.hi-bounds.lo)));};brush(g,bounds,at,x,20,95);box.append(g);return box;
 }
 function setFilters(values){if('search'in values)search=values.search;if('state'in values)stateFilter=values.state;if('kind'in values)kindFilter=values.kind;writeURL({search,state:stateFilter,kind:kindFilter});render();}
 function controls(bounds){
  const box=el('div',undefined,'ex-range-tools'),row=el('div',undefined,'ex-range-row');
  const range=el('div',undefined,'ex-range-label');range.append(el('strong',time(bounds.lo-bounds.origin)+' – '+time(bounds.hi-bounds.origin)),el('span','Time since first recorded operation','ex-muted'));row.append(range);
  const actions=el('div',undefined,'ex-range-actions');
  for(const [name,action,disabled] of [
   ['Zoom in',()=>change(zoomRange(bounds,.5),true),bounds.hi===bounds.lo],
   ['Zoom out',()=>change(zoomRange(bounds,2),true),bounds.lo<=bounds.fullLo&&bounds.hi>=bounds.fullHi],
   ['Undo interval',()=>change(rangeHistory.pop()),!rangeHistory.length],
   ['Full range',()=>change({start:null,end:null},true),false]]){const b=button(name,action);b.disabled=!!data.saved||disabled;actions.append(b);}row.append(actions);box.append(row);
  const advanced=el('details',undefined,'ex-exact');advanced.dataset.disclosure='exact-interval';advanced.append(el('summary','Exact interval & clock'));
  const form=el('form',undefined,'ex-controls'),clockLabel=el('label','Time basis'),clock=el('select');clock.setAttribute('aria-label','Execution clock');clock.dataset.control='clock';
  for(const c of data.clocks.filter(c=>c.clock)){const o=el('option',c.clock);o.value=c.clock;clock.append(o);}clock.value=data.selection.clock||'';clock.disabled=!!data.saved;clockLabel.append(clock);form.append(clockLabel);clock.onchange=()=>{rangeHistory.length=0;change({clock:clock.value,start:null,end:null,focus:null});selected=null;};
  const from=el('input'),to=el('input');for(const[input,label,value,id]of [[from,'From (seconds)',bounds.lo-bounds.origin,'range-from'],[to,'To (seconds)',bounds.hi-bounds.origin,'range-to']]){const l=el('label',label);input.type='number';input.step='any';input.required=true;input.value=String(Math.round(value*1000)/1000);input.disabled=!!data.saved;input.dataset.control=id;l.append(input);form.append(l);}
  const apply=button('Apply interval');apply.type='submit';apply.disabled=!!data.saved;form.append(apply);form.onsubmit=e=>{e.preventDefault();to.setCustomValidity(Number(to.value)<Number(from.value)?'End must follow start.':'');if(form.reportValidity())change({start:Number(from.value)+bounds.origin,end:Number(to.value)+bounds.origin},true);};to.oninput=from.oninput=()=>to.setCustomValidity('');
  advanced.append(form);box.append(advanced);return box;
 }
 function render(){
  const host=document.getElementById('training-execution'),current=document.activeElement,control=current?.dataset.control,focusKey=current?.dataset.focusKey,caret=current?.type==='search'?current.selectionStart:null;
  const opened=new Set([...document.querySelectorAll('#training-execution details[open],.ex-inspector-dialog details[open]')].map(n=>n.dataset.disclosure).filter(Boolean));
  const timelineScroll=host.querySelector('.ex-timeline'),scroll=timelineScroll?{x:timelineScroll.scrollLeft,y:timelineScroll.scrollTop}:null,detailScroll=document.getElementById('execution-detail')?.scrollTop||0;
  host.replaceChildren();
  if(error){const notice=el('div',undefined,'ex-notice');notice.setAttribute('role','status');notice.append(el('span',error+' · Showing the last captured data.'),button('Retry',()=>load(true)));host.append(notice);}
  const top=el('div',undefined,'ex-toolbar'),status=el('div',undefined,'ex-status');status.id='execution-status';top.append(status);
  if(!data.saved){const pause=button(paused?'Resume live':'Pause updates',()=>{paused=!paused;++request;writeURL({paused:paused?'1':null});render();if(!paused)load(true);});top.append(pause);}
  const save=button(data.saved?'Return to live':paused?'Save latest data':'Save view',async()=>{if(data.saved){paused=false;writeURL({paused:null});change({saved:null});return;}save.disabled=true;try{const r=await fetch('/api/training-execution/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(options())});const v=await r.json();if(!r.ok)throw Error(v.error);data=v;change({saved:v.saved});}catch(e){save.disabled=false;status.textContent=e.message;}});
  if(paused&&!data.saved)save.title='Capture the latest server data in this interval. Export view keeps the data currently displayed.';
  const compare=el('a','Compare training runs →');compare.href='/?'+new URLSearchParams({view:'health',...(scope.experiment?{experiment:scope.experiment}:{}),...(scope.environment?{environment:scope.environment}:{})})+'#trainer-telemetry';top.append(compare,save,button('Export view',()=>download(data)));host.append(top);
  if(!data.available){host.append(el('p','Update the collector to record execution spans.','ex-empty'));refreshStatus();return;}
  const bounds=boundsFor(data);host.append(controls(bounds));
  const counters=el('div',undefined,'ex-counts');for(const[value,label,filter]of [[data.counts.executions,'Operations',null],[(data.counts.states.running||0)+(data.counts.states.queued||0)+(data.counts.states.suspended||0),'In progress','active'],[data.counts.states.failed||0,'Failed','failed'],[data.counts.linked_logs,'Metric logs',undefined],[data.counts.source_linked_samples,'Linked samples',undefined]]){const box=filter!==undefined?button('',()=>setFilters({state:filter||'',kind:'',search:''}),'ex-count'):el('div',undefined,'ex-count');if(filter!==undefined){box.title='Filter timeline: '+label;box.setAttribute('aria-pressed',String(stateFilter===(filter||'')));}box.append(el('strong',String(value)),el('span',label));counters.append(box);}host.append(counters);
  if(!data.executions.length){const p=el('p',data.selection.start!=null||data.selection.end!=null?'No operations in this interval. Use Full range to return to available data.':'No timed execution data yet. Connect an execution recorder to populate this view.','ex-empty'),a=el('a','Capture example');a.href='/connections#execution-section';host.append(p,a);refreshStatus();return;}
  if(data.environment)host.append(el('p','Environment filters narrow rollout lanes. Shared learner updates retain their complete batch and native metrics.','ex-muted'));
  const missingTime=data.clocks.filter(c=>!c.clock).reduce((n,c)=>n+c.records,0);
  if(data.truncated||missingTime||data.missing_logs.length)host.append(el('p',[data.truncated?'Showing the newest '+data.limit+' operations. Narrow the interval to inspect earlier work.':'',missingTime?`${missingTime} executions have no time coordinates.`:'',data.missing_logs.length?`${data.missing_logs.length} referenced trainer logs have not arrived.`:''].filter(Boolean).join(' '),'ex-notice'));
  const view=model(data),layout=el('div',undefined,'ex-layout'+(selected&&!small?' ex-has-detail':'')),main=el('div',undefined,'ex-main'),panel=el('section',undefined,'ex-panel');
  const title=el('div',undefined,'ex-panel-heading');title.append(el('h3','Execution timeline'),el('span','Drag to select · click to inspect','ex-muted'));panel.append(title);
  const filters=el('div',undefined,'ex-filters'),find=el('input');find.type='search';find.placeholder='Find worker or operation…';find.setAttribute('aria-label','Find execution');find.dataset.control='execution-search';find.value=search;find.oninput=()=>setFilters({search:find.value});filters.append(find);
  for(const [name,items,value,onChange]of [['Operation type',[['','All operations'],['learner_update','Learner updates'],['inference','Inference'],['rollout','Rollouts'],['environment','Environment'],['verification','Verification'],['weight_sync','Weight sync'],['configuration','Configuration']],kindFilter,v=>setFilters({kind:v})],['Operation status',[['','All statuses'],['active','In progress'],['completed','Completed'],['failed','Failed'],['cancelled','Cancelled']],stateFilter,v=>setFilters({state:v})]]){const s=el('select');s.setAttribute('aria-label',name);s.dataset.control=name;for(const [v,label]of items){const o=el('option',label);o.value=v;s.append(o);}s.value=value;s.onchange=()=>onChange(s.value);filters.append(s);}
  if(search||stateFilter||kindFilter)filters.append(button('Clear filters',()=>setFilters({search:'',state:'',kind:''})));panel.append(filters,timeline(view,bounds));
  const legend=el('div',undefined,'ex-legend');for(const[cls,label]of [['completed','Completed'],['running','In progress'],['failed','Failed'],['kind-weight_sync','Weight sync'],['kind-configuration','Configuration']]){const item=el('span',label);item.prepend(el('i',undefined,'ex-'+cls));legend.append(item);}panel.append(legend,el('p',`${filterRows(view.lanes.flatMap(l=>l.rows)).length} operations shown · filters apply to the timeline; curves use the full time interval.`,'ex-filter-note'));main.append(panel);
  const chartControls=el('div',undefined,'ex-chart-controls'),smoothLabel=el('label','Curves'),smooth=el('select');smooth.setAttribute('aria-label','Curve smoothing');smooth.dataset.control='smoothing';
  for(const [v,label]of [[0,'Raw'],[.1,'Raw + EMA · α 0.1'],[.3,'Raw + EMA · α 0.3'],[.6,'Raw + EMA · α 0.6']]){const option=el('option',label);option.value=v;smooth.append(option);}smooth.value=smoothing;
  smooth.onchange=()=>{smoothing=Number(smooth.value);writeURL({ema:smoothing||null});render();};smoothLabel.append(smooth);const hint=el('span',smoothing?'Faint: raw · bold: EMA. Click raw points for update evidence.':'Click a raw point to inspect its update and samples.','ex-muted');hint.title='EMA uses logged points, starts at the selected interval and resets at missing data. Numeric readouts always use raw values.';chartControls.append(smoothLabel,hint);main.append(chartControls);
  const grid=el('div',undefined,'ex-signals'),groups=new Map();for(const s of view.series){if(!groups.has(s.group))groups.set(s.group,[]);groups.get(s.group).push(s);}
  const ordering={reward:'Reward',age:'Policy age',mismatch:'Policy mismatch',gradients:'Gradient norms',throughput:'Throughput',kl:'KL divergence',loss:'Loss',entropy:'Entropy',clipping:'Clipping',tokens:'Tokens',systems:'Systems',other:'Additional signals'};
  for(const[group,label]of Object.entries(ordering)){
   const streams=groups.get(group);if(!streams)continue;const card=el('article',undefined,'ex-panel ex-signal');card.dataset.group=group;card.append(el('h3',label));const chosen=streams.find(s=>s.id===picks.get(group))||streams[0];
   if(streams.length>1){const select=el('select');select.dataset.control='signal-'+group;select.setAttribute('aria-label',label+' signal');for(const s of streams){const o=el('option',s.label+' · '+s.producer+' / '+s.session);o.value=s.id;select.append(o);}select.value=chosen.id;select.onchange=()=>{picks.set(group,select.value);render();};card.append(select);}else card.append(el('p',chosen.label,'ex-signal-name'));
   const visible={...chosen,points:chosen.points.filter(p=>p.time>=bounds.lo&&p.time<=bounds.hi)},summary=readout(visible,selected),value=el('div',undefined,'ex-signal-value');value.append(el('strong',summary.point?fmt(summary.point.value):'—'),el('span',chosen.unit));card.append(value);
   card.append(el('p',summary.point?`${selected?'Selected':'Latest'} · update ${summary.point.step}`:selected?'No metric logged on this operation':'No value at the latest logged boundary','ex-signal-context'));
   const scaleLabel=el('label','Y scale','ex-scale-control'),scale=el('select');scale.setAttribute('aria-label',label+' scale');scale.dataset.control='scale-'+group;
   for(const [v,title]of [['linear','Linear'],['log','Log']]){const o=el('option',title);o.value=v;scale.append(o);}scale.value=logGroups.has(group)?'log':'linear';scale.onchange=()=>{scale.value==='log'?logGroups.add(group):logGroups.delete(group);writeURL({log:[...logGroups].join(',')});render();};scaleLabel.append(scale);card.append(scaleLabel,curve(chosen,bounds));
   const foot=el('div',undefined,'ex-signal-footer');foot.append(el('span',`${summary.measured} / ${summary.total} points measured`));if(summary.delta!=null)foot.append(el('span',(summary.delta>0?'+':'')+fmt(summary.delta)+' vs prior measured update'));card.append(foot);
   const def=el('details');def.dataset.disclosure='signal-'+group;def.append(el('summary','Definition & source'),el('p',chosen.definition),el('p',chosen.population),el('p',chosen.producer+' · '+chosen.session));card.append(def);grid.append(card);
  }
  if(!view.series.length)main.append(el('p','No aligned metrics in this interval. Attach trainer-log references to update spans; existing native logs remain in Training health.','ex-notice'));
  if(view.unplaced)main.append(el('p',`${view.unplaced} logs cannot be placed at one completed execution boundary. Their evidence remains in Export view.`,'ex-notice'));
  main.append(grid);layout.append(main);host.append(layout);
  if(selected){
   if(small){if(!drawer){drawer=el('dialog',undefined,'ex-inspector-dialog');drawer.setAttribute('aria-label','Operation details');drawer.oncancel=e=>{e.preventDefault();focus(null);};document.body.append(drawer);}drawer.replaceChildren(detail());if(!drawer.open)drawer.showModal();}
   else{drawer?.close();drawer?.replaceChildren();layout.append(detail());}
  }else{drawer?.close();drawer?.replaceChildren();}
  for(const d of document.querySelectorAll('#training-execution details,.ex-inspector-dialog details'))if(opened.has(d.dataset.disclosure))d.open=true;
  const newTimeline=host.querySelector('.ex-timeline');if(scroll&&newTimeline){newTimeline.scrollLeft=scroll.x;newTimeline.scrollTop=scroll.y;}
  const detailEl=document.getElementById('execution-detail');if(detailEl)detailEl.scrollTop=detailScroll;
  if(control){const replacement=document.querySelector('[data-control="'+CSS.escape(control)+'"]');replacement?.focus({preventScroll:true});if(caret!==null&&replacement?.type==='search')replacement.setSelectionRange(caret,caret);}
  else if(focusKey&&!drawer?.open)document.querySelector('[data-focus-key="'+CSS.escape(focusKey)+'"]')?.focus({preventScroll:true});
  refreshStatus();
 }
 window.addEventListener('jev:scope',e=>{const initialized=Object.hasOwn(scope,'experiment'),changed=scope.experiment!==e.detail.experiment||scope.environment!==e.detail.environment;scope=e.detail;if(changed){data=null;signature='';rangeHistory.length=0;if(initialized&&active()){selected=null;drawer?.close();change({saved:null,clock:null,start:null,end:null,focus:null});return;}}if(!params().has('execution_saved')||!data)load();});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!data?.saved)load();});
 window.addEventListener('resize',()=>{const next=innerWidth<=1280;if(next!==small){small=next;if(data&&active())render();}});
 document.getElementById('refresh')?.addEventListener('click',()=>{if(active()&&!data?.saved)load(true);});
 setInterval(()=>{if(!data?.saved)load();},5000);
})();
