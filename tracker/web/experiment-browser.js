/* Secondary run management; monitoring stays in the training overview. */
(()=>{
 'use strict';
 const host=document.getElementById('experiment-browser');if(!host)return;
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const selected=new Set(),selectionRows=new Map();let scope={},offset=0,query='',sequence=0,visible=false,timer=null,rows=[],project='',state='active',saved=[],workspaceId='',restoredKey='',busy=false,selectionRevision=0,notice='';
 const url=(view,experiment,extra={})=>'/?'+new URLSearchParams({view,experiment,...(scope.environment?{environment:scope.environment}:{}),...extra});
 const link=(label,href)=>{const a=el('a',label);a.href=href;return a;};
 const head=el('div',undefined,'experiment-heading'),copy=el('div');copy.append(el('h2','Experiments'),el('p','Open a run, compare training signals, or select runs to organize together.'));
 head.append(copy,link('Connect data →','/connections#directory-section'));host.append(head);
 const workspaceInfo=el('p',undefined,'experiment-note');host.append(workspaceInfo);
 const identity=fetch('/api/workspace-identity').then(r=>{if(!r.ok)throw Error();return r.json();}).then(w=>{workspaceId=w.identity;workspaceInfo.append('Workspace: '+(w.label||w.name)+' · ',link('Download workspace','/api/workspace/snapshot'));}).catch(()=>{});
 const controls=el('div',undefined,'experiment-controls'),search=el('input'),compare=el('button','Compare training signals'),clear=el('button','Clear selection'),status=el('span');
 search.type='search';search.placeholder='Search experiments…';search.setAttribute('aria-label','Search experiments');
 compare.type=clear.type='button';compare.disabled=true;status.setAttribute('role','status');
 const projects=el('select'),states=el('select'),savedSelect=el('select'),save=el('button','Save selection');save.type='button';
 projects.setAttribute('aria-label','Project');projects.append(new Option('All projects',''));projects.onchange=()=>{project=projects.value;offset=0;load();};
 states.setAttribute('aria-label','Run filter');for(const [value,label]of [['active','Unarchived runs'],['pinned','Pinned runs'],['archived','Archived runs'],['all','All runs']])states.append(new Option(label,value));states.onchange=()=>{state=states.value;offset=0;load();};
 savedSelect.setAttribute('aria-label','Saved comparisons');savedSelect.append(new Option('Saved comparisons',''));savedSelect.onchange=()=>{const item=saved.find(s=>s.name===savedSelect.value);if(!item)return;const q=new URLSearchParams({view:'health',experiment:item.experiments[0]});if(item.environment)q.set('environment',item.environment);item.experiments.slice(1).forEach(n=>q.append('signals_compare',n));location.assign('/?'+q);};
 const searchIn=el('select');searchIn.setAttribute('aria-label','Search in');searchIn.append(new Option('Names & tags','labels'),new Option('Recorded settings','settings'));searchIn.onchange=()=>{offset=0;search.placeholder=searchIn.value==='settings'?'Search a recorded setting or value…':'Search experiments…';load();};
 controls.append(search,searchIn,projects,states,savedSelect);host.append(controls);
 const toolbar=el('div',undefined,'experiment-bulk'),selectionCount=el('strong'),action=el('select'),apply=el('button','Apply'),review=el('details',undefined,'experiment-selected-review'),selection=el('div',undefined,'experiment-selection'),comparisonHint=el('span',undefined,'experiment-comparison-hint');
 action.setAttribute('aria-label','Selected run action');for(const [value,label]of [['','Choose action…'],['project','Move to project'],['tags','Edit tags'],['pin','Pin'],['unpin','Unpin'],['archive','Archive'],['restore','Restore']])action.append(new Option(label,value));
 apply.type='button';action.onchange=sync;review.append(el('summary','Review selection'),selection);
 const bulkActions=el('div',undefined,'experiment-bulk-actions'),comparisonActions=el('div',undefined,'experiment-comparison-actions');
 const settings=el('button','Compare settings');settings.type='button';settings.onclick=()=>ConfigurationComparison.open([...selected],scope.environment||null);
 bulkActions.append(selectionCount,action,apply,clear);comparisonActions.append(compare,settings,save,comparisonHint);toolbar.append(bulkActions,comparisonActions,review);host.append(toolbar,status);
 toolbar.hidden=true;
 const result=el('div',undefined,'experiment-results');host.append(result);
 const footer=el('div',undefined,'experiment-footer'),previous=el('button','Previous'),next=el('button','Next'),count=el('span'),note=el('p',undefined,'experiment-note');
 previous.type=next.type='button';footer.append(previous,count,next);host.insertBefore(footer,result);host.append(note);
 const selectionKey=()=>workspaceId?'rilldex.experiments.selection:'+JSON.stringify([workspaceId,scope.environment||null]):'';
 function remember(){try{const key=selectionKey();if(key)localStorage.setItem(key,JSON.stringify([...selected]));}catch(_){}}
 function restore(){const key=selectionKey();if(!key||key===restoredKey)return;restoredKey=key;selected.clear();selectionRows.clear();try{const ids=JSON.parse(localStorage.getItem(key)||'[]');if(Array.isArray(ids)&&ids.length<=500&&ids.every(v=>typeof v==='string'&&v.trim()&&v.length<=500))ids.forEach(v=>selected.add(v));}catch(_){}selectionRevision++;}
 function sync(){
  const outside=[...selected].filter(id=>!rows.some(r=>r.experiment===id)).length,missingLogs=[...selected].filter(id=>!selectionRows.get(id)?.logs).length;
  toolbar.hidden=!selected.size;selectionCount.textContent=selected.size+' selected'+(outside?' · '+outside+' outside this page':'');
  const comparable=selected.size>=2&&selected.size<=3&&!missingLogs;
  settings.disabled=busy||selected.size<2||selected.size>3;
  save.disabled=busy||!selected.size||selected.size>3||!!missingLogs;
  compare.disabled=busy||!comparable;compare.textContent=selected.size>=2&&selected.size<=3?'Compare '+selected.size+' runs':'Compare curves';clear.disabled=busy;action.disabled=busy;apply.disabled=busy||!action.value||!selected.size;
  comparisonHint.textContent=selected.size>3?'Choose 2–3 runs for curve comparison.':missingLogs?missingLogs+' selected '+(missingLogs===1?'run has':'runs have')+' no trainer logs in this environment.':selected.size===1?'Select another run to compare curves.':'';
  selection.replaceChildren();for(const name of selected){const chip=el('button',(selectionRows.get(name)?.title||name)+' ×');chip.type='button';chip.disabled=busy;chip.setAttribute('aria-label','Remove '+name+' from selection');chip.onclick=()=>{selected.delete(name);selectionRevision++;remember();sync();};selection.append(chip);}
  for(const input of result.querySelectorAll('tbody input[type=checkbox]')){input.checked=selected.has(input.value);input.disabled=busy||!input.checked&&selected.size>=500;input.closest('tr').classList.toggle('is-selected',input.checked);}
  selectPage.checked=!!rows.length&&rows.every(r=>selected.has(r.experiment));selectPage.indeterminate=!selectPage.checked&&rows.some(r=>selected.has(r.experiment));selectPage.disabled=busy||!rows.length;
 }
 compare.onclick=()=>{const names=[...selected],q=new URLSearchParams({view:'health',experiment:names[0],...(scope.environment?{environment:scope.environment}:{})});for(const name of names.slice(1))q.append('signals_compare',name);location.assign('/?'+q);};
 clear.onclick=()=>{selected.clear();selectionRevision++;remember();sync();};
 async function post(path,value){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)}),data=await r.json();if(!r.ok)throw Error(data.error||'Save failed');return data;}
 function editor(title,inputs,onSave){
  const prior=document.activeElement,d=el('dialog',undefined,'run-details-dialog'),head=el('div',undefined,'run-detail-head'),close=el('button','Close');d.setAttribute('aria-label',title);close.type='button';close.onclick=()=>d.close();head.append(el('h2',title),close);d.append(head);
  const form=el('form',undefined,'run-detail-content capture-edit'),message=el('p'),submit=el('button','Save');submit.type='submit';const controls={};
  for(const [key,label,value,type]of inputs){const wrapper=el('label',label),input=el(type==='textarea'?'textarea':'input');if(type==='checkbox'){input.type='checkbox';input.checked=!!value;}else{input.value=value;if(type!=='textarea')input.type='text';}wrapper.append(input);if(key==='project'){input.maxLength=200;const choices=el('datalist');choices.id='experiment-project-choices';for(const option of projects.options)if(option.value)choices.append(new Option(option.value,option.value));input.setAttribute('list',choices.id);form.append(choices);}form.append(wrapper);controls[key]=input;}
  message.setAttribute('role','status');form.append(message,submit);form.onsubmit=async e=>{e.preventDefault();submit.disabled=true;try{await onSave(Object.fromEntries(Object.entries(controls).map(([k,v])=>[k,v.type==='checkbox'?v.checked:v.value])));d.close();load();}catch(error){message.textContent=error.message;submit.disabled=false;}};
  d.append(form);d.onclose=()=>{d.remove();prior?.focus();};document.body.append(d);d.showModal();
 }
 function organize(row){editor('Organize run',[
  ['title','Run name',row.title,'text'],['project','Project · leave empty to unassign',row.project,'text'],['tags','Tags · comma separated',row.tags.join(', '),'text'],['notes','Notes',row.notes,'textarea'],['pinned','Pin run',row.pinned,'checkbox'],['archived','Archive run',row.archived,'checkbox']
 ],value=>post('/api/experiment-labels',{experiment:row.experiment,...value,tags:value.tags.split(',').map(v=>v.trim()).filter(Boolean)}));}
 save.onclick=()=>editor('Save comparison',[['name','Name · saving an existing name replaces that selection','','text']],value=>post('/api/experiment-selections',{name:value.name,experiments:[...selected],environment:scope.environment||null}));
 const tags=value=>value.split(',').map(t=>t.trim()).filter(Boolean);
 async function bulk(experiments,changes){busy=true;sync();try{const value=await post('/api/experiments/organize',{experiments,...changes});notice=value.updated+' runs updated.';status.textContent=notice;action.value='';return value;}finally{busy=false;sync();}}
 apply.onclick=async()=>{
  const experiments=[...selected],label=experiments.length+' selected runs';
  if(action.value==='project'){editor('Move '+label,[['project','Project · leave empty to unassign','','text']],value=>bulk(experiments,{project:value.project}));return;}
  if(action.value==='tags'){editor('Edit tags on '+label,[['add','Add tags · comma separated','','text'],['remove','Remove tags · comma separated','','text']],value=>bulk(experiments,{add_tags:tags(value.add),remove_tags:tags(value.remove)}));return;}
  const changes={pin:{pinned:true},unpin:{pinned:false},archive:{archived:true},restore:{archived:false}}[action.value];
  if(changes)try{await bulk(experiments,changes);await load();}catch(e){status.textContent=e.message;}
 };
 const pageSelection=el('label',undefined,'experiment-page-selection'),selectPage=el('input');selectPage.type='checkbox';selectPage.setAttribute('aria-label','Select this page');pageSelection.append(selectPage,'Select this page');footer.prepend(pageSelection);
 selectPage.onchange=()=>{if(selectPage.checked){const additions=rows.filter(r=>!selected.has(r.experiment));if(selected.size+additions.length>500){status.textContent='Select up to 500 runs at a time.';sync();return;}for(const row of additions){selected.add(row.experiment);selectionRows.set(row.experiment,row);}}else rows.forEach(r=>selected.delete(r.experiment));selectionRevision++;remember();sync();};
 search.oninput=()=>{query=search.value;offset=0;clearTimeout(timer);timer=setTimeout(load,180);};
 previous.onclick=()=>{offset=Math.max(0,offset-30);load();};next.onclick=()=>{offset+=30;load();};
 async function load(){
  if(!visible)return;const ticket=++sequence;status.textContent='Loading…';
  try{
   await identity;if(ticket!==sequence||!visible)return;restore();
   const revision=selectionRevision,ids=[...selected];
   const q=new URLSearchParams({q:query,search_in:searchIn.value,offset,limit:30,state,...(project?{project}:{}),...(scope.environment?{environment:scope.environment}:{})});
   const [response,resolved]=await Promise.all([fetch('/api/experiments?'+q),ids.length?post('/api/experiments/selection',{experiments:ids,environment:scope.environment||null}):Promise.resolve({rows:[],unavailable:[]})]),data=await response.json();if(ticket!==sequence||!visible)return;if(!response.ok)throw Error(data.error||'Experiments unavailable');
   if(offset&&offset>=data.total){offset=Math.max(0,Math.floor((data.total-1)/30)*30);return load();}
   rows=data.rows;for(const row of [...resolved.rows,...rows])selectionRows.set(row.experiment,row);host.hidden=false;
   let removed=0;if(revision===selectionRevision){for(const id of resolved.unavailable){selected.delete(id);removed++;}remember();}
   projects.replaceChildren(new Option('All projects',''));for(const name of data.projects||[])projects.append(new Option(name,name));projects.value=project;
   saved=data.selections||[];savedSelect.replaceChildren(new Option('Saved comparisons',''));for(const s of saved)savedSelect.append(new Option(s.name,s.name));
   status.textContent=removed?removed+' unavailable runs removed from selection.':notice;result.replaceChildren();const table=el('table'),thead=el('thead'),header=el('tr');
   for(const title of ['Select','Experiment / recorded trainer','Rollouts','Trainer logs','Last received','Open']){const th=el('th',title);th.scope='col';header.append(th);}thead.append(header);table.append(thead);
   const body=el('tbody');table.append(body);
   for(const row of rows){
    const tr=el('tr'),checkCell=el('td'),check=el('input');check.type='checkbox';check.value=row.experiment;check.setAttribute('aria-label','Select '+row.experiment);check.dataset.hasLogs=String(!!row.logs);
    check.onchange=()=>{if(check.checked)selected.add(row.experiment);else selected.delete(row.experiment);selectionRevision++;remember();sync();};checkCell.append(check);tr.append(checkCell);
    const name=el('td');name.append(link((row.pinned?'★ ':'')+row.title,url('',row.experiment)));if(row.project||row.tags.length)name.append(el('small',[row.project,...row.tags].filter(Boolean).join(' · ')));
    const contexts=row.trainer_contexts;if(contexts.length===1)name.append(el('small',contexts[0].framework+' · '+contexts[0].objective));
    else name.append(el('small',contexts.length?contexts.length+' recorded trainer configurations':'No trainer metadata'));
    if(contexts.length){const detail=el('details');detail.append(el('summary','Trainer details'));for(const c of contexts)detail.append(el('p',c.framework+' '+c.framework_version+' · '+c.objective));name.append(detail);}
    const rollouts=el('td',row.rollouts.toLocaleString()),logs=el('td',row.logs.toLocaleString());rollouts.dataset.label='Rollouts';logs.dataset.label='Trainer logs';tr.append(name,rollouts,logs);
    const received=el('td'),time=el('time',new Date(row.last_received).toLocaleString());received.dataset.label='Last received';time.dateTime=row.last_received;received.append(time);tr.append(received);
    const actions=el('td',undefined,'experiment-links'),details=el('button','Run details'),edit=el('button','Organize');edit.type=details.type='button';edit.onclick=()=>organize(row);details.onclick=()=>ExperimentDetails.open(row.experiment,scope.environment,row.title);actions.append(details,edit);if(row.logs)actions.append(link('Training',url('health',row.experiment)));if(row.rollouts)actions.append(link('Behavior',url('measures',row.experiment)),link('Rollouts','/runs?'+new URLSearchParams({experiment:row.experiment,...(scope.environment?{environment:scope.environment}:{})})));if(row.executions)actions.append(link('Execution',url('execution',row.experiment)));if(row.training_records)actions.append(link('Training data',url('training',row.experiment)));tr.append(actions);body.append(tr);
   }
   if(rows.length)result.append(table);else result.append(el('p',query?'No matching experiments.':project||state!=='active'?'No runs in this view. Change the project or run filter.':'No experiment data received. Connect a trainer or import saved output to start.'));
   count.textContent=data.total?(offset+1)+'–'+(offset+rows.length)+' of '+data.total:'0 experiments';previous.disabled=offset===0;next.disabled=offset+rows.length>=data.total;
   note.textContent='Last received is data arrival, not training status. Trainer details show recorded identifiers, not a full configuration snapshot.'+(data.unassigned_rollouts?' '+data.unassigned_rollouts+' rollouts have no experiment assigned.':'');
   sync();
  }catch(e){if(ticket===sequence)status.textContent=e.message;}
 }
 window.addEventListener('jev:scope',e=>{
  const section=typeof OverviewLayout!=='undefined'?OverviewLayout.mode(location.search).section:'';
  const allowed=['/','/dashboard'].includes(location.pathname)&&section==='library';
  const changed=(scope.environment||null)!==(e.detail.environment||null);scope=e.detail;visible=allowed;host.hidden=!allowed;
  if(!allowed){sequence++;return;}if(changed){selected.clear();selectionRows.clear();offset=0;notice='';}load();
 });
})();
