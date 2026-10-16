/* Source checks and receipt handoffs share the same evidence vocabulary. */
(function(root){
 'use strict';
 const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
 const kinds={context:'Context',instruction:'Instruction',message:'Message',reasoning:'Reasoning text',action:'Tool / environment action',feedback:'Returned result'};
 function readable(value){return value&&!/^(?:[a-z]+-)?[a-f0-9]{20,}$/i.test(String(value))?String(value):null;}
 function recordLabel(run,index){
  const identity=run.source_preview?.identity||{};
  const name=readable(identity.task_id)||readable(identity.sample_id)||readable(identity.logical_rollout_id);
  const file=identity.source_export_path;
  return name|| (file?file+(identity.source_line?' · line '+identity.source_line:''):'Rollout '+(index+1));
 }
 function renderOne(host,run){
  host.replaceChildren();
  const preview=run.source_preview;
  if(!preview){host.append(el('p','Content preview unavailable. Import this source to inspect its records.','muted'));return;}
  host.append(el('p',`${preview.events.length} of ${preview.total_events} events · ${preview.relations.length} recorded action/result links shown`,'source-preview-count'));
  if(preview.delivery)host.append(el('p',`Sampled revision ${preview.delivery.revision} · ${preview.delivery.state.replaceAll('_',' ')}`,'source-preview-count'));
  const list=el('ol',undefined,'source-preview-events'),targets=new Map();
  const trajectories=[...new Set(preview.events.map(event=>event.trajectory_id))];
  for(const event of preview.events){
   const item=el('li',undefined,'source-preview-event');item.tabIndex=-1;item.dataset.kind=event.kind;
   targets.set(event.id,item);
   const header=el('div',undefined,'source-preview-event-head');
   header.append(el('strong','#'+(event.index+1)),el('span',kinds[event.kind]||event.kind),el('small',event.actor));
   if(event.tool)header.append(el('code',event.tool));
   if(trajectories.length>1)header.append(el('small','Timeline '+(trajectories.indexOf(event.trajectory_id)+1)));
   const children=Object.entries(event.child_counts||{}).map(([kind,count])=>`${count} ${kind==='action'?'action':kind==='reasoning'?'reasoning segment':kind}${count===1?'':'s'}`);
   const empty=children.length?'Message contains '+children.join(' and ')+', recorded as separate events.':'No text recorded.';
   item.append(header,el('pre',event.text||empty));
   const notes=[];
   if(event.omitted_characters)notes.push(event.omitted_characters.toLocaleString()+' more characters');
   if(event.media_count)notes.push(event.media_count+' media references · content not inspected');
   if(event.unlinked_response)notes.push('No unambiguous recorded action link');
   if(notes.length)item.append(el('small',notes.join(' · '),'source-preview-note'));
   for(const relation of preview.relations.filter(r=>r.feedback_id===event.id)){
    const action=preview.events.find(e=>e.id===relation.action_id);
    const button=el('button',`Result for #${action.index+1}${action.tool?' · '+action.tool:''}`,'source-preview-link');
    button.type='button';button.title=relation.basis;
    button.onclick=()=>{const target=targets.get(action.id);target?.focus({preventScroll:true});target?.scrollIntoView({block:'nearest',behavior:'smooth'});};
    item.append(button);
   }
   const location=el('details'),summary=el('summary','Source location');
   location.append(summary,el('code',event.source_pointer||'Not recorded'));item.append(location);list.append(item);
  }
  host.append(list);
  const omitted=[];
  if(preview.omitted_events)omitted.push(preview.omitted_events+' later events outside this preview');
  if(preview.omitted_relations)omitted.push(preview.omitted_relations+' links have endpoints outside this preview');
  if(preview.copied_context_events)omitted.push(preview.copied_context_events+' copied context events excluded');
  if(omitted.length)host.append(el('p',omitted.join(' · '),'source-preview-note'));
  host.append(el('p',preview.note,'source-preview-note'));
 }
 function renderPreview(host,runs){
  if(!runs?.length)return;
  const section=el('div',undefined,'source-preview');section.append(el('h4','Rollout preview'));
  const content=el('div');
  if(runs.length>1){
   const label=el('label','Sampled rollout'),select=el('select');select.setAttribute('aria-label','Sampled rollout');
   runs.forEach((run,index)=>{const option=el('option',`${index+1} · ${recordLabel(run,index)}`);option.value=index;select.append(option);});
   select.onchange=()=>renderOne(content,runs[Number(select.value)]);label.append(select);section.append(label);
  }
  renderOne(content,runs[0]);section.append(content);host.append(section);
 }
 function receiptDestinations(receipts,returnTo){
  return (receipts||[]).map((receipt,index)=>{
   const map=new URLSearchParams({run:receipt.run_id,observer:'source',return_to:returnTo});
   const name=readable(receipt.task_id)||(receipt.export_path?receipt.export_path+(receipt.source_line?' · line '+receipt.source_line:''):'Rollout '+(index+1));
   return {label:name,map:'/semantic-map?'+map,
    experiment:receipt.experiment,
    overview:receipt.experiment?'/?'+new URLSearchParams({experiment:receipt.experiment,return_to:returnTo}):null,
    detail:`Revision ${receipt.revision} · ${receipt.state.replaceAll('_',' ')}${receipt.training_step!==null&&receipt.training_step!==undefined?' · step '+receipt.training_step:''}`};
  });
 }
 function renderReceipts(host,receipts,returnTo){
  const destinations=receiptDestinations(receipts,returnTo);if(!destinations.length)return;
  const list=el('div',undefined,'connection-evidence');
  for(const item of destinations){
   const row=el('div'),map=el('a',item.label+' →');map.href=item.map;
   row.append(map,el('small',item.detail));list.append(row);
  }
  const experiments=new Map(destinations.filter(item=>item.overview).map(item=>[item.experiment,item.overview]));
  for(const [name,url]of experiments){const overview=el('a','Open '+name+' overview →');overview.href=url;overview.className='connection-overview';list.append(overview);}
  host.append(list);
 }
 const api={recordLabel,receiptDestinations,renderPreview,renderReceipts};
 if(typeof module!=='undefined')module.exports=api;else root.SourcePreview=api;
})(typeof window==='undefined'?globalThis:window);
