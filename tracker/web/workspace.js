'use strict';
// A clipped shell keeps the scrollbar between the header and footer, away from rounded corners.
window.WorkspaceDialog={prepare(dialog){
 if(dialog.classList.contains('dialog-frame'))return;
 const layout=dialog.querySelector(':scope > form')||dialog,head=layout.querySelector(':scope > .dialog-head');
 if(!head)return;
 const foot=layout.querySelector(':scope > .dialog-foot'),body=document.createElement('div');body.className='dialog-body';
 for(const child of [...layout.childNodes])if(child!==head&&child!==foot)body.append(child);
 head.after(body);dialog.classList.add('dialog-frame');
 const close=head.querySelector('button');if(close){
  close.setAttribute('aria-label',close.getAttribute('aria-label')||'Close dialog');close.title='Close';close.classList.add('dialog-close');
  close.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';
 }
}};
for(const dialog of document.querySelectorAll('#monitor-dialog,#cases-dialog'))window.WorkspaceDialog.prepare(dialog);
(()=>{
 // Locally bundled syntax rendering is optional; raw, copyable code remains usable if it fails.
 const syntax=document.createElement('script');syntax.src='/code-syntax.js';syntax.onload=()=>{
  const formatted=new WeakMap();let frame=0;
  function renderCode(){
   for(const pre of document.querySelectorAll('pre.code')){
    const source=pre.textContent,previous=formatted.get(pre);
    if(previous?.source===source&&previous.code===pre.firstElementChild)continue;
    formatted.set(pre,{source,code:null});
    const language=pre.dataset.language||(/^\s*(?:from \w[\w.]* import |import \w)/m.test(source)?'python':/^\s*(?:python(?:3)?\s+-m |rilldex\s|pip\s|docker\s|curl\s|export\s)/m.test(source)?'bash':null);
    const grammar=window.Prism?.languages[language];if(!grammar)continue;
    const code=document.createElement('code');code.className='language-'+language;
    code.innerHTML=window.Prism.highlight(source,grammar,language);
    // Never change runnable content, including whitespace, quotes and shell operators.
    if(code.textContent===source){formatted.set(pre,{source,code});pre.replaceChildren(code);}
   }
  }
  new MutationObserver(()=>{if(!frame)frame=requestAnimationFrame(()=>{frame=0;renderCode();});}).observe(document.querySelector('main')||document.body,{childList:true,characterData:true,subtree:true});renderCode();
 };document.head.append(syntax);
 const retired={'/legacy/semantic-map':'/semantic-map','/legacy/rollouts':'/'};
 if(retired[location.pathname]){
  const query=new URLSearchParams(location.search),hash=new URLSearchParams(location.hash.slice(1));for(const [key,value]of hash)if(!query.has(key))query.set(key,value);
  const target=retired[location.pathname]+(query.size?'?'+query:'');const link=document.querySelector('#continue');if(link)link.href=target;location.replace(target);return;
 }
 window.WorkspaceNavigation?.install();
 const nav=document.createElement('nav');nav.className='workspace-nav';nav.setAttribute('aria-label','Research workspace');
 const brandRow=document.createElement('div');brandRow.className='nav-brand';
 const brand=document.createElement('a');brand.className='logo';brand.href='/';brand.setAttribute('aria-label','Rilldex overview');
 const mark=document.createElement('img');mark.className='logo-mark';mark.src='/rilldex-mark.svg';mark.alt='';mark.width=32;mark.height=32;brand.append(mark,document.createTextNode('Rilldex'));brandRow.append(brand);
 const toggle=document.createElement('button');toggle.className='nav-toggle';toggle.textContent='Menu';toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-controls','workspace-navigation');brandRow.append(toggle);nav.append(brandRow);
 const content=document.createElement('div');content.className='nav-content';content.id='workspace-navigation';
 const caption=document.createElement('span');caption.className='nav-caption';caption.textContent='WORKSPACE';content.append(caption);
 const links=document.createElement('div');links.className='nav-links';
 const icons=['M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z','M4 3h6v6H4z M14 15h6v6h-6z M4 15h6v6H4z M7 9v6 M7 12h10v3','M3 12h4l3-8 4 16 3-8h4','M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M12 8v5 M12 16h.01','M4 4h16v4H4z M4 10h16v4H4z M4 16h16v4H4z','M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6','M8 3v5 M16 3v5 M5 8h14v3a7 7 0 0 1-14 0z M12 18v4'];
 for(const [index,[label,href]]of [['Overview','/'],['Behavior map','/semantic-map'],['Monitors','/monitors'],['Reward hacking','/monitors?view=reward'],['Rollouts','/runs'],['Investigations','/investigate'],['Data & workflows','/connections']].entries()){
  const item=document.createElement('a');item.className='nav-link';item.href=href;item.title=label;
  const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('fill','none');icon.setAttribute('stroke','currentColor');icon.setAttribute('stroke-linecap','round');icon.setAttribute('stroke-linejoin','round');icon.setAttribute('aria-hidden','true');const path=document.createElementNS(icon.namespaceURI,'path');path.setAttribute('d',icons[index]);icon.append(path);item.append(icon,document.createTextNode(label));
  if(location.pathname===href||(href==='/'&&['/dashboard','/rollouts'].includes(location.pathname))||(href==='/runs'&&location.pathname==='/source')||(href==='/connections'&&location.pathname==='/integration-guide'))item.setAttribute('aria-current','page');links.append(item);
 }
 content.append(links);
 if(location.pathname==='/monitors'&&new URLSearchParams(location.search).get('view')==='reward'){links.querySelector('[aria-current]')?.removeAttribute('aria-current');links.querySelector('[href="/monitors?view=reward"]').setAttribute('aria-current','page');}
 const workspaceLabel=document.createElement('div');workspaceLabel.className='nav-workspace';workspaceLabel.append(document.createTextNode('RL behavior inspector'));const local=document.createElement('span');local.textContent='Local workspace';workspaceLabel.append(local);brandRow.after(workspaceLabel);
 // Research tools belong to their workflow, not a second set of competing pages.
 const help=document.createElement('a');help.className='nav-help';help.href='/integration-guide';help.textContent='Integration guide';content.append(help);nav.append(content);
 toggle.onclick=()=>{const open=nav.classList.toggle('nav-open');toggle.setAttribute('aria-expanded',String(open));toggle.textContent=open?'Close menu':'Menu';};
 nav.addEventListener('keydown',event=>{if(event.key==='Escape'){nav.classList.remove('nav-open');toggle.setAttribute('aria-expanded','false');toggle.textContent='Menu';toggle.focus();}});
 const foot=document.createElement('div');foot.className='nav-foot';foot.textContent='Connecting to workspace…';nav.append(foot);document.body.prepend(nav);
 const main=document.querySelector('main');if(main){main.id=main.id||'workspace-main';const skip=document.createElement('a');skip.className='skip-link';skip.href='#'+main.id;skip.textContent='Skip to content';document.body.prepend(skip);}
 // Navigation is a local launcher, with no extra server or model requests.
 const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const launcher=node('dialog',undefined,'workspace-launcher');launcher.setAttribute('aria-label','Search workspace');
 const launchHead=node('div',undefined,'launcher-head'),search=node('input');search.type='search';search.placeholder='Find a page or recently viewed rollout…';search.setAttribute('aria-label','Search pages and recent rollouts');
 const close=node('button','Esc');close.type='button';close.setAttribute('aria-label','Close workspace search');close.onclick=()=>launcher.close();launchHead.append(search,close);
 const results=node('div',undefined,'launcher-results');launcher.append(launchHead,results,node('p','↑ ↓ to choose · Enter to open · Esc to close','launcher-help'));document.body.append(launcher);
 const actions=[['Overview','Monitor behavior across rollouts','/'],['Behavior map','Inspect activity units, relationships and work paths','/semantic-map'],['Monitors','Configure measures and evidence requirements','/monitors'],['Rollouts','Search and inspect recorded trajectories','/runs'],['Investigations','Compare a focus set with a reference','/investigate'],['Connections','Import files or connect a running job','/connections'],['Integration guide','Capture from your training code','/integration-guide']];
 actions.push(['Reward hacking','Findings, scan budgets, common checks and custom detectors','/monitors?view=reward']);
 function recent(){try{return JSON.parse(localStorage.getItem('jev-recent-rollouts')||'[]').filter(r=>typeof r.url==='string'&&r.url.startsWith('/semantic-map?')).slice(0,8);}catch{return [];}}
 let selectedLaunch=0;
 function highlight(){[...results.querySelectorAll('a')].forEach((a,i)=>a.classList.toggle('launcher-selected',i===selectedLaunch));}
 function launchRank(row,term){const title=row[0].toLowerCase();return !term?0:title===term?0:title.startsWith(term)?1:title.includes(term)?2:3;}
 function launchResults(){const term=search.value.trim().toLowerCase();results.replaceChildren();const rows=[...actions,...recent().map(r=>[r.title,'Recently inspected rollout',r.url])].filter(r=>(r[0]+' '+r[1]).toLowerCase().includes(term)).sort((a,b)=>launchRank(a,term)-launchRank(b,term));selectedLaunch=0;
  for(const [label,hint,url]of rows){const a=node('a');a.href=url;const text=node('div');text.append(node('strong',label),node('small',hint));a.append(text,node('span','↗'));results.append(a);}if(!rows.length)results.append(node('p','No matching pages or recent rollouts.','launcher-empty'));highlight();}
 const launchButton=node('button',undefined,'workspace-search');launchButton.type='button';launchButton.setAttribute('aria-label','Search workspace');launchButton.append(node('span','Search workspace'),node('kbd','Ctrl K'));
 launchButton.onclick=()=>{search.value='';launchResults();launcher.showModal();search.focus();};search.oninput=launchResults;
 search.onkeydown=e=>{const rows=[...results.querySelectorAll('a')];if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();selectedLaunch=Math.max(0,Math.min(rows.length-1,selectedLaunch+(e.key==='ArrowDown'?1:-1)));highlight();rows[selectedLaunch]?.scrollIntoView({block:'nearest'});}if(e.key==='Enter'&&rows[selectedLaunch]){e.preventDefault();rows[selectedLaunch].click();}};
 document.querySelector('.workspace-bar .bar-actions')?.prepend(launchButton);if(!launchButton.isConnected)document.querySelector('.workspace-bar')?.append(launchButton);
 const alerts=document.createElement('script');alerts.src='/workspace-alerts.js';document.head.append(alerts);
 document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();launcher.open?launcher.close():launchButton.click();}if(e.key==='/'&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&!e.target.closest('input,textarea,select,[contenteditable=true]')){const field=document.querySelector('#monitor-search:not([hidden]),#run-search,#map-search');if(field?.getClientRects().length){e.preventDefault();field.focus();}}});
 window.addEventListener('jev:recent-rollout',event=>{const r=event.detail;if(!r.url?.startsWith('/semantic-map?'))return;try{localStorage.setItem('jev-recent-rollouts',JSON.stringify([{title:r.title,url:r.url},...recent().filter(v=>v.url!==r.url)].slice(0,8)));}catch{}});
 window.addEventListener('jev:scope',event=>{const scope=event.detail;for(const a of links.querySelectorAll('a')){const url=new URL(a.href);if(!['/','/monitors','/runs'].includes(url.pathname))continue;for(const key of ['experiment','environment'])scope[key]?url.searchParams.set(key,scope[key]):url.searchParams.delete(key);a.href=url.pathname+url.search;}});
 let fingerprint=null;
 const stream=new EventSource('/api/live/events');
 stream.addEventListener('state',event=>{
  const s=JSON.parse(event.data);window.trackerLive=s;window.trackerStreamConnected=true;
  const next=JSON.stringify([s.source_revision,s.analysis?.revision]),changed=fingerprint&&fingerprint!==next;fingerprint=next;
  foot.textContent=s.error?'Connection needs attention':'Connected · '+(s.connections||[]).filter(c=>c.running).length+' directories watching';
  foot.dataset.state=s.error?'disconnected':'connected';const captureState=document.querySelector('#stream-state');if(captureState)captureState.textContent=s.error?'Connection needs attention':'Connected · updates pushed by server';
  const live=document.querySelector('#live-state');if(live)live.textContent=document.body.dataset.workspacePending==='true'?'New data · refresh view':s.analysis?.updating?'Source received · updating monitors':'Connected · server updates';
  window.dispatchEvent(new CustomEvent('tracker-live',{detail:s}));
  if(changed&&document.querySelector('#live-updates')?.checked)window.dispatchEvent(new Event('workspace-update'));
 });
 stream.onerror=()=>{window.trackerStreamConnected=false;foot.dataset.state='disconnected';foot.textContent='Disconnected · reconnecting';const captureState=document.querySelector('#stream-state');if(captureState)captureState.textContent='Disconnected · reconnecting';const live=document.querySelector('#live-state');if(live)live.textContent='Disconnected · reconnecting';window.dispatchEvent(new Event('tracker-disconnected'));};
 window.addEventListener('pagehide',()=>stream.close(),{once:true});
 window.addEventListener('pageshow',e=>{if(e.persisted)location.reload();});
 // Retain table semantics while exposing every field and action in narrow panes.
 function labelTables(){
  // The native selectedcontent element clips only the label, keeping the arrow visible.
  // Reapply after async option lists are replaced; never replace the select or its value.
  if(CSS.supports('appearance','base-select')&&matchMedia('(pointer:fine)').matches){
   for(const select of document.querySelectorAll('select:not([multiple]):not([size])')){
    if(select.firstElementChild?.tagName==='BUTTON')continue;
    const trigger=document.createElement('button');trigger.type='button';trigger.className='select-label';
    trigger.append(document.createElement('selectedcontent'));select.prepend(trigger);
   }
  }
  for(const table of document.querySelectorAll('.registry table, #investigation-comparison .iv-table-wrap table')){
  table.parentElement.classList.add('record-table');
  const headers=[...table.querySelectorAll('th')].map(h=>h.textContent.trim());
  for(const row of table.querySelectorAll('tr'))for(const [i,cell]of [...row.children].entries())if(cell.tagName==='TD')cell.dataset.column=headers[i]||'Actions';
 }}
 let tableFrame=0;new MutationObserver(()=>{if(!tableFrame)tableFrame=requestAnimationFrame(()=>{tableFrame=0;labelTables();});}).observe(document.querySelector('main')||document.body,{childList:true,subtree:true});
 for(const dialog of document.querySelectorAll('dialog'))new MutationObserver(labelTables).observe(dialog,{childList:true,subtree:true});labelTables();
})();

'use strict';
window.ToolContractEvidence={render(check){
 const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 const box=el('details');box.className='tool-contract-evidence';
 box.append(el('summary',`${check.counts.invalid} parameter-schema violations · ${check.counts.unavailable} unavailable checks`),el('p',check.protocol.limits));
 for(const call of check.calls){
  const item=el('details');item.append(el('summary',`${call.event_id} · ${call.tool} · ${call.status}`),el('p',call.source_pointer),el('p',call.reason||`Schema: ${call.contract_pointer}`));
  for(const issue of call.issues)item.append(el('p',`${issue.description} · argument ${issue.argument_pointer||'/'} · schema ${issue.schema_pointer||'/'}`));
  box.append(item);
 }
 box.append(el('small',`${check.protocol.id} · ${check.protocol.engine} ${check.protocol.engine_version}`));return box;
}};
