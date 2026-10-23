/* Recorded snapshot comparison, independent of trainer-log availability. */
window.ConfigurationComparison={open(experiments,environment=null,initialSources={}){
 if(!document.querySelector('link[href="/configuration-comparison.css"]')){const css=document.createElement('link');css.rel='stylesheet';css.href='/configuration-comparison.css';document.head.append(css);}
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const button=(text,click)=>{const b=el('button',text);b.type='button';b.onclick=click;return b;};
 const prior=document.activeElement,d=el('dialog',undefined,'configuration-dialog');d.setAttribute('aria-label','Compare settings');
 const head=el('header',undefined,'configuration-head');head.append(el('h2','Compare settings'),button('Close',()=>d.close()));
 const content=el('div',undefined,'configuration-content'),intro=el('p','Compare recorded snapshots. Choose the worker or session for each run; operation settings remain separate.','configuration-note');
 const sourcesHost=el('div',undefined,'configuration-sources'),form=el('form',undefined,'configuration-tools'),search=el('input'),only=el('input'),check=el('label');search.type='search';search.placeholder='Find a setting or value…';search.setAttribute('aria-label','Find a setting or value');only.type='checkbox';only.checked=true;check.append(only,'Differences only');
 const searchButton=el('button','Search');searchButton.type='submit';form.append(search,searchButton,check);
 const status=el('p',undefined,'configuration-note');status.setAttribute('role','status');const result=el('div',undefined,'configuration-table'),footer=el('div',undefined,'configuration-tools');
 let sources={...initialSources},query='',offset=0,serial=0,data=null;
 const prev=button('Previous',()=>{offset=Math.max(0,offset-100);load();}),next=button('Next',()=>{offset+=100;load();}),count=el('span');
 const curves=button('Open training curves',()=>{const q=new URLSearchParams({view:'health',experiment:experiments[0],settings_sources:JSON.stringify(sources)});experiments.slice(1).forEach(e=>q.append('signals_compare',e));if(environment)q.set('environment',environment);location.assign('/?'+q);});
 const download=button('Download snapshots',()=>{if(!data)return;const blob=new Blob([JSON.stringify({schema:data.schema,environment,captured_at:data.captured_at,runs:data.runs.map(r=>({experiment:r.experiment,title:r.title,selected:r.selected}))},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='run-settings.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
 const refresh=button('Refresh sources',()=>{sources={};offset=0;load();});
 footer.append(prev,count,next,refresh,download,curves);content.append(intro,sourcesHost,form,status,result,footer);d.append(head,content);document.body.append(d);d.showModal();
 function render(){
  sourcesHost.replaceChildren();
  for(const run of data.runs){
   const card=el('div',undefined,'configuration-source'),label=el('label',run.title),select=el('select');select.setAttribute('aria-label','Snapshot for '+run.title);
   select.append(new Option('No snapshot selected',''));const choices=[...run.choices];if(run.selected&&!choices.some(c=>c.id===run.selected.id))choices.unshift(run.selected);
   choices.forEach((c,i)=>{const session=c.session?(c.session.length<=24?c.session:'Session '+(i+1)):'Source '+(i+1),stamp=new Date(c.received_at).toLocaleString('en',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});select.append(new Option(`${c.kind==='Run configuration'?'Run':c.kind} · ${c.producer.length<=20?c.producer:'Worker'} / ${session} · ${stamp}`,c.id));});
   select.value=run.selected?.id||'';select.onchange=()=>{sources[run.experiment]=select.value||null;offset=0;load();};label.append(select);card.append(label);
   const source=run.selected;if(source){const provenance=el('details');provenance.append(el('summary','Snapshot details'),el('p','Producer: '+source.producer),el('p','Session: '+(source.session||'Not recorded')),el('p','Received: '+source.received_at));if(source.record_id)provenance.append(el('p','Operation: '+source.record_id+' · revision '+source.revision));card.append(provenance);}else card.append(el('p',run.source_count?'Choose a recorded snapshot.':'No settings captured.'));
   if(run.source_count>run.choices.length)card.append(el('small',`Showing ${run.choices.length} recent sources of ${run.source_count}.`));sourcesHost.append(card);
  }
  status.textContent=`${data.differences} differing fields · ${data.fields} fields recorded · snapshots held until Refresh sources.`;
  result.replaceChildren();const table=el('table'),thead=el('thead'),tr=el('tr');tr.append(el('th','Setting'));data.runs.forEach(r=>tr.append(el('th',r.title)));thead.append(tr);table.append(thead);const tbody=el('tbody');table.append(tbody);
  for(const row of data.rows){const tr=el('tr');if(row.different)tr.className='is-different';const name=el('th');name.scope='row';name.append(el('code',row.path||'(root)'));tr.append(name);
   for(const cell of row.cells){const td=el('td');if(!cell.present)td.append(el('span','Not recorded','configuration-missing'));else{const value=JSON.stringify(cell.value,null,2);td.append(el('small',cell.type));if(value.length>500){const detail=el('details');detail.append(el('summary',value.slice(0,100)+'…'),el('pre',value));td.append(detail);}else td.append(el('pre',value));}tr.append(td);}tbody.append(tr);
  }
  if(data.rows.length)result.append(el('p','Swipe horizontally to compare columns.','configuration-scroll-hint'),table);else result.append(el('p',data.fields?'No fields match this view.':'No settings recorded in the selected snapshots.'));
  count.textContent=data.total?`${offset+1}–${offset+data.rows.length} of ${data.total}`:'0 fields';prev.disabled=offset===0;next.disabled=offset+data.rows.length>=data.total;
 }
 async function load(){const ticket=++serial;status.textContent='Loading settings…';download.disabled=curves.disabled=true;try{
  const r=await fetch('/api/experiments/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({experiments,environment,sources,q:query,differences_only:only.checked,limit:100,offset})}),value=await r.json();if(ticket!==serial||!d.isConnected)return;if(!r.ok)throw Error(value.error||'Settings unavailable');data=value;
  sources=Object.fromEntries(data.runs.map(r=>[r.experiment,r.selected?.id||null]));render();download.disabled=false;curves.disabled=data.runs.some(r=>!r.trainer_logs);curves.title=curves.disabled?'Trainer logs are required for each selected run.':'';
 }catch(e){if(ticket===serial)status.textContent=e.message;}}
 form.onsubmit=e=>{e.preventDefault();query=search.value;offset=0;load();};only.onchange=()=>{offset=0;load();};d.onclose=()=>{serial++;d.remove();prior?.focus({preventScroll:true});};load();
}};
