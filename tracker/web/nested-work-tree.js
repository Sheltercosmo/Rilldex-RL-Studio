/* Native declared structure. No text clustering, state propagation or new model work. */
((root,factory)=>{const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.NestedWorkTree=api;})(typeof window==='undefined'?globalThis:window,()=>{
 const LABEL={sequence:'In sequence',fallback:'Fallback alternatives',parallel:'Independent subgoals'};
 function model(data){
  const byId=new Map(data.nodes.map(n=>[n.id,n])),children=new Map(),parent=new Map();
  for(const e of [...data.links].filter(e=>e.type==='contains').sort((a,b)=>(a.order??0)-(b.order??0))){if(!children.has(e.source))children.set(e.source,[]);children.get(e.source).push(e.target);parent.set(e.target,e.source);}
  function descendants(id){const out=[],seen=new Set(),pending=[id];while(pending.length){const k=pending.shift();if(seen.has(k))continue;seen.add(k);if(byId.has(k))out.push(byId.get(k));pending.push(...(children.get(k)||[]));}return out;}
  function summary(id){const ns=descendants(id),rs=[...new Map(ns.flatMap(n=>n.records||[]).map(r=>[r.occurrence_id||r.id,r])).values()];return {goals:ns.filter(n=>n.kind==='native_goal').length,operations:rs.filter(r=>r.kind==='operation').length,failures:rs.filter(r=>r.kind==='reported_failed').length,completions:rs.filter(r=>r.kind==='reported_complete').length,records:rs.length};}
  function path(id){const out=[],seen=new Set();while(byId.has(id)&&!seen.has(id)){seen.add(id);if(byId.get(id).kind==='native_goal')out.unshift(id);id=parent.get(id);}return out;}
  return {byId,children,parent,descendants,summary,path};
 }
 function render(host,data,rootId,inspect,openUnit,onFocus){
  const m=model(data),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  const root=m.byId.get(rootId);let focus=new URL(location.href).searchParams.get('work_focus');
  if(!m.path(focus).includes(rootId))focus=rootId;
  const shell=el('section',null,'nw-shell');shell.setAttribute('aria-label','Nested goal map');host.append(shell);
  function navigate(id){focus=id;const url=new URL(location.href);url.searchParams.set('work_focus',id);if(onFocus)onFocus(id);else history.replaceState(null,'',url);draw();}
  function stateClass(n){return n.state==='Reported failed'?'is-failed':n.state==='Reported complete'?'is-complete':n.state==='No recorded visit'?'is-unvisited':'';}
  function reports(n){const list=(n.records||[]).filter(r=>['statement','reported_complete','reported_failed'].includes(r.kind));return list.at(-1);}
  function card(id,isRoot=false){const n=m.byId.get(id),s=m.summary(id),box=el('article',null,'nw-card '+stateClass(n)+(isRoot?' nw-root':''));box.dataset.workNode=id;
   const main=el('button',null,'nw-card-main');main.type='button';main.append(el('small',id===rootId?'OBJECTIVE':'SUBGOAL'),el('strong',n.label));main.onclick=()=>inspect(n);box.append(main);
   box.append(el('span',n.state,'nw-status'));
   const count=el('p',null,'nw-counts');count.append(el('b',String(s.operations)),el('span',' operation request'+(s.operations===1?'':'s')));if(s.goals>1)count.append(el('span',` · ${s.goals-1} nested goals`));box.append(count);if(s.goals>1&&n.operation_count)box.append(el('p',`${n.operation_count} directly scoped to this goal`,'nw-preview'));
   const evidence=(n.records||[]).filter(r=>r.kind==='statement').at(-1);if(evidence&&s.goals===1)box.append(el('p',evidence.evidence.text.replace(/^Think: /,''),'nw-preview'));
   if(s.goals>1&&(s.failures||s.completions)){const outcomes=el('div',null,'nw-reports');if(s.failures)outcomes.append(el('span',`${s.failures} failure report${s.failures===1?'':'s'}`,'nw-failure'));if(s.completions)outcomes.append(el('span',`${s.completions} completion report${s.completions===1?'':'s'}`,'nw-complete'));box.append(outcomes);}
   const actions=el('div',null,'nw-card-actions');const detail=el('button','Inspect work');detail.onclick=()=>inspect(n);actions.append(detail);
   if(!isRoot){const next=el('button',(m.children.get(id)||[]).length?'Open subgoals →':'Open work history →');next.onclick=()=>navigate(id);actions.append(next);}box.append(actions);return box;
  }
  function draw(){shell.replaceChildren();const sum=m.summary(rootId),current=m.byId.get(focus);
   const bar=el('div',null,'nw-top'),crumbs=el('nav',null,'nw-breadcrumbs');crumbs.setAttribute('aria-label','Goal path');for(const id of m.path(focus)){const n=m.byId.get(id),b=el('button',id===rootId?'Objective':n.label);b.title=n.label;b.onclick=()=>navigate(id);if(id===focus)b.setAttribute('aria-current','location');crumbs.append(b);}bar.append(crumbs);shell.append(bar);
   if(sum.failures){const alert=el('div',null,'nw-alert');alert.append(el('strong',`${sum.failures} failed-branch reports`),el('span','Inspect the affected branches and their outcomes.'));
    for(const failed of m.descendants(rootId).filter(n=>(n.records||[]).some(r=>r.kind==='reported_failed'))){const jump=el('button',failed.label);jump.onclick=()=>{const goalParent=m.path(failed.id).at(-2)||rootId;navigate(goalParent);inspect(failed);};alert.append(jump);}shell.append(alert);}
   const map=el('div',null,'nw-map');map.append(card(focus,true));const groups=el('div',null,'nw-groups');
   for(const controlId of m.children.get(focus)||[]){const control=m.byId.get(controlId);if(control.kind!=='native_control')continue;const group=el('section',null,'nw-group'),tag=el('button',LABEL[control.control]||control.label,'nw-control');tag.title=control.state;tag.onclick=()=>inspect(control);group.append(tag);
    const branchIds=m.children.get(controlId)||[],total=Math.max(0,...branchIds.map(id=>m.summary(id).operations)),branches=el('div',null,'nw-subgoals');
    branchIds.forEach((id,i)=>{const row=el('div',null,'nw-branch'),n=m.byId.get(id);row.append(el('span',String(i+1),'nw-order'),card(id));const weight=m.summary(id).operations,share=el('div',null,'nw-effort');share.title=`${weight} operation requests; largest sibling has ${total}`;const fill=el('span');fill.style.width=(total?100*weight/total:0)+'%';share.append(fill);row.append(share);branches.append(row);});
    group.append(branches);if(total)group.append(el('p','Bars compare operation counts. Shared requests may belong to more than one branch.','nw-footnote'));groups.append(group);
   }
   if(!groups.children.length)groups.append(el('p','No subgoals declared through this record.','nw-footnote'));map.append(groups);shell.append(map);
   const recent=el('section',null,'nw-records');recent.append(el('h3','Work recorded directly under this goal'));
   const own=current.records||[];if(!own.length)recent.append(el('p','No scoped records through this cutoff.','nw-footnote'));
   else for(const r of own){const item=el('div',null,'nw-record '+r.kind),b=el('button',`Record ${r.event_index+1}`);b.onclick=()=>openUnit('event:'+r.evidence.event_id);item.append(el('small',({entered:'Goal entered',operation:'Operation requested',statement:'Agent statement',observation:'Observation',reported_complete:'Completion report',reported_failed:'Failure report'})[r.kind]),el('p',r.evidence.text),b);recent.append(item);}
   shell.append(recent,el('p','Declared structure · '+root.producer+'. Operation requests are native protocol records, not inferred semantic attempts. Reports do not verify objective success.','nw-footnote'));
  }
  draw();
 }
 return {model,render};
});
