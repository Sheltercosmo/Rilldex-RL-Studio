/* Complete hardware history; plot reduction never changes the statistics. */
(()=>{
 'use strict';
 const units=(value,unit)=>value==null?'Unavailable':(unit==='bytes'?value/1073741824:value).toLocaleString(undefined,{maximumFractionDigits:1})+' '+(unit==='bytes'?'GiB':unit);
 function segments(points){const groups=[];let previous=null;for(const p of points){if(p.segment!==previous){groups.push([]);previous=p.segment;}groups.at(-1).push(p);}return groups;}
 if(typeof module!=='undefined'){module.exports={segments,units};return;}
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const button=(text,fn)=>{const b=el('button',text);b.type='button';b.onclick=fn;return b;};
 const stamp=value=>new Date(value).toLocaleString('en-GB',{timeZone:'UTC',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'})+' UTC';
 function mount(host,experiment,options={}){
  let disposed=false,serial=0,offset=0,asOf=options.asOf??null,range=options.timeRange||null,worker=options.selection?JSON.stringify([options.selection.producer,options.selection.session]):'',live=false,timer=null;
  const tools=el('div',undefined,'capture-tools'),workers=el('select'),refresh=button('Refresh latest',()=>{asOf=null;load();}),follow=button('Follow',()=>{live=!live;follow.textContent=live?'Pause follow':'Follow';follow.setAttribute('aria-pressed',String(live));if(live)asOf=null;load();});
  workers.setAttribute('aria-label','Worker and session');tools.append(workers,refresh,follow);
  const form=el('form',undefined,'hardware-range'),start=el('input'),end=el('input');for(const [input,label]of [[start,'From (UTC)'],[end,'To (UTC)']]){input.type='datetime-local';input.step='0.001';input.setAttribute('aria-label',label);const field=el('label',label);field.append(input);form.append(field);}
  if(range){start.value=range.start?new Date(range.start).toISOString().slice(0,23):'';end.value=range.end?new Date(range.end).toISOString().slice(0,23):'';}
  const select=el('button','Select interval');select.type='submit';form.append(select,button('Full history',()=>{range=null;start.value=end.value='';offset=0;load();}));
  const status=el('p',undefined,'run-detail-note'),error=el('p',undefined,'hardware-error'),result=el('div'),pager=el('div',undefined,'run-detail-pager');status.setAttribute('role','status');error.setAttribute('role','alert');
  host.append(tools,form,status,error,result,pager,el('p','Machine samples, grouped by host and process capture. Means use recorded samples; workers may have different clock offsets.','run-detail-note'));
  workers.onchange=()=>{worker=workers.value;offset=0;const pair=worker?JSON.parse(worker):null;options.onSelection?.(pair?{producer:pair[0],session:pair[1]}:null);load();};
  form.onsubmit=e=>{e.preventDefault();try{range={start:start.value?new Date(start.value+'Z').toISOString():null,end:end.value?new Date(end.value+'Z').toISOString():null};if(range.start&&range.end&&range.start>range.end)throw Error('Start time must not follow end time');live=false;follow.textContent='Follow';follow.setAttribute('aria-pressed','false');offset=0;load();}catch(e){error.textContent=e.message;}};
  function openLogs(group,selected){ExperimentDetails.open(experiment,null,options.displayName,{section:'console',capture:{producer:group.producer,session:group.session},timeRange:selected,asOf});}
  function chart(series,group){
   const card=el('section',undefined,'capture-chart hardware-chart');card.dataset.sensor=series.key;
   const value=el('div',units(series.latest?.value,series.unit),'hardware-value');value.append(el('small','latest sample'));card.append(el('strong',series.label),value);
   const summary=el('p',undefined,'run-detail-note');summary.append('Peak '+units(series.maximum?.value,series.unit)+' · mean '+units(series.mean,series.unit));card.append(summary);
   if(!series.points.length){card.append(el('p','0 / '+group.samples+' samples measured · sensor values unavailable.','run-detail-note'));return card;}
   const NS='http://www.w3.org/2000/svg',svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 500 180');svg.setAttribute('role','img');svg.setAttribute('aria-label',series.label+' across the selected capture interval');
   const add=(tag,attrs,text)=>{const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!=null)n.textContent=text;svg.append(n);return n;};
   const lo=Date.parse(group.start),hi=Date.parse(group.end),max=series.unit==='%'?100:Math.max(1,series.maximum.value),x=t=>48+440*(Date.parse(t)-lo)/Math.max(1,hi-lo),y=v=>145-125*v/max;
   for(const v of [0,max/2,max]){add('line',{x1:48,x2:488,y1:y(v),y2:y(v),stroke:'#e2e7ef'});add('text',{x:42,y:y(v)+4,'text-anchor':'end',fill:'#5c687b','font-size':14},units(v,series.unit).split(' ')[0]);}
   for(const group of segments(series.points)){
    add('polyline',{points:group.map(p=>x(p.time)+','+y(p.value)).join(' '),fill:'none',stroke:'#355bdb','stroke-width':2});
    if(group.length===1)add('circle',{cx:x(group[0].time),cy:y(group[0].value),r:2.5,fill:'#355bdb'});
   }
   add('text',{x:48,y:170,fill:'#5c687b','font-size':14},stamp(group.start));add('text',{x:488,y:170,'text-anchor':'end',fill:'#5c687b','font-size':14},stamp(group.end));
   const details=el('div',undefined,'hardware-sample'),cursor=add('line',{x1:0,x2:0,y1:12,y2:145,stroke:'#9eabc5','stroke-dasharray':'4 3',visibility:'hidden'});
   function inspect(p){cursor.setAttribute('x1',x(p.time));cursor.setAttribute('x2',x(p.time));cursor.setAttribute('visibility','visible');details.replaceChildren(el('span',stamp(p.time)+' · '+units(p.value,series.unit)),button('Logs ±30 seconds',()=>openLogs(group,{start:new Date(Date.parse(p.time)-30000).toISOString(),end:new Date(Date.parse(p.time)+30000).toISOString()})));}
   svg.onclick=e=>{const rect=svg.getBoundingClientRect(),pixel=(e.clientX-rect.left)*500/rect.width;inspect(series.points.reduce((best,p)=>Math.abs(x(p.time)-pixel)<Math.abs(x(best.time)-pixel)?p:best));};
   card.append(svg,el('p',series.measured+' / '+group.samples+' samples measured'+(series.missing?' · '+series.missing+' unavailable':'')+' · '+series.points.length+' plot points','run-detail-note'),button('Inspect peak',()=>inspect(series.maximum)),details);return card;
  }
  function renderGroup(group,index){
   const card=el('article',undefined,'run-detail-record hardware-group'),head=el('div',undefined,'run-detail-record-head');head.append(el('h3',group.host+' · '+group.producer),el('span','Capture '+index+' · '+group.samples.toLocaleString()+' samples'));card.append(head);
   const actions=el('div',undefined,'capture-tools');actions.append(button('Open interval logs',()=>openLogs(group,{start:range?.start||group.start,end:range?.end||group.end})));card.append(actions);
   const charts=el('div',undefined,'capture-charts');for(const s of group.series.filter(s=>!s.device&&!s.key.endsWith('total_bytes')))charts.append(chart(s,group));card.append(charts);
   const devices=[...new Set(group.series.filter(s=>s.device).map(s=>s.device))];
   devices.forEach((device,i)=>{const rows=group.series.filter(s=>s.device===device),details=el('details',undefined,'hardware-device'),name=rows[0].device_name,capacity=rows.find(s=>s.key.endsWith('memory_total_bytes"]'));
    const title=el('summary',name+' · device '+(i+1)+(capacity?.latest?.value!=null?' · '+units(capacity.latest.value,'bytes'):''));title.title=device;details.append(title);let loaded=false;
    function expand(){if(!details.open||loaded)return;loaded=true;const main=el('div',undefined,'capture-charts'),extra=el('details'),other=el('div',undefined,'capture-charts');
     for(const s of rows){if(s.key.endsWith('memory_total_bytes"]'))continue;(s.label==='Temperature'||s.label==='Power'?other:main).append(chart(s,group));}
     extra.append(el('summary','Temperature & power'),other);details.append(main,extra);}
    details.ontoggle=expand;details.open=i===0;expand();card.append(details);
   });
   if(group.unavailable.length){const gaps=el('details');gaps.append(el('summary','Sensor availability'),el('p',group.unavailable.join(' · '),'run-detail-note'));card.append(gaps);}return card;
  }
  async function load(){
   clearTimeout(timer);const ticket=++serial;status.textContent='Loading hardware history…';error.textContent='';result.inert=true;result.setAttribute('aria-busy','true');
   try{
    const q=new URLSearchParams({experiment,offset});if(worker){const pair=JSON.parse(worker);q.set('producer',pair[0]);q.set('session',pair[1]);}if(asOf!=null&&!live)q.set('as_of',asOf);if(range?.start)q.set('observed_from',range.start);if(range?.end)q.set('observed_to',range.end);
    const response=await fetch('/api/hardware-history?'+q),data=await response.json();if(disposed||ticket!==serial)return;if(!response.ok)throw Error(data.error||'Hardware history unavailable');asOf=data.as_of;
    workers.replaceChildren(new Option('All workers / sessions',''));data.streams.forEach((s,i)=>workers.append(new Option(s.producer+' · capture '+(i+1),JSON.stringify([s.producer,s.session]))));if(worker&&![...workers.options].some(o=>o.value===worker))workers.append(new Option('Selected capture · no samples',worker));workers.value=worker;
    status.textContent=data.total_samples.toLocaleString()+' samples in '+data.group_count+' host/process groups · '+(live?'live, refreshes every 3 seconds':'captured view; Refresh latest includes later arrivals');result.replaceChildren();pager.replaceChildren();
    data.groups.forEach((group,i)=>result.append(renderGroup(group,data.offset+i+1)));
    if(!data.groups.length)result.append(el('p',range?'No hardware samples in this interval.':'No hardware captured. Start collection with rilldex record or Run.'),el('pre','rilldex --db study.sqlite record --name trial-1 -- python -u train.py','capture-example'));
    if(data.group_count>data.limit){const prev=button('Previous captures',()=>{offset=Math.max(0,offset-data.limit);load();}),next=button('Next captures',()=>{offset+=data.limit;load();});prev.disabled=!offset;next.disabled=offset+data.limit>=data.group_count;pager.append(prev,el('span',(offset+1)+'–'+Math.min(offset+data.limit,data.group_count)+' of '+data.group_count),next);}
   }catch(e){if(!disposed&&ticket===serial){status.textContent='';error.textContent=e.message;}}
   if(!disposed&&ticket===serial){result.inert=false;result.setAttribute('aria-busy','false');if(live)timer=setTimeout(load,3000);}
  }
  load();return ()=>{disposed=true;serial++;clearTimeout(timer);};
 }
 window.HardwareHistory={mount};
})();
