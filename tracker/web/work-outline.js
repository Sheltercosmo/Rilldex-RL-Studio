/* Work relationships are reviewed evidence, never inferred from the layout. */
((root,factory)=>{const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.WorkOutline=api;})(typeof window==='undefined'?globalThis:window,()=>{
 const names={part_of:'Part of',alternative_to:'Alternative to',depends_on:'Depends on',replaces:'Replaces'};
 function model(data){
  const byId=new Map(data.items.map(n=>[n.id,n])),children=new Map(),parents=new Map();
  for(const e of data.links.filter(e=>e.type==='part_of')){if(!children.has(e.target))children.set(e.target,[]);children.get(e.target).push(e.source);if(!parents.has(e.source))parents.set(e.source,[]);parents.get(e.source).push(e.target);}
  function path(root,target){const queue=[[root]],seen=new Set();while(queue.length){const p=queue.shift(),k=p.at(-1);if(k===target)return p;if(seen.has(k))continue;seen.add(k);for(const n of children.get(k)||[])queue.push([...p,n]);}return null;}
  return {byId,children,parents,path,connections:id=>data.links.filter(e=>e.type!=='part_of'&&(e.source===id||e.target===id))};
 }
 // A shared work item is expanded once. Other parentage stays an explicit reference.
 function overview(m,rootId,collapsed=new Set()){
  const seen=new Set();
  function visit(id){const shared=seen.has(id);seen.add(id);return {id,shared,children:shared||collapsed.has(id)?[]:(m.children.get(id)||[]).map(visit)};}
  return visit(rootId);
 }
 function decisionHistory(data,ids){
  return data.items.filter(n=>ids.has(n.id)).flatMap(n=>(n.decisions||[]).map(d=>({...d,item_id:n.id,label:n.label})))
   .sort((a,b)=>a.event_index-b.event_index||a.evidence.end-b.evidence.end||a.id.localeCompare(b.id));
 }
 function decisionWindowText(value){
  if(!value)return '';
  const reasons={execution_unmapped:'Execution is not mapped to this work item.',conflicting_statements:'Overlapping statements conflict; execution is not attributed to either statement.',order_unresolved:'Statement order is unresolved; execution is not attributed to this window.'};
  if(value.status!=='mapped')return reasons[value.status]||'Execution evidence is unavailable.';
  const c=value.counts;
  const count=(n,label)=>`${n} ${label}${n===1?'':'s'}`;
  return c.actions?`${count(c.attempts,'attempt')} · ${count(c.preparations,'preparation')} · ${count(c.checks,'check')} · ${c.with_assessment}/${c.actions} actions with assessed feedback`:'No linked action in this window; this does not establish that the work was ignored.';
 }
 function decisionWindowBoundary(value){
  if(!value)return '';
  return value.window.boundary==='next_statement'?`After this statement, before the next statement at record ${value.window.end_event_index+1}.`:`After this statement, through record ${value.window.end_event_index+1}. Window remains open at this observation cutoff.`;
 }
 const decisionNames={introduced:'Introduced',requested:'Requested',pursue:'Chosen for work',defer:'Deferred',stop:'Stopped',resume:'Resumed',reported_complete:'Reported complete',reported_failed:'Reported failed'};
 const decisionSymbols={introduced:'○',requested:'◇',pursue:'▶',defer:'Ⅱ',stop:'■',resume:'↻',reported_complete:'✓',reported_failed:'×'};
 // Rows follow reviewed parentage; positions use source-record indices only.
 // Close events share a button instead of overlapping or losing a statement.
 function workTimeline(data,rootId,collapsed=new Set()){
  const m=model(data),rows=[],seen=new Set();
  function visit(entry,depth){
   if(seen.has(entry.id))return;seen.add(entry.id);
   const item=m.byId.get(entry.id),intro={id:item.id+':intro',type:item.source_actor==='user'?'requested':'introduced',event_index:item.event_index,evidence:item.evidence[0]},
    sameQuote=point=>['event_id','start','end','text'].every(key=>point.evidence[key]===intro.evidence[key]),
    decisions=(item.decisions||[]).map(point=>({...point,introduces:sameQuote(point)})),
    points=[...(decisions.some(point=>point.introduces)?[]:[intro]),...decisions].map(point=>({...point,item_id:item.id,label:item.label})).sort((a,b)=>a.event_index-b.event_index||a.evidence.end-b.evidence.end||a.id.localeCompare(b.id));
   rows.push({item,depth,points,childCount:(m.children.get(entry.id)||[]).length});
   for(const child of entry.children)visit(child,depth+1);
  }
  visit(overview(m,rootId,collapsed),0);
  const end=Math.max(0,data.cutoff_event_index??0,...rows.flatMap(row=>row.points.map(p=>p.event_index)));
  return {rows,start:0,end,recordCount:end+1};
 }
 function markerGroups(points,end,minGap=5){
  const groups=[];
  for(const point of points){const position=end?point.event_index/end*100:0,last=groups.at(-1);
   if(last&&position-last.position<minGap)last.points.push(point);else groups.push({position,points:[point]});
  }
  return groups;
 }
 function clear(){if(typeof window!=='undefined')window.WorkCanvas?.clear();}
 function render(host,data,rootId,inspect,openPlan,plans,onFocus,onView){
  const m=model(data),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  const params=new URL(location.href).searchParams,saved=params.get('outline_focus');let focus=m.path(rootId,saved)?saved:rootId;
  let view=params.get('outline_view')||(focus===rootId?'overview':'focus');if(!['overview','focus','timeline'].includes(view))view='overview';
  const timelineCollapsed=new Set();let includeUndecided=false;
  const shell=el('section',null,'wo-shell');shell.setAttribute('aria-label','Work outline');host.append(shell);let disposeCanvas=()=>{};
  function saveView(value){view=value;if(onView)onView(value);else{const u=new URL(location.href);u.searchParams.set('outline_view',value);history.replaceState(null,'',u);}}
  function go(id){focus=id;if(onFocus)onFocus(id);else{const u=new URL(location.href);u.searchParams.set('outline_focus',id);history.replaceState(null,'',u);}if(view!=='timeline')saveView('focus');}
  function timeline(active){
   const value=workTimeline(data,active,timelineCollapsed),panel=el('section',null,'wo-journey');panel.setAttribute('aria-label','Work timeline');
   const intro=el('div',null,'wo-journey-intro');intro.append(el('h4','When the work changed'),el('p','Each row is one work item. Markers show source statements; space between them is not proof of continued work.','wo-note'));panel.append(intro);
   const decided=value.rows.filter(row=>row.item.decisions?.length),rows=includeUndecided||!decided.length?value.rows:decided;
   if(decided.length&&decided.length<value.rows.length){const label=el('label',null,'wo-journey-filter'),check=el('input');check.type='checkbox';check.checked=includeUndecided;check.onchange=()=>{includeUndecided=check.checked;draw();};label.append(check,el('span','Include items without annotated decisions'));panel.append(label);}
   const legend=el('div',null,'wo-journey-legend'),types=new Set(rows.flatMap(row=>row.points.map(p=>p.type)));
   for(const type of Object.keys(decisionNames).filter(type=>types.has(type))){const key=el('span',null,'wo-key');key.append(el('b',decisionSymbols[type],'wo-marker-symbol wo-mark-'+type),el('span',decisionNames[type]));legend.append(key);}panel.append(legend);
   const scroll=el('div',null,'wo-journey-scroll');scroll.tabIndex=0;scroll.setAttribute('role','region');scroll.setAttribute('aria-label','Work timeline chart; scroll horizontally on small screens');
   const chart=el('div',null,'wo-journey-chart'),axis=el('div',null,'wo-journey-axis'),scale=el('div',null,'wo-journey-scale');axis.append(el('span','Work item / latest statement'));
   for(const index of [...new Set([0,Math.round(value.end*.25),Math.round(value.end*.5),Math.round(value.end*.75),value.end])]){const tick=el('span',String(index+1));tick.style.left=(value.end?index/value.end*100:0)+'%';tick.title='Source record '+(index+1);scale.append(tick);}axis.append(scale);chart.append(axis);
   const readout=el('section',null,'wo-journey-readout');readout.hidden=true;readout.setAttribute('aria-label','Timeline statement');readout.setAttribute('aria-live','polite');
   function show(group,item,button){
    for(const b of chart.querySelectorAll('.wo-time-marker'))b.setAttribute('aria-pressed',String(b===button));readout.replaceChildren();readout.hidden=false;
    const close=el('button','Close','wo-readout-close');close.onclick=()=>{readout.hidden=true;shell.onkeydown=null;button.setAttribute('aria-pressed','false');button.focus({preventScroll:true});};shell.onkeydown=e=>{if(e.key==='Escape')close.click();};readout.append(close,el('h4',item.label));
    for(const point of group.points){const row=el('div',null,'wo-statement'),detail=el('button','Open source details');detail.onclick=()=>{readout.hidden=true;inspect({id:point.id,label:item.label,state:decisionNames[point.type],evidence:[point.evidence],source_node_ids:['event:'+point.evidence.event_id]});};row.append(el('small','Record '+(point.event_index+1)+' · '+decisionNames[point.type]+(point.introduces?' · first appearance':'')),el('blockquote',point.evidence.text));if(point.followthrough)row.append(el('p',decisionWindowText(point.followthrough)),el('small',decisionWindowBoundary(point.followthrough)));row.append(detail);readout.append(row);}
   }
   for(const row of rows){
    const track=el('div',null,'wo-journey-row'),label=el('div',null,'wo-journey-label');track.dataset.workId=row.item.id;label.style.setProperty('--depth',String(row.depth));
    const title=el('button',row.item.label,'wo-journey-name');title.onclick=()=>inspect(row.item);label.append(title,el('small',row.item.state));
    if(row.childCount&&(includeUndecided||!decided.length)){const toggle=el('button',(timelineCollapsed.has(row.item.id)?'＋':'−')+' '+row.childCount+' nested','wo-time-toggle');toggle.setAttribute('aria-expanded',String(!timelineCollapsed.has(row.item.id)));toggle.setAttribute('aria-label',(timelineCollapsed.has(row.item.id)?'Show':'Hide')+' nested work under '+row.item.label);toggle.onclick=()=>{timelineCollapsed.has(row.item.id)?timelineCollapsed.delete(row.item.id):timelineCollapsed.add(row.item.id);draw();};label.append(toggle);}
    const rail=el('div',null,'wo-journey-rail');
    for(const group of markerGroups(row.points,value.end)){
     const type=group.points.length===1?group.points[0].type:'group',button=el('button',group.points.length===1?decisionSymbols[type]:String(group.points.length),'wo-time-marker wo-mark-'+type);
     button.style.left=group.position+'%';button.setAttribute('aria-pressed','false');const description=group.points.map(p=>'Record '+(p.event_index+1)+' · '+decisionNames[p.type]).join('; ');button.setAttribute('aria-label',row.item.label+' · '+description);button.title=description;button.onclick=()=>show(group,row.item,button);rail.append(button);
    }
    track.append(label,rail);chart.append(track);
   }
   scroll.append(chart);panel.append(scroll,el('p','Source-record position · '+rows.length+' / '+value.rows.length+' work items shown · through record '+value.recordCount+'. Numbered markers contain nearby observations. Select a marker to read its source.','wo-note'),readout);shell.append(panel);return rows;
  }
  function draw(){
   disposeCanvas();shell.onkeydown=null;shell.replaceChildren();const toolbar=el('div',null,'wo-toolbar'),switcher=el('div',null,'wo-view-switch');switcher.setAttribute('role','group');switcher.setAttribute('aria-label','Work outline view');
   for(const [value,label]of [['overview','Mind map'],['timeline','Work timeline']]){const b=el('button',label);b.setAttribute('aria-pressed',String(value==='timeline'?view==='timeline':view!=='timeline'));b.onclick=()=>{saveView(value);draw();};switcher.append(b);}toolbar.append(switcher);shell.append(toolbar);
   if(view==='timeline'){
    const nav=el('nav',null,'wo-breadcrumbs');nav.setAttribute('aria-label','Work outline path');
    for(const id of m.path(rootId,focus)||[rootId]){const b=el('button',id===rootId?'Objective':m.byId.get(id).label);b.onclick=()=>{go(id);draw();};nav.append(b);}shell.append(nav);timeline(focus);
   }else{
    const canvas=WorkCanvas.render(shell,data,rootId,{inspect,openPlan,plans,initialFocus:focus,onFocus:go});disposeCanvas=canvas.dispose;
   }
   const reading=el('details',null,'wo-reading');reading.append(el('summary','Reading this map'),el('p',data.basis==='model_selected'?'Proposed by '+data.selection.producer+' · Selected by Jev. Retrospective interpretation; execution and outcomes are not verified.':'Retrospective review by '+data.revision.author+'. Missing decisions remain unknown.'),el('p','Lines show work hierarchy, not execution order. Depth is hierarchy depth, not a measured exploration horizon. Gray cards require an explicit stop or defer decision. Completion reports are claims; no outcome is inherited from a parent or child.'));
   if(data.revision.note)reading.append(el('p',data.revision.note));shell.append(reading);
  }
  draw();
 }
 function citation(event,text){
  const start=event.text.indexOf(text);if(!text.trim()||start<0||event.text.indexOf(text,start+1)>=0)throw Error('Choose an exact quote that occurs once in the selected source record.');
  return {event_id:event.id,start:[...event.text.slice(0,start)].length,end:[...event.text.slice(0,start+text.length)].length,text};
 }
 async function edit(host,graph){
  host.replaceChildren();host.className='wo-editor';host.setAttribute('aria-label','Work outline editor');
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  try{
   const response=await fetch('/api/work-outline?'+new URLSearchParams({graph:graph.id})),data=await response.json();if(!response.ok)throw Error(data.error||'Could not load the outline');
   const d=data.document,events=graph.nodes.filter(n=>n.kind==='event'&&['agent','user'].includes(n.properties.actor)&&!n.properties.copied_context).sort((a,b)=>a.event_index-b.event_index).map(n=>({...n.properties,index:n.event_index}));
   let readers=[];
   const label=(text,control)=>{const l=el('label');l.append(el('span',text),control);return l;};
   function input(value,name){const n=el('input');n.value=value||'';n.setAttribute('aria-label',name);return n;}
   function select(values,value,name){const n=el('select');n.setAttribute('aria-label',name);for(const [v,t]of values){const o=el('option',t);o.value=v;n.append(o);}n.value=value||values[0]?.[0]||'';return n;}
   function read(strict=false){for(const r of readers)r(strict);}
   function source(container,ref,name){const choice=select(events.map(e=>[e.id,`Record ${e.index+1} · ${e.actor} · ${e.text.slice(0,65)}`]),ref?.event_id,'Source record for '+name),quote=el('textarea');quote.rows=3;quote.setAttribute('aria-label','Exact source quote for '+name);quote.value=ref?.text||'';const preview=el('details'),pre=el('pre');preview.append(el('summary','Read source record'),pre);function previewSource(){pre.textContent=events.find(e=>e.id===choice.value)?.text||'';}previewSource();choice.onchange=previewSource;container.append(label('Source record',choice),label('Exact supporting quote',quote),preview);return strict=>strict?citation(events.find(e=>e.id===choice.value),quote.value):{event_id:choice.value,start:0,end:0,text:quote.value};}
   function draw(){host.replaceChildren();readers=[];host.append(el('h3','Review work outline'),el('p','Create source-linked work items, connect them, and record explicit decisions. Changes create a new graph version; unchanged reviews reuse the saved version. Review uses the full recorded source. No model runs or unit tags change.','wo-note'));
    const status=el('p',null,'wo-editor-status');status.setAttribute('role','status');
    const author=input(d.revision.author,'Review author'),note=input(d.revision.note,'Review rationale');host.append(label('Review author',author),label('Review rationale',note));readers.push(()=>{d.revision={author:author.value,note:note.value};});
    for(const item of d.items){const box=el('details',null,'wo-edit-row'),title=input(item.label,'Target '+item.id),kind=select(data.kinds.map(k=>[k,k]),item.kind,'Kind '+item.id);box.open=!item.evidence;box.append(el('summary',item.label||'New work item'),label('Work target',title),label('Kind',kind));const ref=source(box,item.evidence,item.id);readers.push(strict=>{item.label=title.value;item.kind=kind.value;item.evidence=ref(strict);});const remove=el('button','Remove work item');remove.type='button';remove.onclick=()=>{try{read();d.items=d.items.filter(i=>i!==item);d.links=d.links.filter(e=>e.from!==item.id&&e.to!==item.id);d.decisions=d.decisions.filter(e=>e.item_id!==item.id);if(d.bindings)d.bindings=d.bindings.filter(e=>e.item_id!==item.id);draw();}catch(e){status.textContent=e.message;}};box.append(remove);host.append(box);}
    const add=el('button','Add work item');add.type='button';add.onclick=()=>{try{read();let i=1;while(d.items.some(x=>x.id==='work-'+i))i++;d.items.push({id:'work-'+i,kind:'subgoal',label:'',evidence:null});draw();}catch(e){status.textContent=e.message;}};host.append(add);
    const targets=d.items.map(i=>[i.id,i.label||i.id]);
    for(const [collection,title,types]of [['links','Connections',data.links],['decisions','Branch decisions',data.decisions]]){
     host.append(el('h4',title));d[collection].forEach((row,index)=>{const box=el('details',null,'wo-edit-row'),isLink=collection==='links';box.open=!row.evidence;box.append(el('summary',row.type.replaceAll('_',' ')+' · '+(d.items.find(i=>i.id===(row.from||row.item_id))?.label||'Select work')+(isLink?' → '+(d.items.find(i=>i.id===row.to)?.label||'Select work'):'')));
      const from=select(targets,isLink?row.from:row.item_id,title+' source '+index),kind=select(Object.keys(types).map(k=>[k,k.replaceAll('_',' ')]),row.type,title+' type '+index),to=isLink?select(targets,row.to,title+' target '+index):null;
      box.append(label(isLink?'From work':'Work item',from),label('Relationship',kind));if(to)box.append(label('To work',to));const hint=el('p',types[kind.value],'wo-note');kind.onchange=()=>hint.textContent=types[kind.value];box.append(hint);const ref=source(box,row.evidence,title+' '+index);
      readers.push(strict=>{if(isLink){row.from=from.value;row.to=to.value;}else row.item_id=from.value;row.type=kind.value;row.evidence=ref(strict);});const remove=el('button','Remove '+(isLink?'connection':'decision'));remove.type='button';remove.onclick=()=>{try{read();d[collection].splice(index,1);draw();}catch(e){status.textContent=e.message;}};box.append(remove);host.append(box);
     });const add=el('button','Add '+(collection==='links'?'connection':'branch decision'));add.type='button';add.disabled=!targets.length;add.onclick=()=>{try{read();d[collection].push(collection==='links'?{from:targets[0][0],to:targets.at(-1)[0],type:'part_of',evidence:null}:{item_id:targets[0][0],type:'pursue',evidence:null});draw();}catch(e){status.textContent=e.message;}};host.append(add);
    }
    host.append(el('h4','Execution scope bindings'),el('p',d.schema===data.binding_schema?'Only reviewed bindings supply this version’s execution counts. Match the same work scope and instance; a related prerequisite or shared artifact is insufficient.':'Current execution counts use containing plan citations. Adding reviewed bindings switches this version to explicit scope mapping; include every plan or step you want counted.','wo-note'));
    (d.bindings||[]).forEach((row,index)=>{
     const box=el('details',null,'wo-edit-row');box.open=!row.evidence;box.append(el('summary',(d.items.find(i=>i.id===row.item_id)?.label||'Select work')+' ↔ '+(data.binding_scopes.find(s=>s.id===row.scope_node_id)?.label||'Select plan scope')));
     const work=select([['','Select a work item'],...targets.filter(([id])=>d.items.find(i=>i.id===id)?.kind!=='hypothesis')],row.item_id,'Binding work '+index),scope=select([['','Select an existing plan or step'],...data.binding_scopes.map(s=>[s.id,(s.kind==='plan'?'Plan · ':'Step · ')+s.label])],row.scope_node_id,'Binding scope '+index),note=input(row.note,'Binding rationale '+index);
     box.append(label('Work item',work),label('Same work scope',scope),label('Why these describe the same work',note));
     const ref=source(box,row.evidence,'scope binding '+index);readers.push(strict=>{row.item_id=work.value;row.scope_node_id=scope.value;row.note=note.value;row.evidence=ref(strict);});
     const use=el('button','Use selected plan’s declaration quote');use.type='button';use.onclick=()=>{try{read();const selected=data.binding_scopes.find(s=>s.id===row.scope_node_id);if(!selected)throw Error('Select a plan or step first.');row.evidence=structuredClone(selected.evidence);draw();}catch(e){status.textContent=e.message;}};
     const remove=el('button','Remove scope binding');remove.type='button';remove.onclick=()=>{read();d.bindings.splice(index,1);draw();};box.append(use,remove);host.append(box);
    });
    const addBinding=el('button','Add reviewed scope binding');addBinding.type='button';addBinding.disabled=!targets.length||!data.binding_scopes.length;addBinding.onclick=()=>{read();d.schema=data.binding_schema;d.bindings||=[];d.bindings.push({item_id:'',scope_node_id:'',note:'',evidence:null});draw();};host.append(addBinding);
    const save=el('button','Save reviewed outline');save.type='button';save.onclick=async()=>{try{read(true);save.disabled=true;status.textContent='Saving source-linked review…';const response=await fetch('/api/work-outline',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}),saved=await response.json();if(!response.ok)throw Error(saved.error||'Could not save');const u=new URL(location.href);u.searchParams.set('graph',saved.graph_id);u.searchParams.set('observer',saved.observer);u.searchParams.set('level','plans');for(const key of ['value','plan_step','outline_focus','work_focus','activity_unit','graph_unit'])u.searchParams.delete(key);location.assign(u);}catch(e){status.textContent=e.message;save.disabled=false;}};host.append(el('p','Shared work may have several parent connections. Removing an item here also removes its outline links, bindings and decisions from the new version.','wo-note'),save,status);
   }
   draw();
  }catch(e){host.append(el('p',e.message));}
 }
 return {model,overview,decisionHistory,decisionWindowText,decisionWindowBoundary,workTimeline,markerGroups,render,names,citation,edit,clear};
});
