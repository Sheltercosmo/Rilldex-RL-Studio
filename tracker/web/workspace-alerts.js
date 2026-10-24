'use strict';
const WorkspaceAlerts=(()=>{
 function fresh(rows,seen){const known=new Set(seen);return rows.filter(r=>!known.has(r.id));}
 function remember(seen,rows){return [...new Set([...rows.map(r=>r.id),...seen])].slice(0,2000);}
 function scoped(rows,scope){return rows.filter(r=>['experiment','environment'].every(k=>!scope[k]||(k==='experiment'&&scope[k]==='__unassigned__'?!r[k]:r[k]===scope[k])));}
 function install(){
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const button=(text,fn)=>{const b=el('button',text);b.type='button';b.onclick=fn;return b;};
  let data=null,prefs={seen:[],muted:false},key='',busy=false,again=false,scope={},fingerprint='',pending=[];
  const trigger=button('Findings',()=>{renderDialog();dialog.showModal();});trigger.className='workspace-findings';trigger.title='Recent monitor findings and popup settings';
  document.querySelector('.workspace-bar .bar-actions')?.append(trigger);
  const dialog=el('dialog',undefined,'findings-dialog');dialog.setAttribute('aria-labelledby','findings-title');
  const head=el('div',undefined,'dialog-head'),title=el('h2','Monitor findings');title.id='findings-title';head.append(title,button('Close',()=>dialog.close()));
  const setting=el('label',undefined,'findings-setting'),toggle=el('input');toggle.type='checkbox';toggle.checked=true;
  setting.append(toggle,el('span','Show popups for new findings in this browser'));
  const status=el('p',undefined,'field-note'),list=el('div',undefined,'findings-list');dialog.append(head,setting,status,list);document.body.append(dialog);window.WorkspaceDialog?.prepare(dialog);
  const popup=el('aside',undefined,'finding-popup');popup.hidden=true;popup.setAttribute('aria-label','New monitor findings');popup.setAttribute('aria-live','polite');document.body.append(popup);
  function readPrefs(){try{const raw=localStorage.getItem(key);if(!raw)return prefs;const v=JSON.parse(raw);return {seen:Array.isArray(v.seen)?v.seen.filter(x=>typeof x==='string'):[],muted:v.muted===true};}catch{return prefs;}}
  function save(){try{localStorage.setItem(key,JSON.stringify(prefs));}catch{}}
  function dismiss(){popup.hidden=true;pending=[];}
  toggle.onchange=()=>{prefs.muted=!toggle.checked;save();if(prefs.muted)dismiss();};
  function row(item){
   const card=el('article',undefined,'finding-row'),label=el('span',item.category==='reward'?'Reward check flagged':'Monitor feedback','finding-label');
   const content=el('div',undefined,'finding-content');
   content.append(label,el('strong',item.title),el('small',[item.experiment,item.task===item.run_id?'Rollout':item.task].filter(Boolean).join(' · ')),el('p',item.summary));card.append(content);
   const actions=el('div',undefined,'finding-actions'),evidence=el('a','Inspect evidence');evidence.href=item.evidence_url;
   const chart=el('a','Open monitor');chart.href=item.monitor_url;actions.append(evidence,chart);card.append(actions);return card;
  }
  function renderList(host,rows){host.replaceChildren();for(const item of rows)host.append(row(item));if(!rows.length)host.append(el('p','No current findings from enabled monitors.','field-note'));}
  function renderDialog(){toggle.checked=!prefs.muted;status.textContent=data?(data.total>data.alerts.length?`Showing the latest ${data.alerts.length} of ${data.total} findings. `:'')+'Findings link to saved evidence. Thresholds describe measurements, not verified failures.':'Loading findings…';renderList(list,data?.alerts||[]);}
  function renderFocus(){const host=document.getElementById('reward-findings');if(!host)return;const rows=scoped(data?.alerts||[],scope).filter(r=>r.category==='reward');renderList(host,rows);const count=document.getElementById('reward-finding-count');if(count)count.textContent=`${rows.length} current findings`+(data?.total>data?.alerts.length?' · latest 100 workspace findings searched':'');}
  function announce(rows,first){
   if(prefs.muted||(!rows.length&&!pending.length))return;
   pending=[...new Map([...rows,...pending].map(r=>[r.id,r])).values()];popup.replaceChildren();
   const top=el('div',undefined,'finding-popup-head');top.append(el('strong',`${pending.length} finding${pending.length===1?'':'s'}`),button('Dismiss',dismiss));popup.append(top);
   for(const item of pending.slice(0,2))popup.append(row(item));
   const actions=el('div',undefined,'finding-actions');actions.append(button('View all findings',()=>{dismiss();renderDialog();dialog.showModal();}),button('Mute popups',()=>{prefs.muted=true;save();dismiss();}));popup.append(actions);popup.hidden=false;
  }
  async function refresh(){
   if(document.hidden)return;if(busy){again=true;return;}busy=true;
   try{
    const response=await fetch('/api/monitoring/alerts');if(!response.ok)throw Error('Findings unavailable');
    const next=await response.json(),first=!data,nextKey='rilldex-findings:'+next.workspace_id;
    if(key!==nextKey){key=nextKey;prefs={seen:[],muted:false};}prefs=readPrefs();
    const added=fresh(next.alerts,prefs.seen);prefs.seen=remember(prefs.seen,next.alerts);save();data=next;
    pending=pending.filter(r=>data.alerts.some(a=>a.id===r.id));if(!pending.length)popup.hidden=true;
    trigger.textContent=`Findings${data.total?' · '+data.total:''}`;trigger.title='Recent findings and popup settings';
    renderFocus();if(dialog.open)renderDialog();announce(added,first);
   }catch{trigger.title='Findings unavailable · reconnecting';status.textContent='Findings unavailable. The next update will retry.';}
   finally{busy=false;if(again){again=false;refresh();}}
  }
  window.addEventListener('jev:scope',e=>{scope=e.detail||{};renderFocus();});
  window.addEventListener('storage',e=>{if(e.key===key){prefs=readPrefs();if(prefs.muted)dismiss();if(dialog.open)renderDialog();}});
  window.addEventListener('tracker-live',e=>{const s=e.detail,next=JSON.stringify([s.source_revision,s.semantic_revision,s.analysis?.revision,s.analysis?.updating]);if(next!==fingerprint){fingerprint=next;refresh();}});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
  const timer=setInterval(refresh,30000);window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});refresh();
 }
 return {install,fresh,remember,scoped};
})();
if(typeof module!=='undefined')module.exports=WorkspaceAlerts;
else WorkspaceAlerts.install();
