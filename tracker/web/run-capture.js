/* Console and machine context share the durable run capture, with explicit worker scope. */
(()=>{
 'use strict';
 function configEntries(value,path=[]){
  if(!path.length&&value&&typeof value==='object'&&!Array.isArray(value)&&!Object.keys(value).length)return [];
  if(value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length)
   return Object.keys(value).sort().flatMap(key=>configEntries(value[key],[...path,key]));
  return [[JSON.stringify(path),value]];
 }
 function canonical(value){return JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);}
 function fileSize(bytes){const units=['bytes','KiB','MiB','GiB','TiB','PiB'];let unit=0;while(bytes>=1024&&unit<units.length-1){bytes/=1024;unit++;}return bytes.toLocaleString(undefined,{maximumFractionDigits:unit?2:0})+' '+units[unit];}
 function configChanges(before,after){
  const a=new Map(configEntries(before)),b=new Map(configEntries(after));
  return [...new Set([...a.keys(),...b.keys()])].filter(k=>a.has(k)!==b.has(k)||canonical(a.get(k))!==canonical(b.get(k)))
   .map(k=>({path:JSON.parse(k),before:a.get(k),after:b.get(k),beforePresent:a.has(k),afterPresent:b.has(k)}));
 }
 if(typeof module!=='undefined'){module.exports={configChanges};return;}
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const button=(text,fn)=>{const b=el('button',text);b.type='button';b.onclick=fn;return b;};
 const formatTime=value=>new Date(value).toLocaleString('en-GB',{timeZone:'UTC',hour12:false})+' UTC';
 const fields=value=>{const dl=el('dl',undefined,'run-detail-fields');for(const [k,v] of Object.entries(value))dl.append(el('dt',k),el('dd',v===null?'null':typeof v==='object'?JSON.stringify(v,null,2):String(v)));return dl;};
 function mount(host,experiment,kind,options={}){
  if(kind==='hardware')return HardwareHistory.mount(host,experiment,options);
  let timeRange=options.timeRange||null,asOf=options.asOf??null;
  let disposed=false,serial=0,cursor=0,pages=[],query='',worker=options.selection?JSON.stringify([options.selection.producer,options.selection.session]):'',follow=false,timer=null;
  const tools=el('form',undefined,'capture-tools'),search=el('input'),workers=el('select'),followButton=button('Follow',()=>{follow=!follow;followButton.setAttribute('aria-pressed',String(follow));followButton.textContent=follow?'Pause follow':'Follow';if(follow){asOf=null;load(true);}});
  search.type='search';search.placeholder=kind==='console'?'Search console text…':'Search records…';search.setAttribute('aria-label','Search captured records');workers.setAttribute('aria-label','Worker and session');workers.append(new Option('All workers / sessions',''));
  const submit=el('button','Search');submit.type='submit';tools.append(search,submit,workers);if(kind==='console'||kind==='hardware')tools.append(followButton);
  const status=el('p',undefined,'run-detail-note'),scopeNote=el('p',undefined,'run-detail-note'),result=el('div'),pager=el('div',undefined,'run-detail-pager');status.setAttribute('role','status');host.append(tools,scopeNote,status,result,pager);
  let timeScopeNote;
  if(timeRange||asOf!=null){const scope=el('div',undefined,'capture-time-scope');timeScopeNote=el('p',undefined,'run-detail-note');scope.append(timeScopeNote,button('Clear time filter',()=>{timeRange=null;asOf=null;scope.remove();reset();}));host.insertBefore(scope,scopeNote);}
  if(kind==='file'){
   const referenceForm=el('form',undefined,'capture-reference-form');referenceForm.hidden=true;referenceForm.setAttribute('aria-label','Link stored file');
   const values={};const field=(text,key,parent,type='text')=>{const label=el('label',text),input=el('input');input.type=type;input.setAttribute('aria-label',text);values[key]=input;label.append(input);parent.append(label);return input;};
   referenceForm.append(el('h3','Link stored file'),el('p','Track a checkpoint or dataset in its existing storage. File bytes stay there.','run-detail-note'));
   field('File name','name',referenceForm).required=true;field('Storage URI','uri',referenceForm).required=true;values.uri.placeholder='s3://bucket/checkpoints/model.safetensors';
   const roleLabel=el('label','File type'),role=el('select');role.setAttribute('aria-label','File type');for(const value of ['checkpoint','dataset','model','output','artifact'])role.append(new Option(value[0].toUpperCase()+value.slice(1),value));roleLabel.append(role);referenceForm.append(roleLabel);
   const identity=el('details');identity.append(el('summary','Size, checksum and storage version'));field('Size in bytes','size',identity,'number').min='0';field('SHA-256','sha256',identity);field('Storage version','version',identity);referenceForm.append(identity);
   const save=button('Save reference'),feedback=el('p');save.type='submit';feedback.setAttribute('role','status');referenceForm.append(save,button('Cancel',()=>{referenceForm.hidden=true;}),feedback);
   host.insertBefore(referenceForm,status);tools.append(button('Link stored file',()=>{referenceForm.hidden=!referenceForm.hidden;if(!referenceForm.hidden)values.name.focus();}));
   referenceForm.onsubmit=async event=>{event.preventDefault();save.disabled=true;feedback.textContent='Saving…';
    try{const payload={name:values.name.value,role:role.value,reference:{uri:values.uri.value}};if(values.size.value!==''){payload.size=Number(values.size.value);if(!Number.isSafeInteger(payload.size)||payload.size<0)throw Error('Use an exact, nonnegative byte count');}if(values.sha256.value)payload.sha256=values.sha256.value.trim().toLowerCase();if(values.version.value)payload.reference.version=values.version.value;
     const record={id:crypto.randomUUID(),session:'workspace-files',kind:'file',observed_at:new Date().toISOString(),payload};
     const r=await fetch('/api/run-records',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({schema:'run-records/1',producer:'workspace-upload',experiment,records:[record]})}),data=await r.json();if(!r.ok)throw Error(data.error||'Could not save reference');referenceForm.hidden=true;referenceForm.reset();feedback.textContent='';afterAdd();
    }catch(e){feedback.textContent=e.message;}finally{save.disabled=false;}
   };
   const picker=el('input');picker.type='file';picker.hidden=true;
   const upload=button('Add file · up to 2 MiB',()=>picker.click());tools.append(upload,picker);
   picker.onchange=async()=>{const file=picker.files[0];if(!file)return;upload.disabled=true;
    try{if(file.size>2*1024*1024)throw Error('File snapshots support up to 2 MiB');const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
     const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
     const record={id:crypto.randomUUID(),session:'workspace-files',kind:'file',observed_at:new Date().toISOString(),payload:{name:file.name,size:file.size,sha256:hash,content_base64:btoa(binary)}};
     const r=await fetch('/api/run-records',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({schema:'run-records/1',producer:'workspace-upload',experiment,records:[record]})}),data=await r.json();if(!r.ok)throw Error(data.error||'Upload failed');afterAdd();
    }catch(e){status.textContent=e.message;}finally{upload.disabled=false;picker.value='';}
   };
  }
  function afterAdd(){worker='';query='';search.value='';options.onSelection?.(null);cursor=0;pages=[];load(true);}
  function reset(){cursor=0;pages=[];load();}
  tools.onsubmit=e=>{e.preventDefault();query=search.value;reset();};workers.onchange=()=>{worker=workers.value;const pair=worker?JSON.parse(worker):null;options.onSelection?.(pair?{producer:pair[0],session:pair[1]}:null);reset();};
  async function load(tail=false){
   clearTimeout(timer);const ticket=++serial;
   if(timeScopeNote)timeScopeNote.textContent=(timeRange?'Recorded time: '+(timeRange.start||'start')+' → '+(timeRange.end||'end'):'All recorded times')+(asOf!=null?' · saved capture':' · current received records');
   try{
    const q=new URLSearchParams({experiment,kind,q:query,after:tail?0:cursor,limit:100,tail:tail?'1':'0'});
    if(worker){const [producer,session]=JSON.parse(worker);q.set('producer',producer);q.set('session',session);}
    if(timeRange?.start)q.set('observed_from',timeRange.start);if(timeRange?.end)q.set('observed_to',timeRange.end);if(asOf!=null)q.set('as_of',asOf);
    const response=await fetch('/api/run-records?'+q),data=await response.json();if(disposed||ticket!==serial)return;if(!response.ok)throw Error(data.error||'Capture unavailable');
    workers.replaceChildren(new Option('All workers / sessions',''));data.streams.forEach((s,i)=>workers.append(new Option(s.producer+' · capture '+(s.ordinal||i+1),JSON.stringify([s.producer,s.session]))));
    if(worker&&![...workers.options].some(o=>o.value===worker))workers.append(new Option('Selected capture · unavailable',worker));workers.value=worker;
    scopeNote.textContent=worker?'Current saved process capture across Config, Logs, Hardware, Files and Sessions. It may span several training calls; the chart interval does not filter these records.':'Showing all process captures for this run.';
    if(timeRange)scopeNote.textContent=(worker?'Selected process capture':'All process captures')+' · filtered by recorded time.';
    status.textContent=data.total+' matching records · '+data.rows.length+' shown'+(tail?' · latest window':'')+(follow?' · refreshes every 3 seconds':'');result.replaceChildren();pager.replaceChildren();
    if(!data.rows.length){result.append(el('p',query?'No matching records.':'No '+({manifest:'config or runtime',console:'console logs',hardware:'hardware samples',file:'file snapshots',lifecycle:'session events'}[kind])+' captured.'));
     if(!query)result.append(el('pre','rilldex --db study.sqlite record --project my-project --name run-1 -- python -u train.py','capture-example'));
     if(kind==='file')result.append(el('pre','run.add_file("config.yaml")  # snapshots up to 2 MiB','capture-example'));
    }
    for(const row of ['manifest','file'].includes(kind)?[...data.rows].reverse():data.rows){
     const p=row.record.payload,card=el('article',undefined,'run-detail-record');
     const stamp=formatTime(row.observed_at)+' · '+row.producer;
     if(kind==='console'){
      card.classList.add('capture-console');card.append(el('small',p.stream+' · '+stamp),el('pre',p.text));
     }else if(kind==='file'){
      card.append(el('h3',p.name),el('p',(p.reference?'External · '+(p.role||'artifact'):'Stored snapshot')+' · '+(p.size==null?'Size not recorded':fileSize(p.size))+' · '+stamp,'run-detail-note'));
      if(p.reference){
       card.append(el('code',p.reference.uri));
       if(p.reference.version)card.append(el('p','Storage version: '+p.reference.version,'run-detail-note'));
       if(p.collection_size)card.append(el('p',p.collection_size+' files declared in this directory capture','run-detail-note'));
       const actions=el('div',undefined,'capture-file-actions'),copied=el('span');
       actions.append(button('Copy location',async()=>{try{await navigator.clipboard.writeText(p.reference.uri);copied.textContent='Copied';}catch{copied.textContent='Select and copy the location above.';}}),copied);
       if(/^https?:\/\//.test(p.reference.uri)){const open=el('a','Open storage');open.href=p.reference.uri;open.target='_blank';open.rel='noopener noreferrer';actions.append(open);}
       if(p.step!=null&&p.trainer_session&&p.clock&&window.ExperimentDetails){const chart=el('a','Training step '+p.step);chart.href='/?'+new URLSearchParams({view:'health',experiment,signals_clock:p.clock,signals_session:JSON.stringify([row.producer,p.trainer_session]),signals_from:p.step,signals_to:p.step});actions.append(chart);}
       card.append(actions);const code=el('details');code.append(el('summary','Retrieve with Python'),el('pre','from rilldex import Workspace\nws = Workspace("study.sqlite", experiment='+JSON.stringify(experiment)+')\nws.download_file('+row.sequence+', '+JSON.stringify(p.name.split('/').at(-1))+')'),el('p','Uses storage credentials on your Python host and checks recorded size and SHA-256.','run-detail-note'));card.append(code);
       const meta=el('details');meta.append(el('summary','File identity'),fields({size_bytes:p.size??'Not recorded',sha256:p.sha256||'Not recorded',reference:p.reference,sequence:row.sequence}));card.append(meta);result.append(card);continue;
      }
      const url='/api/run-file?'+new URLSearchParams({experiment,sequence:row.sequence}),download=el('a','Download');download.href=url;download.download=p.name;
      const preview=el('pre');preview.hidden=true;card.append(download,button('Preview text',async()=>{try{const r=await fetch(url);if(!r.ok)throw Error('File unavailable');const bytes=await r.arrayBuffer();const text=new TextDecoder('utf-8',{fatal:true}).decode(bytes.slice(0,65536));if(text.includes('\u0000'))throw Error('Binary file; use Download');preview.textContent=text+(bytes.byteLength>65536?'\n… preview limited to 64 KiB':'');}catch(e){preview.textContent=e.message;}preview.hidden=false;}),preview);
      const meta=el('details');meta.append(el('summary','Checksum'),el('code',p.sha256));card.append(meta);
     }else if(kind==='manifest'){
      card.append(el('h3',p.name+' · '+stamp),el('h4','Configuration'),fields(p.config||{}));const runtime=el('details');runtime.append(el('summary','Python, packages, Git & machine'),fields(p.runtime||{}));card.append(runtime);
      const others=data.rows.filter(r=>r.sequence!==row.sequence);
      if(others.length){
       const compare=el('details'),label=el('label','Compare with snapshot'),select=el('select'),changes=el('div');select.setAttribute('aria-label','Compare configuration snapshot');
       select.append(new Option('Choose a snapshot…',''));for(const other of others)select.append(new Option(other.producer+' · '+formatTime(other.observed_at)+' · #'+other.sequence,String(other.sequence)));
       compare.append(el('summary','Compare configuration'),el('p','Compare recorded fields on this page. Unrecorded fields are not inferred.','run-detail-note'));label.append(select);compare.append(label,changes);card.append(compare);
       select.onchange=()=>{changes.replaceChildren();const prior=others.find(r=>String(r.sequence)===select.value);if(!prior)return;const diff=configChanges(prior.record.payload.config||{},p.config||{});
        changes.append(el('p',diff.length?diff.length+' differing fields':'No recorded configuration differences.'));
        const table=el('table',undefined,'capture-config-diff'),head=el('tr');for(const title of ['Field','Selected snapshot','This snapshot'])head.append(el('th',title));table.append(head);
        for(const change of diff.slice(0,200)){const tr=el('tr');tr.append(el('td',change.path.join(' / ')||'Configuration'),el('td',change.beforePresent?canonical(change.before):'Not recorded'),el('td',change.afterPresent?canonical(change.after):'Not recorded'));table.append(tr);}if(diff.length)changes.append(table);if(diff.length>200)changes.append(el('p','First 200 differences shown; full snapshots are above.'));
       };
      }
     }else card.append(el('h3',p.state+' · '+stamp),fields(p));
     result.append(card);
    }
    const prev=button('Previous',()=>{cursor=pages.pop()||0;load();}),next=button('Next',()=>{pages.push(cursor);cursor=data.next_cursor;load();});prev.disabled=!pages.length;next.disabled=!data.more||tail;
    pager.append(button('From beginning',()=>{follow=false;followButton.textContent='Follow';followButton.setAttribute('aria-pressed','false');reset();}),prev,next,button('Latest',()=>load(true)));
   }catch(e){if(!disposed&&ticket===serial)status.textContent=e.message;}
   if(!disposed&&follow)timer=setTimeout(()=>load(true),3000);
  }
  load(['hardware','manifest','file'].includes(kind));return ()=>{disposed=true;serial++;clearTimeout(timer);};
 }
 window.RunCapture={mount};
})();
