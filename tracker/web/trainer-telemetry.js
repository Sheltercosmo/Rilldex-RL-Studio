/* Native trainer coordinates remain separate from rollout measurements. */
(() => {
 'use strict';
 const names={reward:'Outcome',mismatch:'Policy mismatch',clipping:'Clipping & masking',entropy:'Entropy',throughput:'Throughput',gradients:'Gradient norms',loss:'Loss',kl:'KL divergence',tokens:'Token usage',systems:'Systems',other:'Additional native metrics'};
 function comparable(a,b){
  return ['native_key','unit','reduction','definition','group'].every(k=>a[k]===b[k])&&
   ['clock','split','population','environment','framework'].every(k=>a.context[k]===b.context[k]);
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
 function defaultSeries(series){
  const priority=s=>s.native_key==='comparison/mean_probability_gap'?0:s.native_key.includes('mismatch_kl')?1:s.native_key==='comparison/mean_absolute_gap'?2:s.unit==='fraction'?3:s.unit==='tokens'?9:5;
  return [...series].sort((a,b)=>priority(a)-priority(b)||b.recorded-a.recorded)[0];
 }
 if(typeof module!=='undefined'&&module.exports){module.exports={comparable,smoothPoints,intervalStats,defaultSeries};return;}
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const ns='http://www.w3.org/2000/svg';
 const svg=(tag,attrs={})=>{const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;};
 let scope={},seq=0,saved='',data=null,selection=new Map(),datasets=[],failure='',paused=false,checked=null,dragging=false;
 const query=()=>new URLSearchParams(location.search),colors=['#355cdb','#009b82','#dc6637'];
 let comparisons=query().getAll('signals_compare').slice(0,2),halfLife=Number(query().get('signals_smooth'))||0;
 if(![0,10,50,100].includes(halfLife))halfLife=0;
 let clock=query().get('signals_clock')||'',range=null;
 const from=query().get('signals_from'),to=query().get('signals_to');
 if(from!==null&&to!==null&&Number.isFinite(Number(from))&&Number.isFinite(Number(to))&&Number(from)<=Number(to))range=[Number(from),Number(to)];
 const logarithmic=new Set((query().get('signals_log')||'').split(',').filter(Boolean));
 let layout=query().get('signals_layout')||'';
 const extraMetrics=new Set(query().getAll('signals_extra').slice(0,6));
 try{selection=new Map(Object.entries(JSON.parse(query().get('signals_picks')||'{}')));}catch{}
 function persist(){const u=new URL(location.href);for(const key of [...u.searchParams.keys()])if(key.startsWith('signals_'))u.searchParams.delete(key);for(const run of comparisons)u.searchParams.append('signals_compare',run);for(const id of extraMetrics)u.searchParams.append('signals_extra',id);for(const[k,v]of Object.entries({clock,smooth:halfLife||null,layout,from:range?.[0],to:range?.[1],log:[...logarithmic].join(','),picks:selection.size?JSON.stringify(Object.fromEntries(selection)):null}))if(v!=null&&v!=='')u.searchParams.set('signals_'+k,v);history.replaceState(history.state,'',u);}
 function link(text,view,extra={}){const a=el('a',text);a.href='/?'+new URLSearchParams({view,...(scope.experiment?{experiment:scope.experiment}:{}),...(scope.environment?{environment:scope.environment}:{}),...extra});return a;}
 function button(text,action){const b=el('button',text);b.type='button';b.onclick=action;return b;}
 function choose(label,items,value,onchange){const l=el('label',undefined,'telemetry-control'),s=el('select');l.append(el('span',label),s);s.setAttribute('aria-label',label);s.dataset.telemetryControl=label;for(const[v,t]of items){const o=el('option',t);o.value=v;s.append(o);}s.value=value;s.onchange=()=>onchange(s.value);return l;}
 function exportView(){const a=el('a'),url=URL.createObjectURL(new Blob([JSON.stringify({schema:'training-signals-view/1',captured_at:checked,selection:{experiment:scope.experiment,environment:scope.environment,comparisons,clock,range,halfLife,log:[...logarithmic],metrics:Object.fromEntries(selection),extra:[...extraMetrics]},datasets},null,2)],{type:'application/json'}));a.href=url;a.download='rilldex-training-signals.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 const fmt=v=>v===null?'Unavailable':Number(v).toLocaleString(undefined,Number.isInteger(v)?{maximumFractionDigits:0}:{maximumSignificantDigits:5});
 async function showRecord(s,p){
  const d=el('dialog',undefined,'telemetry-dialog'),close=el('button','Close');d.setAttribute('aria-label',s.label);close.type='button';close.onclick=()=>d.close();
  const links=el('div','Loading linked rollout evidence…'),raw=el('details');raw.append(el('summary','Native point & definition'),el('pre',JSON.stringify({context:s.context,native_key:s.native_key,unit:s.unit,reduction:s.reduction,...p},null,2)));
  d.append(el('h2',s.label),el('p',`${fmt(p.value)} ${s.unit} · ${s.context.clock} ${p.step} · ${p.status}`),el('p',s.definition),links,raw,close);
  d.addEventListener('close',()=>d.remove());document.body.append(d);d.showModal();
  try{
   const records=await Promise.all(p.record_ids.map(async record_id=>{const q=new URLSearchParams({producer:s.context.producer,experiment:s.context.experiment,record_id});const r=await fetch('/api/trainer-telemetry/evidence?'+q);if(!r.ok)throw Error('Linked evidence is unavailable.');return r.json();}));
   if(!links.isConnected)return;links.replaceChildren();
   for(const record of records){
    links.append(el('h3','Linked rollout evidence'),el('p',record.declared_uses?`${record.matched_uses} / ${record.declared_uses} declared training uses have exact source links · ${record.declared_coverage} reference inventory`:'No training-use references recorded. Add references in TrainerTelemetry.log() to enable rollout drill-down.'));
    const list=el('ul');for(const [index,id] of record.run_ids.slice(0,100).entries()){const item=el('li'),a=el('a',`Open rollout ${index+1}`);a.href='/semantic-map?'+new URLSearchParams({run:id,observer:'source',return_to:location.pathname+location.search});item.append(a);list.append(item);}links.append(list);
    if(record.run_ids.length>100)links.append(el('p',`${record.run_ids.length-100} further rollout links are retained in the full evidence record.`));
    const detail=el('details');detail.append(el('summary','Training-use receipts & attribution'),el('p',record.boundary),el('pre',JSON.stringify(record.references,null,2)));links.append(detail);
   }
  }catch(e){if(links.isConnected)links.textContent=e.message;}
 }
 function inspectInterval(streams){
  const d=el('dialog',undefined,'telemetry-dialog'),close=button('Close',()=>d.close());d.setAttribute('aria-label','Recorded updates in interval');
  d.append(el('h2','Recorded updates'),el('p',range?`${clock} ${range[0]}–${range[1]}`:'Full displayed range'),close);
  for(const {series:s} of streams){
   const stats=intervalStats(s.points,range),section=el('section');section.append(el('h3',s.context.experiment),el('p',`${stats.finite.length} measured updates · ${s.context.population} · ${s.context.split}`));
   let shown=0;const list=el('div',undefined,'telemetry-log-list'),more=button('Show more updates',append);
   function append(){for(const p of stats.finite.slice(shown,shown+20)){const b=button(`${s.context.clock} ${p.step} · ${fmt(p.value)} ${s.unit}`,()=>showRecord(s,p));list.append(b);}shown+=20;more.hidden=shown>=stats.finite.length;}
   append();section.append(list,more);d.append(section);
  }
  d.onclose=()=>d.remove();document.body.append(d);d.showModal();
 }
 function chart(streams,bounds,group){
  const compact=(layout||(comparisons.length?'stacked':'compact'))==='compact';
  const log=logarithmic.has(group),width=innerWidth<700?360:compact?440:innerWidth<1100?540:760,left=58,right=18,bottom=147,top=18;
  const box=el('div',undefined,'telemetry-plot'),g=svg('svg',{viewBox:`0 0 ${width} 185`,role:'group','aria-label':`${names[group]||streams[0].series.label} · aligned ${clock}${log?' · logarithmic scale':''}`});
  const prepared=streams.map(s=>({...s,raw:intervalStats(s.series.points,bounds).rows,trend:intervalStats(smoothPoints(s.series.points,halfLife),bounds).rows}));
  const transform=v=>log?Math.log10(v):v,valid=p=>p.value!=null&&Number.isFinite(p.value)&&(!log||p.value>0),values=prepared.flatMap(s=>[...s.raw,...(halfLife?s.trend:[])].filter(valid).map(p=>transform(p.value)));
  const excluded=prepared.reduce((n,s)=>n+s.raw.filter(p=>p.value!=null&&p.value<=0).length,0);
  if(log&&excluded)box.append(el('p',`${excluded} nonpositive values omitted on Log; switch to Linear to include them.`,'telemetry-warning'));
  if(!values.length){box.append(el('p','No plottable values in this interval.','telemetry-empty'));return box;}
  let lo=Math.min(...values),hi=Math.max(...values);if(lo===hi){const pad=log ? .25 : Math.abs(lo)*.05||1;lo-=pad;hi+=pad;}
  const x=v=>left+(width-left-right)*(v-bounds[0])/(bounds[1]-bounds[0]||1),y=v=>bottom-(bottom-top)*(transform(v)-lo)/(hi-lo);
  for(let i=0;i<=2;i++){const v=lo+(hi-lo)*i/2,t=svg('text',{x:left-8,y:bottom-(bottom-top)*i/2+4,'text-anchor':'end'});t.textContent=fmt(log?10**v:v);g.append(svg('line',{x1:left,x2:width-right,y1:bottom-(bottom-top)*i/2,y2:bottom-(bottom-top)*i/2,class:'telemetry-gridline'}),t);}
  for(let i=0;i<=4;i++){const value=bounds[0]+(bounds[1]-bounds[0])*i/4,t=svg('text',{x:x(value),y:173,'text-anchor':i===0?'start':i===4?'end':'middle'});t.textContent=fmt(value);g.append(svg('line',{x1:x(value),x2:x(value),y1:top,y2:bottom,class:'telemetry-gridline'}),t);}
  const highlight=svg('rect',{x:left,y:top,width:0,height:bottom-top,class:'telemetry-brush'}),cursor=svg('line',{x1:left,x2:left,y1:top,y2:bottom,class:'telemetry-cursor',visibility:'hidden'});g.append(highlight,cursor);
  g.dataset.min=bounds[0];g.dataset.max=bounds[1];g.dataset.left=left;g.dataset.right=width-right;
  const path=(points,color,trend)=>{let d='',open=false;for(const p of points){if(!valid(p)){open=false;continue;}d+=`${open?'L':'M'}${x(p.step)} ${y(p.value)} `;open=true;}g.append(svg('path',{d,fill:'none',stroke:color,'stroke-width':trend?2.7:halfLife?1:2,'stroke-opacity':!trend&&halfLife?.25:1,class:trend?'telemetry-trend':'telemetry-raw'}));};
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
  g.onpointerup=e=>{if(start==null)return;const a=start,b=at(e);clear();if(Math.abs(a-b)>(bounds[1]-bounds[0])*.004){range=[Math.min(a,b),Math.max(a,b)];paused=true;++seq;persist();render();}};
  g.onpointercancel=clear;g.onlostpointercapture=()=>{if(start!=null)clear();};g.onpointerleave=()=>{if(start==null)clear();};box.append(g);return box;
 }
 function renderPreview(host){
  host.hidden=false;host.replaceChildren();
  const head=el('div',undefined,'telemetry-heading'),title=el('div');title.append(el('h2','Training signals'),el('p','Recorded learner updates · open the full view to compare runs and select an interval.'));
  head.append(title,link('Open training signals →','health'));host.append(head);
  if(failure)host.append(el('p',failure+' Displayed data is unchanged.','telemetry-warning'));
  if(!scope.experiment){host.append(el('p','Select a training run above to preview its signals.','telemetry-empty'));return;}
  if(!data.records){const note=el('p','No trainer logs in this selection. ','telemetry-empty'),setup=el('a','Connect or import logs →');setup.href='/connections#telemetry-section';note.append(setup);host.append(note);return;}
  const clocks=[...new Set(data.series.map(s=>s.context.clock))],selectedClock=clocks.includes('learner_update')?'learner_update':clocks[0];
  const primary=[];for(const group of Object.keys(names)){const candidates=data.series.filter(s=>s.context.clock===selectedClock&&s.group===group);if(candidates.length)primary.push(defaultSeries(candidates));}
  // Outcome, mismatch and throughput lead the summary; the full view retains every group.
  primary.sort((a,b)=>(['reward','mismatch','throughput'].includes(a.group)?['reward','mismatch','throughput'].indexOf(a.group):9)-(['reward','mismatch','throughput'].includes(b.group)?['reward','mismatch','throughput'].indexOf(b.group):9));
  const grid=el('div',undefined,'telemetry-preview-grid');
  for(const s of primary.slice(0,3)){
   const card=link('','health',{signals_clock:selectedClock}),finite=s.points.filter(p=>p.value!=null&&Number.isFinite(p.value)),latest=finite.at(-1);card.className='telemetry-preview-card';
   card.append(el('h3',s.label),el('strong',latest?fmt(latest.value):'—'),el('small',`${s.unit} · ${s.context.split} · ${s.context.population}`));
   if(finite.length){const first=s.points[0].step,last=s.points.at(-1).step,low=Math.min(...finite.map(p=>p.value)),high=Math.max(...finite.map(p=>p.value)),g=svg('svg',{viewBox:'0 0 300 64',role:'img','aria-label':s.label+' · raw values across loaded updates'});let d='',connected=false;for(const p of s.points){if(p.value==null||!Number.isFinite(p.value)){connected=false;continue;}const x=4+292*(p.step-first)/(last-first||1),y=54-44*(p.value-low)/(high-low||1);d+=`${connected?'L':'M'}${x} ${y} `;connected=true;}g.append(svg('line',{x1:4,x2:296,y1:56,y2:56,stroke:'#e5eaf3'}),svg('path',{d,fill:'none',stroke:'#355cdb','stroke-width':2}));card.append(g,el('small',`${selectedClock} ${first}–${last} · ${finite.length}/${s.points.length} measured`),el('small','Latest measured at '+latest.step));}
   grid.append(card);
  }
  host.append(grid);if(data.truncated||data.omitted_series)host.append(el('p',`Preview uses the latest ${data.records} loaded logs; open the full view for capture limits.`,'telemetry-empty'));
 }
 function render(){
  const host=document.querySelector('#trainer-telemetry');if(!host||!data)return;
  if(typeof OverviewLayout!=='undefined'&&OverviewLayout.mode(location.search).section==='summary'){renderPreview(host);return;}
  const focused=document.activeElement?.dataset.telemetryControl;host.hidden=false;host.replaceChildren();
  const heading=el('div',undefined,'telemetry-heading'),title=el('div');title.append(el('h2','Training signals'),el('p','Compare runs on recorded steps. Select an interval or point to inspect its updates and rollouts.'));
  const actions=el('div',undefined,'telemetry-actions');actions.append(link('Execution timeline →','execution'));
  const setup=el('a',data.records?'Capture settings':'Connect training data');setup.href='/connections#telemetry-section';actions.append(setup);heading.append(title,actions);host.append(heading);
  if(failure)host.append(el('p',failure+' Displayed data is unchanged.','telemetry-warning'));
  if(!scope.experiment){
   host.append(el('p','Select a training run to align its signals. Add another run to compare it.','telemetry-note'));
   const runs=el('div',undefined,'telemetry-run-choices'),ids=[...new Set(data.series.map(s=>s.context.experiment))];
   for(const id of ids)runs.append(link(id,'health',{experiment:id}));host.append(runs);
   if(!ids.length)host.append(el('p','No trainer logs received. Connect a running trainer or import existing logs. Rollout-only data is available in Behavior measures.','telemetry-empty'),link('Open behavior measures →','measures'));
   return;
  }
  const controls=el('div',undefined,'telemetry-board-controls'),available=[...document.querySelector('#experiment').options].map(o=>[o.value,o.textContent]).filter(([v])=>v&&v!==scope.experiment&&!comparisons.includes(v));
  if(comparisons.length<2)controls.append(choose('Compare run',[['','Add a run…'],...available],'',value=>{if(value){comparisons.push(value);paused=false;persist();load(true);}}));
  const clocks=[...new Set(data.series.map(s=>s.context.clock))];if(!clocks.includes(clock))clock=clocks.includes('learner_update')?'learner_update':clocks[0]||'';
  if(clocks.length>1)controls.append(choose('Step clock',clocks.map(c=>[c,c]),clock,v=>{clock=v;range=null;selection.clear();persist();render();}));
  controls.append(choose('Trend',[[0,'Raw'],[10,'EMA · 10-step half-life'],[50,'EMA · 50-step half-life'],[100,'EMA · 100-step half-life']],halfLife,v=>{halfLife=Number(v);persist();render();}),choose('Chart layout',[['stacked','Stacked'],['compact','Compact']],layout||(comparisons.length?'stacked':'compact'),v=>{layout=v;persist();render();}),button(paused?'Resume updates':'Pause updates',()=>{paused=!paused;++seq;render();if(!paused)load(true);}),button('Export comparison',exportView));host.append(controls);
  const legend=el('div',undefined,'telemetry-run-legend');
  datasets.forEach((d,i)=>{const item=el('span',undefined,'telemetry-run-chip'),swatch=el('i');swatch.style.background=colors[i];item.append(swatch,el('strong',d.experiment),el('span',`${d.records} logs`));if(i)item.append(button('Remove',()=>{comparisons=comparisons.filter(x=>x!==d.experiment);paused=false;persist();load(true);}));legend.append(item);});host.append(legend);
  host.append(el('p',`${paused?'Paused · selected data held':'Live · refreshes every 10 seconds'}${checked?' · captured '+new Date(checked).toLocaleTimeString():''}. X: ${clock||'unavailable'}${halfLife?' · faint raw, bold EMA; computed before interval selection':''}.`,'telemetry-note'));
  for(const d of datasets)if(d.truncated||d.omitted_series)host.append(el('p',`${d.experiment}: latest ${d.records} logs; ${d.omitted_series} series omitted. Export includes this bounded view. Full records remain available through Workspace.telemetry().`,'telemetry-warning'));
  if(!data.records){host.append(el('p','No native logs for this selection. Import existing logs or connect your trainer; execution instrumentation is optional.','telemetry-empty'));return;}
  const panels=[];
  const addPanel=(group,label,candidates,extra=false)=>{
   const primary=candidates.find(s=>s.id===selection.get(group))||defaultSeries(candidates);selection.set(group,primary.id);
   const streams=[{series:primary,color:colors[0]}],pending=[];
   datasets.slice(1).forEach((d,i)=>{const matches=d.series.filter(s=>comparable(primary,s)),key=group+'/'+d.experiment;const chosen=matches.find(s=>s.id===selection.get(key))||(matches.length===1?matches[0]:null);if(chosen){selection.set(key,chosen.id);streams.push({series:chosen,color:colors[i+1]});}else pending.push({dataset:d,matches,key});});
   panels.push({group,label,candidates,primary,streams,pending,extra});
  };
  for(const [group,label]of Object.entries(names)){const candidates=data.series.filter(s=>s.group===group&&s.context.clock===clock);if(candidates.length)addPanel(group,label,candidates);}
  for(const id of extraMetrics){const s=data.series.find(s=>s.id===id&&s.context.clock===clock);if(s&&!panels.some(p=>p.primary.id===id))addPanel('extra/'+id,s.label,[s],true);}
  if(extraMetrics.size<6){const unused=data.series.filter(s=>s.context.clock===clock&&!panels.some(p=>p.primary.id===s.id));if(unused.length)host.append(choose('Add metric',[['','Add another signal…'],...unused.map(s=>[s.id,s.label+' · '+s.context.split])],'',id=>{if(id){extraMetrics.add(id);persist();render();}}));}
  const steps=panels.flatMap(p=>p.streams.flatMap(s=>s.series.points.map(p=>p.step))),full=steps.length?[Math.min(...steps),Math.max(...steps)]:[0,1],bounds=range||full;
  const interval=el('form',undefined,'telemetry-interval'),a=el('input'),b=el('input');
  for(const[input,label,value]of [[a,'From step',bounds[0]],[b,'To step',bounds[1]]]){const l=el('label',label,'telemetry-control');input.type='number';input.step='any';input.required=true;input.value=value;input.setAttribute('aria-label',label);l.append(input);interval.append(l);}
  const apply=button('Select interval');apply.type='submit';interval.append(apply,button('Full range',()=>{range=null;persist();render();}));interval.onsubmit=e=>{e.preventDefault();b.setCustomValidity(Number(b.value)<Number(a.value)?'End must follow start.':'');if(interval.reportValidity()){range=[Number(a.value),Number(b.value)];paused=true;++seq;persist();render();}};a.oninput=b.oninput=()=>b.setCustomValidity('');host.append(interval);
  const grid=el('div',undefined,'telemetry-grid telemetry-aligned telemetry-'+(layout||(comparisons.length?'stacked':'compact')));
  for(const {group,label,candidates,primary,streams,pending,extra}of panels){
   const card=el('article',undefined,'telemetry-card');card.dataset.signalGroup=group;const head=el('div',undefined,'telemetry-card-heading');head.append(el('h3',label),choose(label+' scale',[['linear','Linear'],['log','Log']],logarithmic.has(group)?'log':'linear',v=>{v==='log'?logarithmic.add(group):logarithmic.delete(group);persist();render();}));if(extra)head.append(button('Remove chart',()=>{extraMetrics.delete(primary.id);selection.delete(group);persist();render();}));card.append(head);
   if(candidates.length>1)card.append(choose(label+' metric',candidates.map(s=>[s.id,s.label+' · '+s.context.split+(candidates.filter(c=>c.label===s.label&&c.context.split===s.context.split).length>1?' · '+s.context.session+' / '+s.context.producer:'')]),primary.id,v=>{selection.set(group,v);persist();render();}));else card.append(el('p',primary.label,'telemetry-series-name'));
   for(const {dataset:d,matches,key}of pending){
    if(matches.length>1)card.append(choose('Stream · '+d.experiment,[['','Choose a session…'],...matches.map(s=>[s.id,s.context.session+' · '+s.context.producer])],'',v=>{selection.set(key,v);persist();render();}));
    else card.append(el('p',`${d.experiment}: no matching definition, clock and population for this metric.`,'telemetry-empty'));
   }
   const values=el('div',undefined,'telemetry-window-values');for(const {series:s,color}of streams){const stat=intervalStats(s.points,bounds),item=el('div');item.style.borderColor=color;item.append(el('strong',stat.last?fmt(stat.last.value):'—'),el('span',`${s.context.experiment} · ${primary.unit}`),el('small',stat.last?`${stat.finite.length}/${stat.rows.length} measured · latest at ${stat.last.step}${stat.delta!=null?' · Δ '+fmt(stat.delta):''}`:'No measured update in this interval'));values.append(item);}card.append(values,chart(streams,bounds,group));
   const footer=el('div',undefined,'telemetry-card-footer');footer.append(button('Inspect updates',()=>inspectInterval(streams)),el('span',primary.context.split+' · '+primary.context.population));card.append(footer);
   const detail=el('details');detail.append(el('summary','Definition & sources'),el('p',primary.definition),el('p',`${primary.unit} · ${primary.reduction}. Native key: ${primary.native_key}.`));for(const {series:s}of streams)detail.append(el('p',`${s.context.experiment}: ${s.context.framework} ${s.context.framework_version} · ${s.context.objective} · ${s.context.session} · ${s.context.producer}`));card.append(detail);grid.append(card);
  }
  host.append(grid);
  const missing=['reward','mismatch','throughput'].filter(g=>!panels.some(p=>p.group===g));if(missing.length){const p=el('p',`Not recorded in this clock: ${missing.map(g=>names[g]).join(', ')}. `,'telemetry-empty');const guide=el('a','Add these signals');guide.href='/connections#telemetry-section';p.append(guide);host.append(p);}
  const next=el('div',undefined,'telemetry-next');next.append(link('Inspect execution timing →','execution'),link('Compare rollout behavior →','measures'),link('Inspect training samples →','training'));host.append(next);
  if(focused)host.querySelector('[data-telemetry-control="'+CSS.escape(focused)+'"]')?.focus({preventScroll:true});
 }
 async function load(force=false){
  const host=document.querySelector('#trainer-telemetry');if(!host||document.hidden)return;
  const mode=query().get('view'),route=typeof OverviewLayout!=='undefined'?OverviewLayout.mode(location.search):null;
  if(location.pathname!=='/'||(route?route.section!=='summary'&&!(route.section==='training'&&route.panel==='signals'):mode&&mode!=='health')){host.hidden=true;return;}
  if(!force&&(paused||dragging||document.querySelector('.telemetry-dialog[open]')||host.contains(document.activeElement)&&document.activeElement?.matches('input')))return;
  comparisons=[...new Set(comparisons)].filter(x=>x!==scope.experiment).slice(0,2);
  const ticket=++seq,runs=[scope.experiment||'',...(route?.section==='summary'?[]:comparisons)];
  try{
   const values=await Promise.all(runs.map(async experiment=>{const q=new URLSearchParams();if(experiment)q.set('experiment',experiment);if(scope.environment)q.set('environment',scope.environment);const r=await fetch('/api/trainer-telemetry?'+q);if(!r.ok)throw Error('Trainer telemetry is unavailable.');return {...await r.json(),experiment};}));
   if(ticket!==seq)return;host.hidden=false;checked=new Date().toISOString();failure='';const signature=JSON.stringify(values);data=values[0];datasets=values;
   const count=document.getElementById('summary-native-count');if(count){count.textContent=Number(data.records).toLocaleString()+(data.truncated?'+':'');count.title=data.truncated?'Latest loaded records; capture is bounded':'Loaded trainer logs';}
   if(signature!==saved||force){saved=signature;render();}
  }catch(e){if(ticket===seq){failure=e.message;saved='';if(data)render();else{host.hidden=false;host.replaceChildren(el('p',e.message));}}}
 }
 window.addEventListener('jev:scope',e=>{const initialized=Object.hasOwn(scope,'experiment'),changed=scope.experiment!==e.detail.experiment||scope.environment!==e.detail.environment;scope=e.detail;if(changed){++seq;paused=false;data=null;saved='';if(initialized){range=null;clock='';selection.clear();extraMetrics.clear();persist();}}load();});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
 document.getElementById('refresh')?.addEventListener('click',()=>{paused=false;load(true);});
 let screenBand=innerWidth<700?0:innerWidth<1100?1:2;
 window.addEventListener('resize',()=>{const next=innerWidth<700?0:innerWidth<1100?1:2;if(next!==screenBand){screenBand=next;if(data&&!document.querySelector('#trainer-telemetry')?.hidden)render();}});
 setInterval(load,10000);
})();
