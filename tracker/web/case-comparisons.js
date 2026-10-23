(function(root){
 'use strict';
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 const labels={all:'All task contexts',improved:'Improved reported outcome',regressed:'Regressed reported outcome',unchanged:'Unchanged reported outcome',unresolved:'Outcome unresolved',choose_rollouts:'Choose repeat rollouts',unmatched:'No counterpart'};
 const cardModes=[['actions','Actions & feedback'],['all','All units'],['failed-checks','Failed-check paths'],['retry-paths','Retry paths'],['attempt-pairs','Linked attempt pairs']];
 const text=v=>v==null?'Not recorded':typeof v==='object'?JSON.stringify(v):String(v);
 const brief=v=>{const s=text(v);return s.length>260?s.slice(0,260)+'…':s;};
 const button=(name,fn)=>{const b=el('button',name);b.type='button';b.onclick=fn;return b;};
 const field=(name,input)=>{const l=el('label',name);l.append(input);return l;};
 async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined),d=await r.json();if(!r.ok)throw Error(d.error||r.statusText);return d;}
 const url=(route,params)=>route+'?'+new URLSearchParams(params);
 const evidenceReturn=()=>location.pathname+location.search+(!new URLSearchParams(location.search).has('saved')||location.hash==='#research-all'?location.hash:'#research-evidence');
 function options(rows,label){
  const select=el('select');select.setAttribute('aria-label',label);
  if(rows.length!==1){const o=el('option','Select a rollout');o.value='';select.append(o);}
  for(const [index,r]of rows.entries()){
   const m=r.metadata,success=(r.comparison_outcome||r.outcome)?.verified_success;
   const o=el('option',(index+1)+'. '+(m.checkpoint?'Checkpoint '+m.checkpoint:m.training_step!=null?'Step '+m.training_step:m.model||m.experiment||'Rollout')+' · '+(typeof success==='boolean'?success?'success':'failure':'outcome unknown'));o.value=r.id;select.append(o);
  }
  return select;
 }
 async function openPair(doc,reference,selected,observer){
  const dialog=el('dialog',null,'case-dialog'),head=el('div',null,'case-dialog-head'),body=el('div',null,'case-dialog-body');
  head.append(el('h2','Compare rollout evidence'),button('Close',()=>dialog.close()));dialog.append(head,body);document.body.append(dialog);
  const previousFocus=document.activeElement;
  dialog.addEventListener('close',()=>{dialog.remove();const u=new URL(location.href);for(const k of ['case_reference','case_selected','case_observer','case_cards'])u.searchParams.delete(k);history.replaceState(history.state,'',u);previousFocus?.focus();});dialog.showModal();
  let request=0;
  async function load(protocol){
   const token=++request;body.replaceChildren(el('p','Loading saved evidence…'));const query={investigation:doc.id,reference,selected,...(protocol?{observer:protocol}:{})};
   try{
    const data=await api(url('/api/case-comparisons/pair',query));if(!dialog.open||token!==request)return;
    const u=new URL(location.href);u.searchParams.set('case_reference',reference);u.searchParams.set('case_selected',selected);u.searchParams.set('case_observer',data.reference.graph.observer);history.replaceState(history.state,'',u);
    body.replaceChildren();const title=el('div',null,'case-pair-title');title.append(el('h3',text(data.context.task_id)),el('span',labels[data.status]));body.append(title);
    const select=el('select');select.setAttribute('aria-label','Comparison observations');for(const p of data.protocols){const o=el('option',p.label);o.value=p.id;select.append(o);}select.value=data.reference.graph.observer;select.onchange=()=>load(select.value);
    body.append(field('Saved observations on both rollouts',select),el('p','Each column follows its own source order. Open a card to inspect its exact map and relationships.','case-note'));
    if(data.missing_context.length)body.append(el('p','Context not recorded: '+data.missing_context.map(k=>k.replaceAll('_',' ')).join(', ')+'. This is a candidate task match.','case-note'));
    const context=el('details');context.append(el('summary','Task context & configuration changes'),el('pre',JSON.stringify({context:data.context,changes:data.configuration_changes},null,2)));body.append(context);
    const mode=el('select');mode.disabled=true;mode.setAttribute('aria-label','Comparison cards');for(const [v,t]of cardModes){const o=el('option',t);o.value=v;mode.append(o);}const savedMode=new URL(location.href).searchParams.get('case_cards');mode.value=cardModes.some(([v])=>v===savedMode)?savedMode:'actions';body.append(field('Show',mode));
    const columns=el('div',null,'case-columns');body.append(columns);
    const draws=[];
    for(const [key,label]of [['reference','Reference'],['selected','Selected']]){
     const side=data[key],row=side.run,column=el('section',null,'case-column');columns.append(column);
     const outcome=row.comparison_outcome||row.outcome||{},meta=row.metadata,header=el('header');
     const coordinates=[meta.checkpoint?'Checkpoint '+meta.checkpoint:null,meta.training_step!=null?'Step '+meta.training_step:null].filter(Boolean);
     header.append(el('h3',label),el('strong',meta.model||meta.experiment||'Captured rollout'));
     if(coordinates.length)header.append(el('small',coordinates.join(' · ')));
     header.append(el('p','Reported success: '+text(outcome.verified_success)+' · Reward: '+text(row.outcome?.recorded_reward)),el('small','Capture: '+row.state.replaceAll('_',' ')+' · '+side.graph.observer_label));
     if(row.outcome_evaluation){const ev=row.outcome_evaluation,details=el('details',null,'case-evaluation');details.append(el('summary',ev.selection.label+' · '+(ev.status==='missing'?'report missing':ev.status==='multiple'?'multiple reports; outcome unresolved':ev.status)));for(const r of ev.records){details.append(el('strong',r.producer+' · '+r.verdict),el('p',r.summary));for(const item of r.evidence)details.append(el('pre',item.text));}header.append(details);}
     if(meta.synthetic)header.append(el('small','Synthetic control'));
     const mapParams={run:row.id,observer:side.graph.observer,graph:side.graph.id,level:'units',return_to:evidenceReturn()};
     const map=el('a','Open behavior map →');map.href=url('/semantic-map',mapParams);header.append(map);column.append(header);
     const list=el('div','Loading saved cards…','case-units');column.append(list);
     const [graph,foundation]=await Promise.all([api('/api/graphs/'+encodeURIComponent(side.graph.id)),api(url('/api/map-foundation',{graph:side.graph.id}))]);
     if(!dialog.open||token!==request)return;
     const layout=root.RolloutMapLayout.project(graph,foundation.excluded_edge_ids,foundation.content_sources.excluded_unit_ids,foundation.source_order);
     const paths=root.InspectionPaths.catalog(graph,layout,foundation.excluded_edge_ids);
     const units=layout.nodes.filter(n=>n.kind==='unit').length;
     const hasSemantics=graph.coverage.semantic_relations!=='unavailable';header.append(el('small',hasSemantics?units+' semantic units · '+layout.nodes.length+' visible cards · '+graph.coverage.semantic_relations+' relationship coverage':'Source only · '+layout.nodes.length+' cards · semantic paths not yet measured'));
     if(graph.semantic_context?.provenance){const versions=el('details');versions.append(el('summary','Observation versions'),el('pre',JSON.stringify(graph.semantic_context.provenance,null,2)));header.append(versions);}
     if(foundation.excluded_edge_ids.length||foundation.content_sources.excluded_unit_ids.length)header.append(el('small','Source checks excluded '+foundation.excluded_edge_ids.length+' links and '+foundation.content_sources.excluded_unit_ids.length+' annotations.'));
     if(Object.values(foundation.source_order?.nodes||{}).some(n=>n.reason))header.append(el('small','Some source order is unresolved. Card positions do not establish a sequence for those records.'));
     const shortcuts=el('div',null,'case-path-shortcuts');shortcuts.setAttribute('aria-label',label+' saved behavior paths');
     for(const group of paths){const b=button(group.label+' · '+(!hasSemantics&&!group.cases.length?'not measured':group.cases.length),()=>{mode.value=group.id;mode.onchange();});b.disabled=!group.cases.length;shortcuts.append(b);}header.append(shortcuts);
     let shown=0,rows=[];
     const more=button('Show more',append);
     function append(){
      more.remove();for(const n of rows.slice(shown,shown+20)){
       const pathGroup=paths.find(g=>g.id===mode.value);
       if(pathGroup){
        const stats=root.InspectionPaths.summary(n),card=el('article',null,'case-path'),start=n.nodes.find(node=>node.id===n.anchor_id),a=el('a',(start?root.UnitReading.ref(start)+' · ':'')+n.title+' →');
        a.href=url('/semantic-map',{...mapParams,inspect:pathGroup.id,inspect_case:n.id,return_to:evidenceReturn()});
        const outcomes=stats.checks?'recorded checks: '+stats.failed+' failed / '+stats.passed+' passed / '+stats.unknown+' unknown':'check outcomes not recorded';
        card.append(a,el('p',stats.attempts+' linked attempts'+(stats.truncated?' shown':'')+' · '+outcomes),el('small',stats.feedbackUses+' feedback-use links · '+stats.changes+' change links'));
        if(n.gaps.length)card.append(el('small',n.gaps.join(' ')));list.append(card);continue;
       }
       const card=el('article',null,'case-unit'),style=root.RolloutMapLayout.cardStyle(n);card.style.setProperty('--case-color',style.color);card.style.setProperty('--case-tint',style.tint);
       const a=el('a',root.UnitReading.ref(n)+' · '+n.activity.replaceAll('_',' '));a.href=url('/semantic-map',{...mapParams,focus_unit:n.id,return_to:evidenceReturn()});card.append(a,el('p',brief(root.UnitReading.cardText(n))));
       const groups=root.UnitReading.sections(layout,n.id),links=groups.flatMap(g=>g.rows).filter(r=>!r.via);if(links.length)card.append(el('small',links.length+' saved links · '+[...new Set(links.map(r=>root.RolloutMapLayout.relationMeaning(r.edge).label))].slice(0,3).join(' · ')));
       for(const r of root.RolloutMapLayout.capturedResponses(layout,n.id).filter(r=>r.action_card_ids.includes(n.id))){const d=el('details');d.append(el('summary','Captured call feedback'),el('p','Whole-call result; not assigned to one split or partial unit.'),el('pre',r.response.properties.text||''));card.append(d);}
       list.append(card);
      }
      shown+=20;if(shown<rows.length){more.textContent='Show next '+Math.min(20,rows.length-shown)+' · '+(rows.length-shown)+' remaining';list.append(more);}
     }
     function draw(){
      map.href=url('/semantic-map',{...mapParams,return_to:evidenceReturn()});
      const group=paths.find(g=>g.id===mode.value);rows=group?group.cases:layout.nodes.filter(n=>mode.value==='all'||n.lane===1||n.lane===2);shown=0;list.replaceChildren();
      if(group)list.append(el('p',rows.length?group.description:group.empty,'case-note'));
      else if(!rows.length)list.append(el('p','No action or feedback cards. Choose All units to see the recorded text.','case-note'));
      append();
     }
     draws.push(draw);draw();
    }
    mode.onchange=()=>{const url=new URL(location.href);url.searchParams.set('case_cards',mode.value);history.replaceState(history.state,'',url);draws.forEach(fn=>fn());};draws.forEach(fn=>fn());mode.disabled=false;body.append(el('p',data.basis,'case-note'));
   }catch(e){if(dialog.open&&token===request)body.replaceChildren(el('p',e.message,'case-error'));}
  }
  await load(observer);
 }
 function render(host,doc,onRecapture){
  host.replaceChildren(el('h2','Compare rollout cases'),el('p','Pair the same recorded task in both selections. Repeated rollouts stay selectable; missing counterparts remain visible.','case-note'));
  const controls=el('div',null,'case-controls'),filter=el('select');filter.setAttribute('aria-label','Rollout outcome filter');for(const [key,label]of Object.entries(labels)){const o=el('option',label);o.value=key;filter.append(o);}controls.append(field('Cases',filter));host.append(controls);
  const status=el('p',null,'case-note'),list=el('div',null,'case-groups'),paging=el('div',null,'case-controls');host.append(status,list,paging);let offset=0,request=0;
  async function load(){
   const token=++request;list.replaceChildren(el('p','Loading task contexts…'));paging.replaceChildren();
   try{const data=await api(url('/api/case-comparisons',{investigation:doc.id,status:filter.value,offset}));if(token!==request||!host.isConnected)return;
    list.replaceChildren();if(!data.available){list.append(el('p',data.reason,'case-note'),button('Capture a new comparison',onRecapture));controls.hidden=true;return;}
    status.textContent=data.source_counts.baseline+' reference / '+data.source_counts.current+' selected rollouts · '+data.total_contexts+' task contexts · '+(data.counts.unmatched||0)+' without a counterpart · '+data.context_incomplete+' with missing context';
    for(const group of data.groups){
     const card=el('article',null,'case-group'),heading=el('div',null,'case-group-heading');heading.append(el('strong',text(group.context.task_id)),el('span',labels[group.status]));card.append(heading);
     card.append(el('small',[group.context.environment,group.context.split,group.context.task_revision?'Task revision '+text(group.context.task_revision):null].filter(Boolean).join(' · ')||'Task context unspecified'));
     if(group.missing_context.length)card.append(el('small','Missing: '+group.missing_context.map(k=>k.replaceAll('_',' ')).join(', ')));
     const a=options(group.baseline,'Reference rollout'),b=options(group.current,'Selected rollout'),open=button('Compare evidence',()=>openPair(doc,a.value,b.value));
     const leftMap=el('a','Open reference map'),rightMap=el('a','Open selected map');
     const update=()=>{open.disabled=!a.value||!b.value;for(const [select,link]of [[a,leftMap],[b,rightMap]]){const graphs=doc.snapshot.case_evidence?.sources[select.value]?.graphs||[],graph=graphs.find(g=>g.observer!=='source'&&g.coverage.semantic_relations!=='unavailable')||graphs.find(g=>g.observer==='source');link.hidden=!graph;if(graph)link.href=url('/semantic-map',{run:select.value,observer:graph.observer,graph:graph.id,return_to:evidenceReturn()});}};a.onchange=b.onchange=update;update();
     const fields=el('div',null,'case-controls');fields.append(field('Reference · '+group.baseline.length,a),field('Selected · '+group.current.length,b),open);const maps=el('div',null,'case-controls');maps.append(leftMap,rightMap);card.append(fields,maps);list.append(card);
    }
    if(!data.groups.length)list.append(el('p','No cases match this filter.','case-note'));
    const previous=button('Previous cases',()=>{offset=Math.max(0,offset-data.limit);load();}),next=button('Next cases',()=>{offset+=data.limit;load();});previous.disabled=!offset;next.disabled=offset+data.limit>=data.filtered_contexts;paging.append(previous,el('span',data.filtered_contexts+' matching contexts'),next);
   }catch(e){if(token===request)list.replaceChildren(el('p',e.message,'case-error'));}
  }
  const q=new URLSearchParams(location.search);filter.value=Object.hasOwn(labels,q.get('case_filter'))?q.get('case_filter'):'all';
  filter.onchange=()=>{offset=0;const url=new URL(location.href);url.searchParams.set('case_filter',filter.value);history.replaceState(history.state,'',url);load();};load();
  if(q.get('case_reference')&&q.get('case_selected'))openPair(doc,q.get('case_reference'),q.get('case_selected'),q.get('case_observer'));
 }
 async function open(context={}){
  const previous=document.activeElement,dialog=el('dialog',null,'case-dialog case-setup'),head=el('div',null,'case-dialog-head'),body=el('div',null,'case-dialog-body');
  head.append(el('h2','Compare rollout cases'),button('Close',()=>dialog.close()));dialog.append(head,body);document.body.append(dialog);
  dialog.addEventListener('close',()=>{dialog.remove();previous?.focus();});dialog.showModal();body.append(el('p','Loading captured runs…'));
  try{
   const catalog=await api('/api/case-comparisons/scopes');if(!dialog.open)return;
   body.replaceChildren();if(!catalog.experiments.length){body.append(el('p','Import or connect rollouts with an experiment name to compare runs.'),Object.assign(el('a','Connect data'),{href:'/connections'}));return;}
   const form=el('form'),columns=el('div',null,'case-selection-columns');form.append(el('p','Choose each side independently. This saves the current rollouts and graph versions for inspection.','case-note'),columns);body.append(form);
   function choose(name,choices,value){const s=el('select');s.setAttribute('aria-label',name);for(const [v,label]of choices){const o=el('option',label);o.value=v;s.append(o);}if(value!=null)s.value=value;return s;}
   function side(name,initial={},fallback){
    const box=el('fieldset'),legend=el('legend',name);box.append(legend);columns.append(box);
    const run=choose(name+' run',catalog.experiments.map(e=>[e.name,e.name]),initial.experiment||fallback),mode=choose(name+' rollouts',[['all','All captured rollouts'],['checkpoint','One checkpoint'],['range','Rollout step range']],initial.steps?'range':initial.checkpoint?'checkpoint':'all');
    const checkpoint=choose(name+' checkpoint',[]),coordinate=choose(name+' coordinate',[]),from=el('input'),to=el('input'),environment=el('input');
    environment.value=initial.environment||'';environment.placeholder='All environments';environment.setAttribute('aria-label',name+' environment');
    for(const [input,label]of [[from,'first step'],[to,'last step']]){input.type='number';input.min=0;input.step=1;input.setAttribute('aria-label',name+' '+label);}
    const cpField=field('Checkpoint',checkpoint),range=el('div',null,'case-selection-fields');range.append(field('Recorded rollout coordinate',coordinate),field('First step',from),field('Last step',to));
    const evaluator=choose(name+' outcome source',[]);
    const hint=el('p',null,'case-note');box.append(field('Run',run),field('Rollouts',mode),cpField,range,field('Outcome source',evaluator),field('Environment (optional)',environment),hint);
    let group;
    function bounds(){const c=group.coordinates[Number(coordinate.value)];from.value=c?.first??'';to.value=c?.last??'';}
    function visibility(){cpField.hidden=mode.value!=='checkpoint';range.hidden=mode.value!=='range';checkpoint.required=!cpField.hidden;checkpoint.disabled=cpField.hidden;for(const i of [coordinate,from,to]){i.required=!range.hidden;i.disabled=range.hidden;}hint.textContent=mode.value==='range'?'Uses captured rollout coordinates, which may differ from the trainer chart’s steps.':group.rollouts+' captured rollouts in this run';}
    function update(restore=false){
     group=catalog.experiments.find(e=>e.name===run.value)||catalog.experiments[0];run.value=group.name;
     const evaluationKey=e=>JSON.stringify({producer:e.producer,label:e.label,purpose:e.purpose});
     evaluator.replaceChildren(Object.assign(el('option','Outcome recorded in the trajectory'),{value:''}),...(group.evaluations||[]).map(e=>Object.assign(el('option',e.label+' · '+e.producer+' · '+e.purpose.replaceAll('_',' ')+' · '+e.rollouts+' rollouts'),{value:evaluationKey(e)})));
     if(restore&&initial.evaluation){const key=evaluationKey(initial.evaluation);if(!Array.from(evaluator.options).some(o=>o.value===key))evaluator.append(Object.assign(el('option',initial.evaluation.label+' · no matching reports'),{value:key}));evaluator.value=key;}
     checkpoint.replaceChildren(...group.checkpoints.map(v=>Object.assign(el('option',v),{value:v})));
     coordinate.replaceChildren(...group.coordinates.map((c,i)=>Object.assign(el('option',c.clock+' · '+c.basis),{value:String(i)})));
     mode.querySelector('[value="checkpoint"]').disabled=!group.checkpoints.length;mode.querySelector('[value="range"]').disabled=!group.coordinates.length;
     if(mode.selectedOptions[0]?.disabled&&!(restore&&(initial.steps||initial.checkpoint)))mode.value='all';
     if(restore&&initial.checkpoint)checkpoint.value=initial.checkpoint;
     if(restore&&initial.steps){const index=group.coordinates.findIndex(c=>c.clock===initial.clock&&c.basis===initial.basis);if(index>=0)coordinate.value=String(index);}
     bounds();if(restore&&initial.steps){from.value=initial.steps[0];to.value=initial.steps[1];}visibility();
    }
    run.onchange=()=>update();mode.onchange=visibility;coordinate.onchange=bounds;update(true);
    return ()=>{const result={experiment:run.value};if(evaluator.value)result.evaluation=JSON.parse(evaluator.value);if(environment.value.trim())result.environment=environment.value.trim();if(mode.value==='checkpoint')result.checkpoint=checkpoint.value;if(mode.value==='range'){const c=group.coordinates[Number(coordinate.value)];result.steps=[Number(from.value),Number(to.value)];result.clock=c?.clock;result.basis=c?.basis;}return result;};
   }
   const reference=side('Reference',context.reference,catalog.experiments[0].name),selected=side('Selected',context.selected,catalog.experiments[1]?.name||catalog.experiments[0].name);
   const title=el('input');title.value=context.title||'Rollout case comparison';title.maxLength=120;title.required=true;form.append(field('Title',title));
   const error=el('p',null,'case-error');error.setAttribute('role','alert');const submit=el('button','Compare captured rollouts','primary');submit.type='submit';form.append(submit,error);
   form.onsubmit=async event=>{event.preventDefault();submit.disabled=true;error.textContent='';try{const saved=await api('/api/investigations/cases',{reference:reference(),selected:selected(),title:title.value,hypothesis:context.hypothesis||'',...(context.monitor_ids?{monitor_ids:context.monitor_ids}:{}),...(context.parent_id?{parent_id:context.parent_id}:{})});location.href='/investigate?'+new URLSearchParams({saved:saved.id});}catch(e){error.textContent=e.message;submit.disabled=false;}};
  }catch(e){body.replaceChildren(el('p',e.message,'case-error'));}
 }
 function openTrainer(context){
  const previous=document.activeElement,dialog=el('dialog',null,'case-dialog case-setup'),head=el('div',null,'case-dialog-head'),body=el('div',null,'case-dialog-body');
  dialog.setAttribute('aria-label','Compare linked rollouts');head.append(el('h2','Compare linked rollouts'),button('Close',()=>dialog.close()));dialog.append(head,body);document.body.append(dialog);
  dialog.onclose=()=>{dialog.remove();previous?.focus();};dialog.showModal();
  const form=el('form'),columns=el('div',null,'case-selection-columns');
  form.append(el('p','Choose native update intervals. Recorded training-use links select the rollouts; the saved comparison includes link coverage and behavior maps.','case-note'),columns);body.append(form);
  const choices=context.streams,full=choices[0].series.full_range;
  function side(name,index,initial){
   const box=el('fieldset'),select=el('select');select.setAttribute('aria-label',name+' metric stream');box.append(el('legend',name));columns.append(box);
   choices.forEach((c,i)=>select.append(Object.assign(el('option',c.series.context.experiment+' · '+c.series.label+' · '+c.series.context.producer+' · '+c.series.context.split),{value:String(i)})));select.value=String(index);
   const from=el('input'),to=el('input'),hint=el('p',null,'case-note');
   for(const [input,label,value]of [[from,'first step',initial?.[0]],[to,'last step',initial?.[1]]]){input.type='number';input.min=0;input.step='any';input.required=true;input.setAttribute('aria-label',name+' '+label);input.value=value??'';input.oninput=()=>to.setCustomValidity('');}
   const fields=el('div',null,'case-native-range');fields.append(field('From step',from),field('To step',to));box.append(field('Metric stream',select),hint,fields);
   const update=()=>{const s=choices[Number(select.value)].series;hint.textContent=s.context.clock+' · '+s.context.population+' · recorded range '+s.full_range.start+'–'+s.full_range.end;};select.onchange=update;update();
   return ()=>{if(Number(from.value)>Number(to.value)){to.setCustomValidity('End must follow start.');form.reportValidity();throw Error('Check the interval bounds.');}const c=choices[Number(select.value)];return {series_id:c.series.id,as_of:c.as_of,start:Number(from.value),end:Number(to.value)};};
  }
  const split=Math.floor((full.start+full.end)/2),multiple=choices.length>1;
  const selectedRange=context.range||(multiple?[full.start,full.end]:[Math.min(split+1,full.end),full.end]);
  const priorEnd=Math.ceil(selectedRange[0])-1,priorStart=Math.max(full.start,priorEnd-(Math.floor(selectedRange[1])-Math.ceil(selectedRange[0])));
  const referenceRange=multiple?selectedRange:context.range?(priorEnd>=full.start?[priorStart,priorEnd]:null):[full.start,split];
  const reference=side('Reference',multiple?1:0,referenceRange),selected=side('Selected',0,selectedRange);
  if(!referenceRange)form.append(el('p','Enter a reference interval, or add a comparison run to the chart.','case-note'));
  const error=el('p',null,'case-error');error.setAttribute('role','alert');const submit=el('button','Save linked comparison','primary');submit.type='submit';form.append(submit,error);
  form.onsubmit=async event=>{event.preventDefault();submit.disabled=true;error.textContent='';try{const doc=await api('/api/investigations/trainer-cases',{reference:reference(),selected:selected(),return_to:context.return_to});location.href=url('/investigate',{saved:doc.id});}catch(e){error.textContent=e.message;submit.disabled=false;}};
 }
 function renderTrainerSelection(host,doc){
  const data=doc.snapshot.trainer_selection,panel=el('section',null,'iv-panel'),heading=el('div',null,'case-controls');
  heading.append(el('h2','Selected rollouts'));
  if(data.return_to?.startsWith('/?'))heading.append(Object.assign(el('a','Back to training chart'),{href:data.return_to}));
  const status=el('p',null,'case-note'),refresh=button('Recheck linked evidence',async()=>{refresh.disabled=true;try{const next=await api('/api/investigations/trainer-cases',{...doc.controls,title:doc.title,hypothesis:doc.hypothesis,parent_id:doc.id});location.href=url('/investigate',{saved:next.id});}catch(e){status.textContent=e.message;refresh.disabled=false;}});heading.append(refresh);panel.append(heading);
  panel.append(el('p','Saved '+new Date(doc.snapshot.captured_at).toLocaleString()+'. Rechecking keeps these native logs fixed and captures newly available links and maps.','case-note'));
  const columns=el('div',null,'case-selection-columns');
  for(const [side,label]of [['baseline','Reference'],['current','Selected']]){
   const c=data.cohorts[side],s=c.series.context,card=el('div',null,'case-scope'),refs=c.references,inventory=c.reference_inventory,total=Object.values(refs).reduce((a,b)=>a+b,0);
   card.append(el('small',label),el('strong',s.experiment),el('p',c.series.label+' · '+s.clock+' '+(c.selection.start??'first')+'–'+(c.selection.end??'last')),el('small',s.producer+' · '+s.split+' · '+s.population));
   card.append(el('p',doc.snapshot.population[side].length+' distinct rollouts for comparison · '+c.run_ids.length+' linked in total'),el('p',c.records+' native logs · '+(refs.matched||0)+' / '+total+' reference occurrences resolved'));
   card.append(el('small',(inventory.complete||0)+' logs with complete reference inventories · '+(inventory.partial||0)+' partial · '+(inventory.not_declared||0)+' without references'));
   if(c.coordinates.missing)card.append(el('p',c.coordinates.missing+' coordinates without this metric definition; excluded from the linked population.'));
   const gaps=Object.entries(c.coordinates).filter(([key])=>!['recorded','missing'].includes(key));if(gaps.length)card.append(el('p',gaps.map(([key,n])=>n+' '+key.replaceAll('_',' ')+' coordinates').join(' · ')+'. Links retained; values are unresolved.'));
   if(total>(refs.matched||0))card.append(el('p',(total-(refs.matched||0))+' references unresolved; these do not count as unsuccessful rollouts.'));
   if(!c.run_ids.length)card.append(Object.assign(el('a','Add training-use links'),{href:'/integration-guide#training-samples'}));
   const details=el('details');details.append(el('summary','Saved selection & link receipts'),el('pre',JSON.stringify({selection:c.selection,series:c.series,coordinates:c.coordinates,logs:c.logs},null,2)));card.append(details);columns.append(card);
  }
  panel.append(columns);
  if(data.shared_run_ids.length){const shared=el('details');shared.append(el('summary',data.shared_run_ids.length+' rollouts reused on both sides · excluded from outcome changes'));
   const rows=doc.snapshot.source_rows.filter(r=>data.shared_run_ids.includes(r.id));let shown=0;const more=button('Show more reused rollouts',append);
   function append(){more.remove();for(const row of rows.slice(shown,shown+20)){const graphs=doc.snapshot.case_evidence.sources[row.id]?.graphs||[],graph=graphs.find(g=>g.observer!=='source'&&g.coverage.semantic_relations!=='unavailable')||graphs.find(g=>g.observer==='source');const p=el('p');if(graph)p.append(Object.assign(el('a',row.metadata.task_id||'Captured rollout'),{href:url('/semantic-map',{run:row.id,observer:graph.observer,graph:graph.id,return_to:evidenceReturn()})}));else p.append(el('span',(row.metadata.task_id||'Captured rollout')+' · no saved map'));shared.append(p);}shown+=20;if(shown<rows.length)shared.append(more);}append();panel.append(shared);
  }
  panel.append(el('p',data.boundary,'case-note'),status);host.append(panel);
 }
 function renderSaved(host,doc,onRevision){
  if(doc.snapshot.trial_selection){
   host.replaceChildren();const data=doc.snapshot.trial_selection,head=el('section',null,'iv-panel');
   head.append(el('h2','Selected rollouts'),Object.assign(el('a','Back to trial & findings'),{href:'/investigate?'+new URLSearchParams({saved:data.investigation_id,panel:'checks'})+'#'+data.check_id}));
   head.append(el('p',(data.selection==='paired'?'Paired completed trials':'All returned evidence')+' · '+data.seeds.length+' / '+data.planned_seeds.length+' planned seeds','case-note'));
   const columns=el('div',null,'case-selection-columns');
   for(const [side,label]of [['baseline','Reference'],['current',data.arm]]){const card=el('div',null,'case-scope'),group=data.cohorts[side];card.append(el('small',label),el('strong',doc.snapshot.population[side].length+' distinct rollouts'));
    const occurrences=group.flatMap(j=>j.rollouts),unavailable=occurrences.filter(r=>r.status!=='available');card.append(el('p',group.length+' jobs · '+unavailable.length+' unavailable or mismatched source links'));
    const states={};for(const j of group)states[j.execution]=(states[j.execution]||0)+1;card.append(el('small',Object.entries(states).map(([k,n])=>n+' '+k).join(' · ')));columns.append(card);}
   head.append(columns);
   if(data.shared_run_ids.length){const shared=el('details');shared.append(el('summary',data.shared_run_ids.length+' shared source revisions · excluded from behavior changes'));
    for(const rid of data.shared_run_ids){const g=doc.snapshot.case_evidence.sources[rid]?.graphs.find(g=>g.observer==='source');if(g)shared.append(Object.assign(el('a','Inspect shared rollout'),{href:url('/semantic-map',{run:rid,graph:g.id,observer:g.observer,return_to:evidenceReturn()})}));}head.append(shared);}
   if(data.excluded_jobs.length){const omitted=el('details');omitted.append(el('summary',data.excluded_jobs.length+' jobs outside the paired selection'),el('p','A pair needs completed execution, reported applied settings, the primary measurement and every declared rollout source. Inspect the trial for missing results and links.','case-note'));head.append(omitted);}
   head.append(el('p',data.boundary,'case-note'));host.append(head);root.CaseBehaviorView?.render(host,doc);
   const panel=el('section',null,'iv-panel');panel.id='ii-compare-rollout-cases';host.append(panel);render(panel,doc,()=>{});host.append(InvestigationFollowups.render(doc,onRevision,()=>{}));return;
  }
  if(doc.snapshot.trainer_selection){host.replaceChildren();renderTrainerSelection(host,doc);root.CaseBehaviorView?.render(host,doc);const panel=el('section',null,'iv-panel');panel.id='ii-compare-rollout-cases';host.append(panel);render(panel,doc,()=>{});if(doc.hypothesis)host.append(el('p',doc.hypothesis,'case-note'));host.append(InvestigationFollowups.render(doc,onRevision,()=>{}));return;}
  host.replaceChildren();const scope=el('section',null,'iv-panel'),heading=el('div',null,'case-controls');heading.append(el('h2','Selected rollouts'),button('New comparison',()=>open({...doc.controls,title:doc.title,hypothesis:doc.hypothesis,parent_id:doc.id})));scope.append(heading);
  const columns=el('div',null,'case-selection-columns');for(const [side,label]of [['baseline','Reference'],['current','Selected']]){const s=doc.scope[side],card=el('div',null,'case-scope');card.append(el('small',label),el('strong',s.experiment),el('p',doc.snapshot.population[side].length+' rollouts · '+(s.checkpoint?'checkpoint '+s.checkpoint:s.steps?'steps '+s.steps.join('–')+' · '+s.clock+' / '+s.basis:'all captured rollouts')));if(s.environment)card.append(el('p',s.environment));card.append(el('small',s.evaluation?'Outcome: '+s.evaluation.label+' · '+s.evaluation.producer:'Outcome: recorded in trajectory'));columns.append(card);}scope.append(columns,el('p','Saved '+new Date(doc.snapshot.captured_at).toLocaleString()+' · late arrivals do not change this comparison.','case-note'));host.append(scope);
  root.CaseBehaviorView?.render(host,doc);
  const panel=el('section',null,'iv-panel');panel.id='ii-compare-rollout-cases';host.append(panel);render(panel,doc,()=>open(doc.controls));
  if(doc.hypothesis)host.append(el('p',doc.hypothesis,'case-note'));host.append(InvestigationFollowups.render(doc,onRevision,()=>{}));
 }
 root.CaseComparisonsView={render,open,renderSaved,openTrainer};
})(globalThis);
