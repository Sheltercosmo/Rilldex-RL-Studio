/* A readable projection of saved evidence. No semantic inference or model calls. */
(function(root){
 'use strict';
 const mapAPI=typeof module!=='undefined'?require('./map-layout.js'):root.RolloutMapLayout;
 const text=v=>typeof v==='string'?v:v?.text||'';
 const clean=v=>text(v).replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').trim();
 // Display limits never change the source used by search, relationships or evidence.
 function excerpt(value,maxChars=420,maxLines=6){
  const raw=clean(value),head=raw.split(/\r?\n/).slice(0,maxLines).join('\n');
  return head.length<raw.length||head.length>maxChars?head.slice(0,maxChars-1).trimEnd()+'…':head;
 }
 const headingText=value=>excerpt(clean(value).replace(/\s+/g,' '),160,1);
 const names={assesses:'Assesses feedback',uses_evidence:'Uses evidence',responds_to:'Responds to',revises:'Revises',changes_attempt_procedure:'Changes procedure',changes_attempt_prerequisite:'Changes prerequisite',attempts_local_adjustment:'Attempts a local change',adjustment_before_retry:'Change before retry',revisits_after_error_report:'Returns after an error report',completed_after_failed_call:'Completed call after failed call',same_work_target:'Same question or outcome',overlapping_work_scope:'Partly shared work',different_work_same_subject:'Different work on the same subject',alternative_procedure:'Alternative procedure',reconfigured_procedure:'Reconfigured procedure',uses_correction_from:'Uses an earlier correction',attempts_plan_step:'Attempts plan step',prepares_plan_step:'Prepares plan step',checks_plan_step:'Checks plan step',recorded_recheck_of:'Rechecks a criterion'};
 const changeTypes=new Set(['revises','changes_attempt_procedure','changes_attempt_prerequisite','attempts_local_adjustment','adjustment_before_retry','revisits_after_error_report','completed_after_failed_call','alternative_procedure','reconfigured_procedure','uses_correction_from']);
 const reactionTypes=new Set(['assesses','uses_evidence','responds_to']);
 function operation(n){
  const p=n.properties||{},raw=clean(p.source?.text||p.text),fields=p.content||{};
  if(raw&&raw.length<=240&&!/[\r\n]/.test(raw))return {text:raw.replace(/^Running command:\s*/,''),basis:'Recorded action'};
  const annotation=clean(fields.change)||clean(fields.operation)||clean(fields.summary);
  return {text:annotation||n.summary||n.target||'Action text unavailable',basis:annotation?'Action annotation':'Recorded action'};
 }
 function diagnosticLines(lines){return lines.filter(s=>/^(?:[\w.]*Error:|ERROR:|\[WARNING\]|WARNING:|Error:)/.test(s)||/\b(?:not found|No such file or directory|Permission denied)\b/.test(s));}
 function outputExcerpt(raw){
  const lines=raw.split(/[\r\n]+/).map(s=>s.trim()).filter(Boolean).map(s=>/^!\[[^\]]*\]\(data:image\/[\w.+-]+;base64,[A-Za-z0-9+/=]+\)$/.test(s)?'[Embedded image in source record]':s);
  // Exact excerpts, not failure classifications. Full source remains attached.
  const diagnostic=diagnosticLines(lines);
  if(diagnostic.length)return diagnostic.slice(0,3).join('\n').slice(0,260);
  const useful=lines.filter(s=>!/^\[(?:Python Interpreter:|Jupyter |this is the (?:beginning|end) of the file)/i.test(s)&&!/^\(this is the (?:beginning|end) of the file\)/i.test(s)&&!/^\S+@\S+:.*\$/.test(s));
  return useful.slice(0,3).join('\n').slice(0,260)||'No output text beyond environment metadata.';
 }
 function preview(value){const result=responsePreview(value);return {...result,text:excerpt(result.text)};}
 function responsePreview(value){
  const raw=clean(value);let data;
  try{data=JSON.parse(raw);}catch{const notable=diagnosticLines(raw.split(/[\r\n]+/).map(s=>s.trim())).length>0;return {kind:'text',label:notable?'Error / warning text · inspect context':raw?'Output excerpt':'Empty response',notable,text:raw?outputExcerpt(raw):'The response record contains no text.',raw};}
  // Describe fields, not execution success. Nested error strings may be retrieved content.
  if(data&&typeof data==='object'&&!Array.isArray(data)){
   if(typeof data.error==='string'&&data.error.trim())return {kind:'error-field',label:'Returned error field',notable:true,text:data.error,raw};
   const docs=Array.isArray(data.result)?data.result.flat(1):[];
   if(docs.length&&docs.every(d=>d?.document&&typeof d.document.contents==='string'))return {kind:'documents',label:`${docs.length} retrieved documents`,text:docs[0].document.contents.replace(/\\n/g,'\n').replace(/\\"/g,'"'),raw};
   const fields=Object.entries(data).filter(([,v])=>v===null||['string','number','boolean'].includes(typeof v)).slice(0,6);
   if(fields.length)return {kind:'fields',label:'Returned fields',text:fields.map(([k,v])=>`${k}: ${v===null?'null':v}`).join('\n'),raw};
  }
  return {kind:'structured',label:'Structured response',text:JSON.stringify(data,null,2),raw};
 }
 function project(graph,run,layout){
  const all=new Map(graph.nodes.map(n=>[n.id,n])),nodes=layout.nodes,byId=layout.byId,edges=layout.edges;
  const event=n=>all.get(n.kind==='event'?n.id:'event:'+n.properties.source?.event_id);
  const actor=n=>n.properties.actor||event(n)?.properties.actor||'';
  const key=n=>JSON.stringify([n.trajectory_id,actor(n)]);
  const isAction=n=>n.properties.kind==='action',isFeedback=n=>n.lane===2;
  const isRequest=n=>actor(n)==='user'||n.kind==='event'&&n.properties.kind==='instruction';
  const requests=nodes.filter(isRequest),context=nodes.filter(n=>n.kind==='event'&&['system','developer'].includes(actor(n)));
  const actions=nodes.filter(isAction),owner=new Map(),moments=[],byBatch=new Map();
  // Only an explicit source parent groups sibling dispatches. Display order is not execution order.
  for(const n of actions){const parent=event(n)?.properties.parent_id,batch=parent?JSON.stringify([key(n),parent]):n.id;
   let m=byBatch.get(batch);if(!m){m={id:n.id,trajectory:n.trajectory_id,actor:actor(n),actions:[],contributions:[],feedback:[],extras:[],links:[]};byBatch.set(batch,m);moments.push(m);}
   m.actions.push(n);owner.set(n.id,m);
  }
  function attach(n,targets,bucket){const owners=[...new Set(targets.map(id=>owner.get(id)).filter(Boolean))];if(owners.length!==1||owners[0].trajectory!==n.trajectory_id)return false;const m=owners[0];m[bucket].push(n);owner.set(n.id,m);return true;}
  for(const n of nodes.filter(isFeedback)){
   const targets=edges.filter(e=>['feedback_for','response_to'].includes(e.type)&&e.source===n.id).map(e=>e.target);
   attach(n,targets,'feedback');
  }
  for(const n of nodes.filter(n=>!isAction(n)&&!isFeedback(n)&&!isRequest(n)&&!context.includes(n))){
   const targets=edges.filter(e=>['recorded_with','parent_message'].includes(e.type)&&e.source===n.id).map(e=>e.target);
   if(targets.every(id=>!byId.has(id)||key(byId.get(id))===key(n)))attach(n,targets,'contributions');
  }
  for(const n of nodes){if(owner.has(n.id)||requests.includes(n)||context.includes(n))continue;
   // A plan step stays alongside its declared plan, never becomes an attempted action.
   const parent=edges.find(e=>e.type==='contains_plan_step'&&e.target===n.id);
   if(parent&&owner.has(parent.source)){const m=owner.get(parent.source);m.extras.push(n);owner.set(n.id,m);continue;}
   const m={id:n.id,trajectory:n.trajectory_id,actor:actor(n),actions:[],contributions:[],feedback:isFeedback(n)?[n]:[],extras:isFeedback(n)?[]:[n],links:[]};moments.push(m);owner.set(n.id,m);
  }
  const members=m=>[...m.actions,...m.contributions,...m.feedback,...m.extras];
  moments.sort((a,b)=>Math.min(...members(a).map(n=>n.ordinal??Infinity))-Math.min(...members(b).map(n=>n.ordinal??Infinity)));
  const relations=[];
  for(const e of edges){if(!names[e.type])continue;const from=owner.get(e.source),to=owner.get(e.target);if(!from||!to)continue;
   const row={...e,label:names[e.type],from:from.id,to:to.id,within:from===to};from.links.push(row);relations.push(row);
  }
  const stable=v=>Array.isArray(v)?v.map(stable):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,stable(v[k])])):v;
  const occurrences=new Map();
  for(const n of actions){const p=event(n)?.properties||n.properties,k=JSON.stringify([key(n),stable({tool:p.tool??null,arguments:p.arguments??null,text:p.text??p.source?.text??null})]);if(!p.text&&!p.source?.text&&!p.tool)continue;if(!occurrences.has(k))occurrences.set(k,[]);occurrences.get(k).push(n);}
  const repetitionGroups=[...occurrences.values()].filter(rows=>rows.length>1).map(rows=>({actionIds:rows.map(n=>n.id),momentIds:[...new Set(rows.map(n=>owner.get(n.id)?.id).filter(Boolean))],operation:operation(rows[0]).text}));
  const repetitions=new Map(repetitionGroups.flatMap(g=>g.actionIds.map(id=>[id,g])));
  for(const [i,m]of moments.entries()){
   m.number=i+1;m.nodes=members(m).sort((a,b)=>(a.ordinal??Infinity)-(b.ordinal??Infinity));
   m.callLinked=m.feedback.some(n=>mapAPI.capturedResponses(layout,n.id).some(r=>r.response_card_ids.includes(n.id)));
   m.title=m.actions.length>1?m.actions.map(n=>n.target||n.summary).join(' / '):m.actions[0]?.target||m.actions[0]?.summary||m.extras[0]?.target||m.extras[0]?.summary||(m.feedback.length?(m.callLinked?'Captured response · unit pairing unresolved':'Unpaired response'):'Recorded contribution');
   m.displayTitle=headingText(m.title);
   m.responses=m.feedback.map(n=>({node:n,...preview(n.properties.source?.text||n.properties.text),reactions:relations
    .filter(e=>reactionTypes.has(e.type)&&e.target===n.id&&byId.get(e.source)?.trajectory_id===n.trajectory_id)
    .map(e=>({edge:e,node:byId.get(e.source),momentId:owner.get(e.source).id,actor:actor(byId.get(e.source))}))}));
   m.attempts=m.actions.map(n=>({node:n,operation:operation(n),repetition:repetitions.get(n.id)||null,responses:m.responses.filter(r=>edges.some(e=>['feedback_for','response_to'].includes(e.type)&&e.source===r.node.id&&e.target===n.id)),capturedResponses:mapAPI.capturedResponses(layout,n.id).filter(r=>r.action_card_ids.includes(n.id)).map(r=>({...r,...preview(r.response.properties.text)}))}));
   m.checks=m.nodes.flatMap(n=>mapAPI.stateEvidence(graph,n.id).checks).filter((n,i,a)=>a.findIndex(v=>v.id===n.id)===i);
   m.hasChange=m.links.some(e=>changeTypes.has(e.type));
   m.hasSignal=m.hasChange||m.responses.some(r=>r.notable)||m.attempts.some(a=>a.capturedResponses.some(r=>r.notable))||m.checks.length>0||m.links.some(e=>reactionTypes.has(e.type));
   m.activity=[...new Set(m.nodes.filter(n=>!isFeedback(n)).map(n=>n.activity))];
   m.basis=m.nodes.some(n=>n.kind==='unit')?'Saved annotations':'Source records';
  }
  const reports=nodes.filter(n=>n.activity==='report'&&actor(n)==='agent');
  const latestAgentText=nodes.filter(n=>actor(n)==='agent'&&['message','reasoning','semantic'].includes(n.properties.kind)&&clean(n.properties.source?.text||n.properties.text)).at(-1)||null;
  const outcome=run.outcome||{},recorded=[];
  const success=typeof outcome.verified_success==='boolean'?outcome.verified_success:outcome.success;
  if(typeof success==='boolean')recorded.push({label:'Recorded success',value:String(success)});
  const reward=typeof outcome.recorded_reward==='number'?outcome.recorded_reward:outcome.reward;
  if(typeof reward==='number'&&Number.isFinite(reward))recorded.push({label:'Recorded reward',value:String(reward)});
  if(typeof outcome.score==='number'&&Number.isFinite(outcome.score))recorded.push({label:'Recorded score',value:String(outcome.score)});
  if(outcome.source_final_annotation)recorded.push({label:'Dataset final label',value:JSON.stringify(outcome.source_final_annotation.value)});
  const focus=nodes.find(n=>n.kind==='unit'&&actor(n)==='agent'&&n.properties.kind==='semantic'&&text(n.properties.content?.focus));
  return {schema:'rollout-story/1',graphId:graph.id,requests,context,moments,relations,reports,latestAgentText,recorded,focus,repetitionGroups,represented:nodes.length,semantic:layout.semantic,
   counts:{moments:moments.length,actions:actions.length,feedback:nodes.filter(isFeedback).length,changes:relations.filter(e=>changeTypes.has(e.type)).length,signals:moments.filter(m=>m.hasSignal).length,
    notableOutputs:new Set(moments.flatMap(m=>[...m.responses.filter(r=>r.notable).map(r=>event(r.node)?.id||r.node.id),...m.attempts.flatMap(a=>a.capturedResponses.filter(r=>r.notable).map(r=>r.response.id))])).size,repeatedDispatches:repetitionGroups.reduce((n,g)=>n+g.actionIds.length-1,0),
    feedbackWithFollowup: new Set(moments.flatMap(m=>m.responses.filter(r=>r.reactions.length).map(r=>r.node.id))).size},
   limit:'Whole-rollout view. Order is recorded sequence, not causality. Saved summaries and relationships can be wrong; missing links remain unknown.'};
 }
 function matches(m,filter,query=''){
  const hasUse=m.responses.some(r=>r.reactions.length);
  const captured=m.attempts.flatMap(a=>a.capturedResponses||[]);
  const included=filter==='repeated'?m.attempts.some(a=>a.repetition):filter==='output'?m.responses.some(r=>r.notable)||captured.some(r=>r.notable):filter==='linked'?hasUse:filter==='changes'?m.hasChange:filter==='checks'?m.checks.length>0:filter==='unlinked'?m.responses.some(r=>!r.reactions.length):filter==='missing'?m.attempts.some(a=>!a.responses.length&&!a.capturedResponses?.length):true;
  const needle=query.trim().toLocaleLowerCase();
  return Boolean(included)&&(!needle||[m.title,...m.nodes.map(n=>clean(n.properties.source?.text||n.properties.text)||n.summary),...captured.map(r=>r.raw),...m.responses.flatMap(r=>r.reactions.map(a=>clean(a.node.properties.source?.text||a.node.properties.text)||a.node.summary))].join('\n').toLocaleLowerCase().includes(needle));
 }
 const api={project,preview,names,outputExcerpt,operation,matches,excerpt};
 if(typeof module!=='undefined'){module.exports=api;return;}
 const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 function disclosure(label,body){const d=node('details');body.classList.add('rs-disclosure-body');body.tabIndex=0;body.setAttribute('role','region');body.setAttribute('aria-label',label);d.append(node('summary',label),body);return d;}
 function render(host,data,graph,openUnit,options={}){
  host.replaceChildren();const byMoment=new Map(data.moments.map(m=>[m.id,m])),cards=new Map();
  const heading=node('div',null,'rs-heading'),copy=node('div');copy.append(node('h2',data.counts.actions?'Attempts & results':'Activities & conclusions'),node('p',data.counts.actions?'Operation · returned evidence · recorded follow-up':'Expressed work in recording order, with its source content','rs-subtitle'));heading.append(copy,node('span',(data.counts.actions?data.counts.actions+' actions':data.counts.moments+' moments')+' · '+data.counts.changes+' change / return links','rs-basis'));host.append(heading);
  const overview=node('div',null,'rs-overview'),request=node('section',null,'rs-objective'),result=node('section',null,'rs-result');
  request.append(node('span','REQUEST HISTORY','rs-eyebrow'));
  if(data.requests.length){const brief=(r,label)=>{request.append(node('small',label,'rs-eyebrow'),node('p',r.summary.slice(0,240)+(r.summary.length>240?'…':'')));if(r.summary.length>240)request.append(disclosure('Full request',node('p',r.summary)));};brief(data.requests[0],'Initial request');if(data.requests.length>2){const history=node('div');for(const r of data.requests.slice(1,-1))history.append(node('p',r.summary));request.append(disclosure('Earlier changes & follow-ups ('+(data.requests.length-2)+')',history));}if(data.requests.length>1)brief(data.requests.at(-1),'Latest request');}
  else request.append(node('p','User request not captured.'));
  if(data.focus){const first=node('div');first.append(node('p',text(data.focus.properties.content.focus)),node('small','First annotated local focus; not the whole task objective.'));request.append(disclosure('First local work focus',first));}
  const annotatedReport=data.reports.at(-1),last=annotatedReport||data.latestAgentText;
  result.append(node('span',annotatedReport?'REPORTED RESULT':'LATEST AGENT TEXT','rs-eyebrow'));
  if(last){const raw=clean(last.properties.source?.text||last.properties.text),report=raw||text(last.properties.content?.result)||last.summary,excerpt=report.split(/\n\s*\n/)[0].slice(0,420);result.append(node('p',excerpt+(excerpt.length<report.split(/\n\s*\n/)[0].length?'…':'')));if(report!==excerpt)result.append(disclosure(annotatedReport?(raw?'Full agent report':'Full result annotation'):'Full recorded text',node('p',report)));if(data.reports.length>1)result.append(node('small','Latest annotated report · '+last.trajectory_id+' · '+(last.properties.actor||'agent')));const b=node('button',annotatedReport?'Locate report':'Locate text','rs-text-button');b.onclick=()=>jump(data.moments.find(m=>m.nodes.some(n=>n.id===last.id))?.id);result.append(b);}
  else result.append(node('p','No agent prose is available.','rs-muted'));
  if(last)root.SourceEvidence?.append(result,graph,last);
  for(const r of data.recorded)result.append(node('span',r.label+': '+r.value,'rs-outcome'));
  result.append(node('small',annotatedReport?'Agent report; inspect checks for verification.':'Unclassified recorded text; it may be reasoning or an interim update. It does not establish completion.'));overview.append(request,result);host.append(overview);
  if(options.requestEvidence&&root.RequestEvidence)root.RequestEvidence.render(host,options.requestEvidence,openUnit);
  else if(options.requestEvidence)host.append(node('p','Requested-check view could not load. Coverage is unavailable here.','rs-missing'));
  else if(options.requestEvidenceError)host.append(node('p',options.requestEvidenceError,'rs-missing'));
  const tools=node('div',null,'rs-tools'),search=node('input'),filter=node('select'),navigator=node('select');
  search.type='search';search.placeholder='Find an operation, error or follow-up';search.setAttribute('aria-label','Search rollout story');search.value=options.query||'';
  filter.setAttribute('aria-label','Filter rollout story');
  for(const [value,label]of [['all','All moments'],['repeated','Repeated dispatches & original attempts'],['output','Error / warning text in responses'],['linked','Linked feedback follow-up'],['unlinked','Feedback without a use link'],['changes','Recorded changes & returns'],['checks','Recorded checks'],['missing','Actions without a response']]){const o=node('option',label);o.value=value;filter.append(o);}
  filter.value=options.filter||'all';if(!filter.value)filter.value='all';let focusedMoment=options.moment||'';
  const remember=()=>options.onChange?.({query:search.value,filter:filter.value,moment:focusedMoment});
  navigator.setAttribute('aria-label','Jump to story moment');const start=node('option','Jump to a moment…');start.value='';navigator.append(start);
  for(const m of data.moments){const o=node('option',String(m.number).padStart(2,'0')+' · '+m.displayTitle);o.value=m.id;navigator.append(o);}
  navigator.onchange=()=>{jump(navigator.value);navigator.value='';};tools.append(search,filter,navigator);host.append(tools);
  const stats=node('p',null,'rs-filter-note');stats.setAttribute('role','status');host.append(stats);
  function applyFilter(){let count=0;for(const m of data.moments){const show=matches(m,filter.value,search.value);cards.get(m.id).hidden=!show;if(show)count++;}
   const limit=filter.value==='repeated'?'Identical recorded tool, arguments and text within one actor/trajectory. Compare returned evidence; repetition alone is not waste or a failed retry.':filter.value==='output'?'Text search aid, not a failure classification: quotations and retrieved documents can also contain errors.':filter.value==='unlinked'?'Missing links do not establish ignored feedback.':filter.value==='missing'?'Missing response bindings do not establish an execution failure.':'Links reflect saved observations; they do not establish causality.';
   const coverage=data.counts.feedback?`Whole rollout: ${data.counts.feedbackWithFollowup} / ${data.counts.feedback} response records have a linked follow-up.`:'No tool-response records in this view.';
   stats.textContent=`${count} / ${data.moments.length} moments shown. ${coverage} ${limit}`;
  }
  search.oninput=filter.onchange=()=>{focusedMoment='';applyFilter();remember();};
  const shortcuts=node('div',null,'rs-review-shortcuts');
  for(const [f,label]of [['repeated',`${data.counts.repeatedDispatches} exact repeats · compare attempts`],['output',`${data.counts.notableOutputs} response excerpts to inspect`]]){const b=node('button',label);b.type='button';b.onclick=()=>{filter.value=f;search.value='';focusedMoment='';applyFilter();remember();};shortcuts.append(b);}
  if(!data.counts.feedbackWithFollowup)shortcuts.append(node('small','Feedback interpretation is unobserved here. Zero saved links does not mean the agent ignored feedback.'));
  host.append(shortcuts);
  if(options.feedbackTrailError)host.append(node('p',options.feedbackTrailError,'rs-missing'));
  if(options.feedbackTrail?.counts.reference_pairs){const b=node('button','Review feedback → next action','rs-feedback-shortcut');b.type='button';b.onclick=()=>{filter.value='linked';search.value='';focusedMoment='';applyFilter();remember();};shortcuts.append(b);}
  const stream=node('div',null,'rs-stream');host.append(stream);
  function jump(id,behavior='smooth'){const card=cards.get(id);if(!card)return;if(card.hidden){filter.value='all';search.value='';applyFilter();}focusedMoment=id;remember();card.scrollIntoView({behavior,block:'start'});card.focus({preventScroll:true});}
  function inspectUnit(id,moment){focusedMoment=moment;remember();openUnit(id);}
  function compareFeedback(row,trigger){
   const dialog=node('dialog',null,'rs-feedback-dialog');dialog.setAttribute('aria-label','Feedback and following action');
   const head=node('header'),close=node('button','Close');close.type='button';close.onclick=()=>dialog.close();head.append(node('h2','Compare feedback, action & output'),close);dialog.append(head);
   const reference=node('div',null,'rs-compare-reference');reference.append(node('small','Agent reference · '+row.reference.event_id),node('p',clean(row.reference.text)));dialog.append(reference);
   if(row.following_selection==='same_response_dispatches')dialog.append(node('small','Reference and dispatch share one response; their order of deliberation is unknown.'));
   const grid=node('div',null,'rs-compare-grid');dialog.append(grid);
   function evidence(host,label,record,isOutput=false){host.append(node('h3',label+(record?' · '+record.event_id:'')));if(!record){host.append(node('p','Not established in this snapshot.'));return;}const raw=clean(record.text),excerpt=isOutput?preview(raw).text:raw.slice(0,800);host.append(node('pre',excerpt));if(raw!==excerpt)host.append(disclosure('Full recorded text',node('pre',raw)));}
   const before=node('section');evidence(before,'Original action',row.original_action);evidence(before,'Feedback referenced',row.feedback,true);grid.append(before);
   for(const a of row.following){const after=node('section');evidence(after,row.following_selection==='referencing_dispatch'?'Referencing action':row.following_selection==='same_response_dispatches'?'Action in the same response':'Next recorded action',a);const status=a.dispatch_comparison;after.append(node('small',status.status==='identical'?'Recorded dispatch fields are identical.':status.status==='changed'?'Recorded fields changed: '+status.changed_fields.join(', '):'Original action cannot be uniquely compared.'));for(const o of a.outputs)evidence(after,'Output from this action',o,true);if(!a.outputs.length)after.append(node('p','Output not recorded.'));grid.append(after);}
   if(!row.following.length){const missing=node('section');missing.append(node('p','No subsequent dispatch is recorded in this snapshot.'));grid.append(missing);}
   dialog.append(node('p','A reference or a changed command does not establish recovery. Compare the returned evidence against the same criterion.'));document.body.append(dialog);dialog.onclose=()=>{dialog.remove();if(trigger.isConnected)trigger.focus();};dialog.showModal();
  }
  function content(n,label){const box=node('div',null,'rs-content'),raw=clean(n.properties.source?.text||n.properties.text),copy=raw||n.summary;box.append(node('small',label,'rs-eyebrow'),node('p',excerpt(copy,600)));if(excerpt(copy,600)!==copy)box.append(disclosure(raw?'Full contribution':'Full annotation',node('p',copy)));const b=node('button','Unit #'+n.ordinal+' ↗','rs-text-button');b.onclick=()=>inspectUnit(n.id,data.moments.find(m=>m.nodes.some(v=>v.id===n.id))?.id||'');if(n.ordinal)box.append(b);return box;}
  function followupPanel(responses,m){
   const panel=node('div',null,'rs-followups');panel.append(node('small','Linked follow-up','rs-eyebrow'));
   for(const r of responses)for(const reaction of r.reactions){const box=node('div',null,'rs-followup'),from=reaction.node,target=byMoment.get(reaction.momentId),quote=clean(from.properties.source?.text||from.properties.text),copy=quote||from.summary;
    box.append(node('span',reaction.edge.label+' · #'+from.ordinal+' → response #'+r.node.ordinal,'rs-followup-label'),node('p',excerpt(copy),'rs-followup-text'));
    const links=node('div',null,'rs-followup-actions'),open=node('button','Read unit #'+from.ordinal+' ↗','rs-text-button');open.onclick=()=>inspectUnit(from.id,m.id);links.append(open);
    if(target&&target!==m){const next=node('button','Go to moment '+target.number+' →','rs-text-button');next.onclick=()=>jump(target.id);links.append(next);}box.append(links);
    const trail=options.feedbackTrail?.rows.find(row=>row.reference_unit_id===from.id&&row.feedback_unit_id===r.node.id);
    if(trail){const follow=node('div',null,'rs-next-action');follow.append(node('small',trail.following_selection==='referencing_dispatch'?'Referencing dispatch':trail.following_selection==='same_response_dispatches'?'Dispatch in the same response':trail.following_selection==='next_recorded_batch'?'Next recorded batch · unordered':'Next recorded action','rs-eyebrow'));
     for(const a of trail.following){follow.append(node('p',clean(a.text).slice(0,220)+(a.text.length>220?'…':''),'rs-operation'));for(const o of a.outputs){const p=preview(o.text);follow.append(node('small',p.label),node('p',p.text.slice(0,220),'rs-response-text'));}if(!a.outputs.length)follow.append(node('small','Output not recorded.'));}
     if(!trail.following.length)follow.append(node('p','Not recorded in this snapshot.','rs-missing'));
     const compare=node('button','Compare action & output','rs-text-button');compare.type='button';compare.onclick=()=>compareFeedback(trail,compare);follow.append(compare);box.append(follow);}
    const evidence=node('div');evidence.append(node('p',reaction.edge.properties?.explanation||reaction.edge.label));if(copy.length>420)evidence.append(node('pre',copy));for(const s of reaction.edge.properties?.evidence||[])evidence.append(node('pre',s.text));box.append(disclosure(quote?'Why these records are linked':'Annotation · source unavailable',evidence));panel.append(box);
   }
   if(!responses.some(r=>r.reactions.length))panel.append(node('p',responses.length?'No saved assessment or evidence-use link. Follow-up is unknown.':'Follow-up cannot be traced without a response binding.','rs-missing'));
   return panel;
  }
  for(const m of data.moments){
   const card=node('article',null,'rs-moment'+(m.hasSignal?' has-signal':''));card.tabIndex=-1;card.dataset.moment=m.id;cards.set(m.id,card);
   const top=node('header'),num=node('span',String(m.number).padStart(2,'0'),'rs-number'),title=node('div');title.append(node('small',`${m.actor||'Source'} · ${m.trajectory||'main'} · ${m.basis}`),node('h3',m.displayTitle));top.append(num,title);card.append(top);
   if(m.actions.length>1)card.append(node('p','Grouped dispatches · execution order is not established','rs-batch-note'));
   if(m.contributions.length){const context=node('div');for(const c of m.contributions)context.append(content(c,c.activity.toUpperCase()));card.append(disclosure('Agent context · '+m.contributions.map(c=>c.activity).join(', '),context));}
   const grid=node('div',null,'rs-attempts');
   for(const a of m.attempts){
    const action=a.node,attempt=node('section',null,'rs-attempt');attempt.setAttribute('aria-label','Action '+action.ordinal+' and linked evidence');
    const dispatch=node('div',null,'rs-dispatch');dispatch.append(node('small',a.operation.basis+' · #'+action.ordinal,'rs-eyebrow'),node('p',excerpt(a.operation.text),'rs-operation'));
    const inspect=node('button','Unit #'+action.ordinal+' ↗','rs-text-button');inspect.onclick=()=>inspectUnit(action.id,m.id);dispatch.append(inspect);attempt.append(dispatch);
    if(a.repetition){const repeated=node('div',null,'rs-repeat-links');repeated.append(node('small',`${a.repetition.actionIds.length} identical dispatch records · inspect each result`));for(const id of a.repetition.momentIds){const other=byMoment.get(id),b=node('button',`Moment ${other.number}${id===m.id?' · here':''}`,'rs-text-button');b.type='button';b.disabled=id===m.id;b.onclick=()=>jump(id);repeated.append(b);}dispatch.append(repeated);}
    const outcomes=node('div',null,'rs-outcomes');
    for(const r of a.responses){const box=node('div',null,'rs-response '+(r.kind==='error-field'?'rs-error':''));
     const head=node('div',null,'rs-evidence-heading'),locate=node('button','Unit #'+r.node.ordinal+' ↗','rs-text-button');locate.onclick=()=>inspectUnit(r.node.id,m.id);head.append(node('span',r.label,'rs-response-label'),locate);box.append(head,node('p',r.text.slice(0,420)+(r.text.length>420?'…':''),'rs-response-text'));
     if(r.text!==r.raw||r.raw.length>420)box.append(disclosure('Full response',node('pre',r.raw)));outcomes.append(box);
    }
    for(const r of a.capturedResponses||[]){const box=node('div',null,'rs-response');box.append(node('span','Captured call feedback','rs-response-label'),node('p',r.text,'rs-response-text'),node('small','Whole-call result; not assigned to one split or partial unit.'));box.append(disclosure('Full captured response',node('pre',r.raw)));
     for(const id of r.response_card_ids){const response=data.moments.flatMap(m=>m.nodes).find(n=>n.id===id);if(!response)continue;const b=node('button','Response unit #'+response.ordinal+' ↗','rs-text-button');b.onclick=()=>inspectUnit(id,m.id);box.append(b);}outcomes.append(box);}
    if(!a.responses.length&&!a.capturedResponses?.length)outcomes.append(node('p','No response is linked to this action.','rs-missing'));
    attempt.append(outcomes);
    if(!a.responses.length&&a.capturedResponses?.length)attempt.append(node('p','Open the response cards to inspect any saved feedback-use links.','rs-missing'));else attempt.append(followupPanel(a.responses,m));grid.append(attempt);
   }
   if(m.actions.length)card.append(grid);
   for(const n of m.extras)card.append(content(n,n.kind==='plan_step'?'DECLARED PLAN STEP':String(n.activity).toUpperCase()));
   if(!m.actions.length)for(const r of m.responses){const box=node('div',null,'rs-content');box.append(node('small',(m.callLinked?'CAPTURED RESPONSE · UNIT PAIRING UNRESOLVED':'UNPAIRED FEEDBACK')+' · '+r.label,'rs-eyebrow'),node('p',r.text.slice(0,420)+(r.text.length>420?'…':'')));if(r.text!==r.raw||r.raw.length>420)box.append(disclosure('Full response',node('pre',r.raw)));box.append(followupPanel([r],m));card.append(box);}
   for(const check of m.checks)card.append(node('p',`Recorded check · ${check.properties.criterion_id} · ${check.properties.result}`,'rs-check'));
   for(const n of m.nodes){for(const plan of mapAPI.declaredPlans(graph,n.id)){const list=node('ol',null,'rs-plan');for(const item of plan.snapshot.items)list.append(node('li',`${item.text||item.title||item.content||item.id} — ${item.status||'state not recorded'}`));card.append(node('strong','Declared task list · agent-reported states'),list);}}
   if(m.links.length){const links=node('div',null,'rs-links'),groups=new Map();for(const l of m.links){const k=JSON.stringify([l.type,l.to]);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(l);}for(const rows of groups.values()){const l=rows[0],target=byMoment.get(l.to),b=node('button',l.label+(l.within?' · this moment':' → '+String(target.number).padStart(2,'0')+' '+target.displayTitle)+(rows.length>1?' · '+rows.length+' links':''));b.title=l.properties?.explanation||l.label;b.onclick=()=>jump(l.to);links.append(b);}card.append(links);}
   const evidence=node('div',null,'rs-evidence');
   for(const n of m.nodes){const row=node('div');row.append(node('h4',`${n.kind==='event'?'Record':'Unit'} ${n.ordinal||''} · ${n.activity}`),node('pre',clean(n.properties.source?.text||n.properties.text)||n.summary));const b=node('button','Open in Unit map','rs-text-button');b.onclick=()=>inspectUnit(n.id,m.id);row.append(b);evidence.append(row);}
   for(const l of m.links){const row=node('div');row.append(node('h4',l.label),node('p',l.properties?.explanation||'Saved relationship. No additional interpretation was added.'));for(const span of l.properties?.evidence||[])row.append(node('pre',span.text));evidence.append(row);}
   card.append(disclosure(`Read evidence · ${m.nodes.length} record${m.nodes.length===1?'':'s'}`,evidence));
   const searchable=m.nodes.filter(n=>root.SourceEvidence?.anchor(n)).at(-1);if(searchable)root.SourceEvidence.append(card,graph,searchable);
   stream.append(card);
  }
  applyFilter();
  const limits=node('details',null,'rs-limits');limits.append(node('summary','Coverage and interpretation'),node('p',data.limit),node('p',`${data.represented} visible map records represented; ${data.context.length} system/developer context records kept below. Long responses are shortened visually; their full text remains attached. Error fields are source fields, not failure classifications.`));
  for(const c of data.context)limits.append(node('pre',c.summary));host.append(limits);
  if(focusedMoment&&cards.has(focusedMoment)&&!cards.get(focusedMoment).hidden)requestAnimationFrame(()=>{if(cards.get(focusedMoment)?.isConnected&&!host.hidden)jump(focusedMoment,'instant');});
 }
 root.RolloutStory={...api,render};
})(typeof globalThis!=='undefined'?globalThis:this);
