'use strict';
window.TrainingSpansView=(()=>{
 let current=null;
 const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
 const human=s=>String(s||'Unlabeled').replaceAll('_',' ');
 const keys=['schema','producer','experiment','id'];
 function clear(){current=null;const host=document.querySelector('#training-span-context');if(host){host.replaceChildren();host.hidden=true;}}
 async function load(graph,params,onSelect,isCurrent){
  current=null;let host=document.querySelector('#training-span-context');
  if(!host){host=el('section');host.id='training-span-context';host.className='training-span-context';document.querySelector('#measurement-context').before(host);}
  host.replaceChildren();host.hidden=!params.has('training_id');if(host.hidden)return;
  host.append(el('p','Loading exact training-use coverage…'));
  try{
   const query=new URLSearchParams({graph:graph.id});for(const key of keys)query.set('training_'+key,params.get('training_'+key)||'');
   const response=await fetch('/api/training-spans?'+query),value=await response.json();if(!isCurrent())return;
   if(!response.ok)throw Error(value.error||'Training coverage is unavailable');current=value;host.replaceChildren();
   const p=value.projection,heading=el('div');heading.className='training-span-heading';heading.append(el('strong','Training coverage'),el('span',human(value.stage)+' · learner step '+value.learner_step));host.append(heading);
   if(value.status!=='available'||p.status!=='mapped'){host.append(el('p',value.reason||p.reason));return;}
   const assigned=p.coverage.eligible_tokens.unit_assigned||0;
   host.append(el('p',`${assigned} / ${p.eligible_tokens} eligible tokens map to saved units. ${p.eligible_tokens-assigned} remain outside unit-level analysis.`));
   const detail=el('details');detail.append(el('summary','Activity breakdown and exact units'));
   detail.append(el('p','Counts follow one recorded training use and the selected annotation snapshot. They do not establish which behavior caused learning. Activity accuracy remains that of the saved observer.'));
   const table=el('table'),head=el('tr');for(const title of ['Saved activity','Eligible tokens','Nonzero derivative','Zero derivative'])head.append(el('th',title));table.append(head);
   for(const a of p.activities.filter(a=>a.mapped_tokens)){const row=el('tr');for(const text of [human(a.activity),a.eligible_tokens,a.nonzero_derivatives,a.zero_derivatives])row.append(el('td',String(text)));table.append(row);}
   if(p.activities.some(a=>a.mapped_tokens))detail.append(table);else detail.append(el('p','This source has no exact semantic-unit assignments. Source tokens are retained without inventing activity labels.'));
   const gaps=Object.entries(p.coverage.eligible_tokens).filter(([k])=>k!=='unit_assigned');if(gaps.length)detail.append(el('p','Outside unit analysis: '+gaps.map(([k,v])=>`${human(k)} ${v}`).join(' · ')));
   const list=el('div');list.className='training-span-units';
   for(const u of p.units.filter(u=>u.mapped_tokens)){const b=el('button',`${human(u.activity)} · ${u.eligible_tokens} eligible tokens · ${u.source.text.slice(0,85)}`);b.onclick=()=>{detail.open=false;onSelect(u.id);};list.append(b);}detail.append(list);
   const save=el('button','Export training coverage');save.onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})),a=el('a');a.href=url;a.download='training-unit-coverage.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};detail.append(save);host.append(detail);
  }catch(error){if(!isCurrent())return;current=null;host.replaceChildren(el('strong','Training coverage unavailable'),el('p',error.message));}
 }
 function appendUnit(host,id){
  if(!current)return;const p=current.projection;if(current.status!=='available'||p.status!=='mapped')return;
  const u=p.units.find(u=>u.id===id),event=p.events.find(e=>'event:'+e.event_id===id),row=u||event;
  host.append(el('h3','This training use'));
  if(!row||!row.mapped_tokens){host.append(el('p','No exact token assignment for this card. This is not proof it was unused.'));return;}
  host.append(el('p',`${row.eligible_tokens} eligible / ${row.mapped_tokens} source-mapped tokens · ${row.nonzero_derivatives} nonzero derivatives · ${row.zero_derivatives} exact zeros.`),el('p',`${human(current.stage)} · learner step ${current.learner_step}. Counts belong to this use; they are not causal behavior credit.`));
 }
 return {load,appendUnit,clear};
})();
