/* Native trainer coordinates remain separate from rollout measurements. */
(() => {
 'use strict';
 const names={loss:'Loss',entropy:'Entropy',kl:'KL divergence',clipping:'Policy & value clipping',tokens:'Token usage',throughput:'Throughput'};
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const ns='http://www.w3.org/2000/svg';
 const svg=(tag,attrs={})=>{const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;};
 let scope={},seq=0,saved='',data=null,selection=new Map();
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
 function chart(s){
  const g=svg('svg',{viewBox:'0 0 360 160',role:'group','aria-label':`${s.label} by ${s.context.clock}; gaps are unavailable coordinates`});
  const values=s.points.filter(p=>p.value!==null),xs=s.points.map(p=>p.step);
  if(!values.length)return el('p','No finite values in the selected logs.','telemetry-empty');
  let lo=Math.min(...values.map(p=>p.value)),hi=Math.max(...values.map(p=>p.value));
  if(lo===hi){const pad=Math.abs(lo)*.05||1;lo-=pad;hi+=pad;}
  const xmin=Math.min(...xs),xmax=Math.max(...xs),x=v=>52+288*(v-xmin)/(xmax-xmin||1),y=v=>118-104*(v-lo)/(hi-lo);
  for(const v of[lo,hi]){g.append(svg('line',{x1:52,x2:340,y1:y(v),y2:y(v),class:'telemetry-gridline'}));const t=svg('text',{x:48,y:y(v)+4,'text-anchor':'end'});t.textContent=fmt(v);g.append(t);}
  let d='',started=false;
  for(const p of s.points){if(p.value===null){started=false;continue;}d+=`${started?'L':'M'}${x(p.step)} ${y(p.value)} `;started=true;}
  g.append(svg('path',{d,fill:'none',class:'telemetry-line'}));
  for(const p of s.points){if(p.value===null)continue;const dot=svg('circle',{cx:x(p.step),cy:y(p.value),r:3,tabindex:0,role:'button','aria-label':`${s.context.clock} ${p.step}: ${fmt(p.value)} ${s.unit}`});const tip=svg('title');tip.textContent=`${p.step}: ${fmt(p.value)} ${s.unit}`;dot.append(tip);dot.onclick=()=>showRecord(s,p);dot.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();showRecord(s,p);}};g.append(dot);}
  for(const[v,anchor]of(xmin===xmax?[[xmin,'start']]:[[xmin,'start'],[xmax,'end']])){const t=svg('text',{x:x(v),y:142,'text-anchor':anchor});t.textContent=String(v);g.append(t);}
  return g;
 }
 function render(){
  const host=document.querySelector('#trainer-telemetry');if(!host||!data)return;host.hidden=false;host.replaceChildren();
  const heading=el('div',undefined,'telemetry-heading'),title=el('div');title.append(el('h2','Trainer metrics'),el('p',`${data.records} native logs · updates every 10 seconds · recorded trainer steps`));
  const actions=el('div',undefined,'telemetry-actions'),setup=el('a','Connect trainer');setup.href='/connections#telemetry-section';actions.append(setup);
  if(data.records){const download=el('button','Export values');download.type='button';download.onclick=()=>{const a=el('a');const u=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.href=u;a.download='trainer-metrics.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};actions.append(download);}
  heading.append(title,actions);host.append(heading);
  if(data.truncated||data.omitted_series)host.append(el('p',`Bounded view: latest ${data.records} logs; ${data.omitted_series} additional series omitted. Use Workspace.telemetry() or SQL for full scoped analysis.`,'telemetry-warning'));
  const grid=el('div',undefined,'telemetry-grid');
  for(const[group,label]of Object.entries(names)){
   const card=el('article',undefined,'telemetry-card'),title=el('h3',label),streams=data.series.filter(s=>s.group===group);card.append(title);
   if(!streams.length){card.append(el('strong','Not recorded','telemetry-value'),el('p','Connect native trainer logs to populate this measure.','telemetry-empty'));grid.append(card);continue;}
   const chosen=streams.find(s=>s.id===selection.get(group))||streams[0];selection.set(group,chosen.id);
   const select=el('select');select.setAttribute('aria-label',`${label} series`);
   for(const s of streams){const o=el('option',`${s.label} · ${s.context.experiment} · ${s.context.framework} / ${s.context.objective} · ${s.context.split} · ${s.context.producer} · ${s.context.session}`);o.value=s.id;select.append(o);}select.value=chosen.id;select.onchange=()=>{selection.set(group,select.value);render();};card.append(select);
   const latest=chosen.points.at(-1);card.append(el('strong',fmt(latest?.value??null),'telemetry-value'),el('span',`${chosen.unit} · ${chosen.context.clock} ${latest?.step??'—'}`,'telemetry-unit'),chart(chosen));
   const detail=el('details'),summary=el('summary','Definition & source');detail.append(summary,el('p',chosen.definition),el('p',`${chosen.context.framework} ${chosen.context.framework_version} · ${chosen.context.objective} · ${chosen.reduction}`),el('p',`Population: ${chosen.context.population}. Native key: ${chosen.native_key}. Session: ${chosen.context.session}.`));
   card.append(el('p',`${chosen.recorded} / ${chosen.coordinates} logged coordinates with finite values · ${chosen.context.split}`,'telemetry-coverage'),detail);grid.append(card);
  }
  host.append(grid);
  if(data.series.some(s=>s.group==='other'))host.append(el('p','Additional native scalars are included in Export values and Workspace.telemetry(). Unmapped keys keep their original names.','telemetry-note'));
 }
 async function load(){
  const host=document.querySelector('#trainer-telemetry');if(!host||document.hidden)return;
  const mode=new URLSearchParams(location.search).get('view');if(location.pathname!=='/'||mode&&mode!=='health'){host.hidden=true;return;}
  const ticket=++seq,q=new URLSearchParams();for(const[k,v]of Object.entries(scope))if(v)q.set(k,v);
  try{const r=await fetch('/api/trainer-telemetry?'+q);if(!r.ok)throw Error('Trainer telemetry is unavailable on this collector.');const value=await r.json();if(ticket!==seq)return;host.hidden=false;const signature=JSON.stringify(value);if(signature!==saved){data=value;saved=signature;render();}}
  catch(e){if(ticket===seq){saved='';host.hidden=false;host.replaceChildren(el('p',e.message));}}
 }
 window.addEventListener('jev:scope',e=>{scope=e.detail;load();});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
 setInterval(load,10000);
})();
