/* Workspace hierarchy: navigation → active scope → view → evidence → editing. */
(function(root){
 'use strict';
 const routes=new Set(['/','/dashboard','/rollouts','/runs','/semantic-map','/source','/monitors','/investigate','/connections','/integration-guide','/measurement-review','/relations','/detector-validation']);
 function viewPath(value,base='http://workspace.local'){
  try{if(typeof value!=='string'||/[\\\r\n]/.test(value))return null;const u=new URL(value,base),b=new URL(base);if(u.origin!==b.origin||u.username||u.password||!routes.has(u.pathname))return null;u.searchParams.delete('return_to');u.searchParams.sort();return u.pathname+u.search+u.hash;}catch{return null;}
 }
 function cleanPins(rows){return Array.isArray(rows)?rows.filter(r=>r&&typeof r.label==='string'&&r.label.trim()&&viewPath(r.path)===r.path).filter((r,i,a)=>a.findIndex(v=>v.path===r.path)===i).slice(0,12).map(r=>({label:r.label.trim().slice(0,100),path:r.path})):[];}
 function togglePin(rows,item){const pins=cleanPins(rows),path=viewPath(item.path);if(!path||!item.label?.trim())return pins;return pins.some(r=>r.path===path)?pins.filter(r=>r.path!==path):[{path,label:item.label.trim().slice(0,100)},...pins].slice(0,12);}
 function researchGroup(id){return /(?:checks|follow-up)$/.test(id)?'checks':id==='ii-compare-rollout-cases'?'evidence':'summary';}
 function investigationPanel({hash='',panel=''}={}){
  const names=['focus','comparison','process','relationship','checks','notes'],id=hash.replace(/^#/,'');
  if(id.startsWith('check-')||id==='research-checks')return 'checks';
  const named=id.replace(/^investigation-/,'');return names.includes(named)?named:names.includes(panel)?panel:'comparison';
 }
 function researchView({hash='',panel='',caseSelection=false}={},sections=[]){
  const id=hash.replace(/^#/,''),named={'research-summary':'summary','research-evidence':'evidence','research-checks':'checks','research-all':'all'};
  if(named[id])return named[id];
  const section=sections.find(s=>s.id===id||s.containsTarget);if(section)return researchGroup(section.id);
  if(panel==='checks')return 'checks';if(caseSelection)return 'evidence';return 'summary';
 }
 const api={viewPath,cleanPins,togglePin,researchGroup,researchView,investigationPanel,pins:()=>[]};
 if(typeof module!=='undefined')module.exports=api;
 if(typeof document==='undefined')return;
 root.WorkspaceLayout=api;
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 const icon=(path)=>{const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.7');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',path);svg.append(p);return svg;};
 function install(){
  const nav=document.querySelector('.workspace-nav'),bar=document.querySelector('.workspace-bar');if(!nav||!bar)return;
  document.body.classList.add('workspace-organized');
  const content=nav.querySelector('.nav-content'),links=nav.querySelector('.nav-links');
  content.querySelector(':scope > .nav-caption')?.remove();
  const originals=[...links.children];links.replaceChildren();
  const extraIcons={signals:'M3 18h18 M5 14l4-5 4 3 6-8',behavior:'M4 18V9 M9 18V5 M14 18v-7 M19 18V3',execution:'M3 5h10v3H3z M8 11h13v3H8z M3 17h14v3H3z',samples:'M3 5h18v14H3z M3 10h18 M9 5v14',library:'M3 6h7l2 2h9v12H3z M3 6V4h7l2 2'};
  for(const section of root.WorkspaceNavigation.groups(location.pathname,location.search)){
   const group=el(section.fold?'details':'div',null,'nav-group'+(section.fold?' nav-disclosure':''));group.setAttribute('aria-label',section.label);
   if(section.fold)group.open=section.active;else group.setAttribute('role','group');
   const caption=el(section.fold?'summary':'span',section.label,'nav-caption');group.append(caption);
   const items=el('div',null,'nav-group-items');
   for(const item of section.items){const a=originals.find(a=>a.getAttribute('href')===item.href)||el('a',null,'nav-link');a.href=item.href;a.title=item.hint;a.dataset.navKey=item.id;a.removeAttribute('aria-current');
    if(!a.firstChild)a.append(icon(extraIcons[item.id]||'M3 5h18v14H3z'),el('span',item.label));
    else{const svg=a.querySelector('svg');a.replaceChildren(...(svg?[svg]:[]),el('span',item.label));}
    if(item.active)a.setAttribute('aria-current','page');items.append(a);
   }group.append(items);links.append(group);
  }
  document.body.classList.add('workflow-navigation');
  const search=bar.querySelector('.workspace-search');if(search)content.prepend(search);
  document.addEventListener('pointerdown',event=>{if(nav.classList.contains('nav-open')&&!nav.contains(event.target)){nav.classList.remove('nav-open');const t=nav.querySelector('.nav-toggle');t.setAttribute('aria-expanded','false');t.textContent='Menu';}});
  const heading=[...bar.children].find(n=>n!==bar.querySelector('.bar-actions')&&n.tagName==='DIV');
  const trail=el('div',null,'workspace-trail'),back=bar.querySelector('#workspace-back');if(back)trail.append(back);if(heading)trail.append(heading);bar.prepend(trail);
  const pageTitle=document.querySelector('main h1');if(pageTitle){const context=el('span',pageTitle.textContent,'workspace-current-context');trail.append(context);new MutationObserver(()=>{context.textContent=pageTitle.textContent;context.title=pageTitle.textContent;}).observe(pageTitle,{childList:true,characterData:true,subtree:true});new IntersectionObserver(rows=>bar.classList.toggle('past-page-heading',!rows[0].isIntersecting),{rootMargin:'-60px 0px 0px'}).observe(pageTitle);}
  let actions=bar.querySelector('.bar-actions');if(!actions){actions=el('div',null,'bar-actions');bar.append(actions);}
  const pin=el('button',null,'workspace-pin');pin.type='button';pin.disabled=true;pin.title='Loading workspace…';pin.append(icon('M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3l-5.6 2.9 1.1-6.2L3 9.6l6.2-.9z'),el('span','Pin view'));actions.prepend(pin);
  const pinned=el('div',null,'nav-pinned');pinned.hidden=true;content.insertBefore(pinned,links);
  const toast=el('div',null,'workspace-notice');toast.setAttribute('role','status');toast.setAttribute('aria-live','polite');document.body.append(toast);let toastTimer;
  const notify=text=>{toast.textContent=text;clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.textContent='',5000);};
  let key=null,pins=[];
  api.pins=()=>pins.map(r=>[r.label,'Pinned view',r.path]);
  const current=()=>viewPath(location.href,location.origin);
  function renderPins(){
   const here=current(),isPinned=pins.some(r=>r.path===here);pin.setAttribute('aria-pressed',String(isPinned));pin.setAttribute('aria-label',isPinned?'Unpin this view':'Pin this view');pin.querySelector('span').textContent=isPinned?'Pinned':'Pin view';pin.title=isPinned?'Remove this view from your sidebar':'Pin this view, including its selection and filters';
   pinned.replaceChildren();pinned.hidden=!pins.length;if(!pins.length)return;
   pinned.append(el('span','Pinned views','nav-caption'));
   for(const row of pins){const line=el('div',null,'nav-pin-row'),a=el('a',row.label);a.href=row.path;a.title=row.label;if(row.path===here)a.setAttribute('aria-current','page');const remove=el('button','×');remove.type='button';remove.setAttribute('aria-label','Unpin '+row.label);remove.onclick=()=>save(pins.filter(r=>r.path!==row.path));line.append(a,remove);pinned.append(line);}
  }
  function save(next){try{localStorage.setItem(key,JSON.stringify(next));pins=next;renderPins();return true;}catch{notify('Could not save this pin. Browser storage is unavailable.');return false;}}
  pin.onclick=()=>{if(!key)return;const path=current(),was=pins.some(r=>r.path===path);let label=document.querySelector('h1')?.textContent.trim()||document.title.replace(/^Rilldex · /,'');const selection=document.querySelector('#experiment');if(selection?.value)label+=' · '+selection.selectedOptions[0]?.textContent.trim();if(save(togglePin(pins,{path,label})))notify(was?'View removed from pinned views.':'View pinned with its current selection and filters.');};
  fetch('/api/workspace-identity').then(r=>{if(!r.ok)throw Error();return r.json();}).then(w=>{if(!w.identity)throw Error();key='rilldex:pinned-views:'+w.identity;try{pins=cleanPins(JSON.parse(localStorage.getItem(key)||'[]'));}catch{pins=[];}pin.disabled=false;renderPins();}).catch(()=>{pin.title='Pins are unavailable until the workspace is connected';});
  window.addEventListener('storage',e=>{if(e.key===key){try{pins=cleanPins(JSON.parse(e.newValue||'[]'));}catch{pins=[];}renderPins();}});
  for(const event of ['hashchange','popstate','jev:scope','rilldex:navigation'])window.addEventListener(event,renderPins);

  // Only analysis views belong above the canvas; run scope lives in the sidebar.
  const scope=document.querySelector('.dashboard-scope');
  if(scope){const dock=el('div',null,'workspace-context-dock');scope.before(dock);for(const id of ['overview-tabs','overview-subnav']){const n=document.getElementById(id);if(n)dock.append(n);}}
  const setSize=()=>{const nh=matchMedia('(max-width:1100px)').matches?Math.ceil(nav.getBoundingClientRect().height):0;document.body.style.setProperty('--workspace-nav-height',nh+'px');document.body.style.setProperty('--workspace-bar-height',Math.ceil(bar.getBoundingClientRect().height)+nh+'px');};const shellSize=new ResizeObserver(setSize);shellSize.observe(bar);shellSize.observe(nav);setSize();

  // Occasional document operations never compete with the main analysis action.
  function menu(host,items,label='More'){
   const nodes=items.map(s=>document.querySelector(s)).filter(Boolean);if(!host||!nodes.length)return;
   const d=el('details',null,'workspace-action-menu'),summary=el('summary',label),body=el('div',null,'workspace-action-list');summary.setAttribute('aria-label',label+' actions');d.append(summary,body);body.append(...nodes);host.append(d);
   d.addEventListener('keydown',e=>{if(e.key==='Escape'){d.open=false;summary.focus();}});
   document.addEventListener('pointerdown',e=>{if(d.open&&!d.contains(e.target))d.open=false;});
   body.addEventListener('click',e=>{if(e.target.closest('a,button'))d.open=false;});
  }
  menu(document.querySelector('.iv-heading > div:last-child'),['#read-findings-report','#export-investigation']);
  menu(document.querySelector('.map-heading > div:last-child'),['#export-graph']);
  const mapKey=document.querySelector('section.map-key'),connectionToolbar=document.querySelector('.connection-toolbar');
  if(mapKey&&connectionToolbar)mapKey.append(connectionToolbar);

  // Saved comparisons need an outline too; do not replace the metric investigation tabs.
  const host=document.getElementById('investigation-app');let outline,signature='',outlineFrame=0,observedSections=[],researchEntries=[],researchLinks=[],scopeLine;
  function applyResearchView(){
   if(!outline)return;const q=new URLSearchParams(location.search);let targetId=location.hash.slice(1);try{targetId=decodeURIComponent(targetId);}catch{}const target=document.getElementById(targetId),view=researchView({hash:location.hash,panel:q.get('panel'),caseSelection:q.has('case_reference')&&q.has('case_selected')},researchEntries.map(s=>({id:s.id,containsTarget:!!target&&s.contains(target)})));
   for(const s of researchEntries)s.classList.toggle('workspace-section-inactive',view!=='all'&&researchGroup(s.id)!==view);
   for(const a of researchLinks){if(a.dataset.view===view)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
   const scopes=[...host.querySelectorAll('.case-selection-columns > .case-scope')].slice(0,2);
   scopeLine.replaceChildren();for(const s of scopes){const item=el('span');item.append(el('small',s.querySelector('small')?.textContent||''),el('strong',s.querySelector('strong')?.textContent||''));scopeLine.append(item);}
   scopeLine.hidden=view==='summary'||view==='all'||!scopes.length;
   if(target&&researchEntries.some(s=>s===target||s.contains(target)))requestAnimationFrame(()=>target.scrollIntoView({block:'start'}));
  }
  function outlineSaved(){
   if(!host)return;
   const old=document.getElementById('investigation-jumps');
   if(!new URLSearchParams(location.search).has('saved')||!old?.hidden){outline?.remove();outline=null;researchEntries.forEach(s=>s.classList.remove('workspace-section-inactive'));signature='';return;}
   const sections=[...host.querySelectorAll(':scope > section,:scope > .ii-grid > section')];
   const stamp=sections.map(n=>n.id+'|'+n.querySelector('h2')?.textContent).join(';');if(stamp===signature&&outline?.isConnected&&sections.every((n,i)=>n===observedSections[i]))return;signature=stamp;observedSections=sections;outline?.remove();
   if(sections.length<2)return;
   outline=el('div',null,'workspace-research-dock');outline.id='research-outline';host.before(outline);
   const tabs=el('nav',null,'workspace-outline');tabs.setAttribute('aria-label','Saved investigation views');outline.append(tabs);scopeLine=el('div',null,'workspace-selection-context');outline.append(scopeLine);
   researchEntries=sections;researchLinks=[];sections.forEach((s,i)=>{if(!s.id)s.id='research-section-'+i;s.classList.add('workspace-research-section');});
   for(const [id,label]of [['summary','Summary'],['evidence','Rollout evidence'],['checks','Checks & trials'],['all','All sections']]){
    if(id!=='all'&&!sections.some(s=>researchGroup(s.id)===id))continue;const a=el('a',label);a.href='#research-'+id;a.dataset.view=id;tabs.append(a);researchLinks.push(a);
   }
   tabs.addEventListener('click',e=>{const a=e.target.closest('a');if(!a||e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;e.preventDefault();history.pushState(history.state,'',a.hash);applyResearchView();outline.scrollIntoView({block:'start'});window.dispatchEvent(new Event('rilldex:navigation'));});
   applyResearchView();
  }
  if(host){new MutationObserver(()=>{if(!outlineFrame)outlineFrame=requestAnimationFrame(()=>{outlineFrame=0;outlineSaved();});}).observe(host,{childList:true,subtree:true});outlineSaved();}
  for(const event of ['hashchange','popstate'])window.addEventListener(event,applyResearchView);
  // Form dialogs stay modal. Evidence stays beside the map, with a reachable close control.
  const inspector=document.getElementById('map-inspector');
  if(inspector){
   const close=document.getElementById('close-detail');let prior=null,open=false,heightFrame=0;
   const fitInspector=()=>{heightFrame=0;if(inspector.hidden||matchMedia('(max-width:1279px)').matches){inspector.style.removeProperty('--inspector-visible-height');return;}const top=Math.max(0,inspector.getBoundingClientRect().top);inspector.style.setProperty('--inspector-visible-height',Math.max(240,innerHeight-top-20)+'px');};
   const scheduleFit=()=>{if(!heightFrame)heightFrame=requestAnimationFrame(fitInspector);};
   window.addEventListener('scroll',scheduleFit,{passive:true});window.addEventListener('resize',scheduleFit);
   new MutationObserver(()=>{const next=!inspector.hidden;if(next&&!open){prior=document.activeElement;requestAnimationFrame(()=>{if(matchMedia('(max-width:1279px)').matches)close?.focus({preventScroll:true});});}if(!next&&open&&prior?.isConnected)prior.focus({preventScroll:true});open=next;scheduleFit();}).observe(inspector,{attributes:true,attributeFilter:['hidden']});
  }
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
})(typeof window==='undefined'?globalThis:window);

/* One run context for monitoring. Evidence URLs keep their own immutable scope. */
(function(root){
 'use strict';
 function resolve(search,remembered,options=[],recent=[]){
  const q=new URLSearchParams(search),environment=q.get('environment')||'';
  if(q.has('experiment')||q.get('scope')==='all')return {experiment:q.get('experiment')||'',environment};
  if(remembered&&typeof remembered.experiment==='string'&&(!remembered.experiment||options.some(o=>o.id===remembered.experiment)))return {experiment:remembered.experiment,environment:q.has('environment')?environment:typeof remembered.environment==='string'?remembered.environment:''};
  const candidates=recent.filter(r=>!r.archived&&options.some(o=>o.id===r.experiment)).sort((a,b)=>Number(b.logs>0)-Number(a.logs>0)||String(b.last_received||'').localeCompare(String(a.last_received||'')));
  return {experiment:candidates[0]?.experiment||options.find(o=>o.id!=='__unassigned__')?.id||'',environment};
 }
 function scopedHref(path,scope){
  const u=new URL(path,'http://workspace.local');
  for(const key of ['experiment','environment'])if(scope[key])u.searchParams.set(key,scope[key]);else u.searchParams.delete(key);
  if(scope.experiment)u.searchParams.delete('scope');else u.searchParams.set('scope','all');
  return u.pathname+u.search+u.hash;
 }
 function switchHref(path,search,scope){
  const q=new URLSearchParams(search),overview=['/','/dashboard'].includes(path),local=overview||['/runs','/monitors'].includes(path);
  // Comparison, evidence and interval parameters belong to the previous run.
  const keep=new URLSearchParams();if(local&&q.has('view')&&q.get('view')!=='experiments'){keep.set('view',q.get('view'));for(const k of ['health_panel','detail'])if(q.has(k))keep.set(k,q.get(k));}
  return scopedHref((local?path:'/')+(keep.size?'?'+keep:''),scope);
 }
 function graphsForScope(graphs,scope={},runId=''){
  if(runId){const exact=graphs.find(g=>g.run_id===runId);return exact?graphs.filter(g=>g.run_id===runId||(exact.metadata?.experiment&&g.metadata?.experiment===exact.metadata.experiment)):graphs;}
  return graphs.filter(g=>(!scope.experiment||(scope.experiment==='__unassigned__'?!g.metadata?.experiment:g.metadata?.experiment===scope.experiment))&&(!scope.environment||g.metadata?.environment===scope.environment));
 }
 const api={resolve,scopedHref,switchHref,graphsForScope};
 if(typeof module!=='undefined')module.exports.TrainingContext=api;
 if(typeof document==='undefined')return;
 root.TrainingContext=api;
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 let current={experiment:'',environment:''},key='',remembered=null,catalog=[],chooser,trigger,caption,subline,info,available=[],catalogError='',searchSequence=0,evidenceScope=null;
 const ready=Promise.all([
  fetch('/api/workspace-identity').then(r=>{if(!r.ok)throw Error();return r.json();}).then(w=>{if(!w.identity)return;key='rilldex:training-context:'+w.identity;try{remembered=JSON.parse(localStorage.getItem(key));}catch{}}).catch(()=>{}),
  fetch('/api/experiments?limit=100&state=active').then(r=>{if(!r.ok)throw Error();return r.json();}).then(d=>{catalog=d.rows||[];}).catch(()=>{catalogError='Run list unavailable. Retry or open Runs & projects.';})
 ]);
 api.initial=async(options,search)=>{await ready;available=options;current=resolve(search,remembered,options,catalog);display();return {...current};};
 api.current=()=>({...current});
 api.forNavigation=async()=>{await ready;if(!document.getElementById('experiment')&&!evidenceScope)current=resolve(location.search,remembered,catalog.map(r=>({id:r.experiment})),catalog);return {...current};};
 api.viewEvidence=scope=>{evidenceScope={experiment:scope.experiment??'__unassigned__',environment:scope.environment??(current.experiment===scope.experiment?current.environment:'')};current=evidenceScope;display();};
 function label(){return current.experiment==='__unassigned__'?'Unassigned rollouts':catalog.find(r=>r.experiment===current.experiment)?.title||available.find(r=>r.id===current.experiment)?.label||current.experiment||'All training runs';}
 function display(){
  if(!trigger)return;caption.textContent=label();trigger.title='Switch training run · '+label();trigger.closest('.training-context').classList.toggle('has-environment',!!current.environment);
  trigger.setAttribute('aria-label','Switch training run: '+label());
  const isolated=!['/','/dashboard','/runs','/monitors'].includes(location.pathname);
  subline.textContent=isolated?'Navigation context · evidence stays fixed':current.environment||'All environments';
  info.hidden=!current.experiment||current.experiment==='__unassigned__';info.onclick=()=>{if(root.ExperimentDetails)root.ExperimentDetails.open(current.experiment,current.environment,label());else location.assign(scopedHref('/?view=health',current));};
  for(const a of document.querySelectorAll('.workspace-nav .nav-group a')){
   const base=a.dataset.scopeBase||a.getAttribute('href');a.dataset.scopeBase=base;
   const u=new URL(base,location.origin);
   if((['/','/dashboard','/runs','/monitors','/semantic-map'].includes(u.pathname))&&u.searchParams.get('view')!=='experiments')a.href=scopedHref(base,current);
  }
 }
 api.accept=scope=>{current={experiment:scope.experiment||'',environment:scope.environment||''};if(key){try{localStorage.setItem(key,JSON.stringify(current));}catch{}}display();};
 api.open=()=>trigger?.click();
 function install(){
  const sidebar=document.querySelector('.nav-content'),bar=document.querySelector('.workspace-bar');if(!sidebar||!bar)return;
  const context=el('section',null,'training-context');context.setAttribute('aria-label','Training run context');
  const title=el('div',null,'training-context-title');title.append(el('span','Training run'));info=el('button','Details');info.type='button';info.hidden=true;title.append(info);
  trigger=el('button',null,'training-context-switch');trigger.type='button';trigger.setAttribute('aria-haspopup','dialog');trigger.setAttribute('aria-expanded','false');
  caption=el('strong','Loading run…');const arrow=el('span','⌄');arrow.setAttribute('aria-hidden','true');trigger.append(caption,arrow);subline=el('small','');context.append(title,trigger,subline);
  const anchor=el('div',null,'training-context-anchor');sidebar.prepend(anchor);anchor.append(context);
  const position=()=>{const compact=matchMedia('(max-width:1100px)').matches;if(compact){if(context.parentNode!==bar)bar.append(context);}else if(context.parentNode!==anchor)anchor.append(context);};position();window.addEventListener('resize',position);
  const original=document.querySelector('.dashboard-scope');
  if(original){original.hidden=true;const refresh=original.querySelector('#refresh');if(refresh)bar.querySelector('.bar-actions').append(refresh);}
  trigger.onclick=async()=>{
   if(chooser?.open)return;const prior=trigger;chooser=el('dialog',null,'training-run-dialog');chooser.setAttribute('aria-labelledby','training-run-title');
   const head=el('div',null,'dialog-head'),h=el('h2','Switch training run');h.id='training-run-title';const close=el('button','Close');close.type='button';close.onclick=()=>chooser.close();head.append(h,close);chooser.append(head);
   const search=el('input');search.type='search';search.placeholder='Search run names or tags';search.maxLength=200;search.setAttribute('aria-label','Search training runs');
   const list=el('div',null,'training-run-list'),status=el('p',null,'training-run-status');status.setAttribute('role','status');chooser.append(search,status,list);
   const choose=id=>{const env=document.querySelector('#training-environment')?.value||'';api.accept({experiment:id,environment:env});location.assign(switchHref(location.pathname,location.search,current));};
   function render(rows,unassigned=available.some(o=>o.id==='__unassigned__')){list.replaceChildren();const add=(id,title,note)=>{const b=el('button',null,'training-run-option');b.type='button';b.setAttribute('aria-pressed',String(id===current.experiment));b.append(el('strong',title),el('small',note));b.onclick=()=>choose(id);list.append(b);};
    if(!search.value.trim()){add('','All training runs','Combined rollout population · trainer curves remain per run');if(unassigned)add('__unassigned__','Unassigned rollouts','Source records without a training-run assignment');}
    for(const r of rows)add(r.experiment,r.title||r.experiment,[r.archived?'Archived':null,r.project,r.trainer_contexts?.map(c=>c.framework+' · '+c.objective).join(', '),r.logs+' trainer logs · '+r.rollouts+' rollouts'].filter(Boolean).join(' · '));
    if(!search.value.trim()&&current.experiment&&!(unassigned&&current.experiment==='__unassigned__')&&!rows.some(r=>r.experiment===current.experiment))add(current.experiment,label(),'Current selection');
   }
   let timer;const load=async()=>{const ticket=++searchSequence;status.textContent='Loading runs…';try{const r=await fetch('/api/experiments?'+new URLSearchParams({limit:100,state:'all',q:search.value.trim()}));if(!r.ok)throw Error();const d=await r.json();if(ticket!==searchSequence||!chooser.open)return;catalog=[...new Map([...catalog,...d.rows].map(r=>[r.experiment,r])).values()];render(d.rows,d.unassigned_rollouts);status.textContent=d.total>d.rows.length?`Showing ${d.rows.length} of ${d.total} runs · search to narrow the list`:d.total?'Last received does not imply training is running.':'No matching runs.';}catch{if(ticket===searchSequence)status.textContent='Could not load runs. Close and reopen to retry.';}};
   search.oninput=()=>{clearTimeout(timer);timer=setTimeout(load,180);};
   const filter=el('details',null,'training-environment-filter');filter.append(el('summary','Environment filter'+(current.environment?' · '+current.environment:'')));
   const envLabel=el('label','Environment'),env=el('select');env.id='training-environment';env.append(new Option('All environments',''));for(const o of document.querySelectorAll('#environment option'))if(o.value)env.append(new Option(o.textContent,o.value));if(current.environment&&![...env.options].some(o=>o.value===current.environment))env.append(new Option(current.environment,current.environment));env.value=current.environment;envLabel.append(env);filter.append(envLabel);const apply=el('button','Apply environment');apply.type='button';apply.onclick=()=>choose(current.experiment);filter.append(apply);chooser.append(filter);
   let environmentsLoaded=!!document.querySelector('#environment');const modal=chooser;
   filter.ontoggle=async()=>{if(!filter.open||environmentsLoaded)return;environmentsLoaded=true;const note=el('p','Loading environments…');filter.append(note);try{const r=await fetch('/api/monitoring');if(!r.ok)throw Error();const d=await r.json();if(!modal.open)return;const selected=env.value;for(const value of d.environments||[])if(![...env.options].some(o=>o.value===value))env.append(new Option(value,value));env.value=selected;note.remove();}catch{environmentsLoaded=false;note.textContent='Could not load other environments. Close and expand to retry.';}};
   const footer=el('div',null,'dialog-foot'),manage=el('a','Runs & projects →');manage.href='/?view=experiments';footer.append(manage);chooser.append(footer);
   chooser.onclose=()=>{++searchSequence;clearTimeout(timer);chooser.remove();trigger.setAttribute('aria-expanded','false');prior.focus();};document.body.append(chooser);root.WorkspaceDialog?.prepare(chooser);chooser.showModal();trigger.setAttribute('aria-expanded','true');search.focus();render(catalog.filter(r=>!r.archived));status.textContent=catalogError;load();
  };
  window.addEventListener('jev:scope',e=>{if(new URLSearchParams(location.search).get('view')!=='experiments')api.accept(e.detail);});
  ready.then(()=>{if(!document.getElementById('experiment')){available=catalog.map(r=>({id:r.experiment,label:r.title}));current=evidenceScope||resolve(location.search,remembered,available,catalog);}display();});
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
})(typeof window==='undefined'?globalThis:window);
