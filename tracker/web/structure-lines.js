/* Compact projection of saved parentage. Cross-links never become hierarchy. */
(function(root){
 const kinds=new Set(['plan','plan_step','task_list','declared_item','native_goal','native_control','outline_item']);
 const WIDTH=164,PITCH=196,ROW=88;
 const TYPES={objective:['Objective','#3159dc'],subgoal:['Subgoal','#087e79'],approach:['Approach','#8052b6'],plan:['Plan','#5363b9'],plan_step:['Step','#ad681e'],task_list:['Task list','#287b98'],declared_item:['Task','#ad681e'],native_goal:['Goal','#3159dc'],native_control:['Control','#b3437b']};
 function nodeType(node){const key=node.kind==='outline_item'?(node.work_kind||'outline_item'):node.kind;const [label,color]=TYPES[key]||[key==='outline_item'?'Work item':String(key||'Work item').replaceAll('_',' '),'#64748b'];return {key,label,color};}
 function layout(data,focus='all',folded=new Set()){
  const nodes=new Map(data.nodes.filter(n=>kinds.has(n.kind)).map(n=>[n.id,n]));
  const links=[...data.links,...(data.work_outline?.links||[])].filter(e=>nodes.has(e.source)&&nodes.has(e.target));
  const parents=links.filter(e=>['contains','part_of'].includes(e.type)).map(e=>e.type==='part_of'?{...e,source:e.target,target:e.source}:e);
  const children=new Map();for(const e of parents){if(!children.has(e.source))children.set(e.source,[]);children.get(e.source).push(e.target);}
  const roots=focus==='all'?data.roots:[focus],visible=new Set(),todo=[...roots];
  while(todo.length){const id=todo.shift();if(visible.has(id)||!nodes.has(id))continue;visible.add(id);if(!folded.has(id))todo.push(...children.get(id)||[]);}
  const edges=parents.filter(e=>visible.has(e.source)&&visible.has(e.target)&&!folded.has(e.source));
  const indegree=new Map([...visible].map(id=>[id,0])),depth=new Map([...visible].map(id=>[id,0]));
  for(const e of edges)indegree.set(e.target,indegree.get(e.target)+1);
  const ready=[...visible].filter(id=>!indegree.get(id));let visited=0;
  while(ready.length){const id=ready.shift();visited++;for(const e of edges.filter(e=>e.source===id)){depth.set(e.target,Math.max(depth.get(e.target),depth.get(id)+1));indegree.set(e.target,indegree.get(e.target)-1);if(!indegree.get(e.target))ready.push(e.target);}}
  if(visited!==visible.size)throw Error('The saved structure contains cyclic parentage. Open the detailed map to inspect it.');
  const columns=new Map();for(const id of visible){const d=depth.get(id);if(!columns.has(d))columns.set(d,[]);columns.get(d).push(id);}
  const count=Math.max(1,...[...columns.values()].map(c=>c.length));
  const points=[];for(const [d,ids]of columns){ids.sort((a,b)=>(nodes.get(a).event_index??0)-(nodes.get(b).event_index??0)||a.localeCompare(b));ids.forEach((id,i)=>points.push({...nodes.get(id),depth:d,x:24+d*PITCH,y:30+(i+(count-ids.length)/2)*ROW,width:WIDTH,children:children.get(id)?.length||0,folded:folded.has(id)}));}
  const relations=links.filter(e=>!['contains','part_of'].includes(e.type)&&visible.has(e.source)&&visible.has(e.target));
  return {nodes:points,edges,relations,width:Math.max(420,columns.size*PITCH+24),height:Math.max(200,count*ROW+52)};
 }
 function render(host,data,focus,inspect){
  const folded=new Set(),make=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
  function draw(){
   host.replaceChildren();let view;try{view=layout(data,focus,folded);}catch(e){host.append(make('p',e.message));return;}
   const note=make('p','Solid lines: parentage · dashed lines: named relationships. Select a label to inspect evidence; use − to fold a branch.','ph-note');host.append(note);
   const legend=make('div',null,'sl-legend');legend.setAttribute('aria-label','Node types');for(const type of new Map(view.nodes.map(n=>{const type=nodeType(n);return [type.key,type];})).values()){const item=make('span',type.label);item.style.setProperty('--sl-color',type.color);legend.append(item);}host.append(legend);
   const scroll=make('div',null,'sl-scroll');scroll.tabIndex=0;scroll.setAttribute('aria-label','Scrollable structure lines');const board=make('div',null,'sl-board');board.style.width=view.width+'px';board.style.height=view.height+'px';scroll.append(board);host.append(scroll);
   const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('width',view.width);svg.setAttribute('height',view.height);svg.setAttribute('aria-hidden','true');board.append(svg);
   const byId=new Map(view.nodes.map(n=>[n.id,n]));
   for(const [edges,cross]of [[view.edges,false],[view.relations,true]])for(const edge of edges){const a=byId.get(edge.source),b=byId.get(edge.target),p=document.createElementNS(svg.namespaceURI,'path');const x=a.x+a.width,y=a.y+23,ex=b.x,ey=b.y+23;p.setAttribute('d',`M${x},${y} C${x+16},${y} ${ex-16},${ey} ${ex},${ey}`);p.setAttribute('class',cross?'sl-cross':'sl-branch');if(!cross)p.style.stroke=nodeType(b).color;svg.append(p);}
   for(const n of view.nodes){
    const type=nodeType(n),row=make('div',null,'sl-node');row.dataset.kind=n.kind;row.dataset.nodeType=type.key;row.style.setProperty('--sl-color',type.color);row.style.left=n.x+'px';row.style.top=n.y+'px';row.style.width=n.width+'px';row.setAttribute('aria-label',type.label);
    const b=make('button',n.label,'sl-label');b.type='button';b.title=type.label+': '+n.label;b.onclick=()=>inspect(n);row.append(b);
    const stats=data.work_measures?.rows.find(r=>r.id===n.id);row.append(make('small',stats?`Depth ${stats.depth_min===stats.depth_max?stats.depth_max:stats.depth_min+'–'+stats.depth_max} · ${stats.observed?stats.effort+' '+stats.effort_unit:'No linked work observed'}`:n.state||n.kind.replaceAll('_',' ')));
    if(n.children){const fold=make('button',n.folded?'+':'−','sl-fold');fold.type='button';fold.setAttribute('aria-label',(n.folded?'Expand ':'Fold ')+n.label);fold.setAttribute('aria-expanded',String(!n.folded));fold.onclick=()=>{if(folded.has(n.id))folded.delete(n.id);else folded.add(n.id);draw();host.querySelector('[aria-label="'+CSS.escape((n.folded?'Fold ':'Expand ')+n.label)+'"]')?.focus();};row.append(fold);}
    board.append(row);
   }
   if(view.relations.length){const list=make('div',null,'sl-relations');for(const e of view.relations){const b=make('button',`${byId.get(e.source).label} · ${e.label||e.type.replaceAll('_',' ')} → ${byId.get(e.target).label}`);b.type='button';b.onclick=()=>inspect(byId.get(e.source));list.append(b);}host.append(list);}
  }draw();
 }
 const api={layout,render,nodeType};if(typeof module==='object')module.exports=api;else root.StructureLines=api;
})(typeof window==='object'?window:globalThis);
