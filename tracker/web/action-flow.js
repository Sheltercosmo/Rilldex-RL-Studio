(function(root){
 'use strict';
 const names={explore:'Gather information',apply:'Apply approach',verify:'Check results',coordinate:'Coordinate',report:'Report',mixed:'Combined purposes',unresolved:'Unknown purpose'};
 const statuses={uninspected:'Not read',outdated:'Needs refresh',reviewed:'Reviewed',current:'Saved reading'};
 function markers(a){const response=a.fields.feedback_response;return [
  ...(response?.status==='decided'&&['method_change','parameter_change'].includes(response.value)?[{kind:'change',label:response.value==='method_change'?'Changed method':'Adjusted settings'}]:[]),
  ...(a.same_dispatch_as?[{kind:'match',label:'Matching dispatch'}]:[]),
  ...(a.work_returns?.length?[{kind:'return',label:'Return to earlier work'}]:[]),
  ...(['outside','conflicting'].includes(a.scope)?[{kind:'scope',label:a.scope==='outside'?'Outside recorded task':'Conflicts with a requirement'}]:[])];}
 function groups(data){const byId=new Map(data.actions.map(a=>[a.event_id,a]));return data.lanes.map(lane=>{const seen=new Set(),batches=[];for(const id of lane.action_ids){if(seen.has(id))continue;const a=byId.get(id),members=a.dispatch_group.map(eid=>byId.get(eid)).filter(b=>b&&b.lane_id===lane.id).sort((x,y)=>x.number-y.number);for(const member of members)seen.add(member.event_id);batches.push({actions:members,unordered:members.some(a=>!a.order_known)});}return {...lane,batches};});}
 const api={markers,groups,names};if(typeof module!=='undefined'&&module.exports){module.exports=api;return;}
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 async function request(url,body){const response=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);const value=await response.json();if(!response.ok)throw Error(value.error||'Action flow unavailable');return value;}
 function mount(host,run,onSource,{graph,recurrence_order,onWork}={}){
  const panel=el('div',undefined,'action-flow');panel.setAttribute('aria-label','Agent work overview');host.append(panel);
  let data=null,selected=null,focus=null,timer=null,submitting=false,disposed=false;
  const live=()=>!disposed&&panel.isConnected&&!panel.closest('[hidden]');
  function schedule(){clearTimeout(timer);if(live()&&['queued','running'].includes(data?.job?.status))timer=setTimeout(load,2500);}
  function show(){
   const positions=new Map([...panel.querySelectorAll('.af-track')].map(n=>[n.dataset.lane,n.scrollLeft]));
   panel.replaceChildren();const coverage=data.coverage,heading=el('div',undefined,'af-heading'),title=el('div'),notice=el('p',undefined,'af-job');notice.setAttribute('role','status');
   title.append(el('h3','How the agent works'),el('p',coverage.total?`Latest readings · ${coverage.purpose_decided} / ${coverage.total} action purposes identified · ${coverage.uninspected} unread${coverage.outdated?' · '+coverage.outdated+' need refresh':''}`:'Saved work structure · reasoning and other agent contributions'));heading.append(title);
   const controls=el('div',undefined,'af-controls'),active=['queued','running'].includes(data.job?.status),refresh=el('button','Refresh');refresh.type='button';refresh.onclick=load;controls.append(refresh);
   if(coverage.pending){const read=el('button',active?'Reading…':`Read next ${Math.min(coverage.pending,data.batch_limit)}`,'af-read');read.type='button';read.disabled=active||submitting||!data.configured||data.other_job_active;read.onclick=async()=>{submitting=true;read.disabled=true;try{await request('/api/jobs',{run_id:run});await load();}catch(error){notice.textContent=error.message;}finally{submitting=false;if(read.isConnected)read.disabled=false;}};controls.append(read);}
   heading.append(controls);panel.append(heading);
   if(coverage.total){
   if(data.comparison_url){const compare=el('a','Across training →','af-compare');compare.href=data.comparison_url;controls.prepend(compare);}
   const legend=el('div',undefined,'af-legend');for(const [purpose,label]of Object.entries(names)){const item=el('span',`${label} ${data.purposes[purpose]||0}`),swatch=el('i');swatch.dataset.purpose=purpose;item.prepend(swatch);legend.append(item);}panel.append(legend);
   const focusBar=el('div',undefined,'af-focus');
   for(const [kind,label]of [['change','Changes'],['match','Matching calls'],...(data.work?.available?[['return','Returning actions']]:[]),['scope','Task concerns']]){const matches=data.actions.filter(a=>markers(a).some(m=>m.kind===kind)),button=el('button',`${label} ${matches.length}`);button.type='button';button.disabled=!matches.length;button.setAttribute('aria-pressed',String(focus===kind));button.onclick=()=>{focus=focus===kind?null:kind;if(focus)selected=matches[0].event_id;show();panel.querySelector('[aria-pressed=true].af-tile')?.scrollIntoView({block:'nearest',inline:'center'});};focusBar.append(button);}panel.append(focusBar);
   const note=el('p',undefined,'af-note');note.textContent='Recorded action order · select a tile to inspect · grouped tiles have no established internal order';panel.append(note);
   const rows=el('div',undefined,'af-lanes');panel.append(rows);
   const buttons=new Map();
   for(const lane of groups(data)){
    const row=el('div',undefined,'af-lane'),label=el('div',undefined,'af-lane-label');label.append(el('strong',lane.trajectory_id||'main'));if(lane.context_id!==null)label.append(el('span',lane.context_id));label.append(el('small',lane.action_ids.length+' actions'));
    const track=el('div',undefined,'af-track');track.dataset.lane=lane.id;track.setAttribute('aria-label',`${lane.trajectory_id} ${lane.context_id||''} actions`);
    for(const batch of lane.batches){const group=el('div',undefined,'af-batch'+(batch.unordered?' is-unordered':''));if(batch.unordered)group.title='Dispatch group · internal order unknown';
     for(const a of batch.actions){const b=el('button',String(a.number),'af-tile');b.type='button';b.dataset.purpose=a.purpose;b.dataset.event=a.event_id;b.setAttribute('aria-label',`Action ${a.number}: ${a.title}. ${names[a.purpose]}. ${statuses[a.status]}. ${markers(a).map(m=>m.label).join(', ')}`);b.title=b.getAttribute('aria-label');for(const m of markers(a)){const mark=el('i',m.kind==='change'?'↗':m.kind==='match'?'=':m.kind==='return'?'↶':'!','af-mark af-'+m.kind);mark.setAttribute('aria-hidden','true');b.append(mark);}b.onclick=()=>choose(a.event_id);buttons.set(a.event_id,b);group.append(b);}track.append(group);
    }
    const shell=el('div',undefined,'af-track-shell'),overview=el('div',undefined,'af-overview');overview.setAttribute('role','img');overview.setAttribute('aria-label',`Whole context: ${lane.action_ids.length} actions in recorded order. Detailed tiles below.`);overview.title='Whole context · recorded action order';
    for(const batch of lane.batches)for(const a of batch.actions){const segment=el('i');segment.dataset.purpose=a.purpose;overview.append(segment);}
    shell.style.maxWidth=(lane.action_ids.length*83)+'px';shell.append(overview,track);row.append(label,shell);rows.append(row);track.scrollLeft=positions.get(lane.id)||0;
   }
   for(const a of data.actions)buttons.get(a.event_id).classList.toggle('af-dimmed',!!focus&&!markers(a).some(m=>m.kind===focus));
   const details=el('div',undefined,'af-selected');panel.append(details);
   function choose(id){selected=id;for(const [eid,b]of buttons)b.setAttribute('aria-pressed',String(eid===id));const a=data.actions.find(a=>a.event_id===id);details.replaceChildren();if(!a)return;
    const summary=el('div',undefined,'af-action-copy');summary.append(el('small',`ACTION ${a.number} · ${statuses[a.status]}`),el('strong',a.title));const value=a.fields.feedback_response;summary.append(el('span',`${names[a.purpose]}${value?' · '+root.ActionReading.display(value):''}${a.reviewed?' · includes review':''}`));details.append(summary);
    const meta=el('div',undefined,'af-action-markers');for(const marker of markers(a))meta.append(el('span',marker.label,'af-tag af-'+marker.kind));if(!a.order_known)meta.append(el('span','Order unknown','af-tag'));details.append(meta);
    const actions=el('div',undefined,'af-selected-actions');if(a.same_dispatch_as){const match=el('button','Matching call');match.type='button';match.onclick=()=>{choose(a.same_dispatch_as);buttons.get(a.same_dispatch_as)?.scrollIntoView({block:'nearest',inline:'center'});};actions.append(match);}const open=el('button','Open action →','af-open');open.type='button';open.onclick=()=>onSource(id);actions.append(open);details.append(actions);
   }
   const preferred=data.actions.find(a=>markers(a).length)||data.actions.find(a=>a.purpose!=='unresolved')||data.actions[0];choose(data.actions.some(a=>a.event_id===selected)?selected:preferred?.event_id);
   panel.append(notice);
   if(active)notice.textContent=`Reading ${data.job.progress} / ${data.job.total||'…'} · saved after each action`;
   else if(data.job?.error)notice.textContent=data.job.error;
   else if(data.other_job_active)notice.textContent='Another observation job is running for this rollout.';
   else if(coverage.pending)notice.textContent=data.configured?`${coverage.pending} pending model readings · up to ${data.batch_limit} per batch with ${data.model}. Keeps your reviews.`:'Configure Jev in Connections to read the remaining actions.';
   else notice.textContent='Saved readings are current for the selected reader.';
   if(!data.configured&&coverage.pending){const link=el('a','Model setup');link.href='/connections#model-section';notice.append(document.createTextNode(' '),link);}
   const explanation=el('details',undefined,'af-definition');explanation.append(el('summary','Reading coverage & markers'),el('p',`${coverage.current} current readings · ${coverage.reviewed} reviewed without a current model reading · ${coverage.outdated} outdated · ${coverage.uninspected} unread. Combined purposes keeps one dispatch with several requested purposes together. Unknown purpose includes unread, outdated and unresolved actions. Counts cover the whole source rollout; lanes have independent order, not a shared time axis.`),el('p','Colors describe immediate action purpose. Apply approach does not establish an RL exploration–exploitation trade-off. ↗ marks a saved method or settings change, = identical recorded tool, arguments and text, ↶ a supported return to earlier work, and ! a saved task-relationship concern. A matching call does not establish wasted work; a changed method does not establish improvement. Open an action for the reading and original evidence.'));panel.append(explanation);
   }
   if(data.work?.available&&onWork){
    const work=data.work,counts=work.counts,box=el('div',undefined,'af-work'),head=el('div',undefined,'af-work-heading'),copy=el('div');copy.append(el('h4','Returns to earlier work'),el('p',`Work identified in ${counts.assigned} / ${counts.positions} ${work.axis==='contributions'?'contribution spans':'actions'} · ${counts.returned} return${counts.returned===1?'':'s'}${counts.interrupted?' · '+counts.interrupted+' across gaps':''}${counts.disputed?' · '+counts.disputed+' disputed':''}`));
    const open=el('button','Open work path →');open.type='button';open.onclick=()=>onWork(null,work.recurrence_order);head.append(copy,open);box.append(head);
    const labels={returned:'Returned',continued:'Continued',resumed:'Resumed',interrupted:'Gap in evidence',disputed:'Disputed identity'},rank={returned:0,disputed:1,interrupted:2,resumed:3,continued:4};
    const episodes=[...work.episodes].sort((a,b)=>(rank[a.state]??5)-(rank[b.state]??5));
    function row(episode){const button=el('button',undefined,'af-work-episode');button.type='button';button.append(el('span',labels[episode.state]||episode.state,'af-work-state'),el('strong',episode.target),el('small','Inspect evidence →'));button.dataset.state=episode.state;button.onclick=()=>onWork(episode.id,work.recurrence_order);return button;}
    for(const episode of episodes.slice(0,3))box.append(row(episode));
    if(episodes.length>3){const more=el('details');more.append(el('summary',`${episodes.length-3} more recurrence records`));for(const episode of episodes.slice(3))more.append(row(episode));box.append(more);}
    const definition=el('details',undefined,'af-definition');definition.append(el('summary','Saved work evidence'),el('p',work.scope),el('p','Work relationships come from the selected graph; action-purpose readings above use the latest workspace observations.'));box.append(definition);panel.append(box);
   }
   schedule();
  }
  async function load(){clearTimeout(timer);if(!live())return;try{const value=await request('/api/action-reading/flow?'+new URLSearchParams({run,...(graph?{graph}:{}),...(recurrence_order?{recurrence_order}:{})}));if(!live())return;data=value;if(!data.coverage.total&&!data.work?.available){panel.remove();return;}show();}catch(error){if(!live())return;let errorBox=panel.querySelector('.af-load-error');if(!errorBox){errorBox=el('p',undefined,'af-load-error');panel.append(errorBox);}errorBox.replaceChildren(el('span',error.message+' '));const retry=el('button','Retry');retry.type='button';retry.onclick=load;errorBox.append(retry);schedule();}}
  panel.append(el('p','Loading saved action purposes…','af-note'));load();
  return ()=>{disposed=true;clearTimeout(timer);};
 }
 root.ActionFlow={...api,mount};
})(typeof globalThis!=='undefined'?globalThis:this);
