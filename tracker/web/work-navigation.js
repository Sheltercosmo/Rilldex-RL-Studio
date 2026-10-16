/* Work-level navigation preserves every dispatch and links to the unit map. */
(()=>{
 const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 const svg=(tag,attrs={},text)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!=null)n.textContent=text;return n;};
 const short=(text,n=95)=>text.length>n?text.slice(0,n-1)+'…':text;
 function textLines(text,max=34){const lines=[];let line='';for(const word of text.split(/\s+/)){if((line+' '+word).length>max&&line){lines.push(line);line=word;}else line=(line+' '+word).trim();}if(line)lines.push(line);return lines;}
 function grouped(links){const groups=new Map(),result=[];for(const link of links){if(link.type!=='work_relation'){result.push(link);continue;}const key=JSON.stringify([link.source,link.target,link.relation_type]);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(link);}for(const rows of groups.values()){const first=rows[0];result.push(rows.length===1?first:{...first,id:first.id+'+'+rows.length,bundle:rows,label:first.label+' · '+rows.length+' saved links',node_ids:[...new Set(rows.flatMap(r=>r.node_ids))],edge_ids:[...new Set(rows.flatMap(r=>r.edge_ids))]});}return result;}
 function returnContext(data,link){
  const saved=data.links.find(e=>e.type==='same_work_return'&&e.episode_id===link.episode_id&&e.source===link.source&&e.target===link.target);
  if(!saved||saved.source===saved.target)return {available:false,reason:'No separate saved recurrence endpoints.'};
  const paths=data.paths.filter(p=>p.visit_ids.includes(saved.source)&&p.visit_ids.includes(saved.target));
  if(paths.length!==1)return {available:false,reason:'The recurrence endpoints do not share one recorded work route.'};
  const path=paths[0],a=path.visit_ids.indexOf(saved.target),b=path.visit_ids.indexOf(saved.source),byId=new Map(data.visits.map(v=>[v.id,v]));
  if(a>=b||path.visit_ids.slice(a,b+1).some(id=>!byId.has(id)))return {available:false,reason:'The recurrence window has incomplete route evidence.'};
  const previous=byId.get(saved.target),current=byId.get(saved.source),between=path.visit_ids.slice(a+1,b).map(id=>byId.get(id));
  const prior=path.visit_ids.slice(0,b).map(id=>byId.get(id)).filter(Boolean),middle=new Set(between.map(v=>v.id)),same=new Set(prior.filter(v=>v.group_id&&v.group_id===current.group_id).map(v=>v.id));
  const connections=data.links.filter(e=>e.type==='work_relation'&&e.source===current.id);
  const references=connections.filter(e=>['scope','feedback','revision','native'].includes(e.family));
  return {available:true,previous,current,between,episode:data.episodes.find(e=>e.id===saved.episode_id),
   interveningReferences:grouped(references.filter(e=>middle.has(e.target))),
   earlierWorkReferences:grouped(references.filter(e=>same.has(e.target))),
   workComparisons:grouped(connections.filter(e=>e.family==='target'&&(middle.has(e.target)||same.has(e.target))))};
 }
 function recurringWork(data,scopeAudit=null,procedures=null){
  const byId=new Map(data.visits.map(v=>[v.id,v])),episodes=new Map(data.episodes.map(e=>[e.id,e]));
  const affected=new Set(scopeAudit?.affected_subject_ids||[]),rows=[];
  const membership=new Map();for(const p of data.paths)for(const id of p.visit_ids)membership.set(id,(membership.get(id)||0)+1);
  for(const path of data.paths){
   const groups=new Map();for(const id of path.visit_ids){const v=byId.get(id);if(!v?.group_id||membership.get(id)!==1)continue;if(!groups.has(v.group_id))groups.set(v.group_id,[]);groups.get(v.group_id).push(v);}
   for(const[groupId,visits]of groups){
    const ids=new Set(visits.map(v=>v.id)),seen=new Set(),links=[];
    for(const l of data.links){
     if(l.type!=='same_work_return'||!ids.has(l.source)||!ids.has(l.target)||!episodes.has(l.episode_id)||seen.has(l.episode_id))continue;
     const e=episodes.get(l.episode_id);if(!byId.get(l.source).occurrences.some(o=>o.unit_id===e.current_unit_id)||!byId.get(l.target).occurrences.some(o=>o.unit_id===e.previous_unit_id))continue;if(e.category!==l.category||!['continued','returned','resumed','interrupted'].includes(l.category))continue;
     if(path.visit_ids.indexOf(l.target)>path.visit_ids.indexOf(l.source))continue;
     seen.add(l.episode_id);links.push(l);
    }
    if(!links.length)continue;
    const cases=links.map(l=>episodes.get(l.episode_id)),known=[];
    for(const l of links){const comparison=window.WorkTimeline.comparisonFor(data,procedures,episodes.get(l.episode_id),scopeAudit);if(comparison.key!=='unresolved')known.push(comparison.record);}
    const occurrences=new Set(visits.flatMap(v=>v.occurrences.map((o,i)=>o.unit_id||o.event_id||v.id+':'+i)));
    rows.push({id:visits[0].id,group_id:groupId,target:visits[0].target,path,visits,links,occurrences:occurrences.size,
     returns:links.filter(l=>l.category==='returned').length,continued:links.filter(l=>l.category==='continued').length,
     resumed:links.filter(l=>l.category==='resumed').length,interrupted:links.filter(l=>l.category==='interrupted').length,
     disputed:affected.has(groupId),procedure_records:known,procedure_known:known.length,procedure_changed:known.filter(r=>r.procedure!=='same_procedure').length,
     feedback_assessed:data.axis==='contributions'?null:cases.filter(e=>e.assessment_unit_ids?.length).length,
     first:visits[0].positions[0],last:visits.at(-1).positions.at(-1)});
   }
  }
  return rows.sort((a,b)=>b.occurrences-a.occurrences||b.links.length-a.links.length||a.first-b.first);
 }
 function workWindow(data,row){
  if(!row)return {paths:data.paths,visits:data.visits,focusIds:[],available:true};
  const byId=new Map(data.visits.map(v=>[v.id,v])),start=row.path.visit_ids.indexOf(row.visits[0].id),end=row.path.visit_ids.indexOf(row.visits.at(-1).id);
  const ids=row.path.visit_ids.slice(start,end+1);if(start<0||end<start||ids.some(id=>!byId.has(id)))return {paths:data.paths,visits:data.visits,focusIds:[],available:false};
  return {paths:[{...row.path,visit_ids:ids}],visits:ids.map(id=>byId.get(id)),focusIds:row.visits.map(v=>v.id),available:true};
 }
 window.WorkNavigationView={returnContext,recurringWork,workWindow,connections:(data,id)=>grouped(data.links.filter(e=>e.source===id||e.target===id)),render(host,data,selectVisit,selectLink,initialVisit=null,selectContext=()=>{},scopeAudit=null,selectConflict=()=>{},selectGrouping=()=>{},options={}){
  host.replaceChildren();let selected=initialVisit,selectedLink=null,allConnections=false,returnSelect=null,returnControl=null;const enabled=new Set(['same_work_return','attempted_correction_for','scope','feedback','revision','native','target']),contributions=data.axis==='contributions',unit=contributions?'Contribution':'Action',plural=contributions?'contributions':'actions',savedContexts=data.context_nodes||[],drawingLinks=grouped(data.links);
  const conflicts=scopeAudit?.conflicts||[],affected=new Set(scopeAudit?.affected_subject_ids||[]),hasConflicts=conflicts.length>0,coverageNotes=[];
  const grouping=scopeAudit?.grouping,incompleteGrouping=grouping&&(data.counts.unresolved||data.counts.unreviewed||data.counts.source_gaps);
  const recurrenceSummary=(data.counts.returned?`${data.counts.returned} saved return${data.counts.returned===1?'':'s'} after other work`:'No return links saved')+`${data.counts.interrupted?' · '+data.counts.interrupted+' recurrence'+(data.counts.interrupted===1?'':'s')+' with incomplete order or coverage':''}`;
  const title=node('div',null,'wn-heading'),coverage=contributions?`${data.counts.bound||0}/${data.counts.contributions} contributions assigned · ${data.counts.source_gaps} source gaps`:`${data.counts.recorded_actions} actions`;
  title.append(node('h2','Work path'),node('span',`${coverage} · ${data.counts.visits} saved visits · ${hasConflicts?'return summary withheld':incompleteGrouping?'return coverage incomplete':recurrenceSummary}`));host.append(title);
  if(data.recurrence_order)host.append(node('p','Return counts include complete observed parallel work between ordered endpoints. Sibling calls remain unordered. Measurement: “Returns after other work · parallel work included”.','wn-note'));
  if(!data.available){host.append(node('p','Work identities have not been observed for this graph. Open Unit map to inspect the source.','wn-empty'));return()=>{};}
  const repeated=recurringWork(data,scopeAudit,options.procedures);
  const reviewModel=window.WorkReview?.project(data,options.graph,scopeAudit,options.procedures),canReview=reviewModel?.available;
  let view=['route','timeline'].includes(options.view)?options.view:canReview?'review':'timeline',lens=options.lens==='procedure'?'procedure':'work',reviewFilter=options.reviewFilter||'all';
  let focusRow=repeated.find(r=>r.id===options.focus)||null;
  if(!focusRow&&view==='review'&&initialVisit)focusRow=repeated.find(r=>r.visits.some(v=>v.id===initialVisit))||null;
  let preferredAllWork=typeof options.allWork==='boolean'?options.allWork:null,allWork=preferredAllWork??!!focusRow;
  const overview=node('details',null,'wn-repeat-overview');overview.open=!focusRow&&view==='route';
  overview.append(node('summary',`Repeated work · ${repeated.length} target${repeated.length===1?'':'s'}`));
  if(repeated.length){
   const table=node('table'),head=node('tr');for(const text of ['Work target',contributions?'Contributions':'Dispatches','Recorded recurrence',...(contributions?[]:['Procedure comparison'])])head.append(node('th',text));table.append(head);
   for(const r of repeated){
    const tr=node('tr'),target=node('td'),button=node('button',r.target,'wn-repeat-target');button.type='button';button.dataset.workFocus=r.id;button.onclick=()=>chooseWork(r);target.append(button);
    const counts=node('td',r.occurrences),patterns=node('td');counts.dataset.label=contributions?'contributions':'dispatches';patterns.append(node('span',r.disputed?'Identity disputed':`${r.returns} returns · ${r.continued} consecutive`));
    if(!r.disputed&&(r.interrupted||r.resumed))patterns.append(node('small',`${r.interrupted} across gaps · ${r.resumed} resumes`));tr.append(target,counts,patterns);
    if(!contributions){const methods=node('td');methods.append(node('span',r.disputed?'Withheld':r.procedure_known?`${r.procedure_changed} changed / ${r.procedure_known} compared`:'Not compared'),node('small',r.disputed?'Review work identity first':r.links.length===r.procedure_known?'All compared':`${r.links.length-r.procedure_known} unresolved pair${r.links.length-r.procedure_known===1?'':'s'}`));tr.append(methods);}table.append(tr);
   }
   const scroll=node('div',null,'wn-repeat-table');scroll.setAttribute('role','region');scroll.setAttribute('aria-label','Repeated work targets');scroll.tabIndex=0;scroll.append(table);overview.append(scroll);
  }else overview.append(node('p','No saved same-work pairs in this observation. This does not establish that every action addresses new work.','wn-note'));
  overview.append(node('p',`Select a target to see its first-to-last recorded window, including intervening work. Counts use saved identity pairs; ${contributions?'contributions are not attempts':'dispatches include reads and checks'}.`,'wn-note'));host.append(overview);
  const focusPanel=node('section',null,'wn-focus-panel');focusPanel.setAttribute('aria-label','Selected work window');host.append(focusPanel);
  function chooseWork(row,notify=true){focusRow=row;allWork=preferredAllWork??!!row;selected=null;selectedLink=null;overview.open=!row&&view==='route';updateFocusPanel();draw();frame.scrollTop=0;if(notify)options.onFocus?.(row?.id||null);}
  function updateFocusPanel(){
   focusPanel.replaceChildren();if(returnControl)returnControl.hidden=!!focusRow;for(const b of overview.querySelectorAll('[data-work-focus]'))b.setAttribute('aria-pressed',String(b.dataset.workFocus===focusRow?.id));
   if(!focusRow){focusPanel.hidden=true;return;}focusPanel.hidden=false;
   const top=node('div',null,'wn-focus-heading'),all=node('button','Whole route');all.type='button';all.onclick=()=>chooseWork(null);top.append(node('h3',focusRow.target),all);focusPanel.append(top);
   const window=workWindow(data,focusRow),intervening=window.visits.length-focusRow.visits.length;
   focusPanel.append(node('p',window.available?`${unit}s ${focusRow.first}–${focusRow.last} · ${focusRow.occurrences} ${contributions?'contributions':'dispatches'} on this target · ${intervening} intervening visit${intervening===1?'':'s'} · ${window.visits.length}/${data.visits.length} route cards shown`:'The saved route is incomplete; showing the whole route.','wn-window-summary'));
   if(focusRow.disputed)focusPanel.append(node('p','Work identity is disputed. Inspect the saved pairs before interpreting this grouping.','wn-note'));
   const pairs=node('div',null,'wn-pair-list');pairs.setAttribute('aria-label','Exact recurrence pairs');
   const labels={continued:'Consecutive',returned:'Return',resumed:'Resume',interrupted:'Gap'};
   let pairSelect=null;if(focusRow.links.length>8){const label=node('label',`${focusRow.links.length} exact recurrence pairs `);pairSelect=node('select');pairSelect.setAttribute('aria-label','Inspect an exact recurrence pair');pairSelect.dataset.pairSelect='true';const placeholder=node('option','Choose a pair…');placeholder.value='';pairSelect.append(placeholder);pairSelect.onchange=()=>{const l=focusRow.links.find(l=>l.id===pairSelect.value);if(l){selected=l.source;selectedLink=l.id;draw();selectLink(l);}};label.append(pairSelect);pairs.append(label);}
   for(const link of focusRow.links){
    const ep=data.episodes.find(e=>e.id===link.episode_id),pos=uid=>{for(const v of focusRow.visits){const i=v.occurrences.findIndex(o=>o.unit_id===uid);if(i>=0)return v.positions[i];}return '?';};
    const text=`${labels[link.category]} · ${unit.toLowerCase()} ${pos(ep.previous_unit_id)} → ${pos(ep.current_unit_id)}`,method=focusRow.procedure_records.find(r=>r.episode_id===link.episode_id),methodText=method&&!focusRow.disputed?({same_procedure:'Same procedure',reconfigured_procedure:'Changed settings / inputs',alternative_procedure:'Different procedure'})[method.procedure]:null;
    if(pairSelect){const option=node('option',text+(methodText?' · '+methodText:''));option.value=link.id;pairSelect.append(option);continue;}
    const b=node('button',text);b.type='button';b.dataset.workLink=link.id;if(methodText)b.append(node('small',methodText));b.onclick=()=>{selected=link.source;selectedLink=link.id;draw();selectLink(link);};pairs.append(b);
   }
   focusPanel.append(pairs);
  }
  const returns=data.links.filter(l=>l.type==='same_work_return'&&l.source!==l.target&&l.category==='returned');
  if(returns.length){
   const control=node('label',null,'wn-return-control'),select=node('select');select.setAttribute('aria-label','Inspect a return to earlier work');
   const empty=node('option','Choose a return…');empty.value='';select.append(empty);
   for(const [i,l]of returns.entries()){const v=data.visits.find(v=>v.id===l.source),o=node('option',`Return ${i+1} · ${short(v?.target||'Earlier work',75)} · ${unit.toLowerCase()} ${v?.positions[0]??'?'}`);o.value=String(i);select.append(o);}
   returnControl=control;returnSelect=select;select.value=returns.some(l=>l.source===selected)?String(returns.findIndex(l=>l.source===selected)):'';
   select.onchange=()=>{if(select.value==='')return;const l=returns[Number(select.value)],row=repeated.find(r=>r.links.includes(l));if(row!==focusRow)chooseWork(row||null);selected=l.source;selectedLink=l.id;draw();selectLink(l);};
   control.append(node('span','Returns to earlier work'),select);host.append(control);
  }
  if(grouping){
   const c=grouping.counts,complete=!c.missing_pairs&&!c.unresolved_pairs&&!c.conflicting_units&&c.bound===c.units,panel=node('section',null,'wn-grouping-coverage'+(complete?' complete':''));panel.setAttribute('aria-label','Work grouping coverage');
   panel.append(node('h3',`${c.observed_pairs}/${c.eligible_pairs} earlier-work comparisons available`),node('p',(complete?'All eligible pairs are observed. Semantic accuracy remains unvalidated.':`Automatic grouping assigns ${c.bound||0}/${c.units} contributions. Missing or contradictory comparisons stay unresolved.`)+(grouping.reviewed_bindings?' '+grouping.reviewed_bindings+' named reviews retained.':'')));
   const positions=new Map(data.visits.flatMap(v=>v.occurrences.map((o,i)=>[o.unit_id,v.positions[i]]))),list=node('div',null,'wn-conflict-list');
   const reasons={readable_target_unavailable:'Readable target needed',missing_pair_evidence:'Missing comparisons',unresolved_pair_evidence:'Pair meaning unresolved',identity_bridges_distinct_groups:'Conflicting identity links',identity_conflicts_with_group_member:'Conflicting group evidence',earlier_membership_unresolved:'Earlier grouping unresolved'};
   for(const row of grouping.records.filter(r=>r.status==='unresolved')){const b=node('button',`Contribution ${positions.get(row.unit_id)??'?'} · ${reasons[row.reason]||row.reason}`);b.type='button';b.onclick=()=>selectGrouping(row);list.append(b);}panel.append(list);host.append(panel);
  }
  if(hasConflicts){
   const warning=node('section',null,'wn-scope-warning');warning.setAttribute('aria-label','Work scope conflicts');
   warning.append(node('h3',`${conflicts.length} conflicts in saved work grouping`),node('p','Work groups and pair judgments disagree. Highlighted cards and their recurrence links need review. Neither observation is treated as ground truth.'));
   const positions=new Map(data.visits.flatMap(v=>v.occurrences.map((o,i)=>[o.unit_id,v.positions[i]])));
   const list=node('div',null,'wn-conflict-list');for(const c of conflicts){const label=c.expected_same?'same work recorded as separate':'different scopes grouped together',b=node('button',`Contributions ${positions.get(c.target_unit_id)??'?'} and ${positions.get(c.source_unit_id)??'?'} · ${label}`);b.type='button';b.onclick=()=>selectConflict(c);list.append(b);}warning.append(list);host.append(warning);
  }else if(contributions&&!grouping){
   const messages={no_conflicts_in_checked_pairs:`No disagreement found across ${scopeAudit?.counts?.checked_pairs||0} eligible pair judgments; ${scopeAudit?.counts?.unresolved_membership||0} have unresolved membership. Untested pairs and semantic accuracy remain unknown.`,no_comparable_pair_evidence:'No eligible pair judgments are available for this check. Work grouping has not been cross-checked.',scope_not_comparable:'This work profile’s scope is not registered for the pair check. Its groups have not been cross-checked.',check_unavailable:'Work grouping cross-check is unavailable. The saved map remains inspectable.'};
   const review=node('details',null,'wn-review-note');review.append(node('summary','Work grouping review'),node('p',messages[scopeAudit?.state]||'Work grouping has not been cross-checked.','wn-note'));host.append(review);
  }
  if(scopeAudit?.excluded?.length)host.append(node('p',`${scopeAudit.excluded.length} pair judgments were excluded because their source or comparison contract could not be established. See Definition and coverage.`,'wn-note'));
  const viewControl=node('div',null,'wn-view-control');viewControl.setAttribute('role','group');viewControl.setAttribute('aria-label','Work path view');
  for(const [value,label]of [...(canReview?[['review','Review repeated work']]:[]),['timeline','Work timeline'],['route','Detailed route']]){const b=node('button',label);b.type='button';b.dataset.workView=value;b.setAttribute('aria-pressed',String(view===value));b.onclick=()=>{view=value;options.onView?.(value);draw();};viewControl.append(b);}if(returnControl)viewControl.append(returnControl);host.append(viewControl);
  const review=node('div');host.append(review);
  const timeline=node('div',null,'wn-timeline');host.append(timeline);
  const key=node('div',null,'wn-key');key.append(node('span','Dashed: source order · purple: same work'));
  for(const[type,label]of [['same_work_return',hasConflicts?'Recorded recurrence · disputed':'Recorded recurrence'],['attempted_correction_for','Correction attempts']]){if(contributions&&type==='attempted_correction_for')continue;const b=node('button',label);b.type='button';b.setAttribute('aria-pressed','true');b.onclick=()=>{enabled.has(type)?enabled.delete(type):enabled.add(type);b.setAttribute('aria-pressed',String(enabled.has(type)));draw();};key.append(b);}host.append(key);
  if(data.context?.relations){for(const[type,label]of [['target','Related work'],['scope','Stated work & requests'],['feedback','Feedback'],['revision','Changes & checks'],['native','Native references']]){if(!data.context.counts[type])continue;const b=node('button',label);b.type='button';b.setAttribute('aria-pressed','true');b.onclick=()=>{enabled.has(type)?enabled.delete(type):enabled.add(type);b.setAttribute('aria-pressed',String(enabled.has(type)));draw();};key.append(b);}const label=node('label','Show connections '),mode=node('select');mode.setAttribute('aria-label','Work relationship visibility');for(const[value,text]of [['selection','Selected card or pair'],['all','All saved links']]){const o=node('option',text);o.value=value;mode.append(o);}mode.onchange=()=>{allConnections=mode.value==='all';draw();};label.append(mode);key.append(label);coverageNotes.push(`${data.context.relations} saved relationships · ${data.context.within_visit} within a visit. Select a card to reveal its connections. Stated-work cards follow the selected action; choose all cards to expand every origin. Grouped lines retain every original witness.`);}
  if(!data.context?.relations){const label=node('label','Connections '),mode=node('select');mode.setAttribute('aria-label','Work relationship visibility');for(const[value,text]of [['selection','Selected card or pair'],['all','All saved links']]){const o=node('option',text);o.value=value;mode.append(o);}mode.onchange=()=>{allConnections=mode.value==='all';draw();};label.append(mode);key.append(label);}
  const frame=node('div',null,'wn-frame'),canvas=svg('svg',{role:'group','aria-label':'Complete work route'});frame.tabIndex=0;frame.setAttribute('role','region');frame.setAttribute('aria-label','Work route canvas; scroll to move');frame.append(canvas);host.append(frame);
  const explanation=node('p','Cards follow recorded order. Consecutive contributions share a card only with explicit work identity. Unresolved cards preserve gaps; separate cards alone do not establish exploration.','wn-note');host.append(explanation);
  const details=node('details');details.append(node('summary','Definition and coverage'),node('p',data.limit,'wn-note'));for(const note of coverageNotes)details.append(node('p',note,'wn-note'));if(data.context)details.append(node('p',data.context.limit,'wn-note'));details.append(node('pre',JSON.stringify({schema:data.schema,graph_id:data.graph_id,counts:data.counts,issues:data.issues,context:data.context},null,2)));host.append(details);
  if(scopeAudit){details.append(node('p',scopeAudit.scope||'The saved graph was not changed.','wn-note'));const download=node('a','Download work grouping check');download.href='/api/work-scope-audit?graph='+encodeURIComponent(data.graph_id)+'&download=1';details.append(download,node('pre',JSON.stringify({state:scopeAudit.state,counts:scopeAudit.counts,excluded:scopeAudit.excluded},null,2)));}
  const names=new Map();let plan=0,request=0;for(const s of [...data.scopes].sort((a,b)=>a.event_index-b.event_index))names.set(s.id,s.properties.scope_kind==='organized_plan'?'Plan '+(++plan):'Request '+(++request));
  function action(n,label,fn){n.setAttribute('role','button');n.setAttribute('tabindex','0');n.setAttribute('aria-label',label);n.onclick=fn;n.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();fn();}};n.append(svg('title',{},label));}
  function sizeFrame(){if(frame.getClientRects().length){frame.style.maxHeight='none';const height=Math.round(Math.max(280,innerHeight-Math.max(12,frame.getBoundingClientRect().top)-28))+'px';if(frame.style.height!==height)frame.style.height=height;}}
  function draw(){
   host.dataset.workView=view;
   for(const b of viewControl.querySelectorAll('[data-work-view]'))b.setAttribute('aria-pressed',String(b.dataset.workView===view));
   const isTimeline=view==='timeline',isReview=view==='review';timeline.hidden=!isTimeline;frame.hidden=view!=='route';key.hidden=view!=='route';explanation.hidden=view!=='route';review.hidden=!isReview;overview.hidden=isReview;focusPanel.hidden=isReview||!focusRow;if(returnControl)returnControl.hidden=isReview||!!focusRow;
   if(isReview){
    WorkReview.render(review,reviewModel,{selected:focusRow?.id,filter:reviewFilter,onSelect:id=>chooseWork(repeated.find(r=>r.id===id)||null),onFilter:value=>{reviewFilter=value;options.onReviewFilter?.(value);draw();},onUnit:id=>options.onUnit?.(id),onPair:link=>{selected=link.source;selectedLink=link.id;selectLink(link);},onTimeline:id=>{view='timeline';options.onView?.(view);chooseWork(repeated.find(r=>r.id===id)||null);}});return;
   }
   if(isTimeline){
    const window=workWindow(data,focusRow);
    WorkTimeline.render(timeline,WorkTimeline.project(data,{scopeAudit,procedureObservations:options.procedures,visitIds:window.available&&focusRow?window.visits.map(v=>v.id):null}),{selectedVisit:selected,selectedLink,allWork,lens,onLens:value=>{lens=value;options.onLens?.(value);draw();timeline.querySelector('[data-lens="'+value+'"]')?.focus({preventScroll:true});},onAllWork:value=>{preferredAllWork=allWork=value;options.onAllWork?.(value);draw();},onVisit:v=>{selected=v.id;selectedLink=null;draw();selectVisit(v);},onPair:l=>{selected=l.source;selectedLink=l.id;draw();selectLink(l);}});
   }
   sizeFrame();
   for(const b of focusPanel.querySelectorAll('[data-work-link]'))b.setAttribute('aria-pressed',String(b.dataset.workLink===selectedLink));const pairSelect=focusPanel.querySelector('[data-pair-select]');if(pairSelect)pairSelect.value=selectedLink||'';
   const window=workWindow(data,focusRow),focusIds=new Set(window.focusIds),visibleIds=new Set(window.visits.map(v=>v.id));
   canvas.setAttribute('aria-label',focusRow&&window.available?'Selected work and intervening visits':'Complete work route');
   const contextNodes=savedContexts.filter(c=>(!focusRow||data.links.some(l=>l.target===c.id&&visibleIds.has(l.source)))&&(c.kind!=='stated_work'||allConnections||selected===c.id||data.links.some(l=>l.target===c.id&&l.source===selected)));
   const active=document.activeElement,focused=canvas.contains(active)?active.closest('[data-link],[data-visit],[data-context]'):null,focusKey=focused?['link','visit','context'].map(k=>[k,focused.dataset[k]]).find(([,value])=>value):null;
   const columns=frame.clientWidth>=1050?3:frame.clientWidth>=690?2:1,width=Math.max(260,frame.clientWidth),left=columns===1?44:55,gutter=columns===1?56:110,cardW=(width-gutter-(columns-1)*36)/columns,cardH=154,positions=new Map();let top=40;
   canvas.replaceChildren();const colors={target:'#3e7f8b',disputed:'#a96618',recorded_next:'#8996a5',same_work_return:'#7754c1',attempted_correction_for:'#147b70',scope:'#b87512',feedback:'#087e9a',revision:'#b44976',native:'#526176'},defs=svg('defs');for(const[type,color]of Object.entries(colors)){const marker=svg('marker',{id:'wn-arrow-'+type,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto'});marker.append(svg('path',{d:'M0,0 L10,5 L0,10 Z',fill:color}));defs.append(marker);}canvas.append(defs);
   if(contextNodes.length){canvas.append(svg('text',{x:left,y:top-14,class:'wn-lane'},'Source context · stated work, requests and inputs'));for(const[i,c]of contextNodes.entries())positions.set(c.id,{x:left+(i%columns)*(cardW+36),y:top+Math.floor(i/columns)*(cardH+32),w:cardW,h:cardH});top+=Math.ceil(contextNodes.length/columns)*(cardH+32)+35;}
   for(const path of window.paths){if(window.paths.length>1)canvas.append(svg('text',{x:left,y:top-14,class:'wn-lane'},'Trajectory '+path.trajectory_id+(path.context_id?' · '+path.context_id:'')));for(const[i,id]of path.visit_ids.entries()){const row=Math.floor(i/columns),col=row%2?columns-1-i%columns:i%columns;positions.set(id,{x:left+col*(cardW+36),y:top+row*(cardH+62),w:cardW,h:cardH,col});}top+=Math.ceil(path.visit_ids.length/columns)*(cardH+62)+35;}
   canvas.setAttribute('viewBox',`0 0 ${width} ${top}`);canvas.setAttribute('width',width);canvas.setAttribute('height',top);
   const lines=svg('g'),cards=svg('g');canvas.append(lines,cards);
   for(const[index,link]of drawingLinks.entries()){
    const a=positions.get(link.source),b=positions.get(link.target);if(!a||!b||link.source===link.target)continue;
    const category=link.type==='work_relation'?link.family:link.type;if(link.type!=='recorded_next'&&!enabled.has(category))continue;const incident=selected===link.source||selected===link.target;if(link.type!=='recorded_next'&&!allConnections&&(selectedLink?link.id!==selectedLink:!incident))continue;let d;
    if(link.type==='recorded_next'){
     if(a.y===b.y){const right=b.x>a.x,x1=right?a.x+a.w:a.x,x2=right?b.x:b.x+b.w;d=`M${x1},${a.y+a.h/2} L${x2},${b.y+b.h/2}`;}
     else d=`M${a.x+a.w/2},${a.y+a.h} C${a.x+a.w/2},${a.y+a.h+31} ${b.x+b.w/2},${b.y-31} ${b.x+b.w/2},${b.y}`;
    }else{const channel=14+(index%3)*10,ay=a.y-16-(index%3)*5,by=b.y-16-(index%3)*5;d=`M${a.x},${a.y+60} H${a.x-12} V${ay} H${channel} V${by} H${b.x-12} V${b.y+60} H${b.x}`;}
    const disputed=link.type==='same_work_return'&&data.visits.some(v=>[link.source,link.target].includes(v.id)&&affected.has(v.group_id));
    const color=disputed?'#a96618':colors[category],g=svg('g',{class:'wn-edge'+(incident?' selected':''),'data-kind':link.type,'data-family':link.family||'','data-link':link.id});g.append(svg('path',{d,fill:'none',stroke:color,'stroke-width':incident?3.5:2.3,opacity:selected&&!incident?0.15:link.type==='recorded_next'?0.55:0.9,'stroke-linejoin':'round','marker-end':'url(#wn-arrow-'+(disputed?'disputed':category)+')',...(link.type==='recorded_next'?{'stroke-dasharray':'5 5'}:disputed?{'stroke-dasharray':'9 3 2 3'}:{})}));
    if(link.type!=='recorded_next'){const hit=svg('path',{d,fill:'none',stroke:'transparent','stroke-width':14}),from=data.visits.find(v=>v.id===link.source),to=data.visits.find(v=>v.id===link.target);action(hit,link.type==='work_relation'?'Inspect '+link.label:(link.type==='same_work_return'?(disputed?'Inspect disputed recurrence':'Inspect recorded recurrence'):'Inspect correction attempt')+` · ${plural} ${from.positions.join(', ')} → ${to.positions.join(', ')}`,()=>selectLink(link));g.append(hit);}lines.append(g);
   }
   for(const c of contextNodes){const p=positions.get(c.id),g=svg('g',{class:'wn-context'+(selected===c.id?' selected':''),'data-context':c.id,transform:`translate(${p.x},${p.y})`}),label=c.kind==='stated_work'?'Stated work':c.kind==='request'?'Expressed request':'Recorded context';action(g,label+' · '+c.label,()=>{selected=c.id;selectedLink=null;draw();selectContext(c);});g.append(svg('rect',{width:p.w,height:p.h,rx:9,fill:'#fffaf1',stroke:selected===c.id?'#a07943':'#dfd2bf','stroke-width':selected===c.id?2:1}),svg('text',{x:16,y:24,class:'wn-position'},label));const maxChars=Math.max(22,Math.floor((p.w-32)/7)),wrap=textLines(c.label,maxChars);wrap.slice(0,4).forEach((line,i)=>g.append(svg('text',{x:16,y:49+i*20,class:'wn-target'},short(line,maxChars)+(i===3&&wrap.length>4?'…':''))));g.append(svg('text',{x:16,y:137,class:'wn-status'},c.kind==='stated_work'?'Source statement · not an extra action':'Context origin · not an agent activity'));cards.append(g);}
   for(const v of window.visits){const p=positions.get(v.id),disputed=affected.has(v.group_id),related=data.links.filter(e=>e.source===v.id||e.target===v.id),color=disputed?'#a96618':related.some(e=>e.type==='attempted_correction_for')?'#419283':related.some(e=>e.type==='same_work_return')?'#8268b5':'#a7afbe',g=svg('g',{class:'wn-card'+(selected===v.id?' selected':'')+(disputed?' scope-conflict':'')+(focusRow?(focusIds.has(v.id)?' focus-work':' intervening-work'):''),'data-visit':v.id,transform:`translate(${p.x},${p.y})`});
    action(g,v.target+` · ${plural} ${v.positions.join(', ')}${disputed?' · scope conflict':''}`,()=>{selected=v.id;selectedLink=null;draw();selectVisit(v);});
    g.append(svg('rect',{width:p.w,height:p.h,rx:9,fill:selected===v.id?'#f2eef9':'white',stroke:selected===v.id?'#9381b9':'#dfe4ed','stroke-width':selected===v.id?2:1}),svg('rect',{width:4,height:p.h-18,x:0,y:9,rx:2,fill:color}));
    const range=v.positions.length===1?String(v.positions[0]):v.positions[0]+'–'+v.positions.at(-1);g.append(svg('text',{x:16,y:24,class:'wn-position'},`${unit} ${range}${!v.order_known?' · order unresolved':''}`));
    const maxChars=Math.max(22,Math.floor((p.w-32)/7)),wrap=textLines(v.target,maxChars);wrap.slice(0,3).forEach((line,i)=>g.append(svg('text',{x:16,y:49+i*20,class:'wn-target'},short(line,maxChars)+(i===2&&wrap.length>3?'…':''))));
    const scope=contributions?[...new Set(v.occurrences.map(p=>p.activity||p.identity_status))].join(' · '):[...v.scope_ids.map(id=>names.get(id)),...[...new Set((v.plan_stages||[]).map(s=>'Plan step: '+(s.text||s.step_id)))]].join(' · ');g.append(svg('text',{x:16,y:116,class:'wn-scope'},short(focusRow?(focusIds.has(v.id)?'Selected work':'Intervening work · relation not inferred'):scope||'No linked plan or request',Math.floor((p.w-32)/5.8))));
    const refs=data.links.filter(e=>e.type==='same_work_return'&&e.source===v.id),fixes=data.links.filter(e=>e.type==='attempted_correction_for'&&e.source===v.id),count=v.connection_ids?.length;const status=disputed?'Scope conflict · review work grouping':grouping&&v.occurrences.some(o=>o.identity_status==='unresolved')?'Work grouping unresolved':`${v.occurrences.length} ${contributions?(v.occurrences.length===1?'contribution':'contributions'):(v.occurrences.length===1?'dispatch':'dispatches')}${count?' · '+count+' saved links':refs.length?' · '+refs.length+' same-work link'+(refs.length===1?'':'s'):''}${fixes.length?' · correction linked':''}`;g.append(svg('text',{x:16,y:137,class:'wn-status'},short(status,Math.floor((p.w-32)/5.8))));cards.append(g);
   }
   const chosen=positions.get(selected);if(chosen&&(chosen.y<frame.scrollTop||chosen.y+chosen.h>frame.scrollTop+frame.clientHeight))frame.scrollTop=Math.max(0,chosen.y-30);
   if(focusKey){const [key,value]=focusKey,element=[...canvas.querySelectorAll('[data-'+key+']')].find(n=>n.dataset[key]===value);(key==='link'?element?.querySelector('[role=button]'):element)?.focus({preventScroll:true});}
  }
  updateFocusPanel();let timelineWidth=0;const resize=new ResizeObserver(entries=>{const changed=view==='timeline'&&timeline.clientWidth!==timelineWidth;timelineWidth=timeline.clientWidth;if(changed||entries.some(e=>e.target===frame&&view==='route'))draw();});resize.observe(frame);resize.observe(timeline);window.addEventListener('resize',sizeFrame);window.addEventListener('scroll',sizeFrame,{passive:true});draw();const dispose=()=>{resize.disconnect();window.removeEventListener('resize',sizeFrame);window.removeEventListener('scroll',sizeFrame);};
  dispose.focusVisit=id=>{if(returnSelect){const i=returns.findIndex(l=>l.source===id);returnSelect.value=i<0?'':String(i);}if(focusRow&&!workWindow(data,focusRow).visits.some(v=>v.id===id))chooseWork(repeated.find(r=>r.visits.some(v=>v.id===id))||null);if(selected!==id){selected=id;selectedLink=null;draw();}};dispose.focusLink=id=>{selectedLink=id;draw();};return dispose;
 }};
})();
