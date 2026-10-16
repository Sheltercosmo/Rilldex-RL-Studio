'use strict';
// Geometry over existing identities only. No inferred causal or strategy edges.
(function(root){
 const families={feedback_for:'feedback',recorded_with:'execution',same_action_target:'return',revisits_after_error_report:'return',completed_after_failed_call:'return',declares_same_work_as:'declaration',attempts_declared_work:'declaration',prepares_declared_work:'declaration',checks_declared_work:'declaration',attempts_plan_step:'plan',prepares_plan_step:'plan',checks_plan_step:'plan',assesses:'assessment',revises:'assessment',in_work_context:'scope',attempts_requested_work:'scope',prepares_requested_work:'scope'};
 const colors={order:'#b6c4cc',feedback:'#487ca3',execution:'#487ca3',return:'#a169ac',declaration:'#3f8b78',plan:'#c38c36',assessment:'#cb7355',scope:'#58948c',other:'#83919a'};
 families.records_result_for_declared_work='declaration';families.records_result_for_plan_stage='plan';
 const resultLabels={fulfilled:'Work scope fulfilled',partial:'Some work established',failed:'Work attempt failed',pending:'Work result pending',not_established:'Work result not established'};
 function declarationInFocus(edge,focus,layer){return layer==='all'||edge.family!=='declaration'||!focus?.startsWith('declared:')||edge.declared_work_id===focus.slice(9);}
 function project(doc,run,visible){
  const pos=new Map(run.events.map((e,i)=>[e.id,e.index??i]));
  const ordered=[...doc.units].sort((a,b)=>pos.get(a.source.event_id)-pos.get(b.source.event_id)||a.source.start-b.source.start||a.source.end-b.source.end);
  const chosen=ordered.filter(u=>visible.has(u.id)),nodes=[],byId=new Map();let row=-1,lastActor=null,lastTrajectory=null;
  for(const u of chosen){
   const lane=u.kind==='action'?1:u.kind==='feedback'?2:0;
   const linked=u.kind==='feedback'?(doc.relations||[]).find(r=>r.type==='feedback_for'&&r.from===u.id):null;
   const action=linked&&byId.get(linked.to);let yrow;
   if(action&&!nodes.some(n=>n.row===action.row&&n.lane===2))yrow=action.row;
   else if(lane===1&&row>=0&&lastActor===u.actor&&lastTrajectory===u.trajectory_id&&!nodes.some(n=>n.row===row&&n.lane===1))yrow=row;
   else yrow=++row;
   const n={id:u.id,unit:u,lane,row:yrow,x:40+lane*304,y:52+yrow*158,width:264,height:120,ordinal:ordered.indexOf(u)+1};
   nodes.push(n);byId.set(u.id,n);lastActor=u.actor;lastTrajectory=u.trajectory_id;
  }
  const lanes=[...new Set(nodes.map(n=>n.lane))].sort();
  for(const n of nodes)n.x=40+lanes.indexOf(n.lane)*304;
  const edges=[];let prior=null;
  for(const n of nodes){if(prior&&prior.unit.trajectory_id===n.unit.trajectory_id)edges.push({from:prior.id,to:n.id,type:'source_order',family:'order',label:'Source order',hidden:Math.max(0,n.ordinal-prior.ordinal-1)});prior=n;}
  for(const [index,r]of (doc.relations||[]).entries())if(byId.has(r.from)&&byId.has(r.to))edges.push({...r,index,family:families[r.type]||'other',label:resultLabels[r.work_result]||r.type.replaceAll('_',' ')});
  return {nodes,edges,lanes,width:52+Math.max(1,lanes.length)*304,height:Math.max(240,100+(row+1)*158),hidden:ordered.length-chosen.length};
 }
 const materialLabels={contents:'Contents recorded',partial_contents:'Some contents recorded',reference_only:'Reference only',recorded_uninspected:'Material uninspected',absent:'No requested material',unresolved:'Material unresolved',uninspected:'Not inspected'};
 function mountPlans(host,doc,visible,{focus,onUnit,onStage,onStageEvidence,onTransition,onDeclaredLink}){
  const plans=(doc.plan_execution?.plans||[]).filter(p=>visible.has(p.plan_unit_id)||p.stages.some(s=>s.action_unit_ids.some(id=>visible.has(id))));
  const html=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
  const svgEl=(tag,attrs)=>{const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs||{}))e.setAttribute(k,v);return e;};
  for(const plan of plans){
   const section=html('section',undefined,'plan-blueprint');section.dataset.planUnit=plan.plan_unit_id;
   const title=html('button',plan.text,'plan-blueprint-title');title.type='button';title.onclick=()=>onUnit?.(plan.plan_unit_id);section.append(html('p','PLAN STRUCTURE AND OBSERVED WORK','eyebrow'),title);
   section.append(html('p','Dashed gold: declared organization · Solid teal: stage work observed in source order. Open a stage to follow its original units.','blueprint-legend'));
   const scroller=html('div',undefined,'plan-graph-scroll'),canvas=html('div',undefined,'plan-graph');canvas.style.width=Math.max(310,plan.stages.length*310)+'px';
   const hasResults=plan.stages.some(s=>s.work_result_history?.length),height=hasResults?255:215;
   canvas.style.height=height+'px';
   const svg=svgEl('svg',{width:Math.max(310,plan.stages.length*310),height,'aria-label':'Declared stages and observed stage changes'});canvas.append(svg);
   const positions=new Map(plan.stages.map((s,i)=>[s.stage_id,20+i*310]));
   const edge=(from,to,y,color,dashed,label,fn)=>{
    if(!positions.has(from)||!positions.has(to))return;
    const forward=positions.get(to)>positions.get(from),x1=positions.get(from)+(forward?250:0),x2=positions.get(to)+(forward?0:250);
    const path=svgEl('path',{d:`M${x1} ${y} L${x2} ${y}`,stroke:color,'stroke-width':2,fill:'none',...(dashed?{'stroke-dasharray':'5 4'}:{})});svg.append(path);
    svg.append(svgEl('path',{d:`M${x2+(forward?-7:7)} ${y-5} L${x2} ${y} L${x2+(forward?-7:7)} ${y+5}`,stroke:color,'stroke-width':2,fill:'none'}));
    const hit=svgEl('rect',{x:Math.min(x1,x2),y:y-9,width:Math.max(1,Math.abs(x2-x1)),height:18,fill:'transparent',role:'button',tabindex:0,'aria-label':label});hit.onclick=fn;hit.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();fn();}};svg.append(hit);
   };
   for(const link of plan.declared_links)edge(link.from,link.to,85,'#b4822d',true,'Declared '+link.kind+': '+link.from+' to '+link.to,()=>onDeclaredLink?.(plan,link));
   for(const [i,t] of plan.stage_transitions.entries())edge(t.from_stage_id,t.to_stage_id,135+(i%3)*18,t.order_status==='source_order'?'#237f80':'#89959a',false,'Observed stage work: '+t.from_stage_id+' to '+t.to_stage_id+(t.prior_stage_result_at_entry?' · Earlier stage: '+resultLabels[t.prior_stage_result_at_entry.result]:''),()=>onTransition?.(plan,t));
   for(const [i,stage]of plan.stages.entries()){
    const card=html('section',undefined,'plan-stage-card'+(focus==='stage:'+stage.id?' is-focused':''));card.style.left=positions.get(stage.stage_id)+'px';card.dataset.stage=stage.id;
    if(hasResults)card.style.height='225px';
    const choose=html('button',undefined,'plan-stage-focus');choose.type='button';choose.setAttribute('aria-label','Follow stage: '+stage.text);choose.onclick=()=>onStage?.(stage);
    choose.append(html('span','STAGE '+(i+1),'blueprint-kind'),html('strong',stage.text),html('span',stage.target,'plan-stage-target'));
    const c=stage.role_counts;choose.append(html('span',`${c.prepares} preparation${c.prepares===1?'':'s'} · ${c.attempts} attempt${c.attempts===1?'':'s'} · ${c.checks} check${c.checks===1?'':'s'}`,'plan-stage-counts'));
    const forms=Object.entries(stage.material_counts);choose.append(html('span',forms.length?forms.map(([k,n])=>`${materialLabels[k]||k}: ${n}`).join(' · '):'No inspected product response','plan-material-summary'));card.append(choose);
    const latest=stage.work_result_history?.at(-1);
    if(latest)choose.append(html('span',(latest.review_notes?.length?'Review flag · ':'')+resultLabels[latest.result]+' · at '+latest.response_event_id,'work-result-summary '+latest.result));
    const evidence=html('button','Inspect stage evidence','plan-stage-evidence');evidence.type='button';evidence.onclick=()=>onStageEvidence?.(plan,stage);card.append(evidence);canvas.append(card);
   }
   scroller.append(canvas);section.append(scroller);
   const details=html('details',undefined,'plan-observed-phases');details.append(html('summary',`Observed work sequence · ${plan.counts.bound_actions} linked dispatches · ${plan.counts.stage_changes} stage change${plan.counts.stage_changes===1?'':'s'}`));
   const phases=html('div',undefined,'plan-phases');
   for(const [i,phase]of plan.phases.entries()){
    if(i)phases.append(html('span','→','phase-arrow'));
    const names=phase.stage_ids.map(id=>plan.stages.find(s=>s.stage_id===id)?.text||id).join(' + ');
    const changed=i===0||JSON.stringify(phase.stage_ids)!==JSON.stringify(plan.phases[i-1].stage_ids);
    const stageLabel=changed&&phase.stage_ids.length?phase.stage_ids.map(id=>'Stage '+(plan.stages.findIndex(s=>s.stage_id===id)+1)).join(' + ')+' · ':'';
    const roleLabels={prepares:'Prepare',attempts:'Attempt',checks:'Check'};
    const b=html('button',`${stageLabel}${phase.roles.map(r=>roleLabels[r]||r).join(' + ')||'Unassigned'}${phase.positions.length>1?' ×'+phase.positions.length:''}`,'plan-phase');b.type='button';b.title=names+'\n'+phase.action_event_ids.join(', ');b.onclick=()=>{if(phase.action_unit_ids[0])onUnit?.(phase.action_unit_ids[0]);};b.disabled=!phase.action_unit_ids.length;phases.append(b);
   }
   details.append(phases,html('p',`${plan.counts.unassigned_actions} unassigned dispatches and ${plan.counts.multiple_stage_actions} multiple-stage dispatches retained. These are observations of correspondence, not completion or deviation judgments.`,'blueprint-legend'));section.append(details);
   section.append(html('p',hasResults?'Work results apply to the named scope at the displayed response. Open a stage-change line to see the earlier result available at that moment. These are readings of recorded evidence, not independent verification.':'Completion is not established by material presence. A later stage can begin before an earlier stage has been verified.','blueprint-legend'));host.append(section);
  }
 }
 function mount(host,doc,run,visible,{selected,onUnit,onRelation,focus,onStage,onStageEvidence,onTransition,onDeclaredLink}={}){
  const graph=project(doc,run,visible),ns='http://www.w3.org/2000/svg';
  const reports=new Map((doc.execution_reports?.observations||[]).map(r=>[r.response_event_id,r]));
  const outcomes=new Map((doc.operation_outcomes?.observations||[]).map(r=>[r.response_event_id,r]));
  const html=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
  const svgEl=(tag,attrs={})=>{const e=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);return e;};
  host.classList.add('blueprint-host');
  mountPlans(host,doc,visible,{focus,onUnit,onStage,onStageEvidence,onTransition,onDeclaredLink});
  const controls=html('div',undefined,'blueprint-controls'),label=html('label','Connections '),select=html('select');select.setAttribute('aria-label','Blueprint connection layer');
  for(const[value,text]of [['key','Plan, feedback and returns'],['all','All saved connections'],['plan','Plan stages'],['declaration','Stated work and responses'],['return','Returns to earlier targets'],['assessment','Feedback assessments'],['scope','Requested work / scope'],['feedback','Action results']]){const o=html('option',text);o.value=value;select.append(o);}label.append(select);controls.append(label);
  const zoom=html('input');zoom.type='range';zoom.min='35';zoom.max='120';zoom.value=sessionStorage.getItem('blueprintZoom')||'80';zoom.setAttribute('aria-label','Blueprint zoom');
  const zlabel=html('label','Zoom ');zlabel.append(zoom);controls.append(zlabel);
  const selectedOnly=html('input');selectedOnly.type='checkbox';const sl=html('label','');sl.append(selectedOnly,document.createTextNode(' Selected unit connections only'));controls.append(sl);
  select.value=focus?.startsWith('declared:')?'declaration':sessionStorage.getItem('blueprintLayer')||'key';selectedOnly.checked=sessionStorage.getItem('blueprintSelectedOnly')==='1';
  const fit=html('button','Fit width');fit.type='button';controls.append(fit);
  const reset=html('button','Find selected unit');reset.type='button';controls.append(reset);host.append(controls);
  const legend=html('p','Grey dashed: source order · Gold: plan · Purple: same target again · Teal: stated-work links · Blue: action/result · Coral: assessment. Arrows preserve the saved relation direction. Return lines show the most specific recorded outcome; choose All saved connections to see supporting links.','blueprint-legend');host.append(legend);
  const viewport=html('div',undefined,'blueprint-viewport');viewport.tabIndex=0;viewport.setAttribute('aria-label','Agent blueprint; scroll to follow the trace');
  const canvas=html('div',undefined,'blueprint-canvas'),svg=svgEl('svg',{viewBox:`0 0 ${graph.width} ${graph.height}`,width:graph.width,height:graph.height,role:'img','aria-label':'Connected activities and plan stages'});
  const defs=svgEl('defs');for(const[k,color]of Object.entries(colors)){const m=svgEl('marker',{id:'bp-arrow-'+k,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});m.append(svgEl('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:color}));defs.append(m);}svg.append(defs);
  const laneNames=['IDEAS · PLANS · CONTRIBUTIONS','DISPATCHED ACTIONS','RECORDED RESPONSES'];
  for(const [i,lane]of graph.lanes.entries()){const t=svgEl('text',{x:40+i*304,y:28,class:'blueprint-lane'});t.textContent=laneNames[lane];svg.append(t);}
  const nodeMap=new Map(graph.nodes.map(n=>[n.id,n])),edgeLayer=svgEl('g');svg.append(edgeLayer);
  const returnRank={same_action_target:1,revisits_after_error_report:2,completed_after_failed_call:3},strongestReturn=new Map();
  for(const e of graph.edges)if(e.family==='return'){const k=e.from+'|'+e.to;strongestReturn.set(k,Math.max(strongestReturn.get(k)||0,returnRank[e.type]||0));}
  const drawEdges=()=>{edgeLayer.replaceChildren();for(const[eidx,e]of graph.edges.entries()){
   if(!declarationInFocus(e,focus,select.value))continue;
   if(e.family==='return'&&select.value!=='all'&&(returnRank[e.type]||0)<strongestReturn.get(e.from+'|'+e.to))continue;
   if(e.family!=='order'&&((select.value==='key'?!['plan','return','feedback','assessment'].includes(e.family):select.value==='declaration'?!['declaration','feedback','execution'].includes(e.family):select.value!=='all'&&e.family!==select.value)||selectedOnly.checked&&e.from!==selected&&e.to!==selected))continue;
   const a=nodeMap.get(e.from),b=nodeMap.get(e.to),color=colors[e.family]||colors.other,incident=e.from===selected||e.to===selected;
   let d,anchor;
   if(a.row===b.row&&a.lane!==b.lane){const forward=b.x>a.x;const x1=forward?a.x+a.width:a.x,x2=forward?b.x:b.x+b.width;d=`M${x1},${a.y+60} L${x2},${b.y+60}`;anchor=[(x1+x2)/2,a.y+60];}
   else if(e.family!=='order'&&Math.abs(a.lane-b.lane)<=1){const right=Math.max(a.x,b.x),same=a.lane===b.lane,gutter=same?a.x+a.width+10+(eidx%4)*5:right-12-(eidx%3)*5,x1=same||a.lane<b.lane?a.x+a.width:a.x,x2=same||b.lane<a.lane?b.x+b.width:b.x;d=`M${x1},${a.y+75} L${gutter},${a.y+75} L${gutter},${b.y+75} L${x2},${b.y+75}`;anchor=[gutter,(a.y+b.y)/2+75];}
   else if(e.family!=='order'){const gutter=graph.width-32+(eidx%3)*6,y1=a.y+a.height+12,y2=b.y+b.height+12;d=`M${a.x+200},${a.y+a.height} L${a.x+200},${y1} L${gutter},${y1} L${gutter},${y2} L${b.x+200},${y2} L${b.x+200},${b.y+b.height}`;anchor=[gutter,(y1+y2)/2];}
   else{const down=b.y>a.y,x1=a.x+a.width/2,y1=down?a.y+a.height:a.y,x2=b.x+b.width/2,y2=down?b.y:b.y+b.height;d=`M${x1},${y1} C${x1},${(y1+y2)/2} ${x2},${(y1+y2)/2} ${x2},${y2}`;}
   const group=svgEl('g',{'data-edge-type':e.type,'data-from':e.from,'data-to':e.to});
   const path=svgEl('path',{d,fill:'none',stroke:color,'stroke-width':incident?2.8:1.5,'stroke-opacity':e.family==='order'?.65:incident?1:.38,'marker-end':'url(#bp-arrow-'+e.family+')',...(e.family==='order'?{'stroke-dasharray':'5 5'}:{})});
   const title=svgEl('title');title.textContent=`U${a.ordinal} → ${e.label} → U${b.ordinal}${e.work_text?' · '+e.work_text:''}${e.plan_step_text?' · '+e.plan_step_text:''}${e.hidden?' · '+e.hidden+' omitted units':''}`;group.append(title,path);
   if(incident&&e.family!=='order'){const t=svgEl('text',{x:a.x+10,y:a.y+a.height+14+(eidx%2)*12,fill:color,'font-size':9,stroke:'#f6f9fb','stroke-width':3,'paint-order':'stroke','pointer-events':'none'});t.textContent=`${e.label} → U${b.ordinal}${e.plan_step_id?' / '+e.plan_step_id:''}`;group.append(t);}
   if(e.family!=='order'){
    const open=()=>onRelation?.(doc.relations[e.index]);
    const hit=svgEl('path',{d,fill:'none',stroke:'transparent','stroke-width':12});hit.onclick=open;
    const control=svgEl('rect',{x:anchor[0]-6,y:anchor[1]-10,width:12,height:20,fill:'transparent',tabindex:0,role:'button','aria-label':title.textContent});control.onclick=open;control.onkeydown=k=>{if(k.key==='Enter'||k.key===' '){k.preventDefault();open();}};group.append(hit,control);
   }
   edgeLayer.append(group);
  }};
  for(const n of graph.nodes){const u=n.unit,r=reports.get(u.source.event_id),g=svgEl('g',{'data-blueprint-unit':u.id,transform:`translate(${n.x} ${n.y})`});
   g.append(svgEl('rect',{width:n.width,height:n.height,rx:10,fill:u.activity==='plan'?'#fff7e6':u.kind==='feedback'?'#eef6fc':u.actor==='user'?'#f5effa':'#fff',stroke:n.id===selected?'#166f72':r?.error==='reported'?'#b85848':'#cbd9df','stroke-width':n.id===selected?3:1}));
   const fo=svgEl('foreignObject',{x:10,y:8,width:n.width-20,height:n.height-16});const b=html('button',undefined,'blueprint-card');b.type='button';b.dataset.unitId=u.id;
   b.append(html('span',`U${n.ordinal} · ${u.actor} · ${u.activity||u.kind}`,'blueprint-kind'));
   if(r&&(r.error==='reported'||r.warning==='reported'||r.error==='unresolved'||!r.complete_readable_response)){
    const badges=[r.error==='reported'?'Executor error reported':null,r.warning==='reported'?'Warning reported':null,r.error==='unresolved'?'Error report unresolved':null,!r.complete_readable_response?'Some response material uninspected':null].filter(Boolean);
    b.append(html('span',badges.join(' · '),'blueprint-report'));b.dataset.executionReport=r.error;
   }
   const focusedStage=doc.plan_execution?.plans.flatMap(p=>p.stages.map(s=>({...s,plan_unit_id:p.plan_unit_id}))).find(s=>focus==='stage:'+s.id);
   const scopedResults=(doc.work_results?.observations||[]).filter(row=>row.response_event_id===u.source.event_id&&
    (focus?.startsWith('declared:')?row.scope_kind==='declared_work'&&row.declared_work_id===focus.slice(9):focusedStage&&row.scope_kind==='plan_stage'&&row.scope_unit_id===focusedStage.plan_unit_id&&row.plan_step_id===focusedStage.stage_id));
   const outcome=outcomes.get(u.source.event_id);
   if(scopedResults.length===1){const row=scopedResults[0];b.append(html('span',(row.review_notes?.length?'Review flag · ':'')+resultLabels[row.result],'work-result-summary '+row.result));b.dataset.workResult=row.result;}
   else if(outcome){b.append(html('span','Operation: '+outcome.outcome.replaceAll('_',' '),'blueprint-outcome'));b.dataset.operationOutcome=outcome.outcome;}
   b.append(html('span',u.kind==='feedback'?u.source.text.slice(0,220)||u.content.summary.text:u.content.summary.text,'blueprint-summary'));
   if(u.plan_structure?.steps?.length)b.append(html('span',u.plan_structure.steps.map((s,i)=>`${i+1}. ${s.text}`).join(' → '),'blueprint-stage'));
   else if(u.kind!=='feedback'&&u.content.target?.text)b.append(html('span',u.content.target.text,'blueprint-target'));
   b.title=u.content.summary.text+'\n'+(u.plan_structure?.steps?.map(s=>s.text).join('\n')||u.content.target?.text||'');b.onclick=()=>onUnit?.(u.id);fo.append(b);g.append(fo);svg.append(g);
  }
  canvas.append(svg);viewport.append(canvas);host.append(viewport);
  const scale=()=>{const z=Number(zoom.value)/100;sessionStorage.setItem('blueprintZoom',zoom.value);svg.style.transform=`scale(${z})`;svg.style.transformOrigin='0 0';canvas.style.width=graph.width*z+'px';canvas.style.height=graph.height*z+'px';};
  const focusSelected=()=>{const n=nodeMap.get(selected);if(n)viewport.scrollTo({top:Math.max(0,n.y*Number(zoom.value)/100-80),left:0,behavior:'smooth'});};
  fit.onclick=()=>{zoom.value=String(Math.max(35,Math.min(120,Math.floor((viewport.clientWidth-20)/graph.width*100))));scale();};
  zoom.oninput=scale;select.onchange=()=>{sessionStorage.setItem('blueprintLayer',select.value);drawEdges();};selectedOnly.onchange=()=>{sessionStorage.setItem('blueprintSelectedOnly',selectedOnly.checked?'1':'0');drawEdges();};reset.onclick=focusSelected;drawEdges();scale();
  const summary=html('p',`${graph.nodes.length} original unit cards · ${graph.edges.filter(e=>e.family!=='order').length} saved links · ${graph.hidden} units outside this focus. Select a card or line to inspect evidence. Plan attempts and repeated targets do not establish completion, deviation or recovery.`,'blueprint-legend');host.append(summary);
  return {graph,viewport};
 }
 const api={project,mount,materialLabels,declarationInFocus};if(typeof module!=='undefined')module.exports=api;else root.BehaviorBlueprint=api;
})(typeof window==='undefined'?globalThis:window);
