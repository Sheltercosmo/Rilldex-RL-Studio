/* Occurrence positions over saved work identities. No inferred strategy or duration. */
((root,factory)=>{const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.WorkTimeline=api;})(typeof window==='undefined'?globalThis:window,()=>{
 const categories={continued:'Consecutive same work',returned:'Return after other work',resumed:'Resumed after a gap in work assignment',interrupted:'Recurrence with incomplete order or coverage'};
 const procedures={same_procedure:{label:'Same dispatched procedure',symbol:'=',className:'method-same'},reconfigured_procedure:{label:'Changed settings or inputs',symbol:'Δ',className:'method-settings'},alternative_procedure:{label:'Different procedure',symbol:'↔',className:'method-alternative'},unresolved:{label:'Procedure not established',symbol:'?',className:'method-unknown'}};
 function comparisonFor(data,observations,episode,scopeAudit=null){
  const unknown=reason=>({key:'unresolved',...procedures.unresolved,reason,record:null});
  if(data.axis==='contributions')return unknown('Procedure comparisons apply to recorded actions, not arbitrary contributions.');
  const affected=new Set(scopeAudit?.affected_subject_ids||[]);
  if((data.visits||[]).some(v=>affected.has(v.group_id)&&v.occurrences.some(o=>[episode.previous_unit_id,episode.current_unit_id].includes(o.unit_id))))return unknown('Work identity is disputed; review the grouping first.');
  if((data.visits||[]).some(v=>v.occurrences.some(o=>[episode.previous_unit_id,episode.current_unit_id].includes(o.unit_id)&&!(o.order_known??v.order_known))))return unknown('Dispatch order is not established for both endpoints.');
  if(!observations||!['graph_id','run_id','source_hash'].every(k=>data[k]&&data[k]===observations[k]))return unknown('No procedure comparisons for this exact graph and source.');
  if(episode.category==='interrupted')return unknown('Recurrence order or coverage is incomplete.');
  const rows=(observations.records||[]).filter(r=>r.episode_id===episode.id);
  if(rows.length!==1)return unknown(rows.length?'Conflicting comparisons for this pair.':'No comparison for this exact pair.');
  const record=rows[0];
  if(record.previous_unit_id!==episode.previous_unit_id||record.current_unit_id!==episode.current_unit_id)return unknown('Comparison endpoints do not match this recurrence.');
  if(record.episode&&['id','previous_unit_id','current_unit_id','category'].some(k=>record.episode[k]!==episode[k]))return unknown('Comparison evidence does not match this recurrence.');
  if(!Object.hasOwn(procedures,record.procedure))return unknown('Unsupported procedure comparison.');
  return {key:record.procedure,...procedures[record.procedure],reason:record.procedure_reason||procedures[record.procedure].label,record};
 }
 // Textual difference only. Preserve every code point; never derive procedure identity from equality.
 function dispatchDiff(before,after){
  if(typeof before!=='string'||typeof after!=='string')return null;
  const a=Array.from(before),b=Array.from(after);let start=0,end=0;
  while(start<a.length&&start<b.length&&a[start]===b[start])start++;
  while(end<a.length-start&&end<b.length-start&&a[a.length-1-end]===b[b.length-1-end])end++;
  const split=x=>({prefix:x.slice(0,start).join(''),changed:x.slice(start,x.length-end).join(''),suffix:end?x.slice(x.length-end).join(''):''});
  return {equal:before===after,before:split(a),after:split(b)};
 }
 function project(data,{scopeAudit=null,visitIds=null,procedureObservations=null}={}){
  const byId=new Map(),duplicates=new Set(),membership=new Map(),allowed=visitIds&&new Set(visitIds),affected=new Set(scopeAudit?.affected_subject_ids||[]),paths=[];
  for(const v of data.visits){if(byId.has(v.id))duplicates.add(v.id);byId.set(v.id,v);}
  for(const p of data.paths)for(const id of p.visit_ids)membership.set(id,(membership.get(id)||0)+1);
  const episodes=new Map();for(const e of data.episodes||[]){if(!episodes.has(e.id))episodes.set(e.id,[]);episodes.get(e.id).push(e);}
  for(const [index,path]of data.paths.entries()){
   const ids=path.visit_ids.filter(id=>!allowed||allowed.has(id));if(!ids.length)continue;
   const result={id:'path-'+index,path,rows:[],points:[],pairs:[],issues:[],available:true};paths.push(result);
   if(ids.some(id=>!byId.has(id)||duplicates.has(id)||membership.get(id)!==1)){
    result.available=false;result.issues.push('Missing or ambiguous route membership. Open the detailed route.');continue;
   }
   const rows=new Map(),positions=new Set();
   for(const id of ids){
    const visit=byId.get(id),disputed=affected.has(visit.group_id),key=visit.group_id&&!disputed?'group:'+visit.group_id:'visit:'+id;
    if(visit.positions.length!==visit.occurrences.length){result.available=false;result.issues.push('Occurrence positions are incomplete.');break;}
    if(!rows.has(key))rows.set(key,{id:result.id+':'+key,target:visit.target,group_id:visit.group_id,disputed,visits:[],points:[]});
    const row=rows.get(key);row.visits.push(visit);
    for(const [i,occurrence]of visit.occurrences.entries()){
     const position=visit.positions[i];
     if(!Number.isSafeInteger(position)||position<1||positions.has(position)){result.available=false;result.issues.push('Duplicate or invalid occurrence position.');break;}
     positions.add(position);
     const point={id:result.id+':'+id+':'+i,position,visit_id:id,row_id:row.id,occurrence,visit,identity_status:occurrence.identity_status,
      unresolved:!visit.group_id&&occurrence.identity_status!=='not_applicable',not_applicable:occurrence.identity_status==='not_applicable',disputed,order_known:occurrence.order_known??visit.order_known,pairs:[]};
     row.points.push(point);result.points.push(point);
    }
    if(!result.available)break;
   }
   if(!result.points.length){result.available=false;result.issues.push('No occurrence positions available.');}
   if(!result.available){result.points=[];continue;}
   result.rows=[...rows.values()].sort((a,b)=>a.points[0].position-b.points[0].position);
   result.start=Math.min(...result.points.map(p=>p.position));result.end=Math.max(...result.points.map(p=>p.position));
   const seen=new Set();
   for(const link of data.links||[]){
    if(link.type!=='same_work_return'||seen.has(link.episode_id)||episodes.get(link.episode_id)?.length!==1)continue;
    const e=episodes.get(link.episode_id)[0];if(!categories[e.category]||link.category!==e.category)continue;
    const before=result.points.filter(p=>p.visit_id===link.target&&p.occurrence.unit_id===e.previous_unit_id),after=result.points.filter(p=>p.visit_id===link.source&&p.occurrence.unit_id===e.current_unit_id);
    if(before.length!==1||after.length!==1||before[0].position>=after[0].position||before[0].row_id!==after[0].row_id||after[0].disputed||!after[0].visit.group_id)continue;
    const comparison=comparisonFor(data,procedureObservations,e,scopeAudit);
    const pair={link,before:before[0].id,after:after[0].id,category:e.category,label:categories[e.category],comparison};
    result.pairs.push(pair);after[0].pairs.push(pair);seen.add(link.episode_id);
   }
  }
  const totals=Object.fromEntries(Object.keys(procedures).map(k=>[k,0]));for(const p of paths)for(const pair of p.pairs)totals[pair.comparison.key]++;
  const opportunities=Object.values(totals).reduce((a,b)=>a+b,0);
  return {graph_id:data.graph_id,axis:data.axis==='contributions'?'Contribution':'Action',paths,unavailable_paths:paths.filter(p=>!p.available).length,
   procedures:data.axis==='contributions'?null:{counts:totals,opportunities,compared:opportunities-totals.unresolved,unknown:totals.unresolved},
   count:paths.reduce((n,p)=>n+p.points.length,0),limit:'Positions show recording order, not time or effort. Work rows use saved identity; separate rows do not establish exploration.'};
 }
 function overview(path){
  const repeated=path.rows.filter(r=>r.group_id&&!r.disputed&&r.points.length>1);
  if(!repeated.length)return path.rows;
  const others=path.rows.filter(r=>!repeated.includes(r)),points=others.flatMap(r=>r.points).sort((a,b)=>a.position-b.position);
  return [...repeated,...(points.length?[{id:path.id+':other',target:'Other recorded work',aggregate:true,points,visits:others.flatMap(r=>r.visits)}]:[])];
 }
 function render(host,value,{selectedVisit=null,selectedLink=null,onVisit=()=>{},onPair=()=>{},allWork=false,onAllWork=()=>{},lens='work',onLens=()=>{}}={}){
  const old=host.querySelector('.wtl-scroll'),previous={top:old?.scrollTop||0,left:old?.scrollLeft||0,width:Number(host.dataset.viewportWidth)||0},active=host.contains(document.activeElement)?document.activeElement.dataset.point:null,selection=selectedLink||selectedVisit||'',selectionChanged=host.dataset.selection!==selection;
  host.dataset.selection=selection;
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  host.replaceChildren();const intro=node('div',null,'wtl-intro');intro.append(node('h3','Work across the rollout'),node('span',value.count+' '+value.axis.toLowerCase()+(value.count===1?'':'s')+' shown'+(value.unavailable_paths?' · '+value.unavailable_paths+' routes unavailable':'')));host.append(intro);
  const tools=node('div',null,'wtl-options'),label=node('label'),check=node('input');check.type='checkbox';check.checked=allWork;check.onchange=()=>onAllWork(check.checked);label.append(check,document.createTextNode('Show every work target'));tools.append(label,node('span','Each mark is one '+value.axis.toLowerCase()+' in recorded order.'));host.append(tools);
  const methodLens=value.axis==='Action'&&lens==='procedure';
  if(value.axis==='Action'){
   const control=node('div',null,'wtl-lens');control.setAttribute('role','group');control.setAttribute('aria-label','Timeline lens');
   for(const [key,text]of [['work','Work returns'],['procedure','Procedure changes']]){const b=node('button',text);b.type='button';b.dataset.lens=key;b.setAttribute('aria-pressed',String(methodLens?key==='procedure':key==='work'));b.onclick=()=>onLens(key);control.append(b);}tools.prepend(control);
  }
  if(methodLens){const c=value.procedures;host.append(node('p',`${c.compared} of ${c.opportunities} recurrence pairs compared in view · ${c.unknown} not established. Click a comparison to inspect both dispatches and intervening work.`,'wtl-coverage'));}
  const readout=node('div','Hover or focus a mark to read its work and recorded position.','wtl-readout');readout.setAttribute('role','status');host.append(readout);
  const scroller=node('div',null,'wtl-scroll');scroller.tabIndex=0;scroller.setAttribute('role','region');scroller.setAttribute('aria-label','Work occurrence timeline; scroll for all work and positions');host.append(scroller);
  const legend=node('div',null,'wtl-legend');
  const points=value.paths.flatMap(p=>p.points),combined=!allWork&&value.paths.some(p=>p.available&&overview(p).some(r=>r.aggregate));
  const methodLegend=methodLens?Object.entries(procedures).map(([k,p])=>[p.className,p.symbol+' '+p.label+' · '+value.procedures.counts[k],value.procedures.counts[k]>0]):[];
  for(const [cls,label,show]of [...methodLegend,['','Recorded work',!methodLens],['method-context','· Context / no comparable pair in view',methodLens],['is-return','↩ Return after other work',!methodLens&&points.some(p=>p.pairs.some(e=>e.category==='returned'))],['is-other','Other work · expand for separate identities',combined&&!methodLens],['is-unknown','? Unresolved or unannotated',points.some(p=>p.unresolved)],['is-other','— No immediate work target',points.some(p=>p.not_applicable)],['is-unordered','∥ Order not established',points.some(p=>!p.order_known)],['is-disputed','! Identity disputed',points.some(p=>p.disputed)]]){if(!show)continue;const item=node('span',null,cls);item.append(node('i'),document.createTextNode(label));legend.append(item);}host.append(legend);
  host.append(node('p',methodLens?'Comparisons describe the dispatched procedure. The same command can act on changed files or state; a different procedure does not establish exploration or improvement.':value.limit,'wtl-caption'));
  for(const path of value.paths){
   const section=node('section',null,'wtl-path');scroller.append(section);
   if(value.paths.length>1)section.append(node('h4',(path.path.actor||'Agent')+' · '+(path.path.trajectory_id||path.id)+(path.path.context_id?' · '+path.path.context_id:'')));
   if(!path.available){section.append(node('p',path.issues.join(' '),'wn-empty'));continue;}
   const count=path.end-path.start+1,chart=node('div',null,'wtl-chart');chart.style.setProperty('--columns',String(count));
   const header=node('div',null,'wtl-row wtl-axis'),name=node('div','Work / occurrences','wtl-name'),ticks=node('div',null,'wtl-track');header.append(name,ticks);chart.append(header);
   const positions=count<=12?Array.from({length:count},(_,i)=>path.start+i):[...new Set([path.start,...Array.from({length:5},(_,i)=>Math.round(path.start+(path.end-path.start)*i/4)),path.end])];
   for(const position of positions){const tick=node('span',String(position),'wtl-tick');tick.style.gridColumn=String(position-path.start+1);ticks.append(tick);}
   name.append(node('small',value.axis+' position '+path.start+'–'+path.end));
   const selectedPair=path.pairs.find(p=>p.link.id===selectedLink);
   const rows=allWork?path.rows:overview(path);
   for(const row of rows){
    const line=node('div',null,'wtl-row'+(row.disputed?' is-disputed':'')),label=node('div',null,'wtl-name'),title=node('span',row.target),total=node('b',String(row.points.length)),track=node('div',null,'wtl-track');title.title=row.target;label.append(title,total);
    if(row.disputed)label.append(node('small','Identity disputed; visits kept separate'));
    line.append(label,track);chart.append(line);
    for(const point of row.points){
     const method=point.pairs.length===1?point.pairs[0].comparison:null,returning=point.pairs.some(p=>p.category==='returned'),symbol=point.disputed?'!':point.unresolved?'?':point.not_applicable?'—':!point.order_known?'∥':methodLens?(method?.symbol||'·'):returning?'↩':'',button=node('button',symbol,'wtl-mark'+(row.aggregate||point.not_applicable?' is-other':'')+(returning?' is-return':'')+(point.unresolved?' is-unknown':'')+(!point.order_known?' is-unordered':'')+(point.disputed?' is-disputed':'')+(methodLens&&!point.disputed&&!point.unresolved&&point.order_known?' '+(method?.className||'method-context'):''));
     button.type='button';button.dataset.point=point.id;button.dataset.visit=point.visit_id;button.style.gridColumn=String(point.position-path.start+1);
     const unknowns={source_gap:'Unannotated source',not_applicable:'No immediate work target',unreviewed:'Identity not reviewed'},context=point.disputed?'Identity disputed':point.not_applicable?'No immediate work target':point.unresolved?(unknowns[point.identity_status]||'Identity unresolved'):point.pairs.map(p=>p.label).join('; '),description=value.axis+' '+point.position+' · '+point.visit.target+(context?' · '+context:'')+(!point.order_known?' · Recording position only; execution order not established':'')+(methodLens?' · '+(method?.label||'Context / no comparable pair in view'):'');
     button.setAttribute('aria-label',description);button.setAttribute('aria-pressed',String(selectedPair?[selectedPair.before,selectedPair.after].includes(point.id):point.visit_id===selectedVisit));
     const show=()=>{readout.replaceChildren(node('strong',description));const source=point.occurrence.source?.text;if(source)readout.append(node('span',source.replace(/\s+/g,' ').slice(0,250)));};
     if(selectedPair?selectedPair.after===point.id:point.visit_id===selectedVisit)show();
     button.onmouseenter=show;button.onfocus=show;
     button.onclick=()=>point.pairs.length===1?onPair(point.pairs[0].link):onVisit(point.visit);
     track.append(button);
    }
   }
   section.append(chart);
  }
  scroller.scrollTop=previous.top;scroller.scrollLeft=previous.left;
  host.dataset.viewportWidth=String(scroller.clientWidth);
  if(selection&&(selectionChanged||previous.width!==scroller.clientWidth)){
   const marks=[...scroller.querySelectorAll('.wtl-mark[aria-pressed=true]')];
   if(marks.length){const bounds=scroller.getBoundingClientRect(),rects=marks.map(b=>b.getBoundingClientRect()),label=scroller.querySelector('.wtl-name').getBoundingClientRect().width,left=Math.min(...rects.map(r=>r.left)),right=Math.max(...rects.map(r=>r.right));
    if(right>bounds.right-8)scroller.scrollLeft+=right-bounds.right+8;
    else if(left<bounds.left+label+8)scroller.scrollLeft+=left-bounds.left-label-8;
    const top=Math.min(...rects.map(r=>r.top)),bottom=Math.max(...rects.map(r=>r.bottom));if(top<bounds.top+50)scroller.scrollTop+=top-bounds.top-50;else if(bottom>bounds.bottom-8)scroller.scrollTop+=bottom-bounds.bottom+8;
   }
  }
  if(active){const button=[...host.querySelectorAll('[data-point]')].find(b=>b.dataset.point===active);button?.focus({preventScroll:true});}
 }
  return {project,overview,render,comparisonFor,dispatchDiff};
});
