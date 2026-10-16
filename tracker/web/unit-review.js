'use strict';
// Source-bound editor shared by existing rollout and measurement drilldowns.
window.UnitReview = (() => {
 const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
 const field=(name,input)=>{const l=el('label',name);input.setAttribute('aria-label',name);l.append(input);return l;};
 const human=s=>s.replaceAll('_',' ');
 function changeSummary(data){
  if(!data)return [];
  if(data.status!=='available')return [data.reason||'Annotation comparison is unavailable.'];
  const label=x=>x?human(x):'unlabeled',lines=[];
  if(data.activities.length)lines.push('Activity counts: '+data.activities.map(r=>`${label(r.activity)} ${r.baseline} → ${r.current}`).join(' · '));
  else lines.push('Activity counts stay the same; meanings and connections may still change.');
  const bounds=Object.entries(data.boundary_changes).map(([kind,n])=>`${n} ${label(kind)}`);
  if(bounds.length)lines.push('Boundaries: '+bounds.join(' · '));
  if(data.transitions.length){const rows=data.transitions.slice(0,6);lines.push('Recorded activity sequence: '+rows.map(r=>`${label(r.from_activity)} → ${label(r.to_activity)}: ${r.baseline} → ${r.current}`).join(' · ')+(data.transitions.length>6?` · ${data.transitions.length-6} more transition types`:''));}
  if(data.relationship_groups_changed)lines.push(`${data.relationship_groups_changed} source-linked relationship groups change. Removed dependencies need review; they do not mean the behavior did not occur.`);
  lines.push(data.note);return lines;
 }
 async function request(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined),d=await r.json();if(!r.ok)throw Error(d.error||r.statusText);return d;}
 function append(body,node,{payload,receipt,params,onSaved}){
  const p=node.properties;
  if(!['unit','event'].includes(node.kind)||p.actor!=='agent'||node.kind==='unit'&&!['semantic','action'].includes(p.kind))return;
  if(receipt?.review_context){
   const c=receipt.review_context,a=el('a','Review source units behind this measurement');
   const q=new URLSearchParams({run:c.run_id,observer:c.observer,graph:c.graph_id,focus_unit:node.id,review_monitor:c.monitor_id,review_value:receipt.measurement.id});
   if(params.get('return_to'))q.set('return_to',params.get('return_to'));
   a.href='/semantic-map?'+q;body.append(a,el('p','Opens the original observation input. This saved measurement stays fixed.','evidence-note'));return;
  }
  if(!payload.capabilities?.unit_review)return;
  const details=el('details',undefined,'unit-review-editor'),container=el('div');details.append(el('summary','Review unit boundary, activity and content'),container);body.append(details);
  const graphId=payload.graph.id;let loaded=false;
  details.ontoggle=async()=>{if(!details.open||loaded)return;loaded=true;container.textContent='Loading exact source window…';
   try{const data=await request('/api/unit-reviews?'+new URLSearchParams({graph:graphId,unit:node.id}));if(details.isConnected)render(data);}catch(e){container.textContent=e.message;loaded=false;}
  };
  function render(data){
   container.replaceChildren();const d=structuredClone(data.document),w=data.window,chars=Array.from(w.text);
   const form=el('form',undefined,'work-review-form'),units=el('div'),author=el('input'),note=el('textarea'),message=el('p'),impact=el('div'),preview=el('button','Preview correction'),save=el('button','Save corrected units');
   let approved=null,previewResult=null;
   function dirty(){approved=null;save.hidden=true;impact.replaceChildren();}
   if(data.issue)form.append(el('p',data.issue,'evidence-note'));
   if(data.windows.length>1){const select=el('select');for(const option of data.windows){const o=el('option',option.text.slice(0,100));o.value=option.id;select.append(o);}select.value=w.id;select.onchange=async()=>{try{render(await request('/api/unit-reviews?'+new URLSearchParams({graph:graphId,unit:node.id,window:select.value})));}catch(e){message.textContent=e.message;}};form.append(field('Eligible source window',select));}
   form.append(el('p','Keep one coherent contribution per unit. Supporting rationale stays with its contribution. A local next-step announcement is usually Orient; Assess and Revise belong to relationships.','evidence-note'));
   const sourceFor=u=>({...w,start:u.start,end:u.end,text:chars.slice(u.start-w.start,u.end-w.start).join('')});
   const anchorFor=u=>{const {event_id,source_pointer,start,end,text}=sourceFor(u);return {event_id,source_pointer,start,end,text};};
   function empty(start,end){return {start,end,activity:'unresolved',fields:{}};}
   function textInput(label,value,oninput){const input=el('textarea');input.rows=2;input.value=value||'';input.maxLength=2400;input.oninput=()=>{oninput(input.value);dirty();};return field(label,input);}
   function contentValue(text,u,old){return text.trim()?{status:'expressed',text:text.trim(),evidence:old?.evidence||[anchorFor(u)]}:{status:'not_expressed'};}
   function contentField(parent,label,u,obj,key){const initial=obj[key];parent.append(textInput(label,initial?.text,text=>{obj[key]=contentValue(text,u,initial);}));}
   function plan(parent,u){
    const value=u.plan_structure||{schema:'local-plan-content/1',organization:'strategy',steps:[],links:[],completion_criterion:{status:'not_expressed'}};u.plan_structure=value;
    const org=el('select');for(const name of ['strategy','staged']){const o=el('option',name==='strategy'?'Organizing strategy':'Two or more substantive intended stages');o.value=name;org.append(o);}org.value=value.organization;org.onchange=()=>{value.organization=org.value;dirty();};parent.append(field('Plan organization',org));
    const stages=el('div'),links=el('div');
    function draw(){stages.replaceChildren();links.replaceChildren();value.steps.forEach((s,i)=>{const row=el('fieldset');row.append(el('legend','Intended stage '+(i+1)),textInput('Stage description',s.text,text=>s.text=text),textInput('Stage target',s.target,text=>s.target=text));const remove=el('button','Remove stage');remove.type='button';remove.onclick=()=>{value.steps.splice(i,1);value.links=value.links.filter(l=>l.from!==s.id&&l.to!==s.id);dirty();draw();};row.append(remove);stages.append(row);});
     value.links.forEach((link,i)=>{const row=el('div');for(const key of ['from','kind','to']){const select=el('select');const opts=key==='kind'?[['precedes','Explicitly precedes'],['requires','Requires prerequisite']]:value.steps.map((s,j)=>[s.id,'Stage '+(j+1)]);for(const [v,label]of opts){const o=el('option',label);o.value=v;select.append(o);}select.value=link[key];select.onchange=()=>{link[key]=select.value;dirty();};row.append(field('Plan link '+key,select));}const remove=el('button','Remove link');remove.type='button';remove.onclick=()=>{value.links.splice(i,1);dirty();draw();};row.append(remove);links.append(row);});}
    const add=el('button','Add intended stage');add.type='button';add.onclick=()=>{let i=1;while(value.steps.some(s=>s.id==='s'+i))i++;value.steps.push({id:'s'+i,text:'',target:'',evidence:[anchorFor(u)]});dirty();draw();};
    const addLink=el('button','Add expressed stage relation');addLink.type='button';addLink.onclick=()=>{if(value.steps.length<2){message.textContent='Add at least two stages before linking them.';return;}value.links.push({from:value.steps[0].id,to:value.steps[1].id,kind:'precedes',evidence:[anchorFor(u)]});dirty();draw();};
    parent.append(stages,add,el('p','Links record explicitly stated organization, not inferred execution or progress.','evidence-note'),links,addLink);contentField(parent,'Expressed completion criterion (optional)',u,value,'completion_criterion');draw();
   }
   function draw(){units.replaceChildren();d.units.forEach((u,i)=>{
    const box=el('fieldset',undefined,'unit-review-card'),source=el('textarea');source.readOnly=true;source.rows=5;source.value=sourceFor(u).text;source.setAttribute('aria-label','Exact source for unit '+(i+1));
    box.append(el('legend','Unit '+(i+1)),source,el('small','Source codepoints '+u.start+'–'+u.end));
    if(w.kind!=='action_dispatch'){
     const split=el('button','Split at cursor or selection');split.type='button';split.onclick=()=>{const text=source.value,points=[source.selectionStart,source.selectionEnd];for(const pos of points){if(pos>0&&pos<text.length&&/[\uD800-\uDBFF]/.test(text[pos-1])&&/[\uDC00-\uDFFF]/.test(text[pos])){message.textContent='Place the cursor between complete characters.';return;}}
      const cuts=[0,...points.map(p=>Array.from(text.slice(0,p)).length),Array.from(text).length].filter((v,j,a)=>!j||v!==a[j-1]);
      const parts=cuts.slice(1).map((end,j)=>empty(u.start+cuts[j],u.start+end)).filter(part=>sourceFor(part).text.trim());
      if(parts.length<2){message.textContent='Place the cursor inside the unit, or select one complete contribution.';return;}d.units.splice(i,1,...parts);dirty();draw();message.textContent='Boundaries changed. Classify and describe each resulting contribution.';};box.append(split);
     if(i<d.units.length-1){const merge=el('button','Merge with next unit');merge.type='button';merge.onclick=()=>{d.units.splice(i,2,empty(u.start,d.units[i+1].end));dirty();draw();};box.append(merge);}
    }
    const activity=el('select');for(const name of Object.keys(data.activities)){const o=el('option',human(name));o.value=name;activity.append(o);}activity.value=u.activity;
    const definition=el('p',data.activities[u.activity],'evidence-note'),contents=el('div');
    function drawContent(){contents.replaceChildren();definition.textContent=data.activities[u.activity];for(const key of Object.keys(data.fields[u.activity]||{})){if(!u.fields[key])u.fields[key]={status:'not_expressed'};contentField(contents,human(key)+(key==='summary'?' (required)':' (leave blank if not expressed)'),u,u.fields,key);}if(u.activity==='plan')plan(contents,u);}
    activity.onchange=()=>{u.activity=activity.value;u.fields={};delete u.plan_structure;dirty();drawContent();};
    box.append(field('Primary activity for unit '+(i+1),activity),definition,contents);drawContent();units.append(box);
   });}
   author.required=true;author.maxLength=240;note.required=true;note.maxLength=2400;note.rows=3;author.oninput=dirty;note.oninput=dirty;message.setAttribute('role','status');
   preview.type='submit';save.type='button';save.hidden=true;
   form.append(units,field('Unit reviewer',author),field('Why these boundaries and meanings fit',note),el('p','Content keeps existing citations when unchanged; new fields cite this exact unit. Blank optional fields mean not expressed. This records a named interpretation, not an automatic correctness verdict.','evidence-note'),preview,impact,save,message);container.append(form);draw();
   form.onsubmit=async event=>{event.preventDefault();if(!form.reportValidity())return;d.revision={author:author.value.trim(),note:note.value.trim()};preview.disabled=true;message.textContent='Checking source coverage and dependent evidence…';
    try{const result=await request('/api/unit-reviews/preview',d);previewResult=result;approved=JSON.stringify(d);const p=result.impact;impact.replaceChildren(el('strong','Correction impact'),el('p',`${p.replaced_unit_ids.length} replaced units · ${p.new_unit_ids.length} new units · ${p.removed_edge_ids.length} invalidated connections`),el('p',`${p.removed_work_bindings.length} work bindings and ${p.removed_relationship_reviews.length} relationship reviews need rechecking.`));for(const line of changeSummary(result.annotation_changes))impact.append(el('p',line));if(p.invalidated_layers.length)impact.append(el('p','Cleared coverage layers: '+p.invalidated_layers.map(human).join(', ')+'. Their dependencies were not tracked precisely enough to retain them.'));save.hidden=false;message.textContent='Original source and prior measurements remain unchanged.';}catch(e){message.textContent=e.message;}finally{preview.disabled=false;}
   };
   save.onclick=async()=>{if(approved!==JSON.stringify(d)){dirty();message.textContent='Preview the changed review first.';return;}save.disabled=true;try{const result=await request('/api/unit-reviews',d);await onSaved(result);}catch(e){message.textContent=e.message;save.disabled=false;if(previewResult&&e.message.includes('latest')){const a=el('a','Open latest reviewed observer'),q=new URLSearchParams({run:previewResult.run_id,observer:previewResult.observer});for(const key of ['return_to','review_monitor','review_value'])if(params.get(key))q.set(key,params.get(key));a.href='/semantic-map?'+q;message.append(el('br'),a);}}};
  }
 }
 async function continuation(container,{payload,params}){
  if(!params.get('review_monitor')||!payload.graph.semantic_context?.unit_reviews)return;
  const box=el('section',undefined,'unit-review-continuation'),button=el('button','Monitor this reviewed observer'),status=el('p');
  box.append(el('strong','Continue the investigation'),el('p','Keep the original monitor and receipt. Create the same measurement for this reviewed observer; later corrections on that observer update its values.'),button,status);
  if(params.get('review_value')){const a=el('a','Open original saved measurement');a.href='/semantic-map?'+new URLSearchParams({run:payload.run.id,value:params.get('review_value'),...(params.get('return_to')?{return_to:params.get('return_to')}:{})});box.append(a);}container.append(box);
  button.onclick=async()=>{button.disabled=true;try{const d=await request('/api/unit-reviews/monitor',{graph_id:payload.graph.id,monitor_id:params.get('review_monitor')});status.replaceChildren(el('span','Saved. Background analysis will update this monitor. '));const a=el('a','Open reviewed monitor');a.href='/?'+new URLSearchParams({monitor:d.monitor.id});status.append(a);}catch(e){status.textContent=e.message;button.disabled=false;}};
 }
 return {append,continuation,changeSummary};
})();
