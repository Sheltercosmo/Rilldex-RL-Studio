'use strict';
const RewardScanProgress=(()=>{
 const labels={complete:'Complete',partial:'Partial',not_scanned:'Not scanned',failed:'Failed',waiting:'Awaiting capture',unavailable:'Unavailable'};
 function rolloutUrl(row){return '/semantic-map?'+new URLSearchParams({run:row.run_id,observer:'source'});}
 function coverage(row){
  if(Number.isInteger(row.pages_total))return `${row.pages_scanned||0} / ${row.pages_total} pages`;
  if(Number.isInteger(row.requests_completed)){
   const stage={requirement_extraction:'Reading requirements · ',requirement_scan:'Comparing behavior · '}[row.stage]||'';
   return `${stage}${row.requests_completed} request${row.requests_completed===1?'':'s'} checked`;
  }
  return row.status==='complete'?'Scan complete':'No page coverage recorded';
 }
 function install(){
  const host=document.getElementById('reward-scan-progress');
  if(!host||new URLSearchParams(location.search).get('view')!=='reward')return;
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  let scope=Object.fromEntries(new URLSearchParams(location.search)),busy=false,again=false,fingerprint='';
  function render(data){
   const focused=host.contains(document.activeElement)?document.activeElement.dataset.scanFocus:null;
   const opened=new Set([...host.querySelectorAll('details[open]')].map(d=>d.dataset.worker));host.replaceChildren();
   if(!data.workers.length){host.append(el('p','No saved worker scans in this population. Use Scan setup & budget to start a scan.','field-note'));return;}
   for(const worker of data.workers){
    const card=el('article',undefined,'scan-worker'),head=el('div',undefined,'scan-worker-head'),text=el('div');
    const names={search:'Behavior scan',requirements:'Requirement scan',chains:'Evidence-chain scan',source:'Source scan'};
    text.append(el('strong',names[worker.protocol]||'Diagnostic scan'),el('small',`${worker.selection.experiment||(worker.selection.kind==='latest'?'All rollouts':'Selected rollouts')} · ${worker.protocol_version}`));head.append(text);
    if(worker.workspace_path){const resume=el('button','Resume / budget');resume.type='button';resume.dataset.scanFocus=worker.id+':resume';resume.onclick=()=>RewardChecks.openScan({database:worker.database_path,directory:worker.workspace_path,protocol:worker.protocol,selection:worker.selection,retryFailed:!!worker.counts.failed});head.append(resume);}card.append(head);
    const stats=el('dl',undefined,'scan-counts');for(const [key,label]of Object.entries(labels)){const item=el('div');item.dataset.state=key;item.append(el('dt',label),el('dd',String(worker.counts[key]||0)));stats.append(item);}card.append(stats);
    const meta=el('p',undefined,'field-note');meta.append(document.createTextNode(`Last receipt ${new Date(worker.updated_at).toLocaleString()} · ${worker.population} rollout${worker.population===1?'':'s'} in inventory. `));
    if(worker.awaiting_inventory)meta.append(document.createTextNode(`${worker.awaiting_inventory} rollouts await the next worker inventory. `));
    if(worker.superseded)meta.append(document.createTextNode(`${worker.superseded} superseded snapshots excluded. `));card.append(meta);
    const details=el('details');details.dataset.worker=worker.id;details.open=opened.has(worker.id);const summary=el('summary','Rollout coverage & resume workspace');summary.dataset.scanFocus=worker.id+':details';details.append(summary);
    const path=el('p',undefined,'scan-workspace');path.append(el('span','Workspace'),el('code',worker.workspace_path||'Not recorded by this older worker. Run it from its original directory to record the resume path.'));details.append(path);
    const table=el('div',undefined,'scan-rollouts');
    for(const row of worker.rows){
     const item=el('div',undefined,'scan-rollout'),name=el('a',row.task);name.href=rolloutUrl(row);
     const info=el('div');info.append(name,el('small',coverage(row)));
     const state=el('span',labels[row.status]||row.status,'scan-state');state.dataset.state=row.status;item.append(info,state);
     name.dataset.scanFocus=worker.id+':'+row.run_id;
     const note=[row.last_state==='running'?'Last worker state: scanning':null,
      row.request_state==='in_flight'?'Last request: awaiting response':row.request_state==='unknown'?'Last request: outcome unknown':null,
      row.reason,`${row.new_calls} new call${row.new_calls===1?'':'s'} in this attempt`].filter(Boolean).join(' · ');item.append(el('small',note,'scan-row-note'));table.append(item);
    }
    details.append(table);if(worker.population>worker.rows.length)details.append(el('p',`Showing ${worker.rows.length} of ${worker.population} rollouts; use monitor-rollouts status for the full inventory.`,'field-note'));card.append(details);host.append(card);
   }
   if(focused)[...host.querySelectorAll('[data-scan-focus]')].find(n=>n.dataset.scanFocus===focused)?.focus({preventScroll:true});
  }
  async function refresh(){
   if(document.hidden)return;if(busy){again=true;return;}busy=true;const requested=JSON.stringify(scope);
   try{
    const query=new URLSearchParams();for(const k of ['experiment','environment'])if(scope[k])query.set(k,scope[k]);
    const response=await fetch('/api/monitoring/scans?'+query);if(!response.ok)throw Error('Scan progress unavailable');
    const data=await response.json();if(requested!==JSON.stringify(scope)){again=true;return;}
    const next=JSON.stringify(data);if(next!==fingerprint){fingerprint=next;render(data);}host.removeAttribute('data-error');
   }catch{host.dataset.error='true';if(!fingerprint)host.textContent='Saved scan progress is unavailable. Retrying…';}
   finally{busy=false;if(again){again=false;refresh();}}
  }
  window.addEventListener('jev:scope',e=>{scope=e.detail||{};refresh();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
  const timer=setInterval(refresh,5000);window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});refresh();
 }
 return {coverage,rolloutUrl,install};
})();
if(typeof module!=='undefined')module.exports=RewardScanProgress;else RewardScanProgress.install();
