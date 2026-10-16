'use strict';
// Source inspection is read-only. Annotation and review live in the behavior map.
(()=>{
 const $=s=>document.querySelector(s),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 let run=null,runId=null,page=0,selected=null,request=0,filtered=[];
 const returnTo=new URLSearchParams(location.search).get('return_to');
 const safeReturn=returnTo?.startsWith('/semantic-map?')?returnTo:null;
 const size=40,text=v=>typeof v==='string'?v:JSON.stringify(v??'',null,2),human=v=>String(v||'Not recorded').replaceAll('_',' ');
 const error=e=>{$('#source-error').textContent=e.message;$('#source-error').hidden=false;};
 async function api(url){const response=await fetch(url),data=await response.json();if(!response.ok)throw Error(data.error||'Source could not be loaded');return data;}
 function route(){const query=new URLSearchParams(location.search),hash=new URLSearchParams(location.hash.slice(1));return {id:query.get('run')||hash.get('run'),event:query.get('event')||hash.get('event')};}
 function detail(event,focus=false){
  selected=event.id;const box=$('#source-detail');box.replaceChildren(el('h2',human(event.kind)+' · '+event.id));
  box.append(el('p',human(event.actor)+' · '+(event.source_pointer||'Source pointer not recorded'),'muted'));
  box.append(el('pre',event.text||'No text was recorded for this event. Structured fields are available below.','source-text'));
  const fields=el('details');fields.append(el('summary','All recorded fields'),el('pre',JSON.stringify(event,null,2)));box.append(fields);
  for(const button of $('#source-events').querySelectorAll('button'))button.setAttribute('aria-pressed',String(button.dataset.event===selected));
  const url=new URL(location.href);url.searchParams.set('event',selected);history.replaceState(null,'',url);
  if(focus&&matchMedia('(max-width: 1000px)').matches){box.tabIndex=-1;box.focus({preventScroll:true});box.scrollIntoView({block:'start',behavior:'instant'});}
 }
 function render(){
  const term=$('#source-search').value.trim().toLowerCase(),kind=$('#source-kind').value;
  filtered=(run?.events||[]).filter(e=>(!kind||e.kind===kind)&&(!term||[e.id,e.text,e.tool,e.actor,e.kind].map(text).join(' ').toLowerCase().includes(term)));
  page=Math.min(page,Math.max(0,Math.ceil(filtered.length/size)-1));const list=$('#source-events');list.replaceChildren();
  for(const event of filtered.slice(page*size,(page+1)*size)){
   const row=el('div');row.setAttribute('role','listitem');const button=el('button');button.dataset.event=event.id;button.setAttribute('aria-pressed',String(event.id===selected));
   button.append(el('strong',(event.index+1)+' · '+human(event.kind)),el('small',human(event.actor)+(event.tool?' · '+text(event.tool):'')),el('span',event.text?.trim()||'Structured event · open recorded fields'));
   button.onclick=()=>detail(event,true);row.append(button);list.append(row);
  }
  if(!filtered.length)list.append(el('p',run?.events?.length?'No events match these filters.':'No source events were recorded.','empty-state'));
  $('#source-count').textContent=filtered.length+' / '+(run?.events?.length||0)+' events';$('#source-page-number').textContent=filtered.length?`${page*size+1}–${Math.min((page+1)*size,filtered.length)} of ${filtered.length}`:'No matches';
  $('#source-previous').disabled=page===0;$('#source-next').disabled=(page+1)*size>=filtered.length;
  if(!filtered.some(e=>e.id===selected)){$('#source-detail').replaceChildren(el('h2','Select an event'),el('p','Choose a recorded event to inspect its full content.'));selected=null;}
 }
 async function load(id,eventId){
  const token=++request;$('#source-error').hidden=true;$('#source-export').disabled=true;
  try{const data=await api('/api/monitoring/rollout/'+encodeURIComponent(id));if(token!==request)return;run=data.run;runId=id;page=0;selected=null;const m=run.metadata||{};
   $('#source-run').value=id;$('#source-title').textContent=m.task_id||'Source record';$('#source-description').textContent='Recorded events in source order. Original language and content are preserved.';
   $('#source-map').href=safeReturn&&new URL(safeReturn,location.origin).searchParams.get('run')===id?safeReturn:'/semantic-map?run='+encodeURIComponent(id);$('#source-search').value='';$('#source-kind').replaceChildren(el('option','All event types'));$('#source-kind').firstChild.value='';
   for(const kind of [...new Set((run.events||[]).map(e=>e.kind))]){const o=el('option',human(kind));o.value=kind;$('#source-kind').append(o);}
   const facts=$('#source-metadata');facts.replaceChildren();for(const [label,value]of [['Rollout',id],['Experiment',m.experiment],['Environment',m.environment],['Training step',m.training_step],['Policy version',m.policy_version||m.checkpoint],['Source format',run.adapter]])facts.append(el('dt',label),el('dd',value==null?'Not recorded':text(value)));
   history.replaceState(null,'','/source?'+new URLSearchParams({run:id,...(eventId?{event:eventId}:{}),...(safeReturn?{return_to:safeReturn}:{})}));$('#source-export').disabled=false;
   const chosen=(run.events||[]).find(e=>e.id===eventId);if(chosen){page=Math.floor(run.events.indexOf(chosen)/size);selected=chosen.id;}render();if(chosen)detail(chosen);
  }catch(e){if(token===request)error(e);}
 }
 $('#source-run').onchange=()=>load($('#source-run').value);for(const id of ['source-search','source-kind'])$('#'+id).addEventListener('input',()=>{page=0;render();});
 $('#source-previous').onclick=()=>{page--;render();};$('#source-next').onclick=()=>{page++;render();};
 $('#source-export').onclick=()=>{if(!run)return;const url=URL.createObjectURL(new Blob([JSON.stringify(run,null,2)],{type:'application/json'})),a=el('a');a.href=url;a.download='source-'+runId+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
 window.addEventListener('hashchange',()=>{const r=route();if(r.id)load(r.id,r.event);});
 (async()=>{try{const data=await api('/api/runs'),select=$('#source-run');select.replaceChildren();select.append(...ChoiceLabels.choices(data.runs.map(r=>({id:r.id,label:ChoiceLabels.rollout(r)})),{fallback:'Rollout',noun:'Rollout'}).map(ChoiceLabels.option));const r=route();if(r.id||data.runs.length)await load(r.id||data.runs[0].id,r.event);else{select.append(el('option','No rollouts imported'));select.disabled=true;$('#source-count').textContent='No recorded events';const a=el('a','Connect data to get started');a.href='/connections';$('#source-events').append(a);}}catch(e){error(e);}})();
})();
