'use strict';
window.trackerBehaviorMoves=(()=>{
 const names={state:'State or describe',derive:'Derive or interpret',propose:'Propose work',request:'Request or coordinate',perform:'Perform an operation',deliver:'Deliver a result',other:'Other function',not_applicable:'Not applicable',split_needed:'Needs a finer split',unresolved:'Unresolved function'};
 const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
 const item=(bundle,id)=>bundle.behavior_moves?.units?.[id];
 function summary(bundle,id){const x=item(bundle,id);return x?.status==='complete'&&x.moves.length?x.moves.map(m=>names[m.function.value]||m.function.value).join(' → '):null;}
 function render(root,unit,bundle){const data=item(bundle,unit.id);if(!data)return;
  const panel=el('section',undefined,'behavior-moves');panel.dataset.moveUnit=unit.id;
  panel.append(el('h4','Local behavior structure · experimental'),el('p','Moves appear in source order. Each has one function; expressed status is a separate field.','muted'));
  if(data.status!=='complete'){panel.append(el('p','Saved structure needs reinspection against the current source.'));root.append(panel);return;}
  if(!data.moves.length)panel.append(el('p','Partition: '+data.partition_choice.replaceAll('_',' '),'move-partition-gap'));
  const list=el('ol',undefined,'behavior-move-list');
  for(const move of data.moves){const row=el('li',undefined,'behavior-move');row.dataset.moveId=move.id;
   row.append(el('h5',names[move.function.value]||move.function.value,'move-function'),el('pre',move.text,'move-text'));
   const status=el('dl',undefined,'move-dimensions');status.append(el('dt','Expressed status'),el('dd',move.status.value.replaceAll('_',' '),'move-status'));row.append(status);
   for(const reason of move.review_reasons)row.append(el('p',reason,'move-review'));
   row.append(el('p',`${unit.source_pointer} · [${move.start}, ${move.end}) code points`,'source-ref'));
   const highlight=el('button','Highlight this move');highlight.onclick=()=>{const source=root.querySelector('.unit-graph-subject')||root.querySelector(':scope > pre'),chars=Array.from(unit.text),a=move.start-unit.start,b=move.end-unit.start;if(!source||chars.slice(a,b).join('')!==move.text)return;source.replaceChildren(document.createTextNode(chars.slice(0,a).join('')),el('mark',move.text),document.createTextNode(chars.slice(b).join('')));source.scrollIntoView({block:'nearest'});};row.append(highlight);
   if(move.next_fields.length){const fields=el('details',undefined,'move-next-fields');fields.append(el('summary','Next: category fields · not extracted'),el('p',move.next_fields.map(f=>f.replaceAll('_',' ')).join(' · ')));row.append(fields);}list.append(row);
  }panel.append(list);
  const previous=el('details',undefined,'move-legacy-labels');previous.append(el('summary','Earlier flat activity labels'),el('p',(unit.activities||[]).join(' + ')||'No earlier activity selected'),el('p','Preserved for comparison. The earlier entity and reference records still use those labels.','muted'));panel.append(previous);
  const raw=el('details',undefined,'move-raw');raw.append(el('summary','Partitions, choices and source scope'));let loaded=false;raw.ontoggle=()=>{if(raw.open&&!loaded){loaded=true;raw.append(el('pre',JSON.stringify(data,null,2)));}};panel.append(raw);
  root.append(panel);
 }
 return {render,summary};
})();
