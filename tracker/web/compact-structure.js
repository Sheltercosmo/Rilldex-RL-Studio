/* Compact parentage + local sequence + revision evidence. No inferred pairing. */
(function(root){
 'use strict';
 const UNMATCHED='__unmatched__';
 const VIEW_KEYS=['plan_view','plan_root','plan_branch','plan_compare','plan_compare_root','plan_compare_branch','plan_alignment','plan_event','plan_event_side','plan_episode'];
 function syncSelection(target,current){for(const key of VIEW_KEYS){if(current.has(key))target.set(key,current.get(key));else target.delete(key);}return target;}
 function clearSelection(params){for(const key of VIEW_KEYS)if(key!=='plan_view')params.delete(key);return params;}
 function pairedFocus(side,id,aligned){const group=aligned?.available&&aligned.groups.find(g=>g[side==='A'?'a':'b']===id);return group?{A:group.a||UNMATCHED,B:group.b||UNMATCHED}:{[side]:id};}
 const STRUCTURAL=new Set(['plan','plan_step','task_list','declared_item','native_goal','native_control','outline_item']);
 const EVENT_TYPES={action:['Action','#3159dc'],check:['Check','#087e79'],feedback:['Feedback','#738396'],assessment:['Assessment','#b07820'],revision:['Revision','#8052b6'],decision:['Decision','#b3437b'],operation:['Operation','#3159dc'],reported_failed:['Reported failure','#c14949'],reported_complete:['Reported complete','#087e79'],statement:['Statement','#8052b6'],observation:['Observation','#738396'],entered:['Entered','#3159dc']};
 const uniq=values=>[...new Set(values)];
 const short=(value,n=90)=>String(value||'').length>n?String(value).slice(0,n-1)+'…':String(value||'');
 function model(data,focus='all'){
  const nodes=new Map(data.nodes.filter(n=>STRUCTURAL.has(n.kind)).map(n=>[n.id,n]));
  const links=[...data.links,...(data.work_outline?.links||[])].filter(e=>nodes.has(e.source)&&nodes.has(e.target));
  const parents=[],seen=new Set(),children=new Map([...nodes.keys()].map(id=>[id,[]]));
  for(const e of links.filter(e=>['contains','part_of'].includes(e.type))){const a=e.type==='part_of'?e.target:e.source,b=e.type==='part_of'?e.source:e.target,key=JSON.stringify([a,b]);if(seen.has(key))continue;seen.add(key);parents.push({source:a,target:b});children.get(a).push(b);}
  const starts=focus==='all'?data.roots:[focus],visible=new Set();
  function visit(id,path=new Set()){if(path.has(id))throw Error('Cyclic parentage: inspect the detailed map.');if(visible.has(id)||!nodes.has(id))return;visible.add(id);const next=new Set(path).add(id);for(const child of children.get(id))visit(child,next);}
  starts.forEach(id=>visit(id));
  const incoming=new Map([...visible].map(id=>[id,[]]));for(const e of parents)if(visible.has(e.source)&&visible.has(e.target))incoming.get(e.target).push(e.source);
  // One full branch, with an explicit reference tile for every additional parent.
  const primary=new Map([...incoming].map(([id,list])=>[id,list[0]])),depths=new Map(),tiles=[];
  function size(id,alias=false){return alias?1:Math.max(1,children.get(id).reduce((sum,c)=>sum+size(c,primary.get(c)!==id),0));}
  const roots=starts.filter(id=>visible.has(id)&&!incoming.get(id).length),total=roots.reduce((sum,id)=>sum+size(id),0)||1;
  function place(id,start,span,depth,alias=false){tiles.push({id,start,span,depth,alias,parentIds:incoming.get(id),node:nodes.get(id)});if(!depths.has(depth))depths.set(depth,new Set());depths.get(depth).add(id);if(alias)return;let x=start;for(const child of children.get(id)){const shared=primary.get(child)!==id,width=span*size(child,shared)/size(id);place(child,x,width,depth+1,shared);x+=width;}}
  let offset=0;for(const id of roots){const span=size(id)/total;place(id,offset,span,0);offset+=span;}
  function descendants(id){const ids=new Set(),todo=[id];while(todo.length){const current=todo.pop();if(ids.has(current))continue;ids.add(current);todo.push(...children.get(current)||[]);}return ids;}
  const maximumDepth=new Map();function depthOf(id){if(!maximumDepth.has(id))maximumDepth.set(id,Math.max(0,...incoming.get(id).map(parent=>depthOf(parent)+1)));return maximumDepth.get(id);}visible.forEach(depthOf);const actualLayers=new Map();for(const [id,depth]of maximumDepth){if(!actualLayers.has(depth))actualLayers.set(depth,new Set());actualLayers.get(depth).add(id);}for(const tile of tiles)tile.depth=maximumDepth.get(tile.id);
  return {nodes,links,children,tiles,visible,descendants,depth:Math.max(0,...maximumDepth.values()),
   breadth:Math.max(0,...[...actualLayers.values()].map(ids=>ids.size)),shared:[...incoming.values()].filter(p=>p.length>1).length,
   leaves:[...visible].filter(id=>!children.get(id).length).length};
 }
 function sequence(data,structure,focus){
  if(focus===UNMATCHED)return {events:[],columns:[],rows:[],episodes:[],outsideEpisodes:data.revision_episodes?.episodes||[],actions:0,failed:0,measured:0};
  const nodes=new Map(data.nodes.map(n=>[n.id,n])),owned=new Map(),events=new Map();
  const add=(owner,node,type)=>{if(!node)return;events.set(node.id,{...node,eventType:type});if(!owned.has(owner))owned.set(owner,new Set());owned.get(owner).add(node.id);};
  function actions(owner,rows){for(const row of rows||[]){add(owner,nodes.get(row.action_id),row.roles?.includes('checks_plan_step')?'check':'action');for(const response of row.responses||[]){add(owner,nodes.get(response.node_id),'feedback');for(const assessment of response.assessments||[])add(owner,nodes.get(assessment.node_id),'assessment');}}}
  for(const path of data.stage_paths||[])actions(path.stage_id,path.rows);
  for(const n of structure.nodes.values()){
   if(n.execution_summary?.scope==='direct')actions(n.id,n.execution_summary.rows);
   // Outline bindings may aggregate descendant execution. Assign only direct
   // memberships where possible; the selected subtree still deduplicates IDs.
   for(const binding of data.work_outline?.bindings||[])if(binding.item_id===n.id){const scope=structure.descendants(binding.scope_node_id);for(const path of data.stage_paths||[])if(scope.has(path.stage_id))actions(n.id,path.rows);}
   for(const r of n.records||[])add(n.id,{...r,label:r.evidence?.text||r.kind,source_node_ids:['event:'+r.evidence?.event_id],evidence:[r.evidence],state:r.kind.replaceAll('_',' ')},r.kind);
   for(const d of n.decisions||[])add(n.id,{...d,label:d.label||d.evidence?.text||d.type,source_node_ids:['event:'+d.evidence?.event_id],evidence:[d.evidence],state:d.type.replaceAll('_',' ')},'decision');
  }
  const episodes=data.revision_episodes?.episodes||[];
  for(const episode of episodes){
   for(const stage of episode.stages)for(const uid of stage.node_ids){const n=nodes.get(uid);if(!n||STRUCTURAL.has(n.kind))continue;const type=['Declared change','Replacement statement'].includes(stage.label)?'revision':stage.label==='Reassessment'?'assessment':stage.label.includes('Feedback')||stage.label.includes('result')?'feedback':n.kind==='action'||n.source_kind==='action'||['Implementation','Same-work follow-up'].includes(stage.label)?'action':'decision';if(!events.has(uid))events.set(uid,{...n,eventType:type});if(uid===episode.declaration_id)events.set(uid,{...n,eventType:'revision'});}
  }
  const scope=focus==='all'?structure.visible:structure.descendants(focus);
  const idsFor=ids=>new Set([...ids].flatMap(id=>[...owned.get(id)||[]]));
  const selected=idsFor(scope),relevant=episodes.filter(e=>e.node_ids.some(id=>selected.has(id)||scope.has(id))),context=new Set();
  for(const episode of relevant)for(const id of episode.node_ids){const n=nodes.get(id);if(!n||STRUCTURAL.has(n.kind)||selected.has(id))continue;
   // Native aliases of a bound unit do not create a second source occurrence.
   if([...selected].some(uid=>events.get(uid)?.event_index===n.event_index))continue;
   if(!events.has(id))events.set(id,{...n,eventType:n.kind==='action'||n.source_kind==='action'?'action':n.kind==='feedback'||n.source_kind==='feedback'?'feedback':'decision'});context.add(id);}
  const ordered=[...selected,...context].map(id=>events.get(id)).filter(Boolean).sort((a,b)=>(a.event_index??0)-(b.event_index??0)||(a.source_start??a.evidence?.[0]?.start??0)-(b.source_start??b.evidence?.[0]?.start??0)||a.id.localeCompare(b.id));
  const columns=uniq(ordered.map(n=>n.event_index)).filter(Number.isInteger).sort((a,b)=>a-b);
  const rows=focus==='all'?[...structure.visible].filter(id=>owned.has(id)).map(id=>({id,label:structure.nodes.get(id).label,ids:owned.get(id)})):
   [{id:focus,label:'Direct · '+structure.nodes.get(focus).label,ids:owned.get(focus)||new Set()},...(structure.children.get(focus)||[]).map(id=>({id,label:structure.nodes.get(id).label,ids:idsFor(structure.descendants(id))}))];
  if(context.size)rows.push({id:null,label:'Revision context',ids:context});
  const actionsSet=new Set(ordered.filter(e=>selected.has(e.id)&&['action','check','operation'].includes(e.eventType)).map(e=>e.dispatch_id||e.occurrence_id||e.id));
  const outcomes=data.revision_episodes?.operation_results||{};for(const event of ordered)if(outcomes[event.id])event.outcome=outcomes[event.id].outcome;
  const measuredActions=ordered.filter(e=>selected.has(e.id)&&['action','check','operation'].includes(e.eventType)&&['failed','completed'].includes(e.outcome));
  const measured=new Set(measuredActions.map(e=>e.dispatch_id||e.occurrence_id||e.id)),failed=new Set(measuredActions.filter(e=>e.outcome==='failed').map(e=>e.dispatch_id||e.occurrence_id||e.id));
  return {events:ordered,columns,rows,episodes:relevant,outsideEpisodes:episodes.filter(e=>!relevant.includes(e)),actions:actionsSet.size,failed:failed.size,measured:measured.size};
 }
 // Union slots are only shared by explicit pairs, never by a label similarity.
 // Each original tree retains its own depth; unmatched branches keep their space.
 function alignment(a,b,pairs=[]){
  if(a.shared||b.shared)return {available:false,reason:'Shared parentage: independent widths preserve every parent link.'};
  const roots=m=>m.tiles.filter(t=>t.depth===0).map(t=>t.id);
  const ra=roots(a),rb=roots(b);
  if(ra.length!==1||rb.length!==1)return {available:false,reason:'Select one root in each rollout to align branch positions.'};
  const forward=new Map(),reverse=new Set(),ignored=[];
  for(const pair of pairs){if(!Array.isArray(pair)||pair.length!==2)continue;const [x,y]=pair;if(!a.visible.has(x)||!b.visible.has(y)||forward.has(x)||reverse.has(y)){ignored.push(pair);continue;}forward.set(x,y);reverse.add(y);}
  const groups=[],used=new Set();let slots=0;
  function visit(x,y,parent=null){
   const g={id:groups.length,a:x,b:y,parent,start:slots,children:[]};groups.push(g);
   const ac=x?a.children.get(x):[],bc=y?b.children.get(y):[],remaining=new Set(bc);
   for(const child of ac){const match=forward.get(child),paired=remaining.has(match)?match:null;if(paired){remaining.delete(paired);used.add(child);}g.children.push(visit(child,paired,g.id).id);}
   for(const child of bc)if(remaining.has(child))g.children.push(visit(null,child,g.id).id);
   if(!g.children.length)slots++;g.end=slots;return g;
  }
  visit(ra[0],rb[0]);
  for(const [x,y]of forward)if(!used.has(x)&&x!==ra[0])ignored.push([x,y]);
  const tiles={A:[],B:[]},depthA=new Map(a.tiles.map(t=>[t.id,t.depth])),depthB=new Map(b.tiles.map(t=>[t.id,t.depth]));
  for(const g of groups)for(const [side,id,m,depth]of [['A',g.a,a,depthA],['B',g.b,b,depthB]])if(id)tiles[side].push({id,node:m.nodes.get(id),start:g.start/slots,span:(g.end-g.start)/slots,depth:depth.get(id),group:g.id});
  return {available:true,groups,tiles,slots,ignored,matched:groups.filter(g=>g.a&&g.b).length-1};
 }
 const PALETTE={objective:'#e8eef9',plan:'#e8eef9',native_goal:'#e8eef9',subgoal:'#fbf1cc',plan_step:'#fbf1cc',declared_item:'#fbf1cc',task_list:'#fbf1cc',approach:'#f9dced',action:'#ccecee',operation:'#ccecee',check:'#d8f0df',revision:'#fbdcc5',assessment:'#eee4f7',feedback:'#e9edf3',decision:'#f9dced',reported_failed:'#fae0df',reported_complete:'#d8f0df'};
 function color(node){return PALETTE[node.kind==='outline_item'?node.work_kind:node.kind]||'#edf0f5';}
 function render(host,data,focus,inspect){
  const make=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  const button=(label,fn,cls='cs-text-button')=>{const b=make('button',label,cls);b.type='button';b.onclick=fn;return b;};
  const saved=new URL(location.href).searchParams;
  let selected=saved.get('plan_branch')||focus,reference=null,referenceRoot=saved.get('plan_compare_root')||'all',referenceFocus=saved.get('plan_compare_branch')||'all',pairs=[],active=null,ticket=0,disposed=false,offset=0,expanded=false;
  let eventSelection=saved.has('plan_event')?{side:saved.get('plan_event_side')||'A',id:saved.get('plan_event'),episode:saved.get('plan_episode')}:null;
  try{const p=JSON.parse(saved.get('plan_alignment')||'[]');if(Array.isArray(p))pairs=p;}catch{}
  function remember(){const u=new URL(location.href);u.searchParams.set('graph',data.graph_id);u.searchParams.set('plan_branch',selected);if(reference){u.searchParams.set('plan_compare',reference.graph_id);u.searchParams.set('plan_compare_branch',referenceFocus);u.searchParams.set('plan_compare_root',referenceRoot);if(pairs.length)u.searchParams.set('plan_alignment',JSON.stringify(pairs));else u.searchParams.delete('plan_alignment');}else for(const k of ['plan_compare','plan_compare_branch','plan_compare_root','plan_alignment'])u.searchParams.delete(k);const picked=active?{side:active.view.side,id:active.event.id,episode:active.episode?.id}:eventSelection;if(picked){u.searchParams.set('plan_event',picked.id);u.searchParams.set('plan_event_side',picked.side);if(picked.episode)u.searchParams.set('plan_episode',picked.episode);else u.searchParams.delete('plan_episode');}else for(const k of ['plan_event','plan_event_side','plan_episode'])u.searchParams.delete(k);history.replaceState(null,'',u);}
  host.replaceChildren();host.classList.add('cs-workspace');
  const toolbar=make('div',null,'cs-toolbar'),heading=make('div');heading.append(make('h3','Structure & flow'),make('p','Select work, then inspect an action, check or revision.','cs-caption'));toolbar.append(heading);
  const controls=make('div',null,'cs-controls'),compare=make('details',null,'cs-compare');compare.append(make('summary','Compare rollout'));
  const compareBody=make('div',null,'cs-compare-body'),search=make('input'),picker=make('select'),status=make('small');search.type='search';search.placeholder='Find rollout…';search.setAttribute('aria-label','Find comparison rollout');picker.setAttribute('aria-label','Comparison rollout');compareBody.append(search,picker,status);compare.append(compareBody);controls.append(compare);toolbar.append(controls);host.append(toolbar);
  const board=make('div',null,'cs-board'),detail=make('section',null,'cs-inline-evidence');detail.hidden=true;detail.setAttribute('aria-label','Selected flow evidence');host.append(board,detail);let catalog=[];
  function choices(){picker.replaceChildren();const none=make('option','Choose a saved rollout');none.value='';picker.append(none);const matches=catalog.filter(g=>JSON.stringify([g.metadata,g.run_id,g.observer,g.observer_label]).toLowerCase().includes(search.value.toLowerCase()));for(const g of matches.slice(0,150)){const option=make('option',`${root.ChoiceLabels?.rollout(g)||g.run_id} · ${root.ChoiceLabels?.name(g.observer,g.observer_label)||g.observer}`);option.value=g.id;picker.append(option);}if(reference)picker.value=reference.graph_id;}
  compare.addEventListener('toggle',async()=>{if(!compare.open||catalog.length)return;status.textContent='Loading saved rollouts…';try{const response=await fetch('/api/graphs');if(!response.ok)throw Error('Could not load saved rollouts');const result=await response.json();if(disposed)return;catalog=result.graphs.filter(g=>g.id!==data.graph_id);choices();status.textContent='Choose a rollout, then align corresponding work.';}catch(error){status.textContent=error.message;}});
  search.oninput=choices;
  async function loadReference(id,restoring=false){const current=++ticket;status.textContent='Loading structure…';try{const response=await fetch('/api/work-hierarchy?'+new URLSearchParams({graph:id})),result=await response.json();if(!response.ok)throw Error(result.error||'Comparison unavailable');if(current!==ticket||disposed)return;reference=result;if(!restoring){referenceFocus='all';referenceRoot='all';pairs=[];eventSelection=null;}if(referenceRoot==='all'&&result.roots.length>1)referenceRoot=result.roots.includes(referenceFocus)?referenceFocus:result.roots.at(-1);if(referenceRoot!=='all'&&!result.roots.includes(referenceRoot))referenceRoot='all';
    // Identical source units in two snapshots of one rollout can share slots.
    if(!pairs.length&&data.run_id===result.run_id){const aa=model(data,focus),bb=model(result,referenceRoot);pairs=[...aa.visible].filter(id=>bb.visible.has(id)).map(id=>[id,id]);}
    active=null;offset=0;status.textContent='Loaded';compare.open=false;draw();}catch(error){if(current===ticket&&!disposed){status.textContent=error.message;compare.open=true;}}}
  function removeReference(){ticket++;reference=null;pairs=[];active=null;eventSelection=null;if(selected===UNMATCHED)selected='all';picker.value='';draw();}
  picker.onchange=()=>picker.value?loadReference(picker.value):removeReference();
  function source(node,view){if(view.side==='A')return inspect(node);const dialog=make('dialog',null,'ph-detail ph-dialog');dialog.setAttribute('aria-label','Reference source evidence');dialog.append(make('h3',node.label),button('Close',()=>dialog.close()),make('pre',node.source_text||node.evidence?.[0]?.text||node.label));const a=make('a','Open reference rollout ↗');a.href='/semantic-map?'+new URLSearchParams({run:view.current.run_id,graph:view.current.graph_id,level:'plans',plan_view:'compact'});dialog.append(a);dialog.addEventListener('close',()=>dialog.remove(),{once:true});host.append(dialog);dialog.showModal();}
  function openEvent(event,view){const episode=view.seq.episodes.find(e=>e.declaration_id===event.id||e.stages.some(s=>s.label==='Replacement statement'&&s.node_ids.includes(event.id)));active={view,event,episode};eventSelection={side:view.side,id:event.id,episode:episode?.id};remember();drawEvidence();host.querySelectorAll('.cs-event').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.event===view.side+':'+event.id)));detail.scrollIntoView({block:'nearest',behavior:'smooth'});}
  function drawEvidence(){detail.replaceChildren();detail.hidden=!active;if(!active)return;const {view,event,episode}=active;const top=make('div',null,'cs-evidence-heading');top.append(make('strong',`${view.side} · Record ${event.event_index+1} · ${episode?'Revision':EVENT_TYPES[event.eventType]?.[0]||'Source evidence'}`),button('Close',()=>{active=null;eventSelection=null;remember();drawEvidence();}));detail.append(top);
   if(episode){const byId=new Map(view.current.nodes.map(n=>[n.id,n]));const scopes=view.seq.episodes.filter(e=>e.declaration_id===episode.declaration_id);if(scopes.length>1){const alternatives=make('div',null,'cs-revision-scopes');alternatives.append(make('small','This change is linked to more than one earlier attempt:'));for(const e of scopes){const n=byId.get(e.previous_id),b=button(short(n?.label||'Earlier work',100),()=>{active.episode=e;remember();drawEvidence();});b.setAttribute('aria-pressed',String(e.id===episode.id));alternatives.append(b);}detail.append(alternatives);}appendEpisode(detail,episode,byId,n=>source(n,view));const track=make('a','Track revisions across training →','cs-text-button');track.href='/monitors?'+new URLSearchParams({preset:'self-revision',experiment:view.current.metadata?.experiment||'',observer:view.current.observer||''})+'#monitor-presets';detail.append(track);}
   else{detail.append(make('p',event.label),button('Inspect source record →',()=>source(event,view)));const related=view.seq.episodes.filter(e=>e.node_ids.includes(event.id));for(const e of related){const n=view.current.nodes.find(n=>n.id===e.declaration_id);detail.append(button('Follow linked revision →',()=>openEvent({...n,eventType:'revision'},view)));}}
  }
  function draw(){
   board.replaceChildren();controls.querySelector('.cs-align')?.remove();compareBody.querySelector('.cs-reference-root')?.remove();const views=[];if(reference&&reference.roots.length>1){const label=make('label','Reference work root','cs-reference-root'),choice=make('select');choice.setAttribute('aria-label','Reference work root');for(const id of reference.roots){const o=make('option',reference.nodes.find(n=>n.id===id)?.label||id);o.value=id;choice.append(o);}choice.value=referenceRoot;choice.onchange=()=>{referenceRoot=choice.value;referenceFocus='all';active=null;draw();};label.append(choice);compareBody.append(label);}
   for(const [side,current,scope]of [['A',data,selected],...(reference?[['B',reference,referenceFocus]]:[])]){try{const structure=model(current,side==='A'?focus:referenceRoot);let chosen=scope===UNMATCHED?UNMATCHED:scope!=='all'&&structure.visible.has(scope)?scope:'all';const roots=structure.tiles.filter(t=>t.depth===0);if(chosen==='all'&&roots.length===1)chosen=roots[0].id;if(side==='A')selected=chosen;else referenceFocus=chosen;views.push({side,current,scope:chosen,structure,seq:sequence(current,structure,chosen)});}catch(error){board.append(make('p',error.message,'cs-caption'));}}
   if(!views.length)return;if(active)eventSelection={side:active.view.side,id:active.event.id,episode:active.episode?.id};active=null;if(eventSelection){const view=views.find(v=>v.side===eventSelection.side),event=view?.seq.events.find(e=>e.id===eventSelection.id);if(event){const episodes=view.seq.episodes.filter(e=>e.declaration_id===event.id||e.stages.some(s=>s.label==='Replacement statement'&&s.node_ids.includes(event.id)));active={view,event,episode:episodes.find(e=>e.id===eventSelection.episode)||episodes[0]};}else if(view)eventSelection=null;}remember();
   let aligned=views.length===2?alignment(views[0].structure,views[1].structure,pairs):null;
   if(aligned?.available){const align=make('details',null,'cs-align');align.append(make('summary',`Align branches · ${aligned.matched}`));const box=make('div',null,'cs-align-body');box.append(make('p','Confirm work that corresponds. Unmatched does not mean absent.','cs-caption'));
    const aa=make('select'),bb=make('select');aa.setAttribute('aria-label','Current branch to align');bb.setAttribute('aria-label','Reference branch to align');for(const [select,view]of [[aa,views[0]],[bb,views[1]]])for(const t of view.structure.tiles){if(t.alias||!t.depth)continue;const o=make('option','  '.repeat(t.depth)+t.node.label);o.value=t.id;select.append(o);}box.append(make('small','A · Current work'),aa,make('small','B · Reference work'),bb,button('Align selected branches',()=>{pairs=pairs.filter(([a,b])=>a!==aa.value&&b!==bb.value);pairs.push([aa.value,bb.value]);draw();}));
    const candidates=[];for(const g of aligned.groups.filter(g=>g.a&&g.b)){const ac=views[0].structure.children.get(g.a),bc=views[1].structure.children.get(g.b);for(const id of ac){const n=views[0].structure.nodes.get(id),matches=bc.filter(j=>views[1].structure.nodes.get(j).label===n.label);if(matches.length===1&&!pairs.some(([a,b])=>a===id||b===matches[0]))candidates.push([id,matches[0]]);}}
    if(candidates.length){box.append(make('p',`${candidates.length} same-name candidates. Review before using:`, 'cs-caption'));for(const [a,b]of candidates)box.append(make('span',views[0].structure.nodes.get(a).label,'cs-match-candidate'));box.append(button('Confirm these matches',()=>{pairs.push(...candidates);draw();}));}
    if(pairs.length)box.append(button('Clear alignment',()=>{pairs=[];draw();}));if(aligned.ignored.length)box.append(make('p','Pairs outside this root or under different parents remain separate. Align the parents first.','cs-caption'));align.append(box);controls.prepend(align);}
   const legend=make('div',null,'cs-legend');for(const [key,label]of [['objective','Objective / plan'],['subgoal','Subgoal'],['approach','Approach'],['action','Action'],['check','Check'],['revision','Revision']]){const item=make('span',label);item.style.setProperty('--cs-fill',PALETTE[key]);legend.append(item);}board.append(legend);
   const identities=make('div',null,'cs-identities');for(const v of views){const row=make('div',null,'cs-identity');row.title=`${v.current.observer_label||v.current.observer||'Saved observations'} · ${v.current.graph_id}`;row.append(make('strong',v.side),make('span',short(root.ChoiceLabels?.rollout(v.current)||v.current.run_id,95)),make('small',`${v.structure.leaves} terminal branches · depth ${v.structure.depth} · breadth ${v.structure.breadth}${Number.isInteger(v.current.cutoff_event_index)?' · through record '+(v.current.cutoff_event_index+1):''}`));if(v.side==='B')row.append(button('Remove comparison',removeReference));identities.append(row);}board.append(identities);if(reference&&reference.run_id===data.run_id)board.append(make('p','Same rollout · comparing saved observations, not two model strategies.','cs-caption'));
   const scroll=make('div',null,'cs-map-scroll');scroll.tabIndex=0;scroll.setAttribute('aria-label','Compact work structure');const sheet=make('div',null,'cs-sheet');sheet.style.minWidth=Math.max(480,Math.min(2600,(aligned?.slots||Math.max(...views.map(v=>v.structure.leaves)))*68))+'px';
   const maxDepth=Math.max(...views.map(v=>v.structure.depth));
   for(let depth=0;depth<=maxDepth;depth++){const band=make('div',null,'cs-depth-band');for(const v of views){const line=make('div',null,'cs-level'),label=make('span',`${depth}${views.length>1?v.side:''}`,'cs-depth-label'),track=make('div',null,'cs-track');line.append(label,track);
     const tiles=aligned?.available?aligned.tiles[v.side]:v.structure.tiles;
     if(aligned?.available)for(const g of aligned.groups){const id=v.side==='A'?g.a:g.b,other=v.side==='A'?g.b:g.a,otherTiles=aligned.tiles[v.side==='A'?'B':'A'];if(id||!other)continue;const t=otherTiles.find(t=>t.id===other);if(t.depth!==depth)continue;const ghost=make('span',null,'cs-unmatched');ghost.style.left=t.start*100+'%';ghost.style.width=`calc(${t.span*100}% - 3px)`;ghost.title='Unmatched work · correspondence not established';track.append(ghost);}
     for(const t of tiles.filter(t=>t.depth===depth)){const b=button((t.alias?'↗ ':'')+t.node.label,()=>{offset=0;expanded=false;active=null;eventSelection=null;const next=pairedFocus(v.side,t.id,aligned);if(next.A)selected=next.A;if(next.B)referenceFocus=next.B;draw();},'cs-tile');b.style.setProperty('--cs-fill',color(t.node));b.style.left=t.start*100+'%';b.style.width=`calc(${t.span*100}% - 3px)`;b.setAttribute('aria-pressed',String(t.id===v.scope));b.setAttribute('aria-label',`${v.side} depth ${depth} · ${t.node.label}`);b.title=t.node.label+(t.alias?' · shared parent reference':'');track.append(b);}band.append(line);}sheet.append(band);}scroll.append(sheet);board.append(scroll);
   board.append(make('p',aligned?.available?'Shared positions for confirmed pairs · hatched = unmatched · depth at left · width represents branch partitions, not time.':aligned?.reason||'Depth at left · width preserves branch partitions · shared-parent references retain every link.','cs-caption'));
   const path=make('nav',null,'cs-path');path.setAttribute('aria-label','Selected work');path.append(button('All work',()=>{selected='all';referenceFocus='all';active=null;eventSelection=null;offset=0;draw();}));for(const v of views)if(v.scope===UNMATCHED){path.append(make('span',`${v.side} · No matched branch`));}else if(v.scope!=='all'){path.append(make('span','›'),button(`${views.length>1?v.side+' · ':''}${v.structure.nodes.get(v.scope).label}`,()=>source(v.structure.nodes.get(v.scope),v)));}board.append(path);
   const facts=make('div',null,'cs-flow-facts');for(const v of views){if(v.scope===UNMATCHED){facts.append(make('p',`${v.side} · Correspondence not selected. Align a branch to compare this work.`));continue;}const checks=root.RevisionImpact.checkRows(v.seq.episodes),count=status=>checks.filter(c=>c.status===status).length;facts.append(make('p',`${v.side} · ${v.seq.actions} dispatches · ${v.seq.episodes.length} linked revisions · ${v.seq.measured?`${v.seq.failed} failed / ${v.seq.measured} measured · ${Math.max(0,v.seq.actions-v.seq.measured)} outcomes unknown`:'operation outcomes unmeasured'}${checks.length?` · checks: ${count('gain')} improved / ${count('harm')} regressed / ${count('unknown')} unresolved`:' · task-quality checks not captured'}`));}board.append(facts);
   drawMatrix(views,aligned);drawEvidence();
   for(const v of views){const links=v.structure.links.filter(e=>!['contains','part_of'].includes(e.type)&&v.structure.visible.has(e.source)&&v.structure.visible.has(e.target));if(!links.length)continue;const more=make('details',null,'cs-relations');more.append(make('summary',`${v.side} · ${links.length} cross-branch relationships`));for(const e of links)more.append(button(`${v.structure.nodes.get(e.source).label} · ${e.label||e.type.replaceAll('_',' ')} → ${v.structure.nodes.get(e.target).label}`,()=>source(v.structure.nodes.get(e.source),v)));board.append(more);}
  }
  function drawMatrix(views,aligned){
   const groups=[],seen=new Set();
   for(const v of views)for(const row of v.seq.rows){if(!row.ids.size)continue;const g=aligned?.groups.find(g=>g[v.side==='A'?'a':'b']===row.id),key=row.id==null?'context':g?'g'+g.id:v.side+':'+row.id;
    let group=groups.find(x=>x.key===key);if(!group){group={key,label:row.id==null?'Linked revision context':row.label,rows:{}};groups.push(group);}group.rows[v.side]=row;seen.add(key);}
   const maxColumns=Math.max(0,...views.map(v=>v.seq.columns.length)),limit=expanded?groups.length:12;offset=Math.min(offset,Math.max(0,maxColumns-1));const end=Math.min(offset+48,maxColumns);
   const caption=make('div',null,'cs-matrix-heading');caption.append(make('strong','Recorded event order →'),make('small','Each rollout keeps its own order. Aligned columns do not imply matched events or elapsed time.'));board.append(caption);
   if(maxColumns>48){const paging=make('div',null,'cs-paging'),prev=button('← Earlier',()=>{offset=Math.max(0,offset-48);draw();}),next=button('Later →',()=>{offset+=48;draw();});prev.disabled=offset===0;next.disabled=end>=maxColumns;paging.append(prev,make('small',`${offset+1}–${end} of ${maxColumns} visible record positions`),next);board.append(paging);}
   const scroller=make('div',null,'cs-matrix-scroll');scroller.tabIndex=0;scroller.setAttribute('aria-label','Work sequence matrix');const table=make('table',null,'cs-matrix'),body=make('tbody');table.append(body);
   const axis=make('tr',null,'cs-axis');axis.append(make('th','Work'),make('th',''));for(let i=offset;i<end;i++)axis.append(make('th',String(i+1)));body.append(axis);
   for(const group of groups.slice(0,limit))for(const [vi,v]of views.entries()){const row=group.rows[v.side],tr=make('tr',null,vi===views.length-1?'cs-group-end':'');if(!vi){const h=make('th',group.label,'cs-row-label');h.rowSpan=views.length;h.scope='rowgroup';tr.append(h);}tr.append(make('th',v.side,'cs-side'));
     if(!row){const td=make('td','Unmatched work','cs-matrix-unmatched');td.colSpan=Math.max(1,end-offset);tr.append(td);}else for(let i=offset;i<end;i++){const cell=make('td'),record=v.seq.columns[i];for(const event of v.seq.events.filter(e=>e.event_index===record&&row.ids.has(e.id))){const type=event.eventType,name=EVENT_TYPES[type]?.[0]||type,glyph=event.outcome==='failed'?'×':event.outcome==='completed'?'✓':({revision:'R',assessment:'?',decision:'+',feedback:'·',action:'A',check:'C',operation:'A',reported_failed:'!',reported_complete:'✓'}[type]||'·');const b=button(glyph,()=>openEvent(event,v),'cs-event');b.dataset.event=v.side+':'+event.id;b.setAttribute('aria-pressed',String(active?.view.side===v.side&&active?.event.id===event.id));b.style.setProperty('--cs-fill',PALETTE[type]||'#e9edf3');b.setAttribute('aria-label',`${v.side} record ${record+1} · ${name} · ${event.label}`);b.title=`${v.side} · record ${record+1} · ${name}: ${event.label}${event.outcome?' · '+event.outcome+' operation':''}`;cell.append(b);}tr.append(cell);}body.append(tr);}
   scroller.append(table);board.append(scroller);if(groups.length>limit)board.append(button(`Show ${groups.length-limit} more work rows`,()=>{expanded=true;draw();}));if(!groups.length)board.append(make('p','No execution records linked to this branch.','cs-caption'));
   const note=make('p','A action · C check · × failed operation · ✓ completed operation · ? assessment · R revision. Select R to inspect the change and its consequences.','cs-caption');board.append(note);
  }
  draw();if(active)requestAnimationFrame(()=>{if(!disposed)detail.scrollIntoView({block:'nearest'});});if(saved.get('plan_compare'))loadReference(saved.get('plan_compare'),true);return ()=>{disposed=true;ticket++;host.querySelectorAll('dialog').forEach(d=>d.close());};
 }
 function appendEpisode(host,episode,byId,inspect){
  const make=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
  const declaration=byId.get(episode.declaration_id);if(declaration)host.append(make('p',declaration.label,'cs-change-statement'));
  const dimensions=make('dl',null,'cs-dimensions');
  for(const [key,label]of [['trigger','Trigger'],['target','Revision target'],['follow_through','Follow-through'],['consequence','Observed consequence']]){
   const field=episode.dimensions?.[key],item=make('div');item.append(make('dt',label));const reading=make('dd');
   if(field?.node_ids?.some(id=>byId.has(id))){const b=make('button',field.label);b.type='button';b.onclick=()=>inspect(byId.get(field.node_ids.find(id=>byId.has(id))));reading.append(b);}else reading.textContent=field?.label||'Not established';
   if(field?.basis==='saved_relationship')reading.append(make('small','Saved annotation'));item.append(reading);dimensions.append(item);
  }host.append(dimensions);
  root.RevisionImpact.detail(host,episode,ids=>{const available=ids.map(id=>byId.get(id)).filter(Boolean);if(available.length)inspect(available.at(-1));},{showTags:false});const chain=make('details',null,'cs-chain-details');chain.append(make('summary','Inspect the evidence chain'));const list=make('ol',null,'cs-evidence-chain');
  for(const stage of episode.stages){const li=make('li');li.append(make('strong',stage.label));if(!stage.node_ids.length)li.append(make('span','Not linked in saved evidence','ph-note'));for(const id of stage.node_ids){const n=byId.get(id);if(!n)continue;const b=make('button',`Record ${n.event_index+1} · ${short(n.label,160)}`,'ph-source');b.type='button';b.onclick=()=>inspect(n);li.append(b);}list.append(li);}chain.append(list);host.append(chain);
  chain.append(make('p',episode.impact?.limits||episode.limits,'ph-note'));
 }
 const api={model,sequence,alignment,render,appendEpisode,UNMATCHED,syncSelection,clearSelection,pairedFocus};if(typeof module==='object')module.exports=api;else root.CompactStructure=api;
})(typeof window==='object'?window:globalThis);
