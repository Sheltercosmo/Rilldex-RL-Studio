'use strict';
window.trackerActivityTimeline=(()=>{
 const $=s=>document.querySelector(s),node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
 let data=null,kind=null,key=null,actor=null,profile=null,windowIndex=0,selectUnit=null,selected=null;
 const option=(parent,value,label)=>{const o=node('option',label);o.value=value??'';parent.append(o);};
 const streams=()=>data.timeline.streams.filter(s=>s.kind===kind);
 const stream=()=>streams().find(s=>s.trajectory_id===actor);
 const view=()=>stream()?.views.find(v=>(v.profile_id??'')===(profile??''));
 const fieldLabel=(activity,field)=>field==='plan'&&activity.taxonomy_version==='general-activities/2'?'Intended steps / plans (broad)':activity.taxonomy[field]?.label||field.replaceAll('_',' ');
 const fields=()=>data.timeline.field_order.map(field=>[field,{...data.taxonomy[field],label:fieldLabel(data,field)}]);
 function profiles(){const s=stream(),root=$('#activity-time-profile');root.replaceChildren();for(const v of s?.views||[]){const p=data.timeline.profiles[v.profile_id];option(root,v.profile_id,p?`${p.model} · ${p.harness} · ${p.selection_policy}`:'No current observations');}if(!s?.views.some(v=>(v.profile_id??'')===(profile??'')))profile=s?.views[0]?.profile_id??null;root.value=profile??'';}
 function draw(){
  const root=$('#activity-time-grid'),s=stream(),v=view();root.replaceChildren();const windows=v?.windows||[];windowIndex=Math.max(0,Math.min(windowIndex,windows.length-1));const w=windows[windowIndex],range=$('#activity-time-window');range.replaceChildren();for(const [i,item] of windows.entries())option(range,String(i),`Units ${item.start+1}–${item.end}`);range.value=String(windowIndex);range.disabled=!w;$('#activity-time-prev').disabled=!w||windowIndex===0;$('#activity-time-next').disabled=!w||windowIndex===windows.length-1;
  const overview=$('#activity-time-overview');overview.replaceChildren();overview.hidden=windows.length<2;
  if(!s||!w){$('#activity-time-summary').textContent='No eligible source units of this kind are recorded.';return;}
  if(windows.length>1){
   overview.append(node('h4','Whole rollout · consecutive source windows'),node('p','Each bar separates present, absent and unknown for one activity. Labels show present / all units, followed by unknown units. Select a window to inspect its source cells.','muted'));
   const wrap=node('div',undefined,'activity-window-scroll'),t=node('table',undefined,'activity-window-table'),head=node('thead'),header=node('tr');header.append(node('th','Activity'));for(const item of windows)header.append(node('th',`${item.start+1}–${item.end}`));head.append(header);t.append(head);const body=node('tbody');
   for(const [field,definition] of fields()){const row=node('tr');row.append(node('th',definition.label));for(const [i,item] of windows.entries()){const c=item.fields[field],b=node('button',undefined,'activity-window-cell');b.dataset.field=field;b.dataset.window=String(i);b.setAttribute('aria-pressed',String(i===windowIndex));b.setAttribute('aria-label',`${definition.label}, source units ${item.start+1}–${item.end}: ${c.present} present, ${c.absent} absent, ${c.unknown} unknown of ${c.denominator}.`);b.append(node('span',`${c.present} / ${c.denominator} · ? ${c.unknown}`));const bar=node('span',undefined,'activity-window-bar');for(const name of ['present','absent','unknown']){const segment=node('span',undefined,name);segment.style.width=(100*c[name]/c.denominator)+'%';bar.append(segment);}b.append(bar);b.onclick=()=>{windowIndex=i;draw();$('#activity-time-grid').scrollIntoView({block:'nearest'});};const td=node('td');td.append(b);row.append(td);}body.append(row);}t.append(body);wrap.append(t);overview.append(wrap);
  }
  const shown=s.units.slice(w.start,w.end),table=node('table',undefined,'activity-time-table'),head=node('thead'),tr=node('tr');tr.append(node('th','Activity / source position'));for(const [i,u] of shown.entries()){const th=node('th',String(w.start+i+1));th.scope='col';th.title=u.event_id;tr.append(th);}tr.append(node('th','Present / absent / unknown'));head.append(tr);table.append(head);const body=node('tbody');
  for(const [field,definition] of fields()){
   const row=node('tr');row.dataset.field=field;const label=node('th',definition.label);label.scope='row';label.title=definition.definition;row.append(label);
   for(const [i,u] of shown.entries()){
    const original=u.states[field],state=u.profile_id&&u.profile_id!==profile?{value:null,availability:'other_profile',reason:'This unit has a current observation from a different observer.'}:original;
    const limited=state.value&&state.value!=='unresolved'&&state.availability!=='available',symbol=state.value==='present'?'+':state.value==='absent'?'−':state.value==='unresolved'?'?':state.availability==='stale'?'S':state.availability==='other_profile'?'V':'·';
    const b=node('button',symbol+(limited?'!':''),'activity-time-cell '+(state.availability==='available'?state.value:limited?'limited':'unknown'));
    b.dataset.unitId=u.id;b.dataset.field=field;b.dataset.value=state.value??'';b.dataset.availability=state.availability;b.setAttribute('aria-current',String(u.id===selected));
    const description=`${definition.label}, source unit ${w.start+i+1}, ${u.event_id}. Selected option: ${state.value??'none'}. Availability: ${state.availability.replaceAll('_',' ')}.${state.reason?' '+state.reason:''}`;
    b.setAttribute('aria-label',description);b.title=description;b.onclick=()=>selectUnit(u.id,field);const td=node('td');td.append(b);row.append(td);
   }
   const count=w.fields[field],td=node('td',`${count.present} / ${count.absent} / ${count.unknown}`,'activity-time-count');td.dataset.field=field;td.title=`${count.denominator} source units. Unknown reasons: ${JSON.stringify(count.unknown_reasons)}. Raw selected options: ${JSON.stringify(count.selected_options)}.`;row.append(td);body.append(row);
  }
  table.append(body);root.append(table);$('#activity-time-summary').textContent=`Source units ${w.start+1}–${w.end} of ${s.units.length} · actor ${s.trajectory_id}. All eligible units remain in order, including unobserved units. Text and tag filters below affect the list only.`;
 }
 function render(activity,runId,unitKind,unitSelected,onSelect){
  data=activity;selectUnit=onSelect;const changed=key!==runId+':'+unitKind;kind=unitKind;key=runId+':'+unitKind;
  $('#activity-timeline').hidden=false;$('#activity-timeline').dataset.runId=runId;
  if(!activity.timeline){$('#activity-time-summary').textContent='Restart the server to load the semantic activity timeline.';$('#activity-time-grid').replaceChildren();$('#activity-time-controls').hidden=true;return;}
  $('#activity-time-controls').hidden=false;$('#activity-time-definition').textContent=activity.timeline.definition;
  const all=streams();if(changed||!all.some(s=>s.trajectory_id===actor)){actor=all[0]?.trajectory_id;profile=null;windowIndex=0;}
  if(unitSelected&&unitSelected!==selected){const s=all.find(s=>s.units.some(u=>u.id===unitSelected));if(s){actor=s.trajectory_id;windowIndex=Math.floor(s.units.findIndex(u=>u.id===unitSelected)/activity.timeline.window_size);}}
  selected=unitSelected;const actors=$('#activity-time-actor');actors.replaceChildren();for(const s of all)option(actors,s.trajectory_id,s.trajectory_id);actors.value=actor??'';actors.disabled=!all.length;profiles();draw();
 }
 $('#activity-time-actor').onchange=()=>{actor=$('#activity-time-actor').value;profile=null;windowIndex=0;profiles();draw();};
 $('#activity-time-profile').onchange=()=>{profile=$('#activity-time-profile').value||null;draw();};
 $('#activity-time-window').onchange=()=>{windowIndex=Number($('#activity-time-window').value);draw();};
 $('#activity-time-prev').onclick=()=>{windowIndex--;draw();};$('#activity-time-next').onclick=()=>{windowIndex++;draw();};
 return {render,fieldLabel};
})();
