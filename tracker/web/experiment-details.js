/* Recorded run context, shared by experiment entry and native point inspection. */
(()=>{
 'use strict';
 function fields(value,path=[]){
  if(value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length)
   return Object.entries(value).flatMap(([key,item])=>fields(item,[...path,key]));
  return [[path.join(' / ')||'Settings',typeof value==='string'?value:JSON.stringify(value)]];
 }
 function executionURL(experiment,item){
  const q=new URLSearchParams({view:'execution',experiment,execution_focus:JSON.stringify([item.producer,item.id])});
  if(item.record.timing?.clock)q.set('execution_clock',item.record.timing.clock);
  return '/?'+q;
 }
 function trainerURL(experiment,item,environment){
  return '/?'+new URLSearchParams({view:'health',experiment,signals_clock:item.clock,
   signals_session:JSON.stringify([item.producer,item.session]),...(environment?{environment}:{})});
 }
 if(typeof module!=='undefined'){module.exports={fields,executionURL,trainerURL};return;}
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const button=(text,action)=>{const b=el('button',text);b.type='button';b.onclick=action;return b;};
 const link=(text,href)=>{const a=el('a',text);a.href=href;return a;};
 function grid(value){const list=el('dl',undefined,'run-detail-fields');for(const [key,text]of fields(value)){list.append(el('dt',key),el('dd',text));}return list;}
 function execution(item,experiment,compact=false){
  const r=item.record,card=el(compact?'details':'article',undefined,'run-detail-record'),head=el(compact?'summary':'div',undefined,'run-detail-record-head');
  head.append(el('strong',r.kind.replaceAll('_',' ')+' · '+r.state),el('span',r.context?.worker||item.producer));card.append(head);
  const coordinates=(item.trainer_logs||[]).map(log=>log.clock+' '+log.step+' · '+log.session+' · '+log.split);
  if(compact){
   const preview=el('span',coordinates.length?coordinates.join(' | '):r.timing?r.timing.clock+' · '+r.timing.start:'Received '+new Date(item.received_at).toLocaleString(),'run-detail-coordinate');head.append(preview);
   const settings=fields(r.configuration||{});head.append(el('span',settings.slice(0,4).map(([k,v])=>k+': '+v).join(' · ')+(settings.length>4?' · +'+(settings.length-4)+' fields':''),'run-detail-preview'));
  }else for(const coordinate of coordinates)card.append(el('p',coordinate,'run-detail-note'));
  if(r.reason)card.append(el('p',r.reason));
  if(r.timing)card.append(el('p',r.timing.clock+' · '+r.timing.start+(r.timing.end!=null?'–'+r.timing.end:' · unfinished'),'run-detail-note'));
  if(r.configuration)card.append(grid(r.configuration));
  if(item.declared_logs)card.append(el('p',item.matched_logs+' / '+item.declared_logs+' trainer logs received'+(item.matched_logs>coordinates.length?' · '+coordinates.length+' coordinates shown':''),'run-detail-note'));
  if(r.timing)card.append(link('Open execution',executionURL(experiment,item)));
  const raw=el('details');raw.append(el('summary','Record & capture evidence'),el('pre',JSON.stringify(item,null,2)));card.append(raw);return card;
 }
 function pointContext(value,experiment){
  const host=el('section',undefined,'run-point-context');host.append(el('h3','Execution & settings'));
  if(!value?.total){host.append(el('p','No execution record explicitly references this log.'));return host;}
  host.append(el('p','Current saved execution revisions linked by exact log IDs. Settings apply to these operations.','run-detail-note'));
  for(const item of value.records)host.append(execution(item,experiment));
  if(value.truncated)host.append(el('p','Showing '+value.records.length+' of '+value.total+' linked operations.'));
  return host;
 }
 function open(experiment,environment,displayName,options={}){
  if(!displayName){try{displayName=decodeURIComponent(experiment);}catch{displayName=experiment;}}
  const dialog=el('dialog',undefined,'run-details-dialog');dialog.setAttribute('aria-label','Run details');
  const previousFocus=document.activeElement,head=el('header',undefined,'run-detail-head'),title=el('div');title.append(el('h2','Run details'),el('p',displayName));title.title=experiment;
  head.append(title,button('Close',()=>dialog.close()));dialog.append(head);
  const content=el('div',undefined,'run-detail-content'),tabs=el('div',undefined,'run-detail-tabs');tabs.setAttribute('role','group');tabs.setAttribute('aria-label','Run detail sections');
  const form=el('form',undefined,'run-detail-search'),search=el('input'),submit=button('Search');submit.type='submit';search.type='search';search.placeholder='Search recorded settings…';search.setAttribute('aria-label','Search run details');form.append(search,submit);
  const status=el('p',undefined,'run-detail-note'),result=el('div'),pager=el('div',undefined,'run-detail-pager');status.setAttribute('role','status');
  content.append(tabs,form,status,result,pager);dialog.append(content);
  const names={manifest:'Config & runtime',console:'Logs',hardware:'Hardware',file:'Files',settings:'Settings',trainers:'Trainer streams',history:'Run history',lifecycle:'Sessions'},tabButtons={};let section=options.section||'settings',offset=0,query='',serial=0,disposeCapture=null,captureSelection=options.capture||null;
  for(const key of Object.keys(names)){const b=button(names[key],()=>{section=key;offset=0;query='';search.value='';search.placeholder='Search '+names[key].toLowerCase()+'…';load();});tabButtons[key]=b;tabs.append(b);}
  async function load(){
   disposeCapture?.();disposeCapture=null;
   const ticket=++serial;status.textContent='Loading…';result.replaceChildren();pager.replaceChildren();
   for(const [key,b]of Object.entries(tabButtons))b.setAttribute('aria-pressed',String(key===section));
   const captured=['manifest','console','hardware','file','lifecycle'].includes(section);form.hidden=captured;status.hidden=captured;
   if(captured){disposeCapture=RunCapture.mount(result,experiment,section,{displayName,selection:captureSelection,timeRange:options.timeRange,asOf:options.asOf,onSelection:value=>{captureSelection=value;}});return;}
   try{
    const q=new URLSearchParams({experiment,section,q:query,offset,...(environment?{environment}:{})});
    const r=await fetch('/api/experiment-details?'+q),data=await r.json();if(ticket!==serial||!dialog.isConnected)return;if(!r.ok)throw Error(data.error||'Run details unavailable');
    for(const [key,b]of Object.entries(tabButtons))if(data.counts[key]!=null)b.textContent=names[key]+' · '+data.counts[key];
    status.textContent=section==='settings'?'Settings recorded on individual operations; no complete effective configuration is inferred.':section==='trainers'?'Each producer, session, clock and logged population is shown separately.':'Researcher-recorded events on their original clocks.';
    if(environment)status.append(' Environment: '+environment+'. Shared settings and history remain included.');
    for(const item of data.rows){
     if(section==='settings'){const itemView=execution(item,experiment,true);itemView.open=result.childElementCount===0;result.append(itemView);continue;}
     const card=el('article',undefined,'run-detail-record');
     if(section==='trainers'){
      card.append(el('h3',item.framework+' · '+item.objective),grid({'Framework version':item.framework_version,'Producer':item.producer,'Session':item.session,'Clock':item.clock,'Recorded steps':item.first_step+'–'+item.last_step,'Logs':item.logs,'Split':item.split,'Population':item.population,'Environment':item.environment||'Not specified'}));
      card.append(link('Open training curves',trainerURL(experiment,item,environment)),button('Session details',()=>{dialog.close();openTrainer(experiment,item.producer,item.session);}));
     }else{
      card.append(el('h3',item.title+(item.superseded?' · superseded':'')),el('p',item.kind.replaceAll('_',' ')+' · '+item.clock+' / '+item.basis+' '+item.step,'run-detail-note'),el('p',item.detail));
      if(item.investigation_id)card.append(link('Open investigation','/investigate?saved='+encodeURIComponent(item.investigation_id)));
      const raw=el('details');raw.append(el('summary','Event record'),el('pre',JSON.stringify(item,null,2)));card.append(raw);
     }result.append(card);
    }
    if(!data.rows.length){
     result.append(el('p',query?'No records match this search.':section==='settings'?'No settings captured. Attach configuration to ExecutionRecorder spans to show it here.':section==='trainers'?'No native trainer logs in this scope.':'No run events recorded. Add events from an interval investigation or Workspace.annotate_history().'));
     if(!query&&section==='settings')result.append(link('Capture execution settings','/connections#execution-section'));
    }
    const prev=button('Previous',()=>{offset=Math.max(0,offset-data.limit);load();}),next=button('Next',()=>{offset+=data.limit;load();});prev.disabled=offset===0;next.disabled=offset+data.rows.length>=data.total;
    pager.append(prev,el('span',data.total?(offset+1)+'–'+(offset+data.rows.length)+' of '+data.total:'0 records'),next,button('Refresh',()=>load()));
   }catch(e){if(ticket===serial)status.textContent=e.message;}
  }
  form.onsubmit=e=>{e.preventDefault();query=search.value;offset=0;load();};
  dialog.onclose=()=>{serial++;disposeCapture?.();dialog.remove();previousFocus?.focus({preventScroll:true});};document.body.append(dialog);dialog.showModal();
  if(options.section||options.capture){section=options.section||'manifest';load();}
  else fetch('/api/run-records?'+new URLSearchParams({experiment,kind:'manifest',limit:1})).then(r=>r.json()).then(data=>{if(serial||!dialog.isConnected)return;section=data.counts?.manifest?'manifest':'settings';load();}).catch(()=>{if(!serial&&dialog.isConnected)load();});
 }
 function openTrainer(experiment,producer,session,section='manifest'){
  const d=el('dialog',undefined,'run-details-dialog');d.setAttribute('aria-label','Trainer session context');
  const head=el('header',undefined,'run-detail-head');head.append(el('h2','Session details'),button('Close',()=>d.close()));
  const content=el('div',undefined,'run-detail-content'),status=el('p','Finding recorded capture…');content.append(status);d.append(head,content);
  const previous=document.activeElement;d.onclose=()=>{d.remove();previous?.focus({preventScroll:true});};document.body.append(d);d.showModal();
  fetch('/api/trainer-telemetry/context?'+new URLSearchParams({experiment,producer,session})).then(async r=>{const value=await r.json();if(!r.ok)throw Error(value.error||'Session context unavailable');return value;}).then(value=>{
   if(!d.isConnected)return;
   const use=capture=>{d.close();open(experiment,null,null,{section,capture});};
   if(value.capture_sessions.length===1){use(value.capture_sessions[0]);return;}
   status.textContent=value.capture_sessions.length?'Choose a recorded process capture for this trainer session.':'No process capture is linked to this trainer session.';
   if(!value.capture_sessions.length)content.append(el('p','Use Run to capture console, configuration and hardware alongside trainer metrics.'),link('Capture a training run','/connections#setup-section'));
   for(const [i,capture]of value.capture_sessions.entries()){const row=el('article',undefined,'run-detail-record');row.append(el('strong',capture.producer+' · capture '+(i+1)),el('p',Object.entries(capture.counts).map(([k,v])=>v+' '+k).join(' · ')),button('Open capture',()=>use(capture)));content.append(row);}
  }).catch(e=>{if(d.isConnected)status.textContent=e.message;});
 }
 window.ExperimentDetails={open,openTrainer,pointContext};
 const scopeButton=document.getElementById('run-details-open');
 if(scopeButton)window.addEventListener('jev:scope',e=>{scopeButton.hidden=!e.detail.experiment;scopeButton.onclick=()=>open(e.detail.experiment,e.detail.environment);});
})();
