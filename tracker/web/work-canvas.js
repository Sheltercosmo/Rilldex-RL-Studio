/* Geometry is a view of saved work relationships, never a source of new ones. */
((root,factory)=>{const api=factory(typeof module==='object'&&module.exports?require('./work-outline.js'):root.WorkOutline);if(typeof module==='object'&&module.exports)module.exports=api;else root.WorkCanvas=api;})(typeof window==='undefined'?globalThis:window,(outline)=>{
 const W=264,H=132,GX=70,GY=22;
 const states={
  'No decision recorded':{tone:'unknown',label:'No decision recorded',symbol:'○'},
  'Chosen for work':{tone:'chosen',label:'Chosen for work',symbol:'▸'},
  'Explicitly resumed':{tone:'chosen',label:'Resumed',symbol:'↶'},
  'Explicitly deferred':{tone:'inactive',label:'Deferred',symbol:'Ⅱ'},
  'Explicitly stopped':{tone:'inactive',label:'Stopped',symbol:'■'},
  'Reported complete':{tone:'complete',label:'Reported complete',symbol:'✓'},
  'Reported failed':{tone:'failed',label:'Reported failed',symbol:'×'},
  'Conflicting decisions':{tone:'conflict',label:'Conflicting decisions',symbol:'!'}
 };
 const state=item=>states[item.state]||{tone:'unknown',label:item.state||'State not established',symbol:'○'};
 function descendants(m,id){const seen=new Set(),queue=[id];while(queue.length){const next=queue.shift();if(seen.has(next))continue;seen.add(next);queue.push(...(m.children.get(next)||[]));}seen.delete(id);return seen;}
 function layout(data,rootId,options={}){
  const m=outline.model(data),collapsed=options.collapsed||new Set(),root=outline.overview(m,rootId,collapsed),full=outline.overview(m,rootId),nodes=[],edges=[];
  if(!m.byId.has(rootId))return {nodes,edges,crosslinks:[],bounds:{x:0,y:0,width:W,height:H}};
  const height=n=>Math.max(H,n.children.reduce((sum,c)=>sum+height(c)+GY,0)-GY);
  // Choose sides from the full hierarchy so expanding a branch never changes sides.
  const heights=full.children.map(height),total=heights.reduce((a,b)=>a+b+GY,0);let split=0,best=Infinity,sum=0;
  for(let i=0;i<heights.length-1;i++){sum+=heights[i]+GY;const difference=Math.abs(total-2*sum);if(difference<best){best=difference;split=i+1;}}
  if(options.direction==='right')split=0;
  let serial=0;
  function place(entry,depth,side,cy,parent=null){
   const key='node-'+serial++,item=m.byId.get(entry.id),node={key,id:entry.id,item,parent,depth,side,shared:entry.shared,x:side*depth*(W+GX),y:cy-H/2,width:W,height:H,hiddenCount:collapsed.has(entry.id)&&!entry.shared?descendants(m,entry.id).size:0};nodes.push(node);
   if(parent)edges.push({source:parent,target:key,type:'part_of'});
   let y=cy-height(entry)/2;for(const child of entry.children){const h=height(child);place(child,depth+1,side,y+h/2,key);y+=h+GY;}return node;
  }
  const center=place({...root,children:[]},0,1,0);
  for(const [entries,side] of [[root.children.slice(0,split),-1],[root.children.slice(split),1]]){
   const h=entries.reduce((s,c)=>s+height(c)+GY,0)-GY;let y=-h/2;
   for(const entry of entries){const size=height(entry);place(entry,1,side,y+size/2,center.key);y+=size+GY;}
  }
  const primary=new Map();for(const node of nodes)if(!primary.has(node.id))primary.set(node.id,node);
  const crosslinks=data.links.filter(e=>e.type!=='part_of'&&(primary.has(e.source)||primary.has(e.target))).map(e=>({...e,from:primary.get(e.source)?.key,to:primary.get(e.target)?.key}));
  const minX=Math.min(...nodes.map(n=>n.x))-28,minY=Math.min(...nodes.map(n=>n.y))-28,maxX=Math.max(...nodes.map(n=>n.x+W))+28,maxY=Math.max(...nodes.map(n=>n.y+H))+28;
  return {nodes,edges,crosslinks,bounds:{x:minX,y:minY,width:maxX-minX,height:maxY-minY}};
 }
 function summary(data,rootId){
  const m=outline.model(data),depth=new Map([[rootId,0]]),queue=[rootId];
  while(queue.length){const id=queue.shift();for(const child of m.children.get(id)||[])if(!depth.has(child)){depth.set(child,depth.get(id)+1);queue.push(child);}}
  const items=data.items.filter(n=>depth.has(n.id)),decisions=outline.decisionHistory(data,new Set(depth.keys()));
  const count=type=>decisions.filter(d=>d.type===type).length,stops=decisions.filter(d=>d.type==='stop').map(d=>({...d,depth:depth.get(d.item_id)}));
  return {items:items.length,branches:(m.children.get(rootId)||[]).length,depth:Math.max(0,...depth.values()),chosen:count('pursue'),resumed:count('resume'),deferred:count('defer'),stopped:count('stop'),reportedComplete:items.filter(n=>n.state==='Reported complete').length,reportedFailed:items.filter(n=>n.state==='Reported failed').length,unknown:items.filter(n=>state(n).tone==='unknown').length,stopDepths:[...new Set(stops.map(d=>d.depth))].sort((a,b)=>a-b),stops,decisions,alternatives:data.links.filter(e=>e.type==='alternative_to'&&depth.has(e.source)&&depth.has(e.target)).length};
 }
 function execution(item){
  const evidence=item.execution_summary;
  if(!evidence)return {available:false,label:'Execution not mapped',note:'No unique saved plan binding for this item or its subplans. This does not establish whether work was attempted.'};
  const c=evidence.counts,scope=evidence.scope==='descendants'?'In subplans':evidence.scope==='mixed'?'Here + subplans':evidence.binding_basis==='reviewed_scopes'?'Reviewed scope':'Linked plan';
  const retry=item.retry_summary,parts=[`${c.attempts} ${c.attempts===1?'attempt':'attempts'}`,`${c.checks} ${c.checks===1?'check':'checks'}`];
  if(retry?.repeated_attempts)parts.push(`${retry.repeated_attempts} ${retry.repeated_attempts===1?'repeat':'repeats'}`);
  return {available:true,label:parts.join(' · '),scope,note:`${scope}: ${c.actions} unique actions; ${c.preparations} preparation actions; ${c.with_feedback} with returned feedback; ${c.with_assessment} with assessed feedback. Counts cover saved links only; roles may overlap.`};
 }
 function matching(item,mode){return mode==='all'||(mode==='attempted'&&item.execution_summary?.counts.attempts>0)||(mode==='unmapped'&&!item.execution_summary)||(mode==='retries'&&item.retry_summary?.after_reported_error>0)||(mode==='repeated'&&item.retry_summary?.repeated_attempts>0)||(mode==='complete'&&item.state==='Reported complete')||(mode==='inactive'&&['Explicitly deferred','Explicitly stopped'].includes(item.state))||(mode==='failed'&&item.state==='Reported failed')||(mode==='returns'&&(item.decisions||[]).some(d=>d.type==='resume'))||(mode==='ideas'&&['approach','hypothesis'].includes(item.work_kind));}
 function fitTransform(bounds,width,height,min=0.12){const scale=Math.max(min,Math.min(1.08,(width-48)/bounds.width,(height-72)/bounds.height));return {scale,x:(width-bounds.width*scale)/2-bounds.x*scale,y:(height-bounds.height*scale)/2-bounds.y*scale};}
 function zoomAt(transform,scale,x,y){scale=Math.max(.12,Math.min(2,scale));const ratio=scale/transform.scale;return {scale,x:x-(x-transform.x)*ratio,y:y-(y-transform.y)*ratio};}
 const disposers=new Set();
 function clear(){for(const dispose of [...disposers])dispose();}
 function render(host,data,rootId,{inspect,onFocus,openPlan,plans=new Set(),initialFocus=rootId}={}){
  const m=outline.model(data),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;},svg=(tag,attributes={})=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attributes))n.setAttribute(k,v);return n;};
  let active=m.path(rootId,initialFocus)?initialFocus:rootId,collapsed=new Set(),mode='all',direction='mind',geometry,transform={scale:1,x:0,y:0},fitted=true,fitMinimum=.12,disposed=false;
  if(data.items.length>32||window.innerWidth<900)for(const id of m.children.keys())if(id!==active)collapsed.add(id);
  const shell=el('div',null,'wc-shell'),toolbar=el('div',null,'wc-toolbar'),nav=el('nav',null,'wc-breadcrumbs');nav.setAttribute('aria-label','Work canvas scope');
  const actions=el('div',null,'wc-toolbar-actions'),branchMenu=el('select');branchMenu.setAttribute('aria-label','Highlight work branches');
  for(const [value,label] of [['all','All work'],['attempted','Linked attempts'],['unmapped','Execution not mapped'],['retries','Retries after error'],['repeated','Repeated attempts'],['complete','Completion reports'],['failed','Failure reports'],['inactive','Stopped / deferred'],['returns','Resumed work'],['ideas','Approaches / hypotheses']]){const o=el('option',label);o.value=value;branchMenu.append(o);}
  const button=(label,fn,cls)=>{const b=el('button',label,cls);b.type='button';b.onclick=fn;return b;};
  const expand=button('Expand all',()=>{collapsed.clear();draw();}),collapse=button('Main branches',()=>{collapsed=new Set([...m.children.keys()].filter(id=>id!==active));draw();}),maximize=button('Enlarge canvas',()=>{shell.classList.toggle('wc-expanded');maximize.textContent=shell.classList.contains('wc-expanded')?'Exit enlarged view':'Enlarge canvas';maximize.setAttribute('aria-pressed',String(shell.classList.contains('wc-expanded')));fitted=true;viewport.focus({preventScroll:true});});maximize.setAttribute('aria-pressed','false');
  actions.append(branchMenu,expand,collapse,maximize);toolbar.append(nav,actions);
  const viewport=el('div',null,'wc-viewport');viewport.tabIndex=0;viewport.setAttribute('role','region');viewport.setAttribute('aria-label','Work mind map. Drag to pan; control and wheel to zoom. Arrow keys pan; plus and minus zoom; zero fits the map.');
  const world=el('div',null,'wc-world'),lines=svg('svg',{'class':'wc-lines','aria-hidden':'true'}),cards=el('div',null,'wc-cards');world.append(lines,cards);viewport.append(world);
  const message=el('div',null,'wc-message');message.setAttribute('role','status');viewport.append(message);
  const minimap=svg('svg',{'class':'wc-minimap',role:'img','aria-label':'Map overview. The outlined rectangle is the visible area.'}),miniNodes=svg('g'),windowRect=svg('rect',{'class':'wc-minimap-window'});minimap.append(miniNodes,windowRect);viewport.append(minimap);
  const zoom=el('div',null,'wc-zoom'),percent=el('output');percent.setAttribute('aria-label','Canvas zoom');
  const zoomBy=factor=>{fitted=false;transform=zoomAt(transform,transform.scale*factor,viewport.clientWidth/2,viewport.clientHeight/2);paint();};
  const zoomOut=button('−',()=>zoomBy(1/1.2)),zoomIn=button('+',()=>zoomBy(1.2));zoomOut.setAttribute('aria-label','Zoom work map out');zoomIn.setAttribute('aria-label','Zoom work map in');
  zoom.append(zoomOut,percent,zoomIn,button('Fit',()=>fit()),button('100%',()=>{fitted=false;transform=zoomAt(transform,1,viewport.clientWidth/2,viewport.clientHeight/2);paint();}));viewport.append(zoom);
  const footer=el('div',null,'wc-footer'),legend=el('div',null,'wc-legend');for(const [tone,label] of [['chosen','Chosen / resumed'],['complete','Reported complete'],['failed','Reported failed'],['inactive','Stopped / deferred'],['unknown','No decision']]){const key=el('span',label,'wc-key wc-'+tone);legend.append(key);}
  const hint=el('span','Drag to pan · Ctrl + wheel to zoom · Click a card for evidence','wc-hint');footer.append(legend,hint);
  const stats=el('div',null,'wc-stats');shell.append(toolbar,stats,viewport,footer);host.append(shell);
  function focus(id){if(!m.path(rootId,id))return;active=id;collapsed.delete(id);onFocus?.(id);draw();}
  function details(n){const plan=n.work_kind==='approach'&&(n.source_node_ids||[]).find(id=>plans.has(id));inspect({...n,canvas_focus:()=>focus(n.id),canvas_inspect:details,...(plan?{canvas_plan:()=>{shell.classList.remove('wc-expanded');maximize.textContent='Enlarge canvas';maximize.setAttribute('aria-pressed','false');openPlan(plan);}}:{})});}
  function fit(min=0.12){fitMinimum=min;if(!viewport.clientWidth||!geometry)return;fitted=true;transform=fitTransform(geometry.bounds,viewport.clientWidth,viewport.clientHeight,min);if(min>.12&&geometry.bounds.width*transform.scale>viewport.clientWidth){transform.x=viewport.clientWidth/2-W*transform.scale/2;transform.y=viewport.clientHeight/2;}paint();}
  function paint(){world.style.transform=`translate(${transform.x}px,${transform.y}px) scale(${transform.scale})`;percent.textContent=Math.round(transform.scale*100)+'%';shell.dataset.scale=transform.scale.toFixed(3);windowRect.setAttribute('x',-transform.x/transform.scale);windowRect.setAttribute('y',-transform.y/transform.scale);windowRect.setAttribute('width',viewport.clientWidth/transform.scale);windowRect.setAttribute('height',viewport.clientHeight/transform.scale);}
  function emphasize(){
   const matches=new Set(geometry.nodes.filter(n=>matching(n.item,mode)).map(n=>n.id)),pathIds=new Set(matches);
   for(const id of matches)for(const p of m.path(active,id)||[])pathIds.add(p);
   for(const card of cards.children){card.classList.toggle('wc-muted',mode!=='all'&&!pathIds.has(card.dataset.workId));card.classList.toggle('wc-match',mode!=='all'&&matches.has(card.dataset.workId));}
   message.textContent=mode==='all'?`${new Set(geometry.nodes.map(n=>n.id)).size} work items visible · select a branch to inspect`:`${matches.size} matching branch card${matches.size===1?'':'s'} · `+(['retries','repeated','attempted'].includes(mode)?'parent and child counts overlap':mode==='unmapped'?'missing links do not establish inactivity':'other branches dimmed for this highlight');
   for(const edge of lines.children)edge.classList.toggle('wc-muted',mode!=='all'&&(!pathIds.has(edge.dataset.from)||!pathIds.has(edge.dataset.to)));
  }
  branchMenu.onchange=()=>{mode=branchMenu.value;if(mode!=='all')for(const item of data.items)if(matching(item,mode))for(const id of m.path(active,item.id)||[])collapsed.delete(id);draw();};
  function draw(){
   nav.replaceChildren();const path=m.path(rootId,active)||[rootId];
   const up=button('↑ Scope up',()=>focus(path.at(-2)));up.disabled=path.length<2;nav.append(up);
   for(const id of path){const b=button(id===rootId?'Objective':m.byId.get(id).label,()=>focus(id));b.title=m.byId.get(id).label;if(id===active)b.setAttribute('aria-current','location');nav.append(b);}
   geometry=layout(data,active,{collapsed,direction});world.style.width='1px';world.style.height='1px';cards.replaceChildren();lines.replaceChildren();miniNodes.replaceChildren();
   const placed=new Map(geometry.nodes.map(n=>[n.key,n]));
   for(const edge of geometry.edges){const a=placed.get(edge.source),b=placed.get(edge.target),side=b.side,ax=a.x+(side>0?W:0),bx=b.x+(side>0?0:W),ay=a.y+H/2,by=b.y+H/2,line=svg('path',{d:`M${ax},${ay} C${ax+side*GX/2},${ay} ${bx-side*GX/2},${by} ${bx},${by}`,'class':'wc-branch-line'});line.dataset.from=a.id;line.dataset.to=b.id;lines.append(line);}
   for(const e of geometry.crosslinks)if(e.from&&e.to){const a=placed.get(e.from),b=placed.get(e.to),y=Math.min(a.y,b.y)-20,line=svg('path',{d:`M${a.x+W/2},${a.y} C${a.x+W/2},${y} ${b.x+W/2},${y} ${b.x+W/2},${b.y}`,'class':'wc-cross-line wc-edge-'+e.type});const title=svg('title');title.textContent=outline.names[e.type];line.append(title);line.dataset.from=a.id;line.dataset.to=b.id;lines.append(line);}
   for(const n of geometry.nodes){const info=state(n.item),card=el('article',null,'wc-node wc-'+info.tone+(n.depth===0?' wc-root':'')+(n.shared?' wc-shared':''));card.dataset.workId=n.id;card.dataset.nodeKey=n.key;card.dataset.side=n.side;card.style.left=n.x+'px';card.style.top=n.y+'px';card.style.width=W+'px';card.style.height=H+'px';
    const main=button(null,()=>details(n.item),'wc-node-main');main.setAttribute('aria-label',n.item.label+' · '+info.label);main.title=n.item.label;const meta=el('span',null,'wc-node-meta');meta.append(el('span',(n.shared?'SHARED · ':'')+n.item.work_kind.toUpperCase()),el('span','D'+n.depth,'wc-depth'));main.append(meta,el('strong',n.item.label),el('span',info.symbol+' '+info.label,'wc-node-state'));card.append(main);
    const observed=execution(n.item),evidence=el('span',null,'wc-node-evidence'+(observed.available?'':' wc-evidence-missing'));evidence.title=observed.note;
    if(observed.available)evidence.append(el('small',observed.scope));evidence.append(el('span',observed.label));main.append(evidence);
    const children=m.children.get(n.id)||[];
    if(children.length&&!n.shared){const toggle=button(collapsed.has(n.id)?'+'+n.hiddenCount:'−',()=>{collapsed.has(n.id)?collapsed.delete(n.id):collapsed.add(n.id);draw();cards.querySelector(`[data-node-key="${n.key}"] .wc-node-main`)?.focus({preventScroll:true});},'wc-toggle');toggle.setAttribute('aria-expanded',String(!collapsed.has(n.id)));toggle.setAttribute('aria-label',(collapsed.has(n.id)?'Expand':'Collapse')+' '+n.item.label);toggle.title=children.length+' direct child'+(children.length===1?'':'ren');card.append(toggle);}
    if(n.depth>0){const scope=button('↗',()=>focus(n.id),'wc-scope');scope.setAttribute('aria-label','Focus branch: '+n.item.label);scope.title='Focus this branch';card.append(scope);}
    // Keyboard focus on an offscreen card pans it into view without scrolling the page.
    card.addEventListener('focusin',()=>{if(!document.activeElement?.matches(':focus-visible'))return;const left=transform.x+n.x*transform.scale,top=transform.y+n.y*transform.scale;if(left<0||top<0||left+W*transform.scale>viewport.clientWidth||top+H*transform.scale>viewport.clientHeight){fitted=false;transform.x=viewport.clientWidth/2-(n.x+W/2)*transform.scale;transform.y=viewport.clientHeight/2-(n.y+H/2)*transform.scale;paint();}});
    cards.append(card);miniNodes.append(svg('rect',{x:n.x,y:n.y,width:W,height:H,rx:14,'class':'wc-mini-'+info.tone}));
   }
   const b=geometry.bounds;minimap.setAttribute('viewBox',`${b.x} ${b.y} ${b.width} ${b.height}`);minimap.setAttribute('preserveAspectRatio','none');
   const totals=summary(data,active);stats.replaceChildren();
   const scopeItems=[active,...descendants(m,active)].map(id=>m.byId.get(id)),unmapped=scopeItems.filter(n=>!n.execution_summary).length,metric=el('span');metric.append(el('b',String(totals.items)),el('span','work items'));stats.append(metric);
   const gaps=button(`${unmapped} execution not mapped`,()=>{mode='unmapped';branchMenu.value=mode;emphasize();},'wc-coverage');gaps.title='Work items without a unique saved plan binding, directly or through their subplans.';stats.append(gaps);
   const executionHere=m.byId.get(active).execution_summary;if(executionHere){const b=button(`${executionHere.counts.actions} linked actions`,()=>details(m.byId.get(active)),'wc-coverage');b.title='Distinct recorded dispatches; counts do not establish completion.';stats.append(b);}
   const retry=m.byId.get(active).retry_summary;if(retry){const b=button(retry.after_reported_error+(retry.after_reported_error===1?' retry':' retries')+' after error · '+retry.repeated_attempts+' repeated attempts',()=>details(m.byId.get(active)),'wc-retry-total');b.title='Unique later dispatches in linked plans. Not a total over unassigned rollout work.';stats.append(b);}
   const signals=button('Branch signals ↗',()=>inspect({id:active+':signals',label:'Branch signals · '+m.byId.get(active).label,state:'Source-linked statements',source_node_ids:[],evidence:[],canvas_summary:totals}),'wc-signals');stats.append(signals);
   const external=geometry.crosslinks.filter(e=>!e.from||!e.to);if(external.length)stats.append(el('span',external.length+' cross-scope connection'+(external.length===1?'':'s')+' in node details'));
   emphasize();fit(viewport.clientWidth<900?.65:.12);
  }
  // Canvas gestures are local and reversible; source and graph objects stay untouched.
  const pointers=new Map();let gesture=null;
  viewport.onpointerdown=e=>{if(e.target.closest('button,select,.wc-minimap,.wc-zoom')||e.button!==0)return;viewport.focus({preventScroll:true});viewport.setPointerCapture(e.pointerId);pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});gesture=null;fitted=false;viewport.classList.add('wc-dragging');};
  viewport.onpointermove=e=>{if(!pointers.has(e.pointerId))return;const prev=pointers.get(e.pointerId);pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});if(pointers.size===1){transform.x+=e.clientX-prev.x;transform.y+=e.clientY-prev.y;}else{const [a,b]=[...pointers.values()],distance=Math.hypot(b.x-a.x,b.y-a.y),box=viewport.getBoundingClientRect(),center={x:(a.x+b.x)/2-box.left,y:(a.y+b.y)/2-box.top};if(gesture){transform=zoomAt(transform,transform.scale*distance/gesture.distance,center.x,center.y);transform.x+=center.x-gesture.x;transform.y+=center.y-gesture.y;}gesture={distance,...center};}paint();};
  const endPointer=e=>{pointers.delete(e.pointerId);gesture=null;if(!pointers.size)viewport.classList.remove('wc-dragging');};viewport.onpointerup=endPointer;viewport.onpointercancel=endPointer;viewport.onlostpointercapture=endPointer;
  viewport.addEventListener('wheel',e=>{e.preventDefault();fitted=false;if(e.ctrlKey||e.metaKey){const b=viewport.getBoundingClientRect();transform=zoomAt(transform,transform.scale*Math.exp(-e.deltaY*.004),e.clientX-b.left,e.clientY-b.top);}else{transform.x-=e.deltaX;transform.y-=e.deltaY;}paint();},{passive:false});
  viewport.onkeydown=e=>{if(e.target!==viewport)return;const movement={ArrowLeft:[60,0],ArrowRight:[-60,0],ArrowUp:[0,60],ArrowDown:[0,-60]}[e.key];if(movement){e.preventDefault();fitted=false;transform.x+=movement[0];transform.y+=movement[1];paint();}else if(['+','=','-','0'].includes(e.key)){e.preventDefault();e.key==='0'?fit():zoomBy(e.key==='-'?1/1.2:1.2);}};
  shell.addEventListener('keydown',e=>{if(!shell.classList.contains('wc-expanded'))return;if(e.key==='Escape'){e.stopPropagation();maximize.click();maximize.focus({preventScroll:true});}else if(e.key==='Tab'){const controls=[...shell.querySelectorAll('button:not(:disabled),select,[tabindex="0"]')].filter(n=>n.offsetWidth>0);if(e.shiftKey&&e.target===controls[0]){e.preventDefault();controls.at(-1)?.focus({preventScroll:true});}else if(!e.shiftKey&&e.target===controls.at(-1)){e.preventDefault();controls[0]?.focus({preventScroll:true});}}});
  minimap.onpointerdown=e=>{e.stopPropagation();const r=minimap.getBoundingClientRect(),b=geometry.bounds;fitted=false;transform.x=viewport.clientWidth/2-(b.x+(e.clientX-r.left-7)/(r.width-14)*b.width)*transform.scale;transform.y=viewport.clientHeight/2-(b.y+(e.clientY-r.top-7)/(r.height-14)*b.height)*transform.scale;paint();};
  const resize=new ResizeObserver(()=>{if(disposed||!viewport.clientWidth)return;if(fitted)fit(fitMinimum);else paint();});resize.observe(viewport);
  const dispose=()=>{disposed=true;resize.disconnect();shell.classList.remove('wc-expanded');disposers.delete(dispose);};disposers.add(dispose);draw();return {dispose,focus};
 }
 return {layout,summary,state,execution,matching,fitTransform,zoomAt,descendants,render,clear};
});
