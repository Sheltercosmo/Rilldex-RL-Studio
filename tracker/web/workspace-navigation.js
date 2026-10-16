/* Shared return destinations and section navigation. No rollout data is changed. */
(function(root){
 'use strict';
 const names={'/':'Overview','/dashboard':'Overview','/rollouts':'Overview','/runs':'Rollouts','/semantic-map':'Behavior map','/source':'Source record','/monitors':'Monitors','/investigate':'Investigation','/connections':'Data & workflows','/integration-guide':'Integration guide','/measurement-review':'Measurement review','/relations':'Graph query'};
 function internal(value,base){
  if(!value||/[\\\r\n]/.test(value))return null;
  try{const u=new URL(value,base),b=new URL(base);return u.origin===b.origin&&!u.username&&!u.password&&names[u.pathname]?u.pathname+u.search+u.hash:null;}catch{return null;}
 }
 function destination(current,{explicit,arrival,referrer}={}){
  const here=internal(current,current);
  for(const candidate of [explicit,arrival,referrer]){const path=internal(candidate,current);if(path&&path!==here)return path;}
  return new URL(current).pathname==='/semantic-map'||new URL(current).pathname==='/source'?'/runs':'/';
 }
 function title(path){return names[new URL(path,'http://workspace.local').pathname]||'workspace';}
 function captureView(hash,views=[],recipe=false){
  const id=hash.replace(/^#/,''),routes={'setup-section':'setup','snapshot-section':'import','capture-bundle-receive':'import','directory-section':'watch','worker-section':'workers','code-section':'code','telemetry-section':'code','training-setup':'config','question-section':'readiness','data-access-section':'outputs','analysis-code':'outputs','workspace-transfer':'outputs'};
  return routes[id]||views[0]||(recipe?'readiness':'setup');
 }
 function install(){
  const bar=document.querySelector('.workspace-bar');if(!bar)return;
  const read=key=>{try{return JSON.parse(sessionStorage.getItem(key)||'null');}catch{return null;}};
  const write=(key,value)=>{try{sessionStorage.setItem(key,JSON.stringify(value));}catch{}};
  const path=()=>location.pathname+location.search+location.hash;
  const arrival=read('rilldex-arrival');write('rilldex-arrival',null);
  const previous=arrival?.to===path()?arrival.from:history.state?.rilldexOrigin;
  const initial=destination(location.href,{explicit:new URLSearchParams(location.search).get('return_to'),arrival:previous,referrer:document.referrer});
  history.replaceState({...history.state,rilldexOrigin:initial},'');
  const back=document.createElement('a');back.id='workspace-back';back.className='workspace-back';
  function refresh(){
   const explicit=new URLSearchParams(location.search).get('return_to');
   const target=destination(location.href,{explicit,arrival:history.state?.rilldexBack||initial});
   back.href=target;back.textContent='← Back';back.title='Back to '+title(target);back.setAttribute('aria-label',back.title);
   back.hidden=location.pathname==='/'&&target==='/'&&path()==='/';
  }
  bar.prepend(back);refresh();
  function remember(){const positions=read('rilldex-page-positions')||{};delete positions[path()];positions[path()]={x:scrollX,y:scrollY};write('rilldex-page-positions',Object.fromEntries(Object.entries(positions).slice(-40)));}
  back.addEventListener('click',event=>{
   if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
   if(history.state?.rilldexBack===internal(back.href,location.href)){event.preventDefault();history.back();return;}
   write('rilldex-restore-page',internal(back.href,location.href));
  });
  document.addEventListener('click',event=>{
   const a=event.target.closest?.('a[href]');if(event.defaultPrevented||event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey||!a||a.target||a.hasAttribute('download'))return;
   const to=internal(a.href,location.href);if(!to||to===path())return;
   const u=new URL(a.href);if(u.pathname===location.pathname&&u.search===location.search)return;
   remember();write('rilldex-arrival',{from:path(),to});
  });
  window.addEventListener('pagehide',remember);
  window.addEventListener('popstate',refresh);
  window.addEventListener('hashchange',refresh);
  window.addEventListener('rilldex:navigation',refresh);
  let restored=false;
  function restore(){
   if(restored||read('rilldex-restore-page')!==path())return false;
   const position=read('rilldex-page-positions')?.[path()];
   if(!position)return false;
   restored=true;write('rilldex-restore-page',null);
   requestAnimationFrame(()=>scrollTo({left:position.x,top:position.y,behavior:'instant'}));return true;
  }
  root.WorkspaceNavigation.remember=remember;root.WorkspaceNavigation.restore=restore;
  // Connections restores after revealing its destination panel.
  if(document.body.dataset.app!=='connections')window.addEventListener('load',restore,{once:true});
 }
 const api={internal,destination,title,captureView,install};
 if(typeof module!=='undefined')module.exports=api;else root.WorkspaceNavigation=api;
})(typeof window==='undefined'?globalThis:window);
