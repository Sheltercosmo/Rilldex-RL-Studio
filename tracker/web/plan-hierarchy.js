/* A mind-map projection of existing source-bound plans and task-list history. */
(()=>{
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 const short=(t,n=240)=>String(t||'').length>n?String(t).slice(0,n-1)+'…':String(t||'');
 function workMeasures(host,data,graph){
  const result=data.work_measures;if(!result)return;
  const names={plan_steps:'Expressed Plan steps',declared_tree:'Producer-declared goals',work_outline:'Reviewed work outline',plan_order:'Declared order'};
  const choices={plan_steps:[['plan_steps_attempted','Steps with linked attempts'],['plan_attempt_dispatches','Distinct Plan attempt dispatches']],declared_tree:[['native_goal_depth','Maximum goal depth'],['native_goals_visited','Goals with recorded visits'],['native_operation_requests','Native operation requests']],plan_order:[['plan_order_departures','Declared-order departures']],work_outline:[['work_outline_depth','Maximum outline depth'],['work_resume_decisions','Resume decisions'],['work_stop_decisions','Stop decisions'],['work_defer_decisions','Deferral decisions']]};
  for(const [basis,p]of Object.entries(result.profiles)){
   if(!p.available)continue;
   const box=el('details',null,'ph-measures'),head=el('summary',null,'ph-measure-head');head.append(el('h3',names[basis]),el('span',basis==='plan_order'?p.compared+' comparable · '+p.unresolved+' unresolved':p.declared+' declared · '+p.observed+' with recorded '+(basis==='declared_tree'?'visits':'linked work'),'ph-note'));box.append(head);
   const numbers=el('div',null,'ph-measure-values');
   for(const [key,label]of choices[basis]){const item=el('div'),value=result.scalars?.[key]??result.cases[key]?.length??0,a=el('a','Track across rollouts →');item.append(el('strong',String(value)),el('span',label));const q=new URLSearchParams({create_measure:key,observer:graph.observer});q.set('experiment',graph.metadata?.experiment||'__unassigned__');a.href='/monitors?'+q;item.append(a);numbers.append(item);}box.append(numbers);
   const details=el('details');details.append(el('summary','Compare branch effort and depth'));let shown=12;
   const tableHost=el('div',null,'ph-effort-table'),more=el('button','Show more branches');more.type='button';
   const rows=result.rows.filter(r=>r.profile===basis).sort((a,b)=>b.effort-a.effort||a.depth_min-b.depth_min||a.label.localeCompare(b.label));
   function draw(){tableHost.replaceChildren();const max=Math.max(1,...rows.map(r=>r.effort));for(const r of rows.slice(0,shown)){
    const row=el('div',null,'ph-effort-row'),a=el('a',r.label);const q=new URLSearchParams({run:graph.run_id,observer:graph.observer,graph:graph.id,level:'plans'});
    if(data.cutoff_event_id)q.set('plan_through',data.cutoff_event_id);
    q.set(basis==='declared_tree'?'work_focus':basis==='work_outline'?'outline_focus':'plan_step',r.id);if(basis==='work_outline')q.set('outline_view','focus');a.href='/semantic-map?'+q;
    const metric=el('div',null,'ph-effort-number');metric.append(el('strong',r.effort+' '+r.effort_unit),el('small','Depth '+(r.depth_min===r.depth_max?r.depth_min:r.depth_min+'–'+r.depth_max)+' · '+(r.observed?r.state:'No recorded visit / linked work')));const bar=el('i');bar.style.width=(100*r.effort/max)+'%';metric.append(bar);row.append(a,metric);tableHost.append(row);
   }more.hidden=shown>=rows.length;}
   more.onclick=()=>{shown+=24;draw();};draw();details.append(tableHost,more,el('p','Root depth is 0. Shared work can have several depths. Parent effort includes descendants where scope is captured; totals across branches can overlap.','ph-note'));box.append(details,el('p','Unobserved branches are not evidence of abandonment. Counts describe saved links, native requests or explicit decisions; they do not establish completed work.','ph-note'));host.append(box);
  }
 }
 let request=0;
 window.PlanHierarchyView={clear(){request++;window.PlanAttemptPath?.clear();window.WorkOutline?.clear();},async render(host,graph,navigateUnit,through=null,onCutoff=()=>{},options={}){
  window.PlanAttemptPath?.clear();
  window.WorkOutline?.clear();
  const context=options.context;
  if(context&&context.graph_id!==graph.id)throw Error('Measured plan context belongs to another saved graph.');
  const preferredRoot=host.querySelector('[aria-label="Plan branch to inspect"]')?.value;
  const ticket=++request;host.replaceChildren(el('p','Loading saved plan structure…','ph-note'));
  const url='/api/work-hierarchy?'+new URLSearchParams({graph:graph.id,...(through?{through}:{})});
  let data;try{const r=await fetch(url);data=await r.json();if(!r.ok)throw Error(data.error||'Plan map unavailable');}catch(e){if(ticket===request)host.replaceChildren(el('p',e.message,'ph-note'));return;}
  if(ticket!==request)return;host.replaceChildren();
  const byId=new Map(data.nodes.map(n=>[n.id,n])),source=new Map(graph.nodes.map(n=>[n.id,n])),viewLinks=[...data.links,...(data.work_outline?.links||[]).map(e=>({...e,label:WorkOutline.names[e.type]||e.type})),...(data.work_outline?.bindings||[]).filter(b=>byId.has(b.scope_node_id)).map(b=>({...b,source:b.item_id,target:b.scope_node_id,type:'same_scope',label:'Same work scope'}))];
  const heading=el('div',null,'ph-heading'),intro=el('div');intro.append(el('h2','Plans & attempts'),el('p',data.work_outline?'Follow objectives and approaches, then inspect the attempts behind them.':'Follow declared steps and the work explicitly linked to them.','ph-note'));heading.append(intro);
  const exportLink=el('a','Export this view');exportLink.href=url+'&download=1';heading.append(exportLink);host.append(heading);
  const controls=el('div',null,'ph-controls'),control=el('label'),select=el('select');select.setAttribute('aria-label','Plan evidence through record');
  for(const record of data.records){const o=el('option',record.label);o.value=record.id;select.append(o);}select.value=through||data.records.at(-1)?.id||'';
  const changeCutoff=id=>{onCutoff(id);window.PlanHierarchyView.render(host,graph,navigateUnit,id,onCutoff,options);};
  select.onchange=()=>changeCutoff(select.value);
  const nativeCount=data.counts.roots-data.counts.plans-(data.declared_tree?.roots||0)-(data.work_outline?.roots.length||0);
  const rootKinds=[data.counts.plans?`${data.counts.plans} expressed plan${data.counts.plans===1?'':'s'}`:null,nativeCount?`${nativeCount} native task list${nativeCount===1?'':'s'}`:null,data.declared_tree?`${data.declared_tree.goals} declared goals`:null].filter(Boolean).join(' · ')||'No recorded plans';
  control.append(el('span','Evidence through'),select);controls.append(control,el('span',data.declared_tree?`${rootKinds} · source-bound parentage and scoped work`:`${rootKinds} · ${data.counts.linked_actions} / ${data.counts.visible_actions} actions linked to plan steps`,'ph-count'));
  const editOutline=el('button','Review work outline'),outlineEditor=el('section');outlineEditor.hidden=true;editOutline.onclick=()=>{outlineEditor.hidden=!outlineEditor.hidden;if(!outlineEditor.hidden)WorkOutline.edit(outlineEditor,graph);};controls.append(editOutline);
  host.append(controls,el('p',data.work_outline?`${data.work_outline.items.length} ${data.work_outline.basis==='model_selected'?'model-selected':'reviewed'} work items. Solid branches show annotated parentage; decisions are attributed statements, not verified outcomes.`:data.declared_tree?'Follow the objective into nested subgoals. Branch states are recorded reports; bars show where operation requests were concentrated.':'Solid branches show declared structure. Preparation, attempt and check are different roles. States on native task lists are agent reports.','ph-legend'));
  host.append(outlineEditor);
  if(context){const banner=el('section',null,'ph-measurement');banner.setAttribute('aria-label','Saved plan measurement');banner.append(el('small',options.measurementLabel||'Saved measurement'),el('h3',context.label),el('p',context.summary),el('p',`Measured at record ${context.cutoff_event_index+1} · ${context.status.replaceAll('_',' ')}. Viewing through record ${data.cutoff_event_index+1} does not change this saved result.`,'ph-note'));
   if(context.reason)banner.append(el('p','Unresolved comparison: '+context.reason.replaceAll('_',' '),'ph-note'));
   if(options.cases?.length>1){const choice=el('select');choice.setAttribute('aria-label','Measured plan case');for(const c of options.cases){const o=el('option',c.label+' · '+c.status.replaceAll('_',' '));o.value=c.id;choice.append(o);}choice.value=context.case_id;choice.onchange=()=>options.onCase?.(choice.value);banner.append(choice);}
   const back=el('button','Back to measured case');back.onclick=()=>options.onBack?.();banner.append(back);
   for(const [url,label] of [[options.measurementUrl,'Download saved measurement'],[options.monitorUrl,'Open monitor ↗']])if(url){const a=el('a',label);a.href=url;banner.append(a);}
   if(data.cutoff_event_index!==context.cutoff_event_index){const restore=el('button','Restore measurement cutoff');restore.onclick=()=>changeCutoff(context.cutoff_event_id);banner.append(restore);}
   host.append(banner);
  }
  if(!data.available){host.append(el('p','No supported plan structure is available through this record. This does not mean the agent had no plan. Unit map and Rollout story retain the observed work.','ph-empty'));return;}
  const rootChoice=el('select');rootChoice.setAttribute('aria-label','Plan branch to inspect');const all=el('option','All recorded plans');all.value='all';rootChoice.append(all);for(const id of data.roots){const n=byId.get(id),o=el('option',n.label);o.value=id;rootChoice.append(o);}const rootControl=el('label');rootControl.append(el('span',data.work_outline?'Work branch':'Plan or task list'),rootChoice);controls.insertBefore(rootControl,controls.children[1]);
  workMeasures(host,data,graph);
  const frame=el('div',null,'ph-canvas');frame.setAttribute('aria-label','Plan branch map');const forest=el('div',null,'ph-forest');frame.append(forest);host.append(frame);
  const lineFrame=el('section',null,'ph-line-frame');lineFrame.hidden=true;frame.after(lineFrame);const layoutLabel=el('label'),layoutChoice=el('select');layoutChoice.setAttribute('aria-label','Plan map representation');for(const [value,label]of [['cards','Detailed map'],['lines','Structure lines']]){const o=el('option',label);o.value=value;layoutChoice.append(o);}layoutLabel.append(el('span','View'),layoutChoice);controls.append(layoutLabel);layoutChoice.value=new URL(location.href).searchParams.get('plan_view')==='lines'?'lines':'cards';
  const detail=el('dialog',null,'ph-detail ph-dialog');detail.hidden=true;detail.setAttribute('aria-label','Plan branch evidence');host.append(detail);
  let detailOrigin=null;
  function closeDetail(){if(detail.open)detail.close();detail.hidden=true;if(detailOrigin?.isConnected)detailOrigin.focus({preventScroll:true});}
  detail.addEventListener('cancel',e=>{e.preventDefault();closeDetail();});
  detail.addEventListener('click',e=>{const b=detail.getBoundingClientRect();if(e.target===detail&&(e.clientX<b.left||e.clientX>b.right||e.clientY<b.top||e.clientY>b.bottom))closeDetail();});
  const openUnit=id=>{closeDetail();navigateUnit(id);};
  function related(id,type){return viewLinks.filter(e=>e.source===id&&(!type||e.type===type));}
  function unitOrigin(id){const n=source.get(id);if(!n)return null;if(n.kind==='unit'||n.kind==='event'||n.kind==='plan_step')return id;
   if(n.kind==='declared_plan_item')return 'event:'+n.properties.event_id;
   if(n.kind==='declared_plan_snapshot')return 'event:'+n.properties.event_id;
   if(['declared_work_node','declared_work_record'].includes(n.kind))return 'event:'+n.properties.evidence.event_id;
   return null;
  }
  function inspect(n){if(!detail.open)detailOrigin=document.activeElement;detail.replaceChildren();detail.hidden=false;const top=el('div',null,'ph-detail-title'),close=el('button','Close evidence');close.onclick=closeDetail;top.append(el('h3',n.label),close);detail.append(top,el('span',n.state||'State not established','ph-state'));
   if(n.canvas_focus||n.canvas_plan){const actions=el('div',null,'ph-dialog-actions');for(const [label,fn] of [['Focus this branch',n.canvas_focus],['Open linked plan attempts',n.canvas_plan]])if(fn){const b=el('button',label);b.onclick=()=>{closeDetail();fn();};actions.append(b);}detail.append(actions);}
   if(n.kind==='outline_item'){
    const observed=n.execution_summary,panel=el('section',null,'ph-execution');panel.setAttribute('aria-label','Linked execution evidence');panel.append(el('h4','Linked actions'));
    if(!observed)panel.append(el('p','Execution not mapped'),el('p','No unique plan binding connects this work item or its subplans to actions. Its decision history remains available below.','wc-signal-note'));
    else{
     const c=observed.counts,grid=el('div',null,'ph-execution-grid');
     for(const [count,label] of [[c.actions,'Unique actions'],[c.attempts,'Attempts'],[c.preparations,'Preparation'],[c.checks,'Checks']]){const cell=el('div');cell.append(el('strong',String(count)),el('span',label));grid.append(cell);}panel.append(grid);
     panel.append(el('p',`Feedback returned: ${c.with_feedback}/${c.actions} actions · Assessed: ${c.with_assessment}/${c.actions}`,'ph-execution-feedback'));
     panel.append(el('p',observed.scope==='direct'?(observed.binding_basis==='reviewed_scopes'?'Actions linked to the reviewed plan scope.':'Actions linked to the plan cited by this approach.'):observed.scope==='descendants'?'Actions belong to linked scopes in subbranches. They do not establish execution of every part of this broader target.':'Includes this item’s linked scope and linked scopes in subbranches.','wc-signal-note'));
     const bindings=(data.work_outline?.bindings||[]).filter(b=>observed.binding_ids?.includes(b.id));
     if(bindings.length){const disclosure=el('details',null,'ph-count-rules');disclosure.append(el('summary',`${bindings.length} reviewed scope ${bindings.length===1?'binding':'bindings'}`));for(const b of bindings){const scope=byId.get(b.scope_node_id),work=byId.get(b.item_id);disclosure.append(el('p',work.label+' ↔ '+(scope?.label||b.scope_node_id)),el('p',b.note,'wc-signal-note'));for(const ref of b.evidence){const open=el('button','Open binding evidence ↗','ph-source');open.onclick=()=>openUnit('event:'+ref.event_id);disclosure.append(open);}}panel.append(disclosure);}
     const records=el('details',null,'ph-execution-records');records.append(el('summary',`Inspect ${c.actions} linked actions`));
     const roleNames={attempts_plan_step:'Attempt',prepares_plan_step:'Preparation',checks_plan_step:'Check'};
     for(const row of observed.rows){const action=byId.get(row.action_id),entry=el('div',null,'ph-execution-row'),read=el('button',`Record ${action.event_index+1} · ${row.roles.map(r=>roleNames[r]).join(' + ')}`,'ph-source');read.onclick=()=>inspect({...action,execution_action:row,comparison_parent:n});entry.append(read,el('strong',short(action.target||action.label,180)));
      const assessments=new Set(row.responses.flatMap(r=>r.assessments.map(a=>a.node_id)));
      entry.append(el('small',`${row.responses.length} returned ${row.responses.length===1?'record':'records'} · ${assessments.size} ${assessments.size===1?'assessment':'assessments'}`));records.append(entry);
     }
     const rules=el('details',null,'ph-count-rules');rules.append(el('summary','How counts are defined'),el('p','One count per action ID. Roles and parent/child totals can overlap. Assessed means at least one returned record has a saved assessment link. Checks and completion reports do not establish passing results. Unlinked work is excluded.','wc-signal-note'));panel.append(records,rules);
    }detail.append(panel);
   }
   if(n.execution_action){const row=n.execution_action,panel=el('section',null,'ph-execution');panel.append(el('h4','Why this action is counted'));
    const roleNames={attempts_plan_step:'Attempt',prepares_plan_step:'Preparation',checks_plan_step:'Check'};
    const shownMemberships=new Set();for(const membership of row.memberships){const key=JSON.stringify([membership.stage_id,membership.roles]);if(shownMemberships.has(key))continue;shownMemberships.add(key);const stage=byId.get(membership.stage_id);panel.append(el('p',membership.roles.map(r=>roleNames[r]).join(' + ')+' · '+stage.label));}
    for(const response of row.responses){const feedback=byId.get(response.node_id),b=el('button',`Returned feedback · record ${feedback.event_index+1}`,'ph-source');b.onclick=()=>inspect({...feedback,comparison_parent:n});panel.append(b);
     for(const id of new Set(response.assessments.map(a=>a.node_id))){const assessment=byId.get(id),a=el('button',`Assessment · record ${assessment.event_index+1}`,'ph-source');a.onclick=()=>inspect({...assessment,comparison_parent:n});panel.append(a);}
     if(!response.assessments.length)panel.append(el('small','No assessment link for this returned record.'));
    }
    if(!row.responses.length)panel.append(el('p','No returned feedback is linked through the selected record.'));
    detail.append(panel);
   }
   if(n.retry_summary){const r=n.retry_summary,panel=el('section',null,'ph-retries');panel.setAttribute('aria-label','Retries in linked plan work');panel.append(el('h4','Repeated work'),el('p',`${r.repeated_attempts} of ${r.attempts} attempts repeat earlier work · ${r.after_reported_error} linked to an error report`));
    const cases=el('details',null,'ph-execution-records');cases.append(el('summary',`Inspect ${r.repeated_attempts} repeated attempts`));
    for(const c of [...r.cases].sort((a,b)=>byId.get(a.action_id).event_index-byId.get(b.action_id).event_index)){const action=byId.get(c.action_id),row=el('div',null,'ph-retry-row'),earlier=c.previous_attempt_ids.map(id=>byId.get(id)),read=el('button','Inspect attempt & feedback');row.append(el('small',`Record ${action.event_index+1} · `+(c.after_reported_error?'Retry after reported error':'Repeated attempt; error link not established')),el('strong',action.target||action.label),el('span','Returns to '+earlier.map(a=>'record '+(a.event_index+1)).join(', ')));
     read.onclick=()=>inspect({...action,label:'Attempt at record '+(action.event_index+1),retry_case:c,comparison_parent:n});row.append(read);cases.append(row);
    }
    if(r.cases.length)panel.append(cases);panel.append(el('p','Unique later attempts in saved return links; excludes checks and preparation. No link does not mean no repetition.','wc-signal-note'));
    detail.append(panel);
   }
   if(n.retry_case){const c=n.retry_case;detail.append(el('p',c.after_reported_error?'A saved relationship connects this attempt to earlier work after an error report. This is not verified recovery.':'The saved graph establishes repeated work, but no error-return relationship is attached to this later attempt.','wc-signal-note'));
    for(const previous of c.previous_attempt_ids){const a=byId.get(previous),prior=el('button',`Earlier attempt · record ${a.event_index+1}`,'ph-source');prior.onclick=()=>inspect({...a,comparison_parent:n});detail.append(prior);
     for(const response of related(previous,'response')){const feedback=byId.get(response.target),b=el('button',`Earlier feedback · record ${feedback.event_index+1}`,'ph-source');b.onclick=()=>inspect({...feedback,comparison_parent:n});detail.append(b);}
     const comparison=data.stage_paths.flatMap(p=>p.return_comparisons||[]).find(v=>v.comparison.current_node_id===c.action_id&&v.comparison.previous_node_id===previous);if(comparison){const b=el('button','Compare inputs & intervening work','ph-source');b.onclick=()=>inspect({id:'retry-comparison',label:`Records ${a.event_index+1} → ${n.event_index+1}`,source_node_ids:[previous,n.id],dispatch_comparison:comparison,comparison_parent:n});detail.append(b);}
    }
   }
   if(n.canvas_summary){const s=n.canvas_summary,grid=el('div',null,'wc-signal-grid');for(const [value,label] of [[s.chosen,'Pursue statements'],[s.resumed,'Resume statements'],[s.alternatives,'Alternative links'],[s.stopped,'Stop statements'],[s.deferred,'Defer statements'],[s.unknown,'Items without a decision']]){const cell=el('div');cell.append(el('strong',String(value)),el('span',label));grid.append(cell);}detail.append(grid,el('p',s.stopDepths.length?'Explicit stops at hierarchy depth '+s.stopDepths.join(', ')+'. Depth uses the shortest annotated path from this root.':'No explicit stop is annotated in this scope. The depth at which the agent stopped exploring is not established.','wc-signal-note'),el('p','These are annotation counts through the selected source record, not an exploration/exploitation ratio. Pursuing work does not establish exploitation; nesting alone does not establish exploration. No linked verification establishes which branch found a correct answer.','wc-signal-note'));n={...n,decisions:s.decisions};}
   if(n.dispatch_comparison)PlanAttemptPath.renderComparison(detail,n.dispatch_comparison,child=>inspect({...child,comparison_parent:n}));
   if(n.decisions?.length){detail.append(el('h4','Branch decision history'));for(const d of n.decisions){const row=el('div',null,'wo-decision'),jump=el('button','Open decision record ↗','ph-source');jump.onclick=()=>openUnit('event:'+d.evidence.event_id);row.append(el('small',`Record ${d.event_index+1} · ${d.type.replaceAll('_',' ')}`));if(d.label)row.append(el('strong',d.label));row.append(el('p',d.evidence.text),jump);
    const follow=d.followthrough;if(follow){const evidence=el('section',null,'ph-decision-window');evidence.append(el('strong','Recorded follow-through'),el('p',WorkOutline.decisionWindowText(follow)),el('small',WorkOutline.decisionWindowBoundary(follow)));
     const unresolved=Object.values(follow.unresolved||{}).reduce((sum,ids)=>sum+ids.length,0);if(unresolved)evidence.append(el('p',`${unresolved} linked records could not be placed in this window.`,'ph-note'));
     if(follow.scope==='descendants'||follow.scope==='mixed')evidence.append(el('small','Includes linked work in subbranches; branch totals may overlap.'));
     if(follow.rows?.length){const records=el('details');records.append(el('summary',`Inspect ${follow.rows.length} linked ${follow.rows.length===1?'action':'actions'}`));for(const actionRow of follow.rows){const action=byId.get(actionRow.action_id);if(!action)continue;const b=el('button',`Record ${action.event_index+1} · ${short(action.target||action.label,120)}`,'ph-source');b.onclick=()=>inspect({...action,execution_action:actionRow,comparison_parent:n});records.append(b);}evidence.append(records);}
     evidence.append(el('small','Saved links in source order. This is not a success or compliance judgment.'));row.append(evidence);
    }detail.append(row);}}
   if(n.comparison_parent){const back=el('button','Back to previous details','ph-source');back.onclick=()=>inspect(n.comparison_parent);detail.append(back);}
   if(n.criterion?.status==='expressed')detail.append(el('p','Expressed criterion: '+n.criterion.text));
   if(n.criterion?.status==='not_expressed')detail.append(el('p','No explicit completion criterion was recorded.','ph-note'));
   if(n.history?.length){detail.append(el('h4','Declaration history'));const list=el('ol',null,'ph-history');for(const row of n.history){const li=el('li');li.append(el('strong',`Record ${row.event_index+1} · ${row.label}`),el('p',row.text));if(context?.item_ids.includes(row.source_node_id)){li.className='ph-measured-history';li.append(el('small','Witness in the saved measurement'));}if(!row.order_known)li.append(el('small','Declaration order unresolved'));list.append(li);}detail.append(list);}
   window.WorkContents?.appendReferences(detail,graph,[...(n.evidence||[]),...(n.decisions||[]).map(d=>d.evidence)],openUnit);
   if(n.source_text)detail.append(el('pre',n.source_text));
   if(n.records?.length){detail.append(el('h4',`${n.operation_count||0} operation requests · ${n.records.length} scoped records`));const last=n.records.filter(r=>['reported_failed','reported_complete','statement','observation'].includes(r.kind)).slice(-4);for(const r of last){detail.append(el('small',`Record ${r.event_index+1} · ${r.kind.replaceAll('_',' ')}`),el('pre',r.evidence.text));const b=el('button','Open this record ↗','ph-source');b.onclick=()=>openUnit('event:'+r.evidence.event_id);detail.append(b);}}
   for(const evidence of n.evidence||[])if(evidence.text&&evidence.text!==n.source_text)detail.append(el('pre',evidence.text));
   const outgoing=related(n.id),incoming=viewLinks.filter(e=>e.target===n.id);
   if(outgoing.length||incoming.length){detail.append(el('h4','Saved connections'));for(const e of [...incoming,...outgoing]){const outgoing=e.source===n.id,target=byId.get(outgoing?e.target:e.source),relation=!outgoing?({part_of:'Contains',depends_on:'Required by',replaces:'Replaced by'}[e.type]||e.label):e.label,p=el('button',relation+' · '+(e.type==='response'?'Record '+(target.event_index+1)+' · '+short(target.source_text||target.label,100):target.label),'ph-connection');p.onclick=()=>n.canvas_inspect&&target.work_kind?n.canvas_inspect(target):inspect(target);detail.append(p);if(e.evidence?.length){const witness=el('details',null,'ph-witness');witness.append(el('summary','Connection evidence'));for(const v of e.evidence)if(v.text)witness.append(el('pre',v.text));detail.append(witness);}}}
   const units=[...new Set((n.source_node_ids||[]).map(unitOrigin).filter(Boolean))];for(const id of units){const record=source.get(id)?.event_index,label=id.startsWith('event:')?'Open record':'Open unit at record';const b=el('button',`${label} ${record==null?'':record+1} ↗`,'ph-source');b.onclick=()=>openUnit(id);detail.append(b);}
   if(!detail.open)detail.showModal();detail.scrollTop=0;close.focus({preventScroll:true});
  }
  function chip(state){const suffix={'Reported complete':' reported-complete','Reported in progress':' reported-active','Reported pending':' reported-pending'}[state]||'';return el('span',state||'State not established','ph-state'+suffix);}
  function markCase(card,node){if(PlanCaseContext.matches(node,context)){card.classList.add('ph-measured');card.append(el('span','Measured item','ph-case-badge'));}}
  for(const rootId of data.roots){const root=byId.get(rootId),row=el('div',null,'ph-root-row'),rootCard=el('button',null,'ph-root');row.dataset.root=rootId;
   if(root.kind==='outline_item'){WorkOutline.render(row,data.work_outline,rootId,inspect,id=>{rootChoice.value=id;rootChoice.onchange();},new Set(data.nodes.filter(n=>n.kind==='plan').map(n=>n.id)),options.onOutlineFocus,options.onOutlineView);forest.append(row);continue;}
   if(root.kind==='native_goal'){NestedWorkTree.render(row,data,rootId,inspect,openUnit,options.onWorkFocus);forest.append(row);continue;}
   if(root.kind==='plan'&&data.stage_paths){PlanAttemptPath.render(row,data,rootId,inspect,options.onPlanStep);forest.append(row);continue;}
   rootCard.type='button';rootCard.append(el('small',root.kind==='task_list'?'NATIVE TASK LIST':'EXPRESSED PLAN'),el('strong',root.label),chip(root.state));markCase(rootCard,root);rootCard.onclick=()=>inspect(root);row.append(rootCard);
   const branches=el('div',null,'ph-branches'),children=related(root.id,'contains');
   for(const link of children){const stage=byId.get(link.target),branch=el('div',null,'ph-branch'),stageBox=el('div',null,'ph-stage'),b=el('button',null,'ph-stage-main');b.type='button';b.append(el('small',stage.kind==='declared_item'?(stage.native_id?'ITEM '+stage.native_id:'LIST ITEM'):'PLAN STEP'),el('strong',stage.label),chip(stage.state));markCase(stageBox,stage);b.onclick=()=>inspect(stage);stageBox.prepend(b);
    const correspondences=related(stage.id).filter(e=>['prepares_plan_step','attempts_plan_step','checks_plan_step'].includes(e.type));
    for(const org of data.links.filter(e=>e.source===stage.id&&['requires','precedes'].includes(e.type)))stageBox.append(el('small',(org.type==='requires'?'Requires: ':'Before: ')+byId.get(org.target).label,'ph-order'));
    const actions=el('div',null,'ph-actions');actions.hidden=true;
    if(correspondences.length){const tail=`${correspondences.length} linked action${correspondences.length===1?'':'s'}`,toggle=el('button','Show '+tail,'ph-expand');toggle.setAttribute('aria-expanded','false');toggle.onclick=()=>{actions.hidden=!actions.hidden;branch.classList.toggle('expanded',!actions.hidden);toggle.setAttribute('aria-expanded',String(!actions.hidden));toggle.textContent=(actions.hidden?'Show ':'Hide ')+tail;};stageBox.append(toggle);
     for(const e of correspondences.sort((a,b)=>byId.get(a.target).event_index-byId.get(b.target).event_index)){const a=byId.get(e.target),card=el('div',null,'ph-action '+e.type),button=el('button',null,'ph-action-main');button.type='button';button.append(el('small',e.label.toUpperCase()+' · RECORD '+(a.event_index+1)),el('strong',a.label));button.onclick=()=>inspect(a);card.append(button);
      for(const response of related(a.id,'response')){const r=byId.get(response.target),preview=RolloutStory.preview(r.source_text||r.label),rb=el('button',null,'ph-response');rb.append(el('small',preview.label),el('span',short(preview.text)));rb.onclick=()=>inspect(r);card.append(rb);}
      for(const rel of related(a.id).filter(r=>!['response','contains'].includes(r.type))){const ref=el('button',rel.label+' · '+short(byId.get(rel.target).label,70),'ph-crosslink');ref.onclick=()=>inspect(byId.get(rel.target));card.append(ref);}actions.append(card);
     }
    }else if(stage.kind==='declared_item')stageBox.append(el('small','Reported list state; action correspondence not established.','ph-note'));
    branch.append(stageBox,actions);branches.append(branch);
   }
   if(!children.length)branches.append(el('p','No declared steps are available.','ph-note'));row.append(branches);forest.append(row);
  }
  let surroundings=null;
  if(context?.item_ids.length&&data.nodes.some(n=>PlanCaseContext.matches(n,context))){const scope=el('label',null,'ph-case-scope');surroundings=el('input');surroundings.type='checkbox';surroundings.setAttribute('aria-label','Show surrounding plan items');scope.append(surroundings,el('span','Show surrounding plan items'));frame.before(scope);surroundings.onchange=()=>rootChoice.onchange();}
  function drawLines(){frame.hidden=layoutChoice.value==='lines';lineFrame.hidden=!frame.hidden;if(!lineFrame.hidden)StructureLines.render(lineFrame,data,rootChoice.value,inspect);}
  layoutChoice.onchange=()=>{const u=new URL(location.href);if(layoutChoice.value==='lines')u.searchParams.set('plan_view','lines');else u.searchParams.delete('plan_view');history.replaceState(null,'',u);drawLines();};
  rootChoice.onchange=()=>{drawLines();const caseRoot=PlanCaseContext.rootFor(data,context),focusOnly=surroundings&&!surroundings.checked&&['all',caseRoot].includes(rootChoice.value);for(const row of forest.children){row.hidden=rootChoice.value!=='all'&&row.dataset.root!==rootChoice.value;for(const branch of row.querySelectorAll('.ph-branch'))branch.hidden=focusOnly&&!branch.querySelector('.ph-measured');}};
  const weight=id=>related(id,'contains').reduce((n,e)=>n+related(e.target).length,0)+(byId.get(id)?.kind==='outline_item'?1000:0);rootChoice.value=PlanCaseContext.rootFor(data,context)||data.links.find(e=>e.type==='contains'&&e.target===new URL(location.href).searchParams.get('plan_step'))?.source||(preferredRoot==='all'||data.roots.includes(preferredRoot)?preferredRoot:[...data.roots].sort((a,b)=>weight(b)-weight(a))[0]);rootChoice.onchange();
  const unplaced=el('details',null,'ph-unplaced');unplaced.append(el('summary',`${data.counts.unassigned_actions} actions without a saved plan-step link`),el('p','These actions may be necessary work, unplanned work or missing annotations. They are not classified as deviation.','ph-note'));
  for(const id of data.unassigned_action_ids){const n=source.get(id),p=n.properties,c=p.content||{},b=el('button','Record '+(n.event_index+1)+' · '+short(c.operation?.text||c.target?.text||c.summary?.text||p.text,150));b.onclick=()=>openUnit(id);unplaced.append(b);}if(!data.declared_tree||data.counts.unassigned_actions)host.append(unplaced);
  const note=el('details',null,'ph-limits');note.append(el('summary','Evidence and limits'),el('p',data.limits),el('p','Projection '+data.id));if(data.issues.length)note.append(el('pre',JSON.stringify(data.issues,null,2)));host.append(note);
 }};
})();
