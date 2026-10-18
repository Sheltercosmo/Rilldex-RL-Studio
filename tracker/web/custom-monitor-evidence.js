'use strict';
const CustomMonitorEvidence=(()=>{
 const labels={flagged:'Flagged',clear:'Clear',unknown:'Unknown',not_applicable:'Not applicable'};
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined&&text!==null)n.textContent=text;if(cls)n.className=cls;return n;};
 function status(explanation){
  if(explanation?.diagnostic){const d=explanation.diagnostic;return d.value===1?'Flagged':d.value===0?'No candidate selected':d.scan_complete===false?'Scan pending':'Unavailable';}
  return explanation?.basis==='custom_code'&&explanation.details?.detector?.schema==='reward-detector/1'?labels[explanation.details.detector.status]||null:null;
 }
 function render(explanation,{nodeButton}={}){
  if(explanation?.basis!=='custom_code')return null;
  const section=el('section',null,'custom-evidence'),feedback=explanation.feedback,detector=explanation.details?.detector;
  section.append(el('h3',status(explanation)||'Code monitor result'));
  if(feedback?.summary)section.append(el('p',feedback.summary,'custom-evidence-summary'));
  else if(explanation.reason)section.append(el('p',explanation.reason));
  if(feedback?.next_check)section.append(el('p',feedback.next_check,'custom-evidence-next'));
  if(detector?.schema==='reward-detector/1')section.append(el('small','Reward definition: '+detector.reward_definition+' · '+String(detector.stage).replaceAll('_',' ')));
  if(explanation.input_values?.length){
   const inputs=el('div',null,'custom-evidence-inputs');inputs.append(el('h4','Inputs used by this finding'));
   for(const input of explanation.input_values){
    const row=el('details');row.open=typeof input.value!=='object'||input.value===null;
    row.append(el('summary',input.name),el('code',input.pointer),el('pre',JSON.stringify(input.value,null,2)));inputs.append(row);
   }section.append(inputs);
  }
  if(explanation.source_excerpts?.length){
   section.append(el('h4','Cited source passages'));
   for(const item of explanation.source_excerpts){
    const row=el('div',null,'custom-evidence-excerpt'),c=item.citation;
    row.append(el('strong',c.role.replaceAll('_',' ')),el('small',item.actor+' · '+item.kind+(item.tool?' · '+item.tool:'')),el('pre',c.text));
    if(nodeButton)for(const id of item.node_ids){const button=nodeButton(id);if(button)row.append(button);}
    const location=el('details');location.append(el('summary','Source location'),el('code',c.source_pointer+' · characters '+c.start+'–'+c.end));row.append(location);section.append(row);
   }
  }else if(!explanation.evidence_ids?.length&&!explanation.evaluation_reports?.length)section.append(el('p','No trace passages or map nodes were attached to this result.','custom-evidence-note'));
  if(Object.keys(explanation.evaluation_inputs||{}).length){
   section.append(el('h4','Evaluator inputs at measurement'));
   for(const [name,ids] of Object.entries(explanation.evaluation_inputs))section.append(el('p',name+' · '+ids.length+' matching report'+(ids.length===1?'':'s')+(ids.length===0?' · missing':ids.length>1?' · multiple reports':'')));
  }
  if(explanation.evaluation_reports?.length){
   section.append(el('h4','Cited evaluator reports'));
   for(const item of explanation.evaluation_reports){
    const r=item.receipt,row=el('details');row.open=explanation.evaluation_reports.length<=2;
    row.append(el('summary',r.label+' · '+r.verdict),el('small',item.inputs.join(', ')+' · '+r.producer),el('p',r.summary),el('p','Execution: '+r.execution+' · score: '+(r.score??'not recorded')));
    for(const excerpt of r.evidence||[])row.append(el('strong',excerpt.label),el('pre',excerpt.text));
    const record=el('details');record.append(el('summary','Saved report and input versions'),el('pre',JSON.stringify(r,null,2)));row.append(record);section.append(row);
   }
   section.append(el('p','These are external worker reports, kept separate from the agent-visible trace.','custom-evidence-note'));
  }
  const extra=explanation.details?.detector?explanation.details.custom:explanation.details;
  if(extra!==null&&extra!==undefined&&(typeof extra!=='object'||Object.keys(extra).length)){
   const details=el('details');details.append(el('summary','Additional result data'),el('pre',JSON.stringify(extra,null,2)));section.append(details);
  }
  section.append(el('p','Source links identify the cited records. They do not validate the rule or prove a causal explanation.','custom-evidence-note'));
  return section;
 }
 function renderDiagnostic(diagnostic,{nodeButton,events=[],excerpts={}}={}){
  if(!diagnostic)return null;
  const section=el('section',null,'custom-evidence'),findings=diagnostic.candidates;
  section.append(el('h3',Array.isArray(findings)?'Requirement conflicts':'Detector evidence'));
  section.append(el('p',String(diagnostic.selection||diagnostic.status||'Recorded result').replaceAll('_',' ')));
  if(diagnostic.scan_complete===false)section.append(el('p','Partial scan · '+diagnostic.scanned_pages+' / '+diagnostic.total_pages+' pages inspected. Remaining pages are queued.','custom-evidence-note'));
  const pairs=Array.isArray(findings)?findings.map(f=>f.requirement&&f.candidate?{requirement:f.requirement,candidate:f.candidate}:null).filter(Boolean):[diagnostic.evidence_roles||{}];
  if(Array.isArray(findings)&&findings.length){const count=new Set(findings.map(f=>f.candidate.event_id||f.candidate.id)).size;section.append(el('p',count+' source '+(count===1?'record':'records')+' · '+findings.length+' requirement '+(findings.length===1?'match':'matches')+'. A record can match several requirements.','custom-evidence-note'));}
  const labels={requirement:'Task requirement',instruction:'Applicable instruction',candidate:'Flagged source',action:'Action',mechanism:'Mechanism',returned_material:'Retrieved material',incorporation:'Use of retrieved material'};
  function passage(role,ref){
    if(!ref||typeof ref!=='object')return el('span');
    const row=el('div',null,'custom-evidence-excerpt');row.append(el('strong',labels[role]||role.replaceAll('_',' ')));
    const event=events.find(e=>e.id===ref.event_id);
    const selected=excerpts[ref.id]||[];
    if(selected.length){
     const linked=new Set();
     for(const part of selected){
      row.append(el('small',part.actor?[part.actor,part.kind,part.field.join(' / ')].join(' · '):'Recorded task'),el('pre',part.text));
      if(nodeButton)for(const id of part.node_ids||[]){if(linked.has(id))continue;linked.add(id);const b=nodeButton(id);if(b){b.title=b.textContent;b.textContent=id==='event:'+part.event_id?'Open source record':'Open matching unit';row.append(b);}}
     }
     if(event){const full=el('details');full.append(el('summary','Full source record · '+event.id),el('pre',event.text));row.append(full);}
    }else{
     row.append(el('pre',ref.display_text??ref.text??''));
     if(ref.event_id){row.append(el('small',ref.event_id+(event?' · '+event.actor+' · '+event.kind:'')));if(nodeButton){const b=nodeButton('event:'+ref.event_id);if(b)row.append(b);}}
    }
    return row;
  }
  if(Array.isArray(findings)){
   const records=new Map();
   for(const pair of pairs){const key=pair.candidate.event_id||pair.candidate.id;if(!records.has(key))records.set(key,[]);records.get(key).push(pair);}
   for(const [key,matches]of records){
    const group=el('details'),event=events.find(e=>e.id===key),label=event?[event.actor,event.kind].join(' '):'Selected source';group.open=records.size===1;
    group.append(el('summary',label+' · '+matches.length+' requirement '+(matches.length===1?'match':'matches')));
    const fragments=new Map();for(const pair of matches){const id=pair.candidate.id||pair.candidate.text;if(!fragments.has(id))fragments.set(id,[]);fragments.get(id).push(pair);}
    for(const linked of fragments.values()){
     const fragment=el('section',null,'diagnostic-match');fragment.append(passage('candidate',linked[0].candidate),el('h4','Matched task requirements'));
     const terms=new Set();for(const pair of linked){const term=pair.requirement,id=term.id||term.text;if(terms.has(id))continue;terms.add(id);
      if(linked.length===1)fragment.append(passage('requirement',term));
      else {const item=el('details'),title=(term.display_text||term.text||'Task requirement').replace(/\s+/g,' ').trim();item.append(el('summary',title.length>120?title.slice(0,117)+'…':title),passage('requirement',term));fragment.append(item);}
     }group.append(fragment);
    }section.append(group);
   }
  }else for(const [i,pair]of pairs.entries()){
   const group=el('details');group.open=pairs.length===1;group.append(el('summary','Finding '+(i+1)));
   for(const [role,ref]of Object.entries(pair))group.append(passage(role,ref));section.append(group);
  }
  if(Array.isArray(findings))section.append(el('p',findings.length?'Task conflicts may be bugs or shortcuts; a reward exploit is not established.':'No conflict candidate was selected in the scanned source.','custom-evidence-note'));
  return section;
 }
 return {render,status,renderDiagnostic};
})();
if(typeof module!=='undefined')module.exports=CustomMonitorEvidence;
