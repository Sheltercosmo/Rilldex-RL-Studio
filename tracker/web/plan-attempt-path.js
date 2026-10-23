/* One stage's attempts, returned evidence and assessments; no fresh inference. */
((root,factory)=>{const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.PlanAttemptPath=api;})(typeof window==='undefined'?globalThis:window,()=>{
 const roles={prepares_plan_step:'Preparation',attempts_plan_step:'Attempt',checks_plan_step:'Check'};
 const count=(n,label)=>`${n} ${label}${n===1?'':'s'}`;
 const observers=new Set();
 function clear(){for(const observer of observers)observer.disconnect();observers.clear();}
 const plain=value=>String(value||'').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').replace(/\r\n/g,'\n').replace(/\r/g,'\n').trim();
 function comparisonLabel(c){return c.status==='unavailable'?'Input comparison unavailable':c.basis==='recorded_fields'?(c.status==='unchanged'?'Recorded tool and inputs unchanged':'Recorded tool or inputs changed'):(c.status==='unchanged'?'Recorded action text unchanged':'Recorded action text changed');}
 function valueText(v){return !v.present?'(not present)':v.characters===0?'(empty)':v.preview+(v.truncated?'…':'');}
 function changeTitle(row){return row.path==='/text'?'Recorded action text':row.path==='/tool'?'Tool name':row.path.startsWith('/arguments/')?'Input '+row.path.slice('/arguments'.length):row.path||'Recorded inputs';}
 function dispatchRows(path){
  const groups=new Map();
  for(const row of path.rows){
   const id=row.dispatch_id||row.action_id;
   if(!groups.has(id))groups.set(id,{dispatch_id:id,action_id:row.action_id,action_ids:[],roles:[],rows:[],responses:[]});
   const group=groups.get(id);group.rows.push(row);
   if(!group.action_ids.includes(row.action_id))group.action_ids.push(row.action_id);
   for(const role of row.roles)if(!group.roles.includes(role))group.roles.push(role);
   for(const response of row.responses){
    let saved=group.responses.find(r=>r.node_id===response.node_id);
    if(!saved){saved={...response,assessments:[]};group.responses.push(saved);}
    for(const assessment of response.assessments)if(!saved.assessments.some(a=>JSON.stringify(a)===JSON.stringify(assessment)))saved.assessments.push(assessment);
   }
  }
  return [...groups.values()];
 }
 function model(data,rootId){
  const byId=new Map(data.nodes.map(n=>[n.id,n])),byLink=new Map(data.links.map(e=>[e.id,e]));
  const stages=data.links.filter(e=>e.type==='contains'&&e.source===rootId&&byId.get(e.target)?.kind==='plan_step').map(e=>byId.get(e.target));
  const paths=new Map((data.stage_paths||[]).filter(p=>stages.some(s=>s.id===p.stage_id)).map(p=>[p.stage_id,p]));
  function returns(path,actionId){
   // Coalesce parallel evidence about a pair, not distinct earlier targets.
   const pairs=new Map();for(const id of path.return_link_ids||[]){const e=byLink.get(id);if(!e||e.source!==actionId)continue;const pair=pairs.get(e.target)||{target:e.target,links:[],error:false,completed:false};pair.links.push(e);pair.error||=e.type==='revisits_after_error_report';pair.completed||=e.type==='completed_after_failed_call';pairs.set(e.target,pair);}return [...pairs.values()];
  }
  const preferred=stages.slice().sort((a,b)=>(paths.get(b.id)?.counts.actions||0)-(paths.get(a.id)?.counts.actions||0))[0]?.id;
  function between(path,actionId){const position=path.rows.findIndex(r=>r.action_id===actionId);let prior=-1;for(let i=position-1;i>=0;i--)if(path.rows[i].roles.includes('attempts_plan_step')){prior=i;break;}const current=byId.get(actionId),lower=prior<0?-1:byId.get(path.rows[prior].action_id).event_index;return path.rows.slice(prior+1,position).filter(r=>{const n=byId.get(r.action_id);return n.event_index>lower&&n.event_index<current.event_index;});}
  function comparison(path,source,target){return (path.return_comparisons||[]).find(r=>r.comparison.current_node_id===source&&r.comparison.previous_node_id===target);}
  return {byId,byLink,stages,paths,preferred,returns,between,comparison};
 }
 function renderComparison(host,record,inspect){
  const c=record.comparison,el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  const panel=el('section',null,'pap-comparison');panel.setAttribute('aria-label','Recorded input comparison');host.append(panel);
  if(c.basis)panel.append(el('p',c.basis==='recorded_text'?'Comparing recorded action text; native inputs are unavailable or ambiguous.':'Comparing captured tool names and inputs.','pap-guide'));
  if(c.reason)panel.append(el('p',c.reason,'pap-missing'));
  for(const change of c.changes){const row=el('section',null,'pap-input-change');row.append(el('h4',changeTitle(change)));
   const values=change.text_span||change;if(change.text_span)row.append(el('small','Changed span; shared prefix and suffix omitted.'));
   const grid=el('div',null,'pap-input-values');for(const [key,label]of [['before','Earlier'],['after','Later']]){const side=el('div');side.append(el('small',label),el('pre',valueText(values[key])));if(values[key].truncated)side.append(el('small',`Preview of ${values[key].characters} characters; full value remains in source.`));grid.append(side);}row.append(grid);panel.append(row);
  }
  if(c.status==='unchanged')panel.append(el('p','The captured dispatch is unchanged. This does not establish unchanged files, environment, or effects.','pap-guide'));
  if(c.changes_truncated)panel.append(el('p','More changed fields remain in the original source; this bounded view shows the first 64.','pap-guide'));
  if(c.ordering==='source_order'){
   panel.append(el('h4','Work recorded between these endpoints'));
   if(!record.intervening.length)panel.append(el('p','No intervening action is captured in this source context. This does not rule out external state changes.','pap-guide'));
   for(const n of record.intervening){const b=el('button',null,'pap-context-action');b.append(el('small',`Record ${n.event_index+1} · `+(n.linked_to_step?n.roles.map(r=>roles[r]).join(' / '):'Not linked to this plan step')),el('span',n.label));b.onclick=()=>inspect({...n,state:'Recorded intervening work; causal effect unestablished'});panel.append(b);}
  }
  const limits=el('details',null,'pap-comparison-limits');limits.append(el('summary','How to read this comparison'),el('p',c.limits,'pap-guide'));
  if(c.basis==='recorded_fields')limits.append(el('p','Object key order is ignored; list order, types and missing values are preserved.','pap-guide'));panel.append(limits);
 }
 function render(host,data,rootId,inspect,onStep){
  const m=model(data,rootId),root=m.byId.get(rootId),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  const shell=el('section',null,'pap-shell');shell.setAttribute('aria-label','Plan and attempt path');host.append(shell);
  let selected=m.paths.has(new URL(location.href).searchParams.get('plan_step'))?new URL(location.href).searchParams.get('plan_step'):m.preferred;
  const banner=el('button',null,'pap-plan');banner.append(el('small','EXPRESSED PLAN'),el('strong',root.target||root.label));banner.onclick=()=>inspect(root);shell.append(banner);
  const selector=el('div',null,'pap-stages');selector.setAttribute('aria-label','Declared plan steps');shell.append(selector);
  const body=el('section',null,'pap-body');shell.append(body);let resize=null;
  function showEvidence(node){inspect(node);}
  function inspectReturn(pair){const a=m.byId.get(pair.links[0].source),b=m.byId.get(pair.target);
   inspect({id:'path-connection',label:`Return from record ${a.event_index+1} to work at record ${b.event_index+1}`,state:pair.error?'Same target revisited after an error report':'Same immediate work target',source_node_ids:[a.id,b.id],history:[],source_text:'',evidence:[...new Map(pair.links.flatMap(e=>e.evidence||[]).map(e=>[JSON.stringify(e),e])).values()]});
  }
  function draw(){
   resize?.disconnect();observers.delete(resize);selector.replaceChildren();body.replaceChildren();
   for(const [i,s] of m.stages.entries()){
    const p=m.paths.get(s.id),b=el('button',null,'pap-stage');b.type='button';b.setAttribute('aria-pressed',String(s.id===selected));b.append(el('small','STEP '+(i+1)),el('strong',s.label),el('span',p?.counts.actions?[count(p.counts.attempts,'attempt'),count(p.counts.preparations,'preparation'),count(p.counts.checks,'check')].join(' · '):'No linked actions observed'));
    b.onclick=()=>{selected=s.id;const u=new URL(location.href);u.searchParams.set('plan_step',selected);if(onStep)onStep(selected);else history.replaceState(null,'',u);draw();};selector.append(b);
    for(const link of data.links.filter(e=>e.source===s.id&&['precedes','requires'].includes(e.type))){const label=(link.type==='precedes'?'Stated before: ':'Requires: ')+m.byId.get(link.target).label;if(link.type==='precedes'&&m.stages[i+1]?.id===link.target){const d=el('span','→','pap-order');d.title=label;d.setAttribute('aria-label',label);selector.append(d);}else b.append(el('span',label,'pap-dependency'));}
   }
   const path=m.paths.get(selected);if(!path)return;
   const title=el('div',null,'pap-heading'),copy=el('div');copy.append(el('small','ATTEMPT PATH'),el('h3',m.byId.get(selected).label));title.append(copy);
   const counts=el('div',null,'pap-counts');counts.append(el('strong',`${path.counts.attempts} attempts`),el('span',`${path.counts.with_feedback} / ${path.counts.actions} actions with feedback`),el('span',`${path.counts.with_assessment} with linked assessment`));if(path.retry_summary)counts.append(el('span',`${path.retry_summary.repeated_attempts} repeated attempts · ${path.retry_summary.after_reported_error} ${path.retry_summary.after_reported_error===1?'retry':'retries'} after reported error`));title.append(counts);body.append(title);
   const note=el('p','Read across: dispatched work → returned feedback → the agent’s assessment. Dashed vertical line = source order. Violet return links = saved same-target relationships.','pap-guide');body.append(note);
   if(!path.rows.length){body.append(el('p','No actions are linked to this step through the selected record.','pap-empty'));return;}
   const tools=el('div',null,'pap-toolbar'),all=el('button','All linked work'),attempts=el('button','Compare attempts'),scope=el('span',`${count(path.counts.preparations,'preparation')} · ${count(path.counts.checks,'check')} · ${count(path.counts.returns,'action')} with return links`);all.setAttribute('aria-pressed','true');attempts.setAttribute('aria-pressed','false');tools.append(all,attempts,scope);body.append(tools);
   const columns=el('div',null,'pap-columns');for(const text of ['Dispatched work','Returned feedback','Agent assessment'])columns.append(el('span',text));body.append(columns);
   const trail=el('div',null,'pap-trail'),svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.classList.add('pap-return-rails');svg.setAttribute('aria-hidden','true');trail.append(svg);body.append(trail);
   const cards=new Map(),interludes=new Map(),dispatches=dispatchRows(path);let attemptNumber=0;
   for(const row of dispatches){const a=m.byId.get(row.action_id),article=el('article',null,'pap-row');article.dataset.action=a.id;article.dataset.dispatch=row.dispatch_id;for(const id of row.action_ids)cards.set(id,article);
    const left=el('div',null,'pap-action');if(row.roles.includes('attempts_plan_step'))attemptNumber++;
    const meta=el('div',null,'pap-meta');for(const role of row.roles)meta.append(el('span',roles[role]+(role==='attempts_plan_step'?' '+attemptNumber:''),'pap-role '+role));meta.append(el('span',`Record ${a.event_index+1}`,'pap-record'));left.append(meta);
    if(row.action_ids.length>1)left.append(el('small',`${row.action_ids.length} activity units in this call`,'pap-record'));
    for(const id of row.action_ids){const n=m.byId.get(id),action=el('button',n.target||n.label,'pap-action-title');action.onclick=()=>showEvidence(n);left.append(action);
     if(n.operation&&n.operation!==n.target)left.append(el('p',n.operation,'pap-operation'));
     for(const pair of m.returns(path,id)){const b=m.byId.get(pair.target),link=el('div',null,'pap-return'),jump=el('button',`${pair.error?'After error report · ':''}Same work as record ${b.event_index+1}`),evidence=el('button','Relationship evidence');jump.onclick=()=>{all.click();const card=cards.get(pair.target);card.scrollIntoView({block:'center',behavior:'auto'});card.classList.add('pap-highlight');setTimeout(()=>card.classList.remove('pap-highlight'),1800);};evidence.onclick=()=>inspectReturn(pair);link.append(jump);
      const record=m.comparison(path,id,pair.target);if(record){const c=record.comparison,compare=el('button','Compare inputs & intervening work','pap-compare-button');link.append(el('strong',comparisonLabel(c),'pap-change-summary'));compare.onclick=()=>inspect({id:'dispatch-comparison:'+c.id,label:`What changed · records ${b.event_index+1} → ${n.event_index+1}`,state:comparisonLabel(c),source_node_ids:[b.id,n.id],dispatch_comparison:record});link.append(compare);}link.append(evidence);left.append(link);}
    }
    const middle=el('div',null,'pap-feedback'),right=el('div',null,'pap-assessment');
    if(!row.responses.length)middle.append(el('p','No linked response in this view.','pap-missing'));
    const assessed=new Map();for(const response of row.responses){const r=m.byId.get(response.node_id),box=el('div',null,'pap-response'),raw=plain(r.source_text||r.label);box.append(el('small',`RETURNED · RECORD ${r.event_index+1}`));const text=el('p',raw.slice(0,360)+(raw.length>360?'…':''),'pap-excerpt');box.append(text);
     const evidence=el('button','Read returned evidence','pap-inline');evidence.onclick=()=>showEvidence(r);box.append(evidence);middle.append(box);
     for(const assessment of response.assessments){const previous=assessed.get(assessment.node_id)||{node:m.byId.get(assessment.node_id),records:[]};previous.records.push(r.event_index+1);assessed.set(assessment.node_id,previous);}
    }
    for(const {node:n,records}of assessed.values()){const box=el('div',null,'pap-review');box.append(el('small',`ASSESSMENT · RECORD ${n.event_index+1}`),el('p',n.summary||n.source_text||n.label),el('span',`Assesses feedback at record${records.length>1?'s':''} ${records.join(', ')}`,'pap-review-source'));const b=el('button','Inspect assessment','pap-inline');b.onclick=()=>showEvidence(n);box.append(b);right.append(box);}
    if(!assessed.size)right.append(el('p','No assessment link saved.','pap-missing'));
    if(row.roles.includes('attempts_plan_step')){const between=m.between(path,row.rows.find(r=>r.roles.includes('attempts_plan_step')).action_id);if(between.length){const context=el('div',null,'pap-between');context.hidden=true;context.append(el('small',attemptNumber===1?'LINKED WORK BEFORE FIRST ATTEMPT':'OTHER LINKED WORK SINCE PRIOR ATTEMPT'));for(const r of between){const n=m.byId.get(r.action_id),b=el('button',n.target||n.label);b.onclick=()=>showEvidence(n);context.append(b);}trail.append(context);interludes.set(a.id,context);}}
    article.append(left,middle,right);trail.append(article);
   }
   const lastAttempt=dispatches.map(r=>r.roles.includes('attempts_plan_step')).lastIndexOf(true);
   if(lastAttempt>=0&&lastAttempt<dispatches.length-1){const tail=el('div',null,'pap-between');tail.hidden=true;tail.append(el('small','LINKED WORK AFTER FINAL RECORDED ATTEMPT'));for(const row of dispatches.slice(lastAttempt+1))for(const id of row.action_ids){const n=m.byId.get(id),b=el('button',n.summary||n.target||n.label);b.onclick=()=>showEvidence(n);tail.append(b);}trail.append(tail);interludes.set('tail',tail);}
   function drawRails(){if(!trail.isConnected)return;svg.replaceChildren();svg.setAttribute('viewBox',`0 0 32 ${Math.max(1,trail.offsetHeight)}`);svg.style.height=trail.offsetHeight+'px';let index=0;
    const drawn=new Set();for(const row of path.rows){const start=cards.get(row.action_id);if(start.hidden)continue;for(const pair of m.returns(path,row.action_id)){const end=cards.get(pair.target),key=JSON.stringify([start.dataset.dispatch,end?.dataset.dispatch]);if(!end||end.hidden||end===start||drawn.has(key))continue;drawn.add(key);const y1=start.offsetTop+30,y2=end.offsetTop+30,x=4+(index++%3)*7,p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',`M30 ${y1} H${x+5} Q${x} ${y1} ${x} ${y1-5} V${y2+5} Q${x} ${y2} ${x+5} ${y2} H30 m-5 -4 5 4 -5 4`);svg.append(p);}}
   }
   function filter(only){all.setAttribute('aria-pressed',String(!only));attempts.setAttribute('aria-pressed',String(only));for(const row of dispatches){const card=cards.get(row.action_id);card.hidden=only&&!row.roles.includes('attempts_plan_step');card.classList.remove('pap-last');}const visible=[...new Set(cards.values())].filter(n=>!n.hidden);visible.at(-1)?.classList.add('pap-last');for(const node of interludes.values())node.hidden=!only;drawRails();}
   all.onclick=()=>filter(false);attempts.onclick=()=>filter(true);resize=new ResizeObserver(()=>{if(!trail.isConnected){resize.disconnect();observers.delete(resize);return;}drawRails();});observers.add(resize);resize.observe(trail);requestAnimationFrame(drawRails);
   filter(path.counts.returns>0);
   if(path.other_action_ids.length)body.append(el('p',`${path.other_action_ids.length} other action${path.other_action_ids.length===1?'':'s'} occur in the same recorded span and remain outside this step. Open the Unit map to inspect them.`, 'pap-guide'));
   body.append(el('p','Preparation can include edits and prerequisite work. It is not automatically a repair. Agent assessments are claims; a later call or a quiet response does not establish success.','pap-guide'));
  }
  draw();
 }
 return {model,render,renderComparison,comparisonLabel,valueText,changeTitle,plain,clear,dispatchRows};
});
