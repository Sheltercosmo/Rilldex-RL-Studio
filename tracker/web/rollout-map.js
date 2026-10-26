'use strict';
const $=s=>document.querySelector(s),L=RolloutMapLayout,params=new URLSearchParams(location.search);
let payload,layout,zoom=1,selected=null,edgeLayer,cardElements=new Map(),searchMatches=[],searchIndex=-1,receipt=null,loadToken=0;
let proofNodes=new Set(),proofEdges=new Set(),anchorStatus=new Map();
let strategyReceipt=null,revisitReceipt=null;
let scopeResizers=[];
let workNavigation=null,workProcedures=null,workComparisons=null,workScopeAudit=null,workViewDispose=null,workRequest=null;
let zoomMode='readable',selectedEdge=null;
let connectionOrigin=null,activeEvidenceGuide=null;
let inspectionGroups=[],activeInspection=null;
let connectionMode=['selected','selected_all','response','feedback','plan','changes','all'].includes(params.get('links'))?params.get('links'):'all';
let cardContent=['meaning','target','summary','source'].includes(params.get('card_text'))?params.get('card_text'):'meaning';
let unitReviewLoader=null;
const priorWorkResults=new Map();
function loadUnitReview(){if(window.UnitReview)return Promise.resolve();if(!unitReviewLoader)unitReviewLoader=new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/unit-review.js';script.onload=resolve;script.onerror=()=>{unitReviewLoader=null;script.remove();reject(Error('Unit review editor could not be loaded.'));};document.head.append(script);});return unitReviewLoader;}
const visible=new Set(['execution','feedback','plan','review','return','verification','work','context']);
const short=(v,n)=>String(v||'').replace(/\s+/g,' ').slice(0,n)+(String(v||'').replace(/\s+/g,' ').length>n?'…':'');
const human=v=>String(v||'').replaceAll('_',' ');
function activityLabel(n){const ref=payload?.graph.semantic_context?.reference_annotation;if(!ref||!n.properties.reference_annotation)return human(n.activity);return n.activity.startsWith(ref.label_namespace)?'Native '+n.activity.slice(ref.label_namespace.length):'Reference unresolved';}
function relationLabel(type){const names={parent_message:'Response → action',response_to:'Feedback for action',recorded_with:'Recorded with action',same_work_target:'Same question or outcome',overlapping_work_scope:'Partly shared work',different_work_same_subject:'Same subject, different work',similar_operation_distinct_target:'Different task instance'};const ref=payload?.graph.semantic_context?.reference_annotation;return ref&&type.startsWith(ref.label_namespace)?'Native '+type.slice(ref.label_namespace.length).replace(/^backref:/,''):names[type]||L.relationMeaning({type}).label;}
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function svg(tag,attrs={},text){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;}
async function api(path){const r=await fetch(path);const d=await r.json();if(!r.ok)throw Error(d.error||r.statusText);return d;}
function label(n){return n.kind==='plan_step'?'Stage '+n.properties.id:(n.kind==='event'?'Record ':'Unit ')+n.ordinal;}
function runLabel(g){return(g.coverage.semantic_relations==='unavailable'?'Source · ':'Semantic · ')+ChoiceLabels.rollout(g);}
function connectionSummary(n){return n.lane===2?RolloutStory.preview(n.properties.source?.text||n.properties.text||n.summary).text:n.target||n.summary;}
function cardFoot(n){
 return UnitReading.foot(layout,n);
}
function displayText(n){if(cardContent==='meaning')return UnitReading.cardText(n);if(cardContent==='source')return L.text(n.properties.source?.text||n.properties.text).trim()||'Source excerpt unavailable';if(cardContent==='target'&&n.lane===2)return RolloutStory.preview(n.properties.source?.text||n.summary).text;if(cardContent==='target'&&n.lane===1)return UnitReading.content(n);if(cardContent==='target'&&n.target)return n.target;const plan=L.declaredPlans(payload.graph,n.id)[0]?.snapshot;if(plan)return 'Plan declaration · '+plan.items.length+' items · '+plan.items.filter(i=>i.status==='completed').length+' reported complete';const check=n.kind==='event'&&L.stateEvidence(payload.graph,n.id).checks[0]?.properties;if(check)return 'Recorded check: '+check.criterion_id+' · '+check.result;const text=n.properties.kind==='feedback'?L.text(n.properties.source?.text).trim()||n.summary:n.summary;return text.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'');}
let textMeasure=null;
function wrapText(parent,text,x,y,count=3,limit=29,cls='unit-text'){
 // Measure the actual card font: character counts do not bound JSON or wide glyphs.
 if(!textMeasure){const probe=svg('text',{class:cls,visibility:'hidden'});$('#map-svg').append(probe);textMeasure=document.createElement('canvas').getContext('2d');textMeasure.font=getComputedStyle(probe).font;probe.remove();}
 const width=254,measure=t=>textMeasure.measureText(t).width,words=String(text||'').replace(/\s+/g,' ').trim().split(' '),lines=[''];
 outer:for(const word of words){
  let index=lines.length-1,candidate=lines[index]?(lines[index]+' '+word):word;
  if(measure(candidate)<=width){lines[index]=candidate;continue;}
  if(lines[index]){lines.push('');index++;if(lines.length>count)break;}
  if(measure(word)<=width){lines[index]=word;continue;}
  for(const character of word){if(measure(lines[index]+character)>width){lines.push('');index++;if(lines.length>count)break outer;}lines[index]+=character;}
 }
 const clipped=lines.length>count;lines.slice(0,count).forEach((line,i)=>{if(clipped&&i===count-1){while(line&&measure(line+'…')>width)line=line.slice(0,-1);line+='…';}parent.append(svg('text',{x,y:y+i*18,class:cls},line));});
}

let deliveryCheck=0,deliveryFingerprint=null;
async function refreshSourceStatus(){
 const id=payload?.run?.id;if(!id)return;
 const token=++deliveryCheck,host=$('#source-revision-status');
 try{
  const status=await api('/api/source-status/'+encodeURIComponent(id));
  if(token!==deliveryCheck||payload?.run?.id!==id)return;
  host.replaceChildren();host.hidden=!status.tracked;host.classList.toggle('has-newer',status.tracked&&!status.is_latest);
  if(!status.tracked)return;
  const current=el('span',`Snapshot ${status.revision} · ${human(status.state)}`);host.append(current);
  if(!status.is_latest){
   host.append(el('strong',`New source available · snapshot ${status.latest_revision}`));
   const link=el('a','Open latest source →');link.href='/semantic-map?'+new URLSearchParams({run:status.latest_run_id,observer:'source',level:'units'});host.append(link);
   host.append(el('small','This map stays on its saved evidence. Semantic observations may not yet cover the new source.'));
  }else host.append(el('small',status.state==='in_progress'?'Growing rollout · this map covers the received prefix only. Missing later actions and results remain unknown; this view stays fixed while you inspect it.':'Latest received source. This view stays fixed while you inspect it.'));
 }catch(e){if(token!==deliveryCheck||payload?.run?.id!==id)return;host.hidden=false;host.replaceChildren(el('span','Live revision check unavailable'),el('small','Your saved map is still available. Reconnect to check for newer output.'));}
}
window.addEventListener('tracker-live',event=>{const stamp=event.detail.source_revision;if(stamp!==deliveryFingerprint){deliveryFingerprint=stamp;refreshSourceStatus();}});
window.addEventListener('tracker-disconnected',()=>{const host=$('#source-revision-status');if(payload?.run){deliveryCheck++;host.hidden=false;host.replaceChildren(el('span','Disconnected · viewing saved evidence'),el('small','New source revisions will be checked after reconnection.'));deliveryFingerprint=null;}});

async function load(id,observer){
 const token=++loadToken;deliveryCheck++;$('#source-revision-status').hidden=true;$('#export-graph').disabled=true;
 $('#map-level-controls').hidden=true;$('#map-workbench').hidden=true;
 $('#map-availability').hidden=true;$('#map-foundation-status').replaceChildren();$('#map-foundation-status').hidden=true;
 $('#derive-work-groups').hidden=true;
 window.TrainingSpansView?.clear();window.PlanHierarchyView?.clear();
 workViewDispose?.();workViewDispose=null;workNavigation=null;workProcedures=null;workComparisons=null;workScopeAudit=null;workRequest=null;$('#work-route').replaceChildren();$('#work-level-status').textContent='';
 setMapLevel('units',false);
 $('#work-scope-overview').hidden=true;
 $('#requested-terms-overview').hidden=true;$('#requested-terms-overview').replaceChildren();
 try{const valueId=params.get('value'),nextReceipt=valueId?await api('/api/monitoring/values/'+encodeURIComponent(valueId)+'?run='+encodeURIComponent(id)):null;
  const profileId=params.get('profile'),nextStrategy=!valueId&&profileId?await api('/api/strategies/observations/'+encodeURIComponent(profileId)):null;
  if(nextStrategy&&nextStrategy.run_id!==id)throw Error('This episode belongs to a different rollout.');
  const nextRevisit=!valueId&&!profileId&&params.has('revisit')?await api('/api/work-state/'+encodeURIComponent(params.get('revisit'))):null;
  if(nextRevisit){
   if(nextRevisit.schema!=='repeated-work-comparisons/1'||nextRevisit.run_id!==id)throw Error('This attempt comparison belongs to a different rollout or analysis.');
   if(!nextRevisit.rows.some(r=>r.id===params.get('revisit_case')))throw Error('Attempt pair not found in this saved comparison.');
   if(params.has('graph')&&params.get('graph')!==nextRevisit.graph_id)throw Error('This attempt pair belongs to a different saved graph.');
   params.set('graph',nextRevisit.graph_id);
  }
  const frozen=nextReceipt||nextStrategy;
  const selection=new URLSearchParams();if(observer!=null)selection.set('observer',observer);if(params.has('graph'))selection.set('graph',params.get('graph'));
  const next=frozen?{run:frozen.run,graph:frozen.graph,graphs:frozen.graph?[frozen.graph]:[]}:await api('/api/monitoring/rollout/'+encodeURIComponent(id)+(selection.size?'?'+selection:''));
  if(!next.graph){if(token===loadToken)unavailableMap(next,id);return;}
  if(nextRevisit&&next.graph.source_hash!==nextRevisit.source_hash)throw Error('Saved attempt comparison source does not match this graph.');
  if(next.capabilities?.unit_review||nextReceipt?.review_context)await loadUnitReview();
  if(token!==loadToken)return;receipt=nextReceipt;strategyReceipt=nextStrategy;revisitReceipt=nextRevisit;payload=next;refreshSourceStatus();
  if(!payload.graph)throw Error('This rollout has no saved graph yet.');
  const foundation=await api('/api/map-foundation?graph='+encodeURIComponent(payload.graph.id));if(token!==loadToken)return;
  payload.foundation=foundation;layout=L.project(payload.graph,foundation.excluded_edge_ids,foundation.content_sources.excluded_unit_ids,foundation.source_order);selected=null;selectedEdge=null;connectionOrigin=null;activeEvidenceGuide=null;activeInspection=null;inspectionGroups=InspectionPaths.catalog(payload.graph,layout,foundation.excluded_edge_ids);$('#inspection-context').hidden=true;$('#map-inspector').hidden=true;
  $('#derive-work-groups').hidden=payload.graph.semantic_context?.contribution_scope?.protocol!=='contribution-scope-pairs/2'||!!payload.graph.semantic_context?.work_subjects;
  params.set('run',id);params.set('observer',payload.graph.observer);params.delete('focus');params.delete('graph_unit');params.delete('activity_unit');params.delete('connected');history.replaceState(history.state,'','/semantic-map?'+params);
  if(![...$('#map-run').options].some(o=>o.value===id)){const o=el('option','Saved source · '+(payload.run.metadata.task_id||id));o.value=id;$('#map-run').append(o);}
  $('#map-level-controls').hidden=false;$('#map-workbench').hidden=false;
  renderMapAvailability();$('#map-run').value=id;$('#map-observer').replaceChildren(...ChoiceLabels.choices(payload.graphs.map(g=>({id:g.observer,label:(receipt?'Saved · ':'')+g.observer_label}))).map(ChoiceLabels.option));$('#map-observer').value=payload.graph.observer;
  const m=payload.run.metadata;$('#map-title').textContent=m.task_id?.startsWith('prompt-sha256:')?'Task '+m.task_id.slice(14,26):short((m.task_id||m.environment||'Rollout').replaceAll('_',' '),100);$('#map-title').title=m.task_id||m.environment||'Rollout';$('#map-meta').textContent=id+(m.training_step!=null?' · Training step '+m.training_step:' · Training coordinates not recorded');
  $('#protocol-summary').textContent=payload.graph.observer_label||payload.graph.observer;window.TrainingContext?.viewEvidence(payload.run.metadata||{});window.dispatchEvent(new CustomEvent('jev:recent-rollout',{detail:{title:$('#map-title').textContent,url:location.pathname+location.search}}));
  const units=layout.nodes.filter(n=>n.kind==='unit'),feedback=units.filter(n=>n.properties.kind==='feedback').length,records=layout.nodes.filter(n=>n.kind==='event').length,stages=layout.nodes.filter(n=>n.kind==='plan_step').length;
  $('#open-source').href='/source?'+new URLSearchParams({run:id,return_to:location.pathname+location.search});$('#investigate-rollout').href='/investigate?'+new URLSearchParams({run:id,focus:id,observer:payload.graph.observer});$('#map-count').textContent=(layout.semantic?(units.length-feedback)+' annotated units · '+feedback+' feedback · ':'')+records+' source record'+(records===1?'':'s')+(stages?' · '+stages+' plan stages':'');
  const reference=payload.graph.semantic_context?.reference_annotation,workReview=payload.graph.semantic_context?.work_subjects,relationshipReview=payload.graph.semantic_context?.relationship_reviews,unitReview=payload.graph.semantic_context?.unit_reviews,basis=$('#annotation-basis');basis.hidden=!reference&&!workReview&&!relationshipReview&&!unitReview;basis.textContent='';
  if(unitReview)basis.append(el('p','Unit review · '+unitReview.document.revision.author+' · '+unitReview.document.revision.note+' Named annotation; independent accuracy is not established.'));
  if(reference){basis.textContent='Reference annotations · '+reference.basis+' '+(reference.native_edge_view||'')+' Unannotated source spans: '+(reference.unannotated_spans??'not assessed')+'.';visible.add('context');}
  if(workReview){const authors=[...new Set(workReview.document.bindings.map(r=>r.provenance.kind+' by '+r.provenance.author+' ('+r.provenance.protocol+')'))];basis.append(el('p','Work target annotations · '+(authors.slice(0,4).join('; ')||'No bindings recorded')+(authors.length>4?' · '+(authors.length-4)+' more sources in export.':'')));}
  if(relationshipReview){const authors=[...new Set(relationshipReview.document.reviews.map(r=>r.provenance.author))];basis.append(el('p',`Relationship reviews · ${relationshipReview.document.reviews.length} pairs · ${authors.join('; ')}. Named annotations; independent accuracy is not established.`));}
  if(layout.folded.length)$('#map-count').textContent+=' · '+layout.folded.length+' empty tool wrappers collapsed';
  const notes=payload.graph.semantic_context?.review_notes||[];$('#show-review-notes').hidden=!notes.length;$('#show-review-notes').textContent=notes.length+' review notes';
  $('#map-coverage').textContent=layout.semantic?'Semantic relationship coverage: partial':payload.graph.coverage.observation_kind==='feedback-assessment'?'Source-event assessment links · semantic units not generated':'Source only · semantic observations unavailable';$('#map-error').hidden=true;
  if(payload.graph.semantic_context?.provenance?.protocol?.schema==='feedback-assessment/1')$('#map-coverage').textContent='Rejected development observer: missed success assessments. Retained for audit; unavailable for new monitors.';
  let reviewContext=$('#unit-review-context');if(!reviewContext){reviewContext=el('div');reviewContext.id='unit-review-context';$('#annotation-basis').after(reviewContext);}reviewContext.replaceChildren();
  const foundationHost=$('#map-foundation-status');foundationHost.hidden=!layout.semantic&&!foundation.excluded_edge_ids.length&&!foundation.content_sources.excluded_unit_ids.length;
  if(layout.semantic){const audit=el('details');audit.append(el('summary','Source anchors checked · semantic accuracy not independently validated'),el('p',`${foundation.source_checks.units} units checked against the captured rollout; ${foundation.content_sources.checked_references} content citations checked. ${foundation.relationships.checked} assessment, evidence-use and revision links checked for actor, context and order. These checks do not establish correct activity labels, targets or relationship meaning.`));const link=el('a','Open foundation audit');link.href='/api/map-foundation?graph='+encodeURIComponent(payload.graph.id);audit.append(link);foundationHost.append(audit);}
  if(payload.graph.semantic_context?.unit_reviews){const impact=payload.graph.semantic_context.unit_reviews.impact;reviewContext.append(el('p',`Latest unit review · ${impact.replaced_unit_ids.length} replaced contributions. Dependent relationships need review; prior receipts remain fixed.`,'evidence-note'));}
  if(foundation.excluded_edge_ids.length){const check=el('details');check.append(el('summary',`${foundation.excluded_edge_ids.length} relationships fail source checks and are excluded from this map`),el('p','The original graph and export retain these records. Repair their actor, context or source order before using them as behavioral evidence.'),el('pre',JSON.stringify(foundation.relationships.relationships.filter(r=>r.status==='incompatible'),null,2)));foundationHost.append(check);}
  if(foundation.content_sources.excluded_unit_ids.length){const check=el('details');check.append(el('summary',`${foundation.content_sources.excluded_unit_ids.length} annotations have invalid local evidence; original source is shown instead`),el('pre',JSON.stringify(foundation.content_sources.issues,null,2)));foundationHost.append(check);}
  window.UnitReview?.continuation(reviewContext,{payload,params});
  await window.TrainingSpansView?.load(payload.graph,params,id=>{setMapLevel('units');select(id);requestAnimationFrame(()=>{$('#map-workbench').scrollIntoView({block:'start'});sizeViewport();fit();select(id,true,'instant');});},()=>token===loadToken);if(token!==loadToken)return;$('#export-graph').disabled=false;prepareMeasurement();render();requestAnimationFrame(()=>{sizeViewport();fit();$('#map-viewport').scrollTo(0,0);updatePosition();if(revisitReceipt)explainRevisit();else if(strategyReceipt)explainStrategy();else if(params.get('focus_unit'))select(params.get('focus_unit'),true,'instant');else if(receipt&&params.has('measure_case'))openMeasuredCase(params.get('measure_case'));else if(receipt&&params.has('feedback_case')){const c=receipt.explanation.analysis_cases.find(c=>c.feedback_timing&&c.id===params.get('feedback_case'));if(c)explainAnalysisCase(c);else explainMeasurement();}if(params.get('focus_link')){const edge=layout.edges.find(e=>e.id===params.get('focus_link'));if(edge){connectionOrigin=layout.byId.has(params.get('link_from'))?params.get('link_from'):null;inspectEdge(edge);}}if(params.get('level')==='work')showWorkLevel();else if(params.get('level')==='story')showStoryLevel();else if(params.get('level')==='plans')showPlanLevel();if((params.get('level')||'units')==='units'&&params.get('guide'))openEvidenceGuide(params.get('guide'));if((params.get('level')||'units')==='units'&&params.get('inspect')){const unit=params.get('focus_unit'),link=params.get('focus_link');openInspection(params.get('inspect'),params.get('inspect_case'),!unit&&!link);if(unit)select(unit,true,'instant');else if(link){const edge=layout.edges.find(e=>e.id===link);if(edge)inspectEdge(edge);}}});
 }catch(e){if(token!==loadToken)return;$('#map-error').hidden=false;$('#map-error').textContent=e.message;$('#map-svg').replaceChildren();$('#measurement-context').hidden=true;$('#map-inspector').hidden=true;}}
function unavailableMap(next,id){
 const host=$('#map-availability');host.hidden=false;host.replaceChildren();
 host.append(el('strong','Selected observation unavailable'),el('p','Choose a saved observation for this rollout. Your requested selection has not been replaced.'));
 const choices=el('div',undefined,'map-availability-actions');for(const graph of next.graphs){const q=new URLSearchParams({run:id,observer:graph.observer,graph:graph.id,level:'units'});if(params.has('return_to'))q.set('return_to',params.get('return_to'));const a=el('a',graph.observer_label||graph.observer);a.href='/semantic-map?'+q;choices.append(a);}host.append(choices);
 $('#map-title').textContent=next.run.metadata?.task_id||'Rollout';$('#map-error').hidden=true;
 $('#map-svg').replaceChildren();$('#measurement-context').hidden=true;$('#map-inspector').hidden=true;$('.map-settings').hidden=true;
 $('#open-source').href='/source?'+new URLSearchParams({run:id,return_to:location.pathname+location.search});
 $('#investigate-rollout').href='/investigate?'+new URLSearchParams({run:id,observer:'source'});
}
function renderMapAvailability(){
 $('.map-settings').hidden=false;
 const host=$('#map-availability'),g=payload.graph,source=g.observer==='source',limited=!source&&g.coverage?.semantic_relations==='unavailable',pinned=params.has('graph')||params.has('value')||params.has('profile');
 const alternatives=payload.graphs.filter(x=>x.observer!=='source'&&x.coverage?.semantic_relations!=='unavailable');
 host.hidden=false;host.classList.toggle('map-availability-attention',source||limited);host.replaceChildren();const text=el('div');
 text.append(el('strong',source?'Recorded source view':limited?'Partial observation view':'Saved semantic map'),el('span',source?(alternatives.length?'Semantic observations are also saved for this rollout. Switch below to see their activity and relationship layers.':pinned?'This saved view contains source records only. Browse saved observations to check for other annotations.':'No semantic observations are saved for this rollout. Actions and responses are available; semantic plans and feedback-use links are not.'):`${layout.nodes.length} visible units · ${layout.edges.filter(e=>e.family!=='sequence').length} saved relationships · ${g.observer_label||g.observer}${limited?' · semantic relationship coverage unavailable':''}`));
 const links=el('div',undefined,'map-availability-actions');
 if(source&&alternatives.length===1){const other=alternatives[0],b=el('button',other.observer_label||'Open semantic observations');b.onclick=()=>{clearReceipt(true);load(payload.run.id,other.observer);};links.append(b);}else if(source&&alternatives.length>1){const b=el('button',`Choose semantic observations · ${alternatives.length}`);b.onclick=()=>openMapContext('map-observer');links.append(b);}
 if(pinned){const browse=el('button','Browse saved observations');browse.onclick=()=>{const observer=payload.graph.observer;clearReceipt(true);load(payload.run.id,observer);};links.append(browse);}
 if(source&&!alternatives.length){const pilot=el('a','Set up semantic analysis →');pilot.href='/connections?'+new URLSearchParams({model_run:payload.run.id,return_to:'/semantic-map?'+params})+'#model-section';links.append(pilot);}
 const overview=el('a','Behavior measures →'),q=new URLSearchParams({view:'measures'});if(payload.run.metadata?.experiment)q.set('experiment',payload.run.metadata.experiment);overview.href='/?'+q;links.append(overview);
 const all=el('a','Browse rollouts →');all.href='/runs'+(q.size?'?'+q:'');links.append(all);host.append(text);
 // Browsing and changing observations belong with scope, not above every canvas.
 const contextLinks=$('#map-context-actions');contextLinks.replaceChildren(links);
 if(source||limited){const change=el('button','Change observations');change.onclick=()=>openMapContext('map-observer');host.append(change);}
}
function render(){
 const root=$('#map-svg');root.replaceChildren();root.setAttribute('width',layout.width);root.setAttribute('height',layout.height);cardElements.clear();
 const defs=svg('defs');for(const[k,color]of Object.entries(L.colors)){const m=svg('marker',{id:'arrow-'+k,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});m.append(svg('path',{d:'M0 0 L10 5 L0 10 Z',fill:color}));defs.append(m);}root.append(defs);
 const laneNames=['Ideas & contributions','Actions','Returned feedback'];$('.lane-headings').replaceChildren(...layout.lanes.map(lane=>el('span',laneNames[lane])));$('.lane-headings').style.gridTemplateColumns=`repeat(${Math.max(1,layout.lanes.length)},1fr)`;
 layout.lanes.forEach((lane,col)=>root.append(svg('rect',{x:40+col*370,y:20,width:324,height:layout.height-40,rx:14,class:'lane-band'})));
 edgeLayer=svg('g',{'data-layer':'relationships'});root.append(edgeLayer);
 for(const n of layout.nodes){const g=svg('g',{class:'unit-card',transform:`translate(${n.x} ${n.y})`,'data-node-id':n.id,'data-lane':n.lane,'data-activity':n.activity,role:'button',tabindex:0,'aria-label':label(n)+': '+activityLabel(n)+'. '+RolloutStory.excerpt(n.summary,240,3)});
  const style=L.cardStyle(n);g.dataset.cardKind=style.key;g.dataset.sourceRecord=String(n.kind==='event');g.style.setProperty('--card-accent',style.color);g.style.setProperty('--card-tint',style.tint);
  g.append(svg('rect',{width:n.width,height:n.height,rx:10,class:'card-box'}),svg('rect',{x:10,y:10,width:n.width-20,height:25,rx:4,fill:style.tint}));
  g.append(svg('text',{x:15,y:27,fill:style.color,'font-size':15,'font-weight':700,'aria-hidden':'true'},style.symbol));
  const activityTitle=svg('text',{x:34,y:27,class:'unit-label'},(n.kind==='plan_step'?'STAGE '+n.properties.id:'#'+n.ordinal)+' · '+short(activityLabel(n),22).toUpperCase());activityTitle.append(svg('title',{},style.label+' · '+n.activity));g.append(activityTitle);
  const cardText=svg('g',{class:'card-content'});wrapText(cardText,displayText(n),15,51,3,29);g.append(cardText);
  const returning=layout.edges.some(e=>e.type==='revisits_after_error_report'&&e.source===n.id),earlier=layout.edges.some(e=>e.type==='revisits_after_error_report'&&e.target===n.id);
  const state=L.stateEvidence(payload.graph,n.id),check=state.checks[0]?.properties,stateNote=check?'Recorded check · '+check.result:state.snapshots.length?'Input / object state attached':'';
  const foot=svg('text',{x:15,y:103,class:'unit-target'},short(cardFoot(n),48));foot.append(svg('title',{},cardFoot(n)));g.append(foot);
  const title=svg('title',{},RolloutStory.excerpt(n.summary+(n.target?'\nTarget: '+n.target:'')));g.append(title);g.onclick=()=>select(n.id);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select(n.id);}};root.append(g);cardElements.set(n.id,g);}
 const legend=$('#edge-legend');legend.replaceChildren();for(const [k,name]of Object.entries({sequence:'Sequence',execution:'Action pairing',feedback:'Feedback',plan:'Plan & work',review:'Review & revision',return:'Returns',verification:'Rechecks',work:'Related work',context:'Context'})){const ref=payload.graph.semantic_context?.reference_annotation;if(k==='sequence'||!layout.edges.some(e=>e.family===k))continue;const b=el('button'),i=el('i');b.dataset.family=k;b.title='Show or hide '+name.toLowerCase()+' connections';b.style.setProperty('--edge',L.colors[k]);b.append(i,document.createTextNode(ref&&k==='context'?'Native references':name));b.setAttribute('aria-pressed',String(visible.has(k)));b.onclick=()=>{if(activeInspection?.item){const hidden=activeInspection.hidden;hidden.has(k)?hidden.delete(k):hidden.add(k);}else{visible.has(k)?visible.delete(k):visible.add(k);}drawEdges();};legend.append(b);}
 const moments=layout.nodes.filter(n=>n.activity==='plan'||n.kind==='plan_step'||layout.edges.some(e=>['revisits_after_error_report','revises','changes_attempt_procedure','changes_attempt_prerequisite','alternative_procedure','reconfigured_procedure','uses_correction_from'].includes(e.type)&&e.source===n.id));$('.moment-bar').hidden=!moments.length;$('#jump-moment').replaceChildren(el('option','Jump to a recorded moment…'));$('#jump-moment').firstChild.value='';for(const n of moments){const o=el('option',label(n)+' · '+(n.activity==='plan'||n.kind==='plan_step'?'Plan: ':'Return / revision: ')+short(n.target||n.summary,65));o.value=n.id;$('#jump-moment').append(o);}
 $('#map-settings-name').textContent=$('#map-observer').selectedOptions[0]?.textContent||'';drawEdges();renderMini();paintProof();renderScopes();renderEvidenceGuide();$('#map-jump').max=Math.max(1,...layout.nodes.map(n=>n.ordinal||0));$('#map-search').value='';searchMatches=[];$('#selection-count').textContent='Select a card or a connection';
}
function renderEvidenceGuide(){
 $('#evidence-guide-shell').open=innerWidth>650;const host=$('#evidence-guide');host.replaceChildren(el('span','Inspect'));
 for(const group of inspectionGroups){const b=el('button');b.append(el('span',group.label),el('strong',group.cases.length||'—'));b.setAttribute('aria-pressed',String(activeInspection?.group.id===group.id));b.title=group.title;b.onclick=()=>openInspection(group.id);host.append(b);}
 for(const group of UnitReading.inventory(layout,payload.graph.coverage).filter(g=>g.id!=='retries')){
  const button=el('button');button.append(el('span',group.id==='feedback'?'Feedback use':'Plan links'),el('strong',group.value));button.title=group.question+' '+group.note;button.onclick=()=>openEvidenceGuide(group.id);host.append(button);
 }
}
function openEvidenceGuide(id){
 clearInspection();
 const group=UnitReading.inventory(layout,payload.graph.coverage).find(g=>g.id===id);if(!group)return;activeEvidenceGuide=id;params.set('guide',id);params.set('graph',payload.graph.id);params.delete('focus_unit');params.delete('focus_link');params.delete('link_from');history.replaceState(history.state,'','/semantic-map?'+params);
 selected=null;selectedEdge=null;connectionOrigin=null;drawEdges();
 $('#map-inspector').hidden=false;$('.inspector-foot').hidden=true;$('#detail-title').textContent='Rollout evidence';
 const body=$('#detail-body');body.replaceChildren(el('h2',group.question,'connection-question'),el('p',group.note,'guide-definition'));
 const linked=group.rows.filter(r=>r.links.length),missing=group.rows.filter(r=>!r.links.length),controls=el('div',undefined,'guide-filters'),list=el('div',undefined,'guide-cases');
 const filters=[['linked','With links · '+linked.length,linked],['missing','Without links · '+missing.length,missing]];
 const show=key=>{
  for(const b of controls.children)b.setAttribute('aria-pressed',String(b.dataset.filter===key));
  const rows=filters.find(f=>f[0]===key)[2];list.replaceChildren();
  if(!rows.length)list.append(el('p',key==='linked'?'No matching relationships in this saved observation.':'Every eligible card has a matching saved link.','guide-empty'));
  let shown=0;
  const more=el('button','Show next 20 cases','guide-more');
  const append=()=>{more.remove();for(const row of rows.slice(shown,shown+20)){
   const section=el('section',undefined,'guide-case'),open=el('button',UnitReading.ref(row.node)+' · '+activityLabel(row.node),'guide-unit');open.onclick=()=>select(row.node.id,true,'instant');section.append(open,el('p',short(UnitReading.cardText(row.node),240)));
   if(!row.links.length)section.append(el('small',group.missing));
   for(const edge of row.links){const relation=el('button',UnitReading.sentence(layout,edge),'guide-relation');relation.onclick=()=>{connectionOrigin=row.node.id;inspectEdge(edge);};section.append(relation);}
   list.append(section);
  }shown+=20;if(shown<rows.length){more.textContent='Show next '+Math.min(20,rows.length-shown)+' · '+(rows.length-shown)+' remaining';list.append(more);}};
  more.onclick=append;append();body.scrollTop=0;
 };
 for(const [key,label]of filters){if(id==='retries'&&key==='missing')continue;const b=el('button',label);b.dataset.filter=key;b.onclick=()=>show(key);controls.append(b);}
 body.append(controls,list);show(linked.length||id==='retries'?'linked':'missing');sizeViewport();fit();
}
function clearInspection(){
 activeInspection=null;params.delete('inspect');params.delete('inspect_case');$('#inspection-context').hidden=true;
 if(layout){renderEvidenceGuide();drawEdges();}
}
function appendInspectionReturn(body){
 if(!activeInspection)return;const b=el('button','← '+activeInspection.group.title,'inspection-back');
 b.onclick=()=>openInspection(activeInspection.group.id,activeInspection.item?.id,false);body.append(b);
}
function openInspection(id,caseId=null,scroll=true){
 const group=inspectionGroups.find(g=>g.id===id);if(!group)return;
 const item=caseId?group.cases.find(c=>c.id===caseId):group.cases[0];activeInspection={group,item,hidden:item&&activeInspection?.item?.id===item.id?activeInspection.hidden:new Set()};
 params.delete('guide');params.delete('focus_unit');params.delete('focus_link');params.delete('link_from');
 params.set('inspect',id);if(caseId||item)params.set('inspect_case',caseId||item.id);else params.delete('inspect_case');params.set('graph',payload.graph.id);
 setMapLevel('units',false);params.set('level','units');history.replaceState(history.state,'','/semantic-map?'+params);
 selected=null;selectedEdge=null;connectionOrigin=null;activeEvidenceGuide=null;
 const context=$('#inspection-context');context.hidden=false;context.replaceChildren(el('span',group.title+' · '+(item?item.node_ids.length+' cards in path':group.cases.length+' available cases')));
 const actions=el('div',undefined,'inspection-actions'),back=el('button','Show path details'),exit=el('button','Exit inspection');
 back.onclick=()=>openInspection(id,item?.id,false);exit.onclick=()=>{$('#close-detail').click();};actions.append(back,exit);context.append(actions);
 $('#map-inspector').hidden=false;$('.inspector-foot').hidden=true;$('#detail-title').textContent=group.title;
 InspectionView.render($('#detail-body'),layout,group,item,{open:next=>openInspection(id,next),unit:unit=>select(unit,true,'instant'),edge:edge=>inspectEdge(edge),checks:async()=>{
  const response=await fetch('/api/map-inspection/checks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:payload.run.id,graph_id:payload.graph.id})}),result=await response.json();
  if(!response.ok)throw Error(result.error||'Check analysis failed.');
  if(result.failed_checks){const next=new URLSearchParams({run:result.run_id,graph:result.graph_id,observer:result.observer,level:'units',inspect:'failed-checks',return_to:location.pathname+location.search});location.href='/semantic-map?'+next;}
  return result;
 }});
 $('#detail-body').scrollTop=0;renderEvidenceGuide();drawEdges();sizeViewport();fit();
 const anchor=layout.byId.get(item?.anchor_id);if(scroll&&anchor)$('#map-viewport').scrollTo({top:Math.max(0,(anchor.y-35)*zoom),left:0,behavior:'instant'});
 $('#selection-count').textContent=item?'Inspection path · all '+layout.nodes.length+' cards retained':'Select an available inspection case';updatePosition();
}
function setMapLevel(level,save=true){
 $('#measurement-context').hidden=(!receipt&&!strategyReceipt&&!revisitReceipt)||(level==='plans'&&params.has('plan_case'));
 const work=level==='work',story=level==='story',plans=level==='plans';$('#plan-hierarchy').hidden=!plans;$('#show-plan-level').setAttribute('aria-pressed',String(plans));$('#unit-level-map').hidden=work||story||plans;$('#work-route').hidden=!work;$('#rollout-story').hidden=!story;$('#show-work-level').setAttribute('aria-pressed',String(work));$('#show-unit-level').setAttribute('aria-pressed',String(!work&&!story&&!plans));$('#show-story-level').setAttribute('aria-pressed',String(story));$('#work-level-status').hidden=!work;
 $('#focus-canvas').hidden=plans;
 // Expansion is an explicit viewing preference, never a property of a map level.
 setCanvasFocus(!plans&&params.get('canvas')==='expanded',false);
 if(save){params.set('level',level);history.replaceState(history.state,'','/semantic-map?'+params);}
 if(!work&&!story&&!plans&&layout)requestAnimationFrame(()=>{sizeViewport();fit();});
}
function showPlanLevel(){
 if(!payload?.graph)return;setMapLevel('plans');$('#map-inspector').hidden=true;
 const cases=(receipt?.explanation?.analysis_cases||[]).filter(c=>c.plan_declaration||c.declared_plan_change),caseId=params.get('plan_case'),c=cases.find(c=>c.id===caseId);
 let context;try{if(caseId&&!c)throw Error('This plan case is unavailable in the saved measurement.');context=c?PlanCaseContext.resolve(payload.graph,c):null;}catch(e){$('#plan-hierarchy').replaceChildren(el('p',e.message,'evidence-note'));return;}
 const through=params.get('plan_through')||context?.cutoff_event_id;
 if(context&&!params.has('plan_through')){params.set('plan_through',through);history.replaceState(history.state,'','/semantic-map?'+params);}
 PlanHierarchyView.render($('#plan-hierarchy'),payload.graph,openPlanSource,through,id=>{params.set('plan_through',id);history.replaceState(history.state,'','/semantic-map?'+params);},{context,cases,onWorkFocus:id=>{params.set('work_focus',id);history.replaceState(history.state,'','/semantic-map?'+params);},onOutlineFocus:id=>{params.set('outline_focus',id);history.replaceState(history.state,'','/semantic-map?'+params);},onOutlineView:mode=>{params.set('outline_view',mode);history.replaceState(history.state,'','/semantic-map?'+params);},onPlanStep:id=>{params.set('plan_step',id);history.replaceState(history.state,'','/semantic-map?'+params);},
  measurementLabel:receipt?receipt.monitor.name+' · rollout value '+measuredValue():null,
  measurementUrl:receipt?'/api/monitoring/values/'+encodeURIComponent(receipt.measurement.id)+'?download=1':null,
  monitorUrl:PlanCaseContext.monitorUrl(receipt),
  onCase:id=>{params.set('plan_case',id);params.delete('plan_through');showPlanLevel();},
  onBack:()=>{setMapLevel('units');explainAnalysisCase(c);}});
}
function openPlanSource(id){
 setMapLevel('units');if(layout.byId.has(id)){select(id,true);return;}
 const record=payload.graph.nodes.find(n=>n.id===id&&n.kind==='event');
 selected=null;selectedEdge=null;drawEdges();
 const body=evidenceHeading(record?'Source record '+(record.event_index+1):'Source reference unavailable');
 const back=el('button','Back to Plans & attempts','relation-button');back.onclick=showPlanLevel;body.append(back);
 if(!record){body.append(el('p','This reference is not present in the selected source graph.'));return;}
 body.append(el('h3','Recorded contribution'),el('pre',record.properties.text),el('h3','Units from this record'),sourceButton(id));
 $('#selection-count').textContent='Source record '+(record.event_index+1)+' · open a derived unit below';
}
let feedbackTrailCache=new Map(),requestEvidenceCache=new Map();
async function showStoryLevel(){
 if(!payload?.graph)return;setMapLevel('story');$('#map-inspector').hidden=true;
 const graph=payload.graph,token=loadToken;let trail=feedbackTrailCache.get(graph.id),trailError=null,requestEvidence=requestEvidenceCache.get(graph.id),requestEvidenceError=null;
 if(!trail||!requestEvidence){$('#rollout-story').replaceChildren(el('p','Connecting requests, actions and returned evidence…'));
  await Promise.all([!trail?(async()=>{try{trail=await api('/api/feedback-followthrough?graph='+encodeURIComponent(graph.id));feedbackTrailCache.set(graph.id,trail);if(feedbackTrailCache.size>4)feedbackTrailCache.delete(feedbackTrailCache.keys().next().value);}catch(e){trailError='Feedback comparison unavailable. Saved story and source evidence remain available.';}})():null,
   !requestEvidence?(async()=>{try{requestEvidence=await api('/api/request-evidence?graph='+encodeURIComponent(graph.id));requestEvidenceCache.set(graph.id,requestEvidence);if(requestEvidenceCache.size>4)requestEvidenceCache.delete(requestEvidenceCache.keys().next().value);}catch(e){requestEvidenceError='Requested-check evidence unavailable. Do not infer coverage from missing links.';}})():null]);}
 if(token!==loadToken||payload.graph.id!==graph.id||params.get('level')!=='story')return;
 RolloutStory.render($('#rollout-story'),RolloutStory.project(graph,payload.run,layout),graph,id=>{setMapLevel('units');select(id,true);},{feedbackTrail:trail,feedbackTrailError:trailError,requestEvidence,requestEvidenceError,query:params.get('story_query'),filter:params.get('story_filter'),moment:params.get('story_moment'),onChange:state=>{for(const key of ['query','filter','moment']){if(state[key]&&state[key]!=='all')params.set('story_'+key,state[key]);else params.delete('story_'+key);}params.set('graph',payload.graph.id);history.replaceState(history.state,'','/semantic-map?'+params);}});
}
async function showWorkLevel(){
 if(!payload?.graph)return;setMapLevel('work');$('#map-inspector').hidden=true;const token=loadToken,graph=payload.graph;
 if(workNavigation){renderWorkRoute();return;}
 $('#work-route').replaceChildren(el('p','Loading source-bound work relationships…','wn-loading'));$('#work-level-status').textContent='No model calls';
 try{
  const recurrenceOrder=graph.semantic_context?.work_subjects?(params.get('recurrence_order')||(!params.has('value')&&!params.has('work_episode')&&!params.has('work_visit')&&graph.semantic_context.work_subjects.document.schema==='work-subject-bindings/4'?'bracketed-parallel/1':null)):null;
  if(recurrenceOrder){params.set('recurrence_order',recurrenceOrder);history.replaceState(history.state,'','/semantic-map?'+params);}
  if(!workRequest)workRequest=Promise.all([
   fetch('/api/investigation-plans',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({schema:'investigation-plan/1',nodes:(graph.semantic_context?.work_subjects?[['navigation','work_navigation']]:[['navigation','work_navigation'],['procedures','adaptation_patterns'],['comparisons','repeated_work']]).map(([name,op])=>({name,op,inputs:[],params:{run_id:graph.run_id,source_hash:graph.source_hash,graph_id:graph.id,...(op==='work_navigation'&&recurrenceOrder?{recurrence_order:recurrenceOrder}:{}),...(op==='work_navigation'&&graph.semantic_context?.work_subjects?.document?.schema==='work-subject-bindings/4'?{target_relations:'contribution-scope-pairs/2'}:{})}}))})}).then(async r=>{const d=await r.json();if(!r.ok)throw Error(d.error||'Work path unavailable');return d.outputs;}),
   api('/api/work-scope-audit?graph='+encodeURIComponent(graph.id)).catch(()=>({state:'check_unavailable'}))
  ]);
  const [outputs,audit]=await workRequest;if(token!==loadToken)return;const result=outputs.navigation;workNavigation=result;workProcedures=outputs.procedures;workComparisons=outputs.comparisons;workScopeAudit=audit;$('#work-level-status').textContent=result.axis==='contributions'?`${result.counts.bound||0}/${result.counts.contributions} contributions assigned · saved work groups`:`${result.counts.represented_actions}/${result.counts.recorded_actions} actions represented · saved relationships`;
  renderWorkRoute();
 }catch(error){if(token!==loadToken)return;workRequest=null;$('#work-route').replaceChildren(el('p',error.message,'wn-empty'));$('#work-level-status').textContent='Unit map remains available';}
}
function renderWorkRoute(){
 const eid=params.get('work_episode'),uid=params.get('focus_unit'),vid=params.get('work_visit');
 const link=eid?workNavigation.links.find(l=>l.type==='same_work_return'&&l.episode_id===eid):null;
 const visit=vid?workNavigation.visits.find(v=>v.id===vid):link?workNavigation.visits.find(v=>v.id===link.source):uid?workNavigation.visits.find(v=>v.unit_ids.includes(uid)||v.event_ids.some(e=>'event:'+e===uid)):null;
 workViewDispose?.();workViewDispose=WorkNavigationView.render($('#work-route'),workNavigation,inspectWorkVisit,inspectWorkLink,visit?.id,inspectWorkContext,workScopeAudit,inspectScopeConflict,inspectWorkGrouping,{graph:payload.graph,onUnit:id=>{setMapLevel('units');select(id,true);},reviewFilter:params.get('work_filter'),onReviewFilter:value=>{params.set('work_filter',value);params.set('graph',payload.graph.id);history.replaceState(history.state,'','/semantic-map?'+params);},procedures:workProcedures,inputComparisons:workComparisons,lens:params.get('work_lens'),onLens:value=>{params.set('work_lens',value);params.set('graph',payload.graph.id);history.replaceState(history.state,'','/semantic-map?'+params);},focus:params.get('work_focus'),view:params.get('work_view'),allWork:params.has('work_rows')?params.get('work_rows')==='all':null,onAllWork:value=>{params.set('work_rows',value?'all':'repeated');params.set('graph',payload.graph.id);history.replaceState(history.state,'','/semantic-map?'+params);},onView:value=>{params.set('work_view',value);params.set('graph',payload.graph.id);history.replaceState(history.state,'','/semantic-map?'+params);},onFocus:id=>{
  $('#map-inspector').hidden=true;for(const key of ['work_episode','work_visit','focus_unit'])params.delete(key);if(id)params.set('work_focus',id);else params.delete('work_focus');params.set('graph',payload.graph.id);history.replaceState(history.state,'','/semantic-map?'+params);
 }});
  if(link)inspectWorkLink(link,false);else if(visit&&(vid||$('#work-route').dataset.workView!=='review'))inspectWorkVisit(visit,false);
 else if(eid)$('#work-level-status').textContent='The requested episode is unavailable in this graph. The complete work route is shown.';
}
function workUnitButton(id,text){const b=el('button',text||id,'relation-button');b.dataset.unit=id;b.onclick=()=>{setMapLevel('units');select(id,true);};return b;}
function workDetail(title){$('#map-inspector').hidden=false;$('.inspector-foot').hidden=true;$('#detail-title').textContent=title;$('#previous-unit').disabled=true;$('#next-unit').disabled=true;const body=$('#detail-body');body.replaceChildren();body.scrollTop=0;revealInspector();return body;}
function appendScopeConflicts(body,groupIds){
 const cases=(workScopeAudit?.conflicts||[]).filter(c=>c.bindings.some(b=>groupIds.includes(b.binding?.subject_id)));
 if(!cases.length)return;
 const warning=el('section',null,'wn-scope-warning');warning.append(el('h3','Work grouping is disputed'),el('p','Saved pair judgments conflict with this group. Recurrence from these bindings is not established.'));
 for(const [i,c]of cases.entries()){const b=el('button','Review scope conflict '+(i+1),'relation-button');b.onclick=()=>inspectScopeConflict(c);warning.append(b);}body.append(warning);
}
function inspectScopeConflict(record){
 const body=workDetail('Conflicting work scope');proofNodes=new Set([record.source_unit_id,record.target_unit_id]);proofEdges=new Set([record.edge_id]);paintProof();drawEdges();
 body.append(el('h3','Two saved claims disagree'),el('p',record.membership_same?'The work map assigns both contributions to the same immediate work.':'The work map assigns the contributions to separate immediate work.'),el('p','The pair judgment records: '+relationLabel(record.relation)+'.','evidence-note'),el('p','Review the original contributions and their scope. This check does not decide which claim is correct.'));
 for(const [i,b]of record.bindings.entries()){
  body.append(el('h3',i?'Later contribution':'Earlier contribution'),el('pre',b.source.text),el('small',b.source.source_pointer||b.source.event_id),el('h4','Assigned work target'),el('p',b.subject?.label||'Unresolved'));
  body.append(workUnitButton(b.unit_id,'Inspect contribution and review its work target'));
 }
 body.append(el('p','The displayed pair evidence ends at '+record.cutoff.event_id+':'+record.cutoff.end+'. This checks source order, not whether the original observer used only that prefix.','evidence-note'),el('p','Reviews save a new graph version. Existing graphs and measurements retain their original evidence.','evidence-note'));
 const details=el('details');details.append(el('summary','Saved claims and source evidence'),el('pre',JSON.stringify(record,null,2)));const download=el('a','Download work grouping check');download.href='/api/work-scope-audit?graph='+encodeURIComponent(payload.graph.id)+'&download=1';body.append(details,download);
}
function inspectWorkGrouping(record){
 const body=workDetail('Work grouping evidence'),names={same_work_target:'Same question or outcome',partial_work_overlap:'Partly shared work',different_work_same_subject:'Different work on the same subject',different_instance:'Different task instance',unrelated:'No specific shared work',unresolved:'Unresolved'};
 body.append(el('h3','Contribution'),el('pre',record.source.text),el('small',record.source.source_pointer||record.source.event_id),workUnitButton(record.unit_id,'Inspect contribution and review its work target'));
 if(record.missing_prior_unit_ids.length){body.append(el('h3','Missing comparisons'),el('p','These earlier contributions have not been compared under the same target definition. Missing comparisons are not different-work judgments.'));for(const id of record.missing_prior_unit_ids)body.append(workUnitButton(id,'Inspect earlier contribution · '+short(layout.byId.get(id)?.target||layout.byId.get(id)?.summary||id,90)));}
 if(record.observed_pairs.length){body.append(el('h3','Saved comparisons'));for(const row of record.observed_pairs)body.append(workUnitButton(row.prior_unit_id,(names[row.choice]||row.choice)+' · '+short(layout.byId.get(row.prior_unit_id)?.target||row.prior_unit_id,75)));}
 body.append(el('p',workScopeAudit.grouping.limits,'evidence-note'));const details=el('details');details.append(el('summary','Derivation and exact pair evidence'),el('pre',JSON.stringify(record,null,2)));body.append(details);
 const download=el('a','Export missing comparison requests');download.href='/api/work-grouping?graph='+encodeURIComponent(payload.graph.id)+'&download=1';body.append(download,el('p','Exporting prepares only missing comparisons and sends no model requests. Existing unresolved decisions need source review or a changed question.','evidence-note'));
}
function appendWorkConnections(body,links){
 const caption=v=>short(v?.target||v?.label||'Source',55)+(v?.positions?' ['+(v.positions.length===1?v.positions[0]:v.positions[0]+'–'+v.positions.at(-1))+']':'');
 for(const link of links){const isRelation=link.type==='work_relation',origin=workNavigation.visits.find(v=>v.id===link.source),target=workNavigation.visits.find(v=>v.id===link.target)||workNavigation.context_nodes?.find(v=>v.id===link.target),label=isRelation?link.label:link.type==='same_work_return'?'Same-work recurrence':'Correction attempt',b=el('button',label+(link.within_visit?'':' · '+caption(origin)+' → '+caption(target)),'relation-button');if(link.within_visit)b.append(el('small','Within this visit · not a work transition'));b.onclick=()=>inspectWorkLink(link);body.append(b);}
}
function inspectWorkContext(context){
 const body=workDetail(context.kind==='stated_work'?'Stated work':context.kind==='request'?'Expressed request':'Recorded context');if(context.kind==='stated_work')body.append(el('p',context.label),el('p',context.declaration_label+' · attributed source statement','evidence-note'));body.append(el('p','Referenced spans from one source record are grouped here. Exact relation endpoints remain unchanged.','evidence-note'),el('h3','Original source spans'));for(const s of context.source_spans||[context.source])body.append(el('pre',s.text),el('small',s.source_pointer||s.event_id));
 for(const id of context.source_node_ids)if(layout.byId.has(id))body.append(workUnitButton(id,'Open original contribution'));
 body.append(el('h3','Saved work references'));appendWorkConnections(body,WorkNavigationView.connections(workNavigation,context.id));
 body.append(el('p','This is a source context origin. References to it do not establish authorization, fulfillment or deviation.','evidence-note'));
}
function inspectWorkRelation(link){
 const body=workDetail(link.label);proofNodes=new Set(link.node_ids);proofEdges=new Set(link.edge_ids);paintProof();drawEdges();
 const returnLink=workNavigation.links.find(l=>l.type==='same_work_return'&&l.episode_id===params.get('work_episode'));
 if(returnLink){const back=el('button','← Back to return context','relation-button');back.onclick=()=>inspectWorkLink(returnLink);body.append(back);}
 if(link.bundle){body.append(el('p',link.bundle.length+' recorded relationships share these visual endpoints. Each retains its own contributions and evidence.','evidence-note'));for(const row of link.bundle){const b=el('button',row.label+' · '+row.source_unit_id+' → '+row.target_node_id,'relation-button');b.onclick=()=>inspectWorkRelation(row);body.append(b);}return;}
 body.append(el('p',relationLabel(link.relation_type),'evidence-note'));if(link.within_visit)body.append(el('p','Both contributions belong to this visit. This relationship is not counted as a work transition.','evidence-note'));
 if(link.explanation)body.append(el('p',link.explanation));if(link.step)body.append(el('h3','Selected plan step'),el('p',link.step.text),el('p','The saved role is '+human(link.relation_type)+'. No completion is inferred.','evidence-note'));
 if(link.source_form)body.append(el('small',link.source_form==='recorded_dispatch'?'Recorded action dispatch':'Agent text contribution'));
 if(link.stated_work)body.append(el('h3','Stated work'),el('p',link.stated_work.text),el('p',link.stated_work.declaration_label+' at this action’s cutoff','evidence-note'));
 if(link.interpretation_note){const meaning=el('details');meaning.append(el('summary','Interpretation and limits'),el('p',link.interpretation_note,'evidence-note'));body.append(meaning);}
 body.append(el('h3','Exact source witnesses'));
 for(const id of link.node_ids){const n=payload.graph.nodes.find(n=>n.id===id);if(!n)continue;const p=n.properties,s=p.source;if(layout.byId.has(id))body.append(workUnitButton(id,(id===link.source_unit_id?'Referring contribution':id===link.target_node_id?'Referenced contribution':'Originating operation')+' · '+short(s?.text||id,100)));else body.append(el('h4','Referenced source'));if(s)body.append(el('pre',s.text),el('small',s.source_pointer||s.event_id));}
 const details=el('details');details.append(el('summary','Original relationship records'),el('pre',JSON.stringify(payload.graph.edges.filter(e=>link.edge_ids.includes(e.id)),null,2)),el('p',workNavigation.context?.limit||'Saved observations retain their original meaning.','evidence-note'));body.append(details);
}
function inspectWorkVisit(visit,save=true){
 workViewDispose?.focusVisit?.(visit.id);if(save){params.set('work_visit',visit.id);params.delete('work_episode');params.delete('focus_unit');history.replaceState(history.state,'','/semantic-map?'+params);}
 const generic=workNavigation.axis==='contributions',body=workDetail('Work visit');body.append(el('h3','Immediate work'),el('p',visit.target),el('small',(generic?'Contribution':'Action')+' positions '+visit.positions.join(', ')+' · '+visit.trajectory_id));
 appendScopeConflicts(body,[visit.group_id]);
 if(generic&&visit.scope_memberships?.length)body.append(el('p',visit.scope_memberships.length+' saved scope references apply to named contributions in this visit. Open the relationships below for their exact scope.','evidence-note'));
 if(!generic)for(const id of visit.scope_ids){const s=workNavigation.scopes.find(s=>s.id===id);body.append(el('h3',s.properties.scope_kind==='organized_plan'?'Expressed plan':'Expressed request'),el('p',s.properties.text));}
 for(const stage of visit.plan_stages){body.append(el('h3',human(stage.role)),el('p',stage.text));if(generic)body.append(workUnitButton(stage.unit_id,'Inspect the contribution linked to this step'));}
 const related=WorkNavigationView.connections(workNavigation,visit.id).filter(l=>l.type!=='recorded_next'),internal=generic?related.filter(l=>l.type==='same_work_return'&&l.source===l.target):[],primary=related.filter(l=>!internal.includes(l));
 if(primary.length){body.append(el('h3','Connected work'));appendWorkConnections(body,[...primary.filter(l=>l.type==='work_relation'),...primary.filter(l=>l.type!=='work_relation')]);}
 if(internal.length){const details=el('details');details.append(el('summary',internal.length+' consecutive same-work bindings'));appendWorkConnections(details,internal);body.append(details);}
 body.append(el('h3',generic?'Source contributions':'Recorded attempts'));
 for(const p of visit.occurrences){
  const id=p.unit_id||'event:'+p.event_id,n=layout.byId.get(id),statuses={none_of_these:'No match among inspected earlier targets',no_prior_selected_action:'No earlier selected action',linked:'Linked to earlier work',not_recorded:'Identity not inspected',bound:'Explicit work binding',not_applicable:'No immediate work target applies',source_gap:'Source lacks a usable unit'},categories={first_or_unresolved:'No established recurrence',continued:'Consecutive recurrence',returned:'Return after intervening work',interrupted:'Recurrence across an observation gap',resumed:'Resumed after contributions without an applicable target'};
  if(n)body.append(workUnitButton(id,label(n)+' · '+short(generic?(n.summary||p.source?.text||p.target||'Inspect source'):(p.target||'Inspect unobserved source'),130)));
  else if(p.source)body.append(el('h3','Unannotated source'),el('pre',p.source.text),el('small',p.source.source_pointer||p.event_id));
  else body.append(el('p','Source event '+p.event_id+' is retained in the graph export.'));
  body.append(el('small',(statuses[p.identity_status]||human(p.identity_status))+' · '+(categories[p.category]||human(p.category))));
 }
 body.append(el('p',generic?'Bindings record the reviewer’s or producer’s work identity. Missing bindings remain unresolved; recurrence alone does not establish exploration or progress.':'These attempts share a recorded immediate-work identity. This is not a finding of unchanged strategy, failure, or successful completion.','evidence-note'));
}
function inspectWorkLink(link,save=true){
 if(link.type==='work_relation'){inspectWorkRelation(link);return;}
 workViewDispose?.focusVisit?.(link.source);workViewDispose?.focusLink?.(link.id);
 if(save&&link.type==='same_work_return'){params.set('work_episode',link.episode_id);params.delete('work_visit');params.delete('focus_unit');history.replaceState(history.state,'','/semantic-map?'+params);}
 const body=workDetail(link.type==='same_work_return'?(link.category==='returned'?'Return to earlier work':'Work recurrence'):'Correction attempt'),episode=workNavigation.episodes.find(e=>e.id===link.episode_id);
 appendScopeConflicts(body,workNavigation.visits.filter(v=>[link.source,link.target].includes(v.id)).map(v=>v.group_id));
 if(link.type!=='same_work_return'||link.source===link.target)body.append(el('h3','Work target'),el('p',episode.target));
 if(link.type==='attempted_correction_for'){body.append(el('h3','Recorded correction'),el('p',link.work||'An attempted correction is linked to this earlier work.'),workUnitButton(link.declaration_unit_id,'Inspect the stated adjustment'));}
 const procedure=WorkTimeline.comparisonFor(workNavigation,workProcedures,episode,workScopeAudit);
 const recurrenceLabel={continued:'Consecutive same-work recurrence',returned:'Return after intervening work',interrupted:'Recurrence across an observation gap',resumed:'Resumed after contributions without an applicable work target'};
 if(episode.category!=='returned'||link.type!=='same_work_return')body.append(el('h3','Recorded relationship'),el('p',recurrenceLabel[episode.category]||human(episode.category)));
 const hasProcedure=workNavigation.axis!=='contributions'&&procedure.key!=='unresolved';
 if(!hasProcedure&&link.type==='same_work_return'&&link.source!==link.target)appendReturnContext(body,link);
 if(workNavigation.axis!=='contributions'){
  const known=procedure.key!=='unresolved';
  if(known){
   body.append(el('h3',procedure.label));
   const review=procedure.record.episode?.method?.review;
   body.append(el('p',review?.note||procedure.reason,'wn-procedure-note'));
   if(review)body.append(el('small','Source review · '+review.author));
  }else {const missing=el('details');missing.append(el('summary','Procedure comparison unavailable'),el('p',procedure.reason));body.append(missing);}
  WorkReview.renderReason(body,procedure.record?.stated_reason,workUnitButton);
  WorkReview.renderErrorFollowup(body,procedure.record?.error_followup,workUnitButton);
  const inputs=WorkReview.comparisonFor(workNavigation,workComparisons,episode);
  if(inputs.record){
   body.append(el('h3',inputs.dispatch==='unavailable'?'Input comparison unresolved':inputs.dispatch==='changed'?'Recorded inputs changed':'Recorded inputs unchanged'),el('p','Feedback: '+human(inputs.feedback)));
   const compare=el('a','Inspect inputs and both feedback records →');compare.href='/semantic-map?'+new URLSearchParams({run:payload.run.id,observer:payload.graph.observer,graph:payload.graph.id,level:'units',revisit:workComparisons.id,revisit_case:inputs.record.id,return_to:location.pathname+location.search});body.append(compare);
  }else body.append(el('p',inputs.reason,'evidence-note'));
  appendDispatchComparison(body,episode,known);
 }
 if(hasProcedure&&link.type==='same_work_return'&&link.source!==link.target)appendReturnContext(body,link);
 if(episode.ordering){const proof=episode.ordering;body.append(el('h3','Ordering evidence'),el('p',proof.status==='bracketed_parallel'?'Both recurrence endpoints surround the complete observed dispatch group. The sibling calls remain unordered; their execution or completion order is not inferred.':proof.status==='unresolved'?proof.blockers.join(' '):'The recurrence endpoints and intervening contributions have recorded source order.'));for(const group of proof.parallel_groups)body.append(el('p',`${group.unit_ids.length} contributions dispatched together · ${group.fully_bracketed?'inside the recurrence window':'window or coverage unresolved'} · sibling order unknown`,'evidence-note'));}
 body.append(el('h3','Source witnesses'));for(const card of episode.cards)body.append(workUnitButton(card.unit_id,card.role+' · '+short(card.label,130)));
 const detail=el('details');detail.append(el('summary','Saved edge and episode evidence'),el('pre',JSON.stringify({link,episode},null,2)));body.append(detail,el('p','A return needs an identity link; a correction needs its own linked attempt. Neither establishes exploration, causal effectiveness or recovery.','evidence-note'));
}
function appendDispatchComparison(body,episode,open){
 const units=[episode.previous_unit_id,episode.current_unit_id].map(id=>payload.graph.nodes.find(n=>n.id===id&&n.kind==='unit'));
 const diff=WorkTimeline.dispatchDiff(...units.map(n=>n?.properties?.source?.text));if(!diff)return;
 const box=el('details',null,'wn-dispatch-comparison');box.open=open;box.append(el('summary',diff.equal?'Dispatch text · unchanged':'Compare dispatch text'));
 for(const [i,key]of ['before','after'].entries()){
  const part=diff[key],pre=el('pre');pre.append(document.createTextNode(part.prefix));if(part.changed)pre.append(el('mark',part.changed));pre.append(document.createTextNode(part.suffix));
  const displayed=layout.nodes.find(n=>n.id===units[i].id);
  box.append(workUnitButton(units[i].id,(i?'Later':'Earlier')+' dispatch'+(displayed?' · '+label(displayed):'')));
  if(!diff.equal||i===1)box.append(pre);
 }
 box.append(el('small',diff.equal?'Exact dispatch texts match. Files and environment may have changed.':'Highlight shows a textual difference, not its effect on execution.'));body.append(box);
}
function appendReturnContext(body,link){
 const context=WorkNavigationView.returnContext(workNavigation,link);if(!context.available){body.append(el('p',context.reason,'evidence-note'));return;}
 const list=el('ol',null,'wn-return-context');list.setAttribute('aria-label','Work around this recurrence');
 const section=(label,visits)=>{const item=el('li');item.append(el('strong',label));for(const v of visits){
  const button=el('button',null,'wn-return-visit');button.type='button';button.append(el('span',v.target),el('small',(workNavigation.axis==='contributions'?'Contributions ':'Actions ')+(v.positions.length>1?v.positions[0]+'–'+v.positions.at(-1):v.positions[0])+(v.order_known?'':' · order unresolved')));button.onclick=()=>inspectWorkVisit(v);item.append(button);
 }if(!visits.length)item.append(el('p','No intervening work visit is recorded.'));list.append(item);};
 section('Previous visit',[context.previous]);section('Intervening work',context.between);section(link.category==='returned'?'Returned visit':'Later visit',[context.current]);body.append(list);
 if(context.between.some(v=>!v.order_known))body.append(el('p','Intervening cards retain recording order. Parallel siblings do not have an established execution order.','evidence-note'));
 const referenceCount=context.interveningReferences.length+context.earlierWorkReferences.length;
 if(referenceCount){
  const references=el('section',null,'wn-return-references');references.append(el('h3','References during this visit'));
  for(const [label,links]of [['To intervening work',context.interveningReferences],['To earlier visits of this work',context.earlierWorkReferences]])if(links.length){references.append(el('h4',label));appendWorkConnections(references,links);}
  references.append(el('p','These references can occur later in the visit; they do not explain why the return began.','evidence-note'));body.append(references);
 }else if(workNavigation.axis==='contributions'){
  const coverage=el('details');coverage.append(el('summary','Visit-reference coverage'),el('p','No saved visit-to-visit reference is established in this view. This is not evidence that the model ignored earlier work.','evidence-note'));body.append(coverage);
 }
 if(context.workComparisons.length){const comparisons=el('details');comparisons.append(el('summary','Work-target comparisons · '+context.workComparisons.length),el('p','These saved judgments compare work targets. They do not establish that the agent referred to, used or revised earlier work.','evidence-note'));appendWorkConnections(comparisons,context.workComparisons);body.append(comparisons);}
}
$('#show-plan-level').onclick=showPlanLevel;$('#show-work-level').onclick=showWorkLevel;$('#show-story-level').onclick=showStoryLevel;$('#show-unit-level').onclick=()=>{setMapLevel('units');$('#map-inspector').hidden=true;};
$('#derive-work-groups').onclick=async()=>{
 const token=loadToken,button=$('#derive-work-groups');button.disabled=true;
 try{const r=await fetch('/api/work-grouping',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_graph_id:payload.graph.id})}),result=await r.json();if(!r.ok)throw Error(result.error||'Work grouping failed');if(token!==loadToken)return;
  clearReceipt();for(const key of ['work_episode','work_visit','focus_unit'])params.delete(key);params.set('graph',result.graph_id);params.set('observer',result.observer);params.set('level','work');await load(result.run_id,result.observer);
 }catch(error){if(token===loadToken){$('#map-error').hidden=false;$('#map-error').textContent=error.message;}}finally{button.disabled=false;}
};
function renderScopes(){
 for(const r of scopeResizers)r.disconnect();scopeResizers=[];
 const host=$('#work-scope-overview'),info=payload.graph.semantic_context?.work_scopes;host.replaceChildren();host.hidden=!info;
 renderRequestHistory($('#requested-terms-overview'));
 if(!info)return;
 const scopes=payload.graph.nodes.filter(n=>n.kind==='work_scope').sort((a,b)=>a.event_index-b.event_index||a.id.localeCompare(b.id)),byId=new Map(scopes.map(n=>[n.id,n])),rows=new Map(info.observations.map(r=>[r.unit_id,r]));
 const names=new Map();let request=0,plan=0;for(const n of scopes)names.set(n.id,n.properties.scope_kind==='organized_plan'?'Plan '+(++plan):'Request '+(++request));
 const heading=el('div',undefined,'scope-heading');heading.append(el('h2','Requests & plans'),el('span',`${info.counts.selected||0} contributions assigned · ${scopes.length} expressed scopes`));host.append(heading,el('p','Follow the expressed request or organized plan each contribution refers to. A changed scope does not establish goal drift, progress or completion.','scope-note'));
 const streams=new Map();
 for(const n of layout.nodes){
  const p=n.properties;if(p.actor!=='agent'||p.kind==='feedback'||p.copied_context||n.kind==='plan_step'||n.kind==='unresolved_reference')continue;
  const r=rows.get(n.id),ids=(r?.scope_ids||[]).filter(id=>byId.has(id)),status=r?.status||'uninspected',key=JSON.stringify([status,[...ids].sort()]);
  const lane=n.trajectory_id||'main';if(!streams.has(lane))streams.set(lane,[]);const blocks=streams.get(lane);
  if(!blocks.length||blocks.at(-1).key!==key)blocks.push({key,scope_ids:ids,status,node_ids:[]});blocks.at(-1).node_ids.push(n.id);
 }
 for(const [lane,blocks]of streams){
  if(streams.size>1)host.append(el('h3','Trajectory '+lane));
  const path=el('ol',undefined,'scope-path');path.setAttribute('aria-label','Expressed work scopes in source order');
  for(const [i,b]of blocks.entries()){
   const item=el('li'),button=el('button',undefined,'scope-block');button.type='button';button.dataset.scopeIds=b.scope_ids.join(',');button.dataset.unitCount=String(b.node_ids.length);
   const name=b.scope_ids.length?b.scope_ids.map(id=>names.get(id)).join(' + '):b.status==='no_work_context'?'No work scope':'Scope unresolved';
   button.append(el('small',`${i+1} · ${name}`),el('strong',b.scope_ids.length?short(b.scope_ids.map(id=>byId.get(id).properties.text).join(' / '),210):b.status==='no_work_context'?'Recorded contribution without a task-work scope.':'No complete saved scope assignment for these contributions.'),el('span',b.node_ids.length+' source-linked '+(b.node_ids.length===1?'card':'cards')));
   button.onclick=()=>inspectScopes(b.scope_ids,b.node_ids,b.status);item.append(button);path.append(item);
  }
  const nav=el('div',undefined,'scope-path-nav'),back=el('button','← Earlier'),forward=el('button','Later →');back.type=forward.type='button';
  back.onclick=()=>path.scrollBy({left:-Math.max(240,path.clientWidth*.8),behavior:'smooth'});forward.onclick=()=>path.scrollBy({left:Math.max(240,path.clientWidth*.8),behavior:'smooth'});
  const sync=()=>{back.disabled=path.scrollLeft<=1;forward.disabled=path.scrollLeft+path.clientWidth>=path.scrollWidth-1;};path.onscroll=sync;
  nav.append(el('span',`${blocks.length} scope blocks · source order`),back,forward);host.append(nav,path);const resize=new ResizeObserver(sync);resize.observe(path);scopeResizers.push(resize);requestAnimationFrame(sync);
 }
 host.append(el('p','Blocks follow source order; repeated assignments share a block. Shared membership is shown together and each contribution appears once. Select a block for its request text and contributing units.','scope-note'));
}
function renderRequestHistory(host){
 const model=L.requestedHistory(payload.graph);host.replaceChildren();host.hidden=!model;if(!model)return;
 const section=el('details',undefined,'request-history');
 const clauses=new Set(model.groups.flatMap(g=>g.versions.flatMap(v=>(L.requestedClauses(payload.graph,v.node.id)?.clauses||[]).map(c=>c.node.id))));
 section.append(el('summary',`Task requirements · ${model.groups.length} records${clauses.size?' · '+clauses.size+' clause versions':''} · ${model.info.counts.revisions} revisions`),el('p','Source-backed requested work and conditions. Select a record to inspect distinct clauses and their quotations. Fulfillment has not been checked.','scope-note'));
 const trajectories=new Set(model.groups.map(g=>g.trajectory_id));
 for(const group of model.groups){
  const article=el('article',undefined,'request-history-record');article.dataset.record=group.record_id;
  article.append(el('h3',`${group.kind==='condition'?'Conditions & requested checks':'Requested work'}${trajectories.size>1?' · '+group.trajectory_id:''}`));
  const list=el('ol',undefined,'request-history-versions');
  for(const [i,v]of group.versions.entries()){
   const li=el('li'),b=el('button',undefined,'request-history-version');b.type='button';b.dataset.version=v.node.id;b.dataset.review=String(v.review);
   b.append(el('small',`${i+1} · ${v.label}`),el('span',v.node.properties.text),el('small',`Source ${v.source_event_id||'unavailable'} · ${v.node.properties.status}`));b.onclick=()=>inspectRequestVersion(v);li.append(b);list.append(li);
  }
  article.append(list);section.append(article);
 }
 section.append(el('p','These are source-attributed requests and conditions, not the agent’s active goals, compliance or completion. Select a version to compare the wording and inspect its sources.','scope-note'));host.append(section);
}
function inspectRequestVersion(version){
 const body=workDetail('Requested terms · '+version.label);
 if(version.review)body.append(el('p','This comparison needs source review. The saved selection is an observer judgment, not proof that the request is incorrect. No term-change finding is established.','evidence-note'));
 for(const [heading,n]of [['Earlier version',version.before],['Selected version',version.node]]){
  if(!n)continue;const p=n.properties;
  body.append(el('h3',heading),el('p',p.text),el('small',p.status));
  const clauses=requestedClauseContents(n.id);if(clauses)body.append(clauses);
  const source=el('details');source.append(el('summary','Record source & identity'),el('small',p.version_id));
  for(const ref of p.evidence||[])source.append(el('pre',ref.text),el('small',ref.source_pointer||ref.event_id));
  source.append(workUnitButton(p.source_unit_id,'Open this source contribution'));body.append(source);
 }
 if(version.edge){const raw=el('details');raw.append(el('summary','Recorded decisions and relationship'),el('pre',JSON.stringify(version.edge,null,2)));body.append(raw);}
 const stateIds=new Set(payload.graph.edges.filter(e=>e.type==='contains_requested_version'&&e.target===version.node.id).map(e=>e.source));
 const dispatches=payload.graph.edges.filter(e=>e.type==='request_context_at_dispatch'&&stateIds.has(e.target)).sort((a,b)=>(layout.byId.get(a.source)?.event_index??Infinity)-(layout.byId.get(b.source)?.event_index??Infinity));
 if(dispatches.length){const actions=el('details');actions.append(el('summary',`${dispatches.length} actions had these terms available`),el('p','Source order. Availability does not establish that an action fulfilled the requirement.','evidence-note'));
  for(const e of dispatches){const n=layout.byId.get(e.source),choice=e.properties.choices[version.node.properties.version_id];actions.append(workUnitButton(e.source,`${n?.properties.source?.event_id||e.source} · ${short(n?.summary||'',110)}`),el('small',version.node.properties.kind==='condition'?'Condition availability only; satisfaction not inspected':choice?human(choice)+' · saved correspondence':'Correspondence not inspected'));}
  body.append(actions);
 }
 body.append(el('p','This history concerns requested work. It does not establish the agent’s current goal, authorization validity, execution, progress or drift.','evidence-note'));
}
function requestedClauseContents(versionId){
 const value=L.requestedClauses(payload.graph,versionId);if(!value)return null;
 const box=el('section',undefined,'requested-clauses');box.dataset.version=versionId;
 if(value.status!=='structured'){box.append(el('p',value.status==='unstructured'?'This older record has no separate condition clauses. Absence of clauses does not establish absence of restrictions.':'This saved graph has no clause projection. Its condition text remains available above.','evidence-note'));return box;}
 const names={requirement:'Requirement',requested_check:'Requested check',attributed_claim:'Attributed claim'};
 for(const {node}of value.clauses){const p=node.properties,item=el('article',undefined,'requested-clause');item.dataset.clause=p.version_id;item.dataset.kind=p.kind;
  item.append(el('strong',names[p.kind]),el('p',p.text));
  const details=el('details');details.append(el('summary','Clause source and version'));
  for(const ref of p.evidence)details.append(el('pre',ref.text),el('small',ref.source_pointer||ref.event_id));
  details.append(workUnitButton(p.source_unit_id,'Open clause source contribution'),el('small',p.version_id));item.append(details);box.append(item);
 }
 if(value.retired.length){const history=el('details',undefined,'retired-clauses');history.append(el('summary',`${value.retired.length} clauses removed from this version`),el('p','Removal records changed terms. It does not establish that a check passed or a claim was false.','evidence-note'));
  for(const {node,edge}of value.retired){history.append(el('strong',names[node.properties.kind]),el('p',node.properties.text),el('p',edge.properties.reason));for(const ref of edge.properties.evidence)history.append(el('pre',ref.text));history.append(workUnitButton(edge.properties.source_unit_id,'Open retirement source'));}box.append(history);
 }
 box.append(el('p','These contents were recorded in the request. Applicability, satisfaction and claim truth have not been assessed.','evidence-note'));return box;
}
function inspectScopes(ids,members,status='selected'){
 $('#map-inspector').hidden=false;$('#detail-title').textContent='Expressed work scope';$('#previous-unit').disabled=true;$('#next-unit').disabled=true;
 const body=$('#detail-body');body.replaceChildren();
 for(const id of ids){const n=payload.graph.nodes.find(n=>n.id===id);if(!n)continue;body.append(el('h3',n.properties.scope_kind==='organized_plan'?'Agent’s organized plan':'Expressed user request'),el('p',n.properties.text),el('pre',n.properties.source.text),el('small',n.properties.source.source_pointer||n.properties.source.event_id));}
 if(!ids.length)body.append(el('p',status==='no_work_context'?'The saved observation selects no task-work context for this contribution.':'Scope membership is unresolved or was not inspected. This does not establish unrelated work.'));
 body.append(el('h3',members.length+' contributing cards'));
 for(const id of members){const n=layout.byId.get(id);if(!n)continue;const b=el('button',label(n)+' · '+short(n.summary,135),'relation-button');b.onclick=()=>select(id,true);body.append(b);}
 const relations=payload.graph.edges.filter(e=>e.type==='in_work_scope'&&members.includes(e.source)&&ids.includes(e.target));
 if(relations.length){const raw=el('details');raw.append(el('summary','Saved membership evidence'),el('pre',JSON.stringify(relations,null,2)));body.append(raw);}
 body.append(el('p','Membership records which expressed work a contribution refers to. It does not prove compliance, authorization, task completion or the agent’s private goal.','evidence-note'));body.scrollTop=0;
}
function drawEdges(){if(!edgeLayer||!layout)return;$('#map-svg').classList.toggle('has-selection',!!selected||!!selectedEdge);edgeLayer.replaceChildren();
 const primary=connectionMode==='selected'&&selected?UnitReading.primaryLink(layout,selected,visible):null;
 const path=activeInspection?.item;$('#map-svg').classList.toggle('inspection-active',!!path);$('#connection-view').value=path?'inspection':connectionMode;
 for(const b of document.querySelectorAll('#edge-legend button'))b.setAttribute('aria-pressed',String(path?!activeInspection.hidden.has(b.dataset.family):visible.has(b.dataset.family)));
 const pathEdges=new Set(path?.edge_ids||[]),pathNodes=new Set(path?.node_ids||[]);
 const shown=(path?layout.edges.filter(e=>pathEdges.has(e.id)||e.id===selectedEdge):L.connectionView(layout,connectionMode,selected,selectedEdge,proofEdges)).filter(e=>path?!activeInspection.hidden.has(e.family)||e.id===selectedEdge:visible.has(e.family)||proofEdges.has(e.id)).filter(e=>!!path||connectionMode!=='selected'||!selected||e.id===primary?.id||proofEdges.has(e.id));
 const related=new Set(shown.flatMap(e=>[e.source,e.display_target||e.target]));
 for(const[id,g]of cardElements){g.classList.toggle('inspection-node',pathNodes.has(id));g.classList.toggle('selected',id===selected);g.classList.toggle('related',id!==selected&&related.has(id));g.classList.toggle('connection-end',shown.length===1&&related.has(id));if(shown.length===1)g.style.setProperty('--connection-color',L.colors[shown[0].family]);}
 const incident=layout.edges.filter(e=>e.family!=='sequence'&&(e.source===selected||(e.display_target||e.target)===selected));
 $('#connection-summary').textContent=path?'Inspection path · '+shown.length+' links · '+layout.nodes.length+' cards retained':primary?'R'+(incident.findIndex(e=>e.id===primary.id)+1)+' · '+UnitReading.sentence(layout,primary)+' · '+incident.length+' unit links'+(proofEdges.size?' · measurement evidence also shown':''):
  selectedEdge?UnitReading.sentence(layout,layout.edges.find(e=>e.id===selectedEdge)):
  !shown.length&&!selected?layout.nodes.length+' cards loaded · select a card to read its evidence':shown.length+' links shown · '+layout.nodes.length+' cards loaded';
 for(const [index,e]of shown.entries()){
  const incident=e.id===selectedEdge||e.source===selected||(e.display_target||e.target)===selected;if(!path&&!visible.has(e.family)&&!proofEdges.has(e.id))continue;
  const a=layout.byId.get(e.source),b=layout.byId.get(e.display_target||e.target),color=L.colors[e.family],routing=L.connectionRoute(a,b,index),d=routing.d,group=svg('g',{class:'edge-group'+(incident?' incident':'')+(proofEdges.has(e.id)?' proof-edge':''),'data-relation':e.type,'data-family':e.family,'data-from':e.source,'data-to':e.target});
  group.append(svg('title',{},label(a)+' → '+relationLabel(e.type)+' → '+label(b)),svg('path',{d,class:'edge-line',stroke:color,'marker-end':'url(#arrow-'+e.family+')',...(L.patterns[e.family]?{'stroke-dasharray':L.patterns[e.family]}:{})}));
  if(shown.length===1)group.append(svg('circle',{cx:routing.points[0][0],cy:routing.points[0][1],r:4,fill:'white',stroke:color,'stroke-width':2,'pointer-events':'none'}));
  if(e.family!=='sequence'){
   const hit=svg('path',{d,class:'edge-hit'});group.append(hit);
   // A horizontal SVG path has a zero-height geometric bounding box. Give
   // same-row links a real hit area for keyboard focus and pointer targeting.
   if(routing.kind==='row'){const left=a.x<b.x?a:b,right=a.x<b.x?b:a;
    const area=svg('rect',{class:'edge-hit-area',x:left.x+left.width,y:left.y+left.height/2-12,width:right.x-left.x-left.width,height:24,fill:'transparent',stroke:'none'});
    group.append(area);}
   // Names stay in the hover title and connection inspector. Stacking labels
   // below a shared endpoint covered the next card and other relationship names.
   if(incident||e.id===selectedEdge){
    const code='R'+(layout.edges.filter(x=>x.family!=='sequence'&&(x.source===selected||(x.display_target||x.target)===selected)).findIndex(x=>x.id===e.id)+1);
    const badge=svg('g',{class:'edge-badge'}),{x,y}=routing.badge;
    if(shown.length===1){
     const words=relationLabel(e.type).split(' '),lines=routing.badge.lines===1?[words.join(' ')]:words.length>1?[words.slice(0,-1).join(' '),words.at(-1)]:words;
     const width=Math.min(routing.badge.width,Math.max(46,Math.max(...lines.map(t=>t.length))*5.5+12)),height=lines.length*12+8;
     badge.append(svg('rect',{x:x-width/2,y:y-height/2,width,height,rx:5}));
     lines.forEach((line,i)=>badge.append(svg('text',{x,y:y-height/2+13+i*12,'text-anchor':'middle'},short(line,Math.floor((width-12)/5.5)))));
    }else badge.append(svg('rect',{x:x-15,y:y-10,width:30,height:21,rx:5}),svg('text',{x,y:y+4,'text-anchor':'middle'},selected?code:'Link'));
    group.append(badge);
   }
   group.setAttribute('role','button');group.setAttribute('tabindex','0');
   group.setAttribute('aria-label',label(a)+' → '+relationLabel(e.type)+' → '+label(b));
   group.onclick=()=>inspectEdge(e);
   group.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();inspectEdge(e);}};
  }
  edgeLayer.append(group);
 }
}
function appendWorkSubjectReview(body,n){
 if(!payload.capabilities?.work_subject_review||n.kind!=='unit'||n.properties.actor!=='agent'||!['semantic','action'].includes(n.properties.kind))return;
 const section=el('details'),open=el('summary','Review work target'),container=el('div');section.append(open,container);body.append(section);
 const graphId=payload.graph.id;let loaded=false;
 section.ontoggle=async()=>{
  if(!section.open||loaded)return;loaded=true;container.textContent='Loading source-bound work targets…';
  try{
   const data=await api('/api/work-subjects?graph='+encodeURIComponent(graphId));if(!section.isConnected||payload.graph.id!==graphId)return;
   const unit=data.units.find(u=>u.id===n.id);container.replaceChildren();
   if(!unit){container.append(el('p','Review the contribution boundary before assigning its work target.'));return;}
   const form=el('form',undefined,'work-review-form'),choice=el('select'),target=el('input'),author=el('input'),note=el('textarea'),save=el('button','Save reviewed work target'),status=el('p');
   if(data.document.profile)form.append(el('p','Shared profile: '+data.document.profile.label+' · '+data.document.profile.version,'evidence-note'));
   choice.setAttribute('aria-label','Work target membership');target.setAttribute('aria-label','Natural-language work target');author.setAttribute('aria-label','Reviewer');note.setAttribute('aria-label','Work target rationale');
   for(const[value,text]of [['unresolved','Unresolved'],['not_applicable','No work target applies'],['new','Name work starting here']]){const o=el('option',text);o.value=value;choice.append(o);}
   const eligible=data.document.subjects.filter(s=>{const origin=data.units.find(u=>u.id===s.origin_unit_id);return origin&&JSON.stringify(origin.lane)===JSON.stringify(unit.lane)&&(origin.id===unit.id||origin.position[0]<unit.position[0]||origin.position[0]===unit.position[0]&&origin.position[2]<=unit.position[1]);});
   for(const s of eligible){const o=el('option',s.label);o.value='subject:'+s.id;choice.append(o);}
   const previous=data.document.bindings.find(r=>r.unit_id===n.id);choice.value=previous?.status==='bound'?'subject:'+previous.subject_id:previous?.status||'unresolved';
   target.maxLength=1200;author.maxLength=240;author.required=true;note.required=true;note.maxLength=2400;note.rows=3;
   author.value=previous?.provenance.author||'';note.value=previous?.note||'';target.placeholder='The question, result or artifact this contribution addresses';
   target.value=L.text(n.properties.content?.work_target)||L.text(n.properties.content?.target)||'';
   const field=(name,input)=>{const label=el('label',name);label.append(input);return label;};
   const targetField=field('Immediate work',target),witness=el('p',undefined,'evidence-note');
   function update(){const s=eligible.find(s=>'subject:'+s.id===choice.value),origin=s&&data.units.find(u=>u.id===s.origin_unit_id),editable=choice.value==='new'||origin?.id===unit.id;targetField.hidden=!editable;target.required=editable;if(origin?.id===unit.id)target.value=s.label;witness.textContent=origin?'Origin: '+origin.source.text:'Name one immediate work target. Broader requests and plans remain separate.';}
   choice.onchange=update;update();save.type='submit';status.setAttribute('role','status');
   form.append(field('Membership',choice),targetField,witness,field('Reviewer',author),field('Why this binding is supported',note),el('p','Saves a new graph version. Existing measurements keep their original evidence. No model call.','evidence-note'),save,status);container.append(form);
   form.onsubmit=async event=>{event.preventDefault();if(!form.reportValidity())return;save.disabled=true;status.textContent='Saving review…';
    const d=structuredClone(data.document);let sid=null;
    if(choice.value==='new'){sid='review-'+unit.id;const own=d.subjects.find(s=>s.origin_unit_id===unit.id);if(own)sid=own.id;d.subjects=d.subjects.filter(s=>s.id!==sid);d.subjects.push({id:sid,label:target.value.trim(),origin_unit_id:unit.id});}
    else if(choice.value.startsWith('subject:')){sid=choice.value.slice(8);const subject=d.subjects.find(s=>s.id===sid);if(subject.origin_unit_id===unit.id)subject.label=target.value.trim();}
    d.bindings=d.bindings.filter(r=>r.unit_id!==unit.id);d.bindings.push({unit_id:unit.id,status:sid?'bound':choice.value,subject_id:sid,note:note.value.trim(),provenance:{kind:'review',author:author.value.trim(),protocol:'work-subject-review/1'}});
    const used=new Set(d.bindings.map(r=>r.subject_id));d.subjects=d.subjects.filter(s=>used.has(s.id));
    try{const r=await fetch('/api/work-subjects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}),result=await r.json();if(!r.ok)throw Error(result.error||'Review could not be saved');
     if(!section.isConnected||payload.graph.id!==graphId)return;for(const k of ['value','profile','revisit','revisit_case','work_episode','work_visit'])params.delete(k);params.set('graph',result.graph_id);params.set('observer',result.observer);params.set('level','work');await load(result.run_id,result.observer);
    }catch(error){status.textContent=error.message;save.disabled=false;}
   };
  }catch(error){container.textContent=error.message;loaded=false;}
 };
}
function appendRelationshipReview(body,n){
 if(n.kind!=='unit'||n.properties.actor!=='agent'||n.properties.kind!=='semantic'||n.properties.status!=='selected')return;
 if(!payload.capabilities?.relationship_review){if(receipt||strategyReceipt){const c=receipt?.review_context;const a=el('a','Open observation input to review relationships');a.href='/semantic-map?'+new URLSearchParams({run:payload.graph.run_id,observer:c?.observer||payload.graph.observer,...(c?{graph:c.graph_id,review_monitor:c.monitor_id,review_value:receipt.measurement.id}:{}),focus_unit:n.id,...(params.get('return_to')?{return_to:params.get('return_to')}:{})});body.append(a);}return;}
 const section=el('details'),container=el('div');section.className='relationship-review';section.append(el('summary','Review relationships'),container);body.append(section);
 const graphId=payload.graph.id;let loaded=false;
 section.ontoggle=async()=>{
  if(!section.open||loaded)return;loaded=true;container.textContent='Loading earlier source evidence…';
  try{
   const data=await api('/api/relationship-reviews?'+new URLSearchParams({graph:graphId,unit:n.id}));
   if(!section.isConnected||payload.graph.id!==graphId)return;container.replaceChildren();
   if(!data.candidates.length){container.append(el('p','No eligible earlier referents. Check contribution boundaries and native feedback links first.'));return;}
   const form=el('form',undefined,'work-review-form'),type=el('select'),target=el('select'),status=el('select'),author=el('input'),note=el('textarea'),save=el('button','Save relationship review'),message=el('p'),definition=el('p',undefined,'evidence-note'),witness=el('pre',undefined,'relationship-source');
   const field=(label,input)=>{const l=el('label',label);l.append(input);return l;};
   type.setAttribute('aria-label','Relationship type');target.setAttribute('aria-label','Earlier referent');status.setAttribute('aria-label','Review finding');author.setAttribute('aria-label','Relationship reviewer');note.setAttribute('aria-label','Relationship rationale');
   for(const kind of Object.keys(data.relations)){if(!data.candidates.some(c=>c.types.includes(kind)))continue;const o=el('option',human(kind));o.value=kind;type.append(o);}
   for(const[value,label]of [['present','Present — supported by these sources'],['absent','Absent — this pair is not related'],['unresolved','Unresolved — cannot establish this pair'],['original','Use original observation — remove this review']]){const o=el('option',label);o.value=value;status.append(o);}
   author.required=true;author.maxLength=240;note.required=true;note.maxLength=2400;note.rows=3;save.type='submit';message.setAttribute('role','status');
   author.value=data.document.revision.author||'';
   function choose(){const c=data.candidates.find(c=>c.id===target.value),r=data.document.reviews.find(r=>r.from===n.id&&r.to===target.value&&r.type===type.value);witness.textContent=c?.source.text||'';status.value=r?.status||'unresolved';note.value=r?.provenance.note||'';if(r)author.value=r.provenance.author;}
   function configure(){definition.textContent=data.relations[type.value];target.replaceChildren();for(const c of data.candidates.filter(c=>c.types.includes(type.value))){const o=el('option',(c.source.event_id||'')+' · '+short(c.source.text,120));o.value=c.id;target.append(o);}choose();}
   type.onchange=configure;target.onchange=choose;configure();
   form.append(el('strong','Contribution source · exact text'),el('pre',data.subject.source.text,'relationship-source'),field('Relationship',type),definition,field('Earlier source · exact text',target),witness,field('Finding for this pair',status),field('Reviewer or annotator',author),field('Evidence and rationale',note),el('p',data.limit,'evidence-note'),el('p','Saves a separate reviewed observer. Monitors using that observer follow later corrections; earlier receipts remain unchanged. No model call.','evidence-note'),save,message);container.append(form);
   form.onsubmit=async event=>{
    event.preventDefault();if(!form.reportValidity())return;save.disabled=true;message.textContent='Saving source-bound review…';
    const d=structuredClone(data.document);d.revision={author:author.value.trim(),note:note.value.trim()};d.reviews=d.reviews.filter(r=>!(r.from===n.id&&r.to===target.value&&r.type===type.value));
    if(status.value!=='original')d.reviews.push({from:n.id,to:target.value,type:type.value,status:status.value,provenance:{...d.revision}});
    try{const response=await fetch('/api/relationship-reviews',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}),result=await response.json();if(!response.ok)throw Error(result.error||'Review could not be saved');
     if(!section.isConnected||payload.graph.id!==graphId)return;for(const k of ['value','profile','revisit','revisit_case','work_episode','work_visit'])params.delete(k);params.set('graph',result.graph_id);params.set('observer',result.observer);params.set('focus_unit',n.id);await load(result.run_id,result.observer);
    }catch(error){message.textContent=error.message;save.disabled=false;}
   };
  }catch(error){container.textContent=error.message;loaded=false;}
 };
}
function appendConnectionReading(body,n){
 const edges=layout.edges.filter(e=>e.family!=='sequence'&&(e.source===n.id||(e.display_target||e.target)===n.id));
 const section=el('section',undefined,'connection-reading');
 const groups=UnitReading.sections(layout,n.id);
 if(!groups.length)section.append(el('p','No saved connections between map cards. Adjacent cards show chronology only.','connection-empty'));
 for(const group of groups){
  const block=el('details',undefined,'connection-group');block.open=['result','use','changes','trace'].includes(group.key);
  block.append(el('summary',group.title+(group.rows.length?' · '+group.rows.length:'')));
  if(group.empty)block.append(el('p',group.empty,'connection-empty'));
  for(const {edge:e,node:other,via} of group.rows){
   const index=edges.findIndex(x=>x.id===e.id),row=el('div',undefined,'connection-reading-row');
   const detail=el('button',(index>=0?'R'+(index+1)+' · ':'')+UnitReading.sentence(layout,e),'connection-title');
   detail.title='Isolate this relationship and read its evidence';detail.onclick=()=>inspectEdge(e);
   row.append(detail);
   if(via){const viaButton=el('button','Via returned feedback '+UnitReading.ref(via.node),'connection-via');viaButton.onclick=()=>select(via.node.id,true);row.append(viaButton);}
   const raw=other.properties.source?.text||other.properties.text;
   const copy=other.lane===0&&raw?L.text(raw):UnitReading.content(other);
   row.append(el('small',other.lane===2?'Returned output excerpt':raw&&other.lane===0?(other.properties.actor==='agent'?'Agent text excerpt':'Source text excerpt'):'Saved action detail','connection-source-label'),el('p',short(copy.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,''),360),'connection-excerpt'));
   const go=el('button','Open '+label(other),'connection-go');go.onclick=()=>select(other.id,true);row.append(go);block.append(row);
  }
  section.append(block);
 }
 body.append(section);
}
function appendCapturedResponses(body,n){
 const rows=L.capturedResponses(layout,n.id);if(!rows.length)return;
 const section=el('section',undefined,'connection-reading');section.append(el('h3','Captured call feedback'),el('p','Recorded for this source call; not assigned to a specific sub-unit.','evidence-note'));
 for(const r of rows){const item=el('div');item.append(el('small','Response to '+short(r.action.properties.text||r.action.properties.tool||r.action.properties.id,100)),el('p',RolloutStory.preview(r.response.properties.text).text));
  const raw=el('details');raw.append(el('summary','Full call & response'),el('h4','Captured action'),el('pre',r.action.properties.text||''),el('h4','Captured response'),el('pre',r.response.properties.text||''),el('small',r.response.properties.source_pointer||r.response.id));item.append(raw,sourceButton(r.action_card_ids.includes(n.id)?r.response.id:r.action.id,null,true));section.append(item);
 }body.append(section);
}
function select(id,scroll=false,scrollBehavior='smooth'){const n=layout.byId.get(id);if(!n)return;params.delete('guide');activeEvidenceGuide=null;const openingInspector=$('#map-inspector').hidden;$('.inspector-foot').hidden=false;$('#previous-unit').disabled=false;$('#next-unit').disabled=false;selected=id;selectedEdge=null;connectionOrigin=null;params.delete('focus_link');params.delete('link_from');drawEdges();$('#map-inspector').hidden=false;$('#detail-title').textContent=label(n)+' · '+human(n.activity);$('#selection-count').textContent=label(n)+' selected · all '+layout.nodes.length+' cards retained';const body=$('#detail-body');body.replaceChildren();appendInspectionReturn(body);
 if(params.get('return_to')?.startsWith('/?view=strategies')){const back=el('a','← Behavior distributions');back.href=params.get('return_to');body.append(back);}
 const summary=UnitReading.cardText(n);
 body.append(el('p',RolloutStory.excerpt(summary),'selected-unit-summary'));
 const nativeRecord=n.kind==='event'?n.properties:payload.graph.nodes.find(row=>row.id==='event:'+n.properties?.source?.event_id)?.properties;
 window.ContextMix?.attach(body,payload.run.id,nativeRecord);
 if(nativeRecord?.native_call_id){
  const trace=el('section',undefined,'selected-source-call');trace.append(el('h3','Weave call'));
  if(nativeRecord.call_status)trace.append(el('p',human(nativeRecord.call_status)+' · '+human(nativeRecord.behavior_scope)));
  if(nativeRecord.wb_run_step!==undefined)trace.append(el('p','W&B logging step '+nativeRecord.wb_run_step));
  if(nativeRecord.source_uri?.startsWith('https://wandb.ai/')){const link=el('a','Open call in Weave ↗');link.href=nativeRecord.source_uri;link.target='_blank';link.rel='noopener noreferrer';trace.append(link);}
  body.append(trace);
 }
 if(RolloutStory.excerpt(summary)!==summary){const full=el('details',undefined,'selected-full-text');full.append(el('summary','Full card text'),el('pre',summary));body.append(full);}
 if(n.target&&n.target!==summary)body.append(el('p','Work target · '+RolloutStory.excerpt(n.target),'selected-work-target'));
 if(n.lane===1){const operation=UnitReading.content(n);if(operation!==n.target&&operation!==summary)body.append(el('p',RolloutStory.excerpt(operation),'selected-operation'));}
 appendConnectionReading(body,n);appendCapturedResponses(body,n);window.TrainingSpansView?.appendUnit(body,id);const section=(name,content)=>{if(content===n.target||!n.target)return;const d=el('details');d.append(el('summary',name),el('pre',content));body.append(d);};
 const state=L.stateEvidence(payload.graph,id),hasState=state.checks.length||state.snapshots.length||state.views.length;
 if(L.historyEvidence(payload.graph,id).length){appendHistoryEvidence(body,id);const action=el('details');action.append(el('summary','Dispatched action'),el('pre',n.summary));body.append(action);}else if(!hasState||n.kind!=='event')section('Contribution',n.summary);
 const localWork=payload.graph.nodes.some(item=>item.kind==='work_mention'&&item.properties.unit_id===n.id);
 if(n.target&&!localWork)section('Target',n.target);
 if(n.kind==='unit')window.WorkContents?.append(body,payload.graph,n.id);
 appendPriorWorkSearch(body,n);
 window.SourceEvidence?.append(body,payload.graph,n);
 appendStateEvidence(body,id);
 for(const row of L.declaredPlans(payload.graph,id)){appendPlanDeclaration(body,row.snapshot);if(row.previous){const prior=el('details');prior.append(el('summary','Previous issued list'+(row.comparable?'':' · comparison unresolved')));appendPlanDeclaration(prior,row.previous);prior.append(sourceButton(row.previous.event_id));body.append(prior);}}
 const declaredWork=L.declaredWork(payload.graph,id);if(declaredWork.length){body.append(el('h3','Declared work context'));for(const {goal,record} of declaredWork){body.append(el('p',goal.properties.label),el('small','Producer-captured '+record.properties.kind.replaceAll('_',' ')));const branch=el('button','Open branch in Plans & attempts','relation-button');branch.onclick=()=>{params.set('work_focus',goal.id);showPlanLevel();};body.append(branch);}}
 appendFeedbackSearch(body,n);
 window.UnitReview?.append(body,n,{payload,receipt,params,onSaved:async result=>{
  for(const k of ['value','profile','revisit','revisit_case','work_episode','work_visit'])params.delete(k);
  params.set('graph',result.graph_id);params.set('observer',result.observer);params.set('level','units');
  params.set('focus_unit',result.impact.new_unit_ids[0]||n.id);await load(result.run_id,result.observer);
 }});
 appendRelationshipReview(body,n);
 appendWorkSubjectReview(body,n);
 const requestContext=L.requestContext(payload.graph,id);
 if(requestContext){const box=el('section',undefined,'dispatch-request-context');box.append(el('h3','Requested context at this action'),el('p','Saved request versions available before dispatch. Availability does not establish applicability, permission or satisfaction.','evidence-note'));
  if(!requestContext.versions.length)box.append(el('p','No prior selected request records. This is not evidence that the action had no objective.'));
  for(const v of requestContext.versions){const b=el('button',v.node.properties.text,'relation-button');b.dataset.version=v.node.id;b.append(el('small',v.label+' · '+v.node.properties.status));b.onclick=()=>{const item=L.requestedHistory(payload.graph)?.groups.flatMap(g=>g.versions).find(r=>r.node.id===v.node.id);if(item)inspectRequestVersion(item);};box.append(b);const clauses=requestedClauseContents(v.node.id);if(clauses)box.append(clauses);}
  const raw=el('details');raw.append(el('summary','Dispatch cutoff and saved choices'),el('pre',JSON.stringify(requestContext.edge,null,2)));box.append(raw);body.append(box);
 }
 const notes=(payload.graph.semantic_context?.review_notes||[]).filter(note=>(note.unit_ids||[]).includes(id));
 const memberships=payload.graph.edges.filter(e=>e.type==='in_work_scope'&&e.source===id);
 if(memberships.length){body.append(el('h3','Expressed work scope'));for(const e of memberships){const scope=payload.graph.nodes.find(v=>v.id===e.target),b=el('button',short(scope.properties.text,200),'relation-button');b.onclick=()=>inspectScopes([scope.id],[id]);body.append(b);}}
 if(notes.length){const review=el('details',undefined,'unit-review-notes');review.append(el('summary',notes.length+' source review '+(notes.length===1?'note':'notes')+' · review limitations'));for(const note of notes){if(note.review_scope)review.append(el('small',note.review_scope));review.append(el('p',note.text,'evidence-note'));}body.append(review);}
 const contentFields=Object.entries(n.properties.content||{}).filter(([k,v])=>!['summary','target','recorded_response'].includes(k)&&L.text(v));
 if(localWork&&n.target)contentFields.unshift(['target',n.target]);
 if(contentFields.length){const fields=el('details');fields.append(el('summary','Activity details'));for(const[k,v]of contentFields)fields.append(el('h3',human(k)),el('p',L.text(v)));body.append(fields);}
 if(n.properties.work_adjustments?.length){body.append(el('h3','Work items in this contribution'));for(const item of n.properties.work_adjustments){body.append(el('p',item.work));const declarations={commits:'Undertaking',proposes:'Proposal',defers:'Deferred work',withdraws:'Withdrawn work',reports_finished:'Completion claim',reports_blocked:'Reported blockage'},facets={adjustment_content:'Correction or alteration described',performs_adjustment:'Describes a correction by this work',uses_prior_adjustment:'Describes using a separate correction',other_content:'No correction described for this work'};body.append(el('small',(item.declaration?(declarations[item.declaration]||human(item.declaration))+' · ':'')+(facets[item.selection]||human(item.selection))+' · '+item.item_id));}}
 const source=n.properties.source||n.properties;
 if(hasState&&n.kind==='event'){const raw=el('details');raw.append(el('summary','Source evidence · full recorded contribution'),el('pre',source.text||n.summary),el('small',source.source_pointer||'Saved source'));body.append(raw);}
 else {const raw=el('details');raw.append(el('summary','Source evidence'),el('pre',source.text||n.summary),el('small',source.source_pointer||'Saved plan content'));body.append(raw);}
 const details=el('details');details.append(el('summary','Observation provenance'),el('pre',JSON.stringify(n.properties,null,2)));body.append(details);
 body.scrollTop=0;
 if((params.get('level')||'units')==='units'){params.delete('feedback_case');params.set('focus_unit',id);history.replaceState(history.state,'','/semantic-map?'+params);}
 if(openingInspector){sizeViewport();fit();}
 if(scroll)$('#map-viewport').scrollTo({top:Math.max(0,(n.y-172)*zoom),left:Math.max(0,n.x*zoom-40),behavior:openingInspector?'instant':scrollBehavior});
 updatePosition();revealInspector();}
function revealInspector(){/* Keep the selected map position; compact screens use a dismissible side sheet. */}
function appendConnectionFocus(body,r){
 if(activeEvidenceGuide){const back=el('button','← Evidence guide','connection-back');back.onclick=()=>openEvidenceGuide(activeEvidenceGuide);body.append(back);}
 const origin=layout.byId.get(connectionOrigin),links=origin?UnitReading.sections(layout,origin.id).flatMap(g=>g.rows).filter(row=>!row.via).map(row=>row.edge):[];
 if(origin){
  const back=el('button','← Back to '+label(origin)+' · '+links.length+' connections','connection-back');back.onclick=()=>select(origin.id);body.append(back);
  if(links.length>1){const nav=el('div',undefined,'connection-pager'),previous=el('button','←'),choice=el('select'),next=el('button','→');
   previous.setAttribute('aria-label','Previous relationship');next.setAttribute('aria-label','Next relationship');choice.setAttribute('aria-label','Read unit relationship');
   for(const edge of links){const option=el('option',UnitReading.sentence(layout,edge));option.value=edge.id;choice.append(option);}choice.value=r.edge.id;
   const index=links.findIndex(edge=>edge.id===r.edge.id);previous.disabled=index<=0;next.disabled=index<0||index>=links.length-1;
   previous.onclick=()=>inspectEdge(links[index-1]);next.onclick=()=>inspectEdge(links[index+1]);choice.onchange=()=>inspectEdge(links.find(e=>e.id===choice.value));nav.append(previous,choice,next);body.append(nav);
  }
 }else if(!activeEvidenceGuide){const back=el('button','← Back to map','connection-back');back.onclick=()=>$('#close-detail').click();body.append(back);}
 body.append(el('h2',r.question,'connection-question'));
 const pair=el('div',undefined,'connection-pair');
 for(const [index,n]of [r.from,r.to].entries()){
  if(index)pair.append(el('div','↓ '+r.label,'connection-predicate'));
  const card=el('div',undefined,'connection-endpoint'),style=L.cardStyle(n);card.style.setProperty('--endpoint-accent',style.color);
  card.append(el('small',UnitReading.ref(n)+' · '+activityLabel(n)),el('p',short(UnitReading.evidenceText(n),380)));
  const actions=el('div'),locate=el('button','Locate '+UnitReading.ref(n)),open=el('button','Full unit');
  locate.onclick=()=>{const v=$('#map-viewport');v.scrollTo({top:Math.max(0,(n.y-35)*zoom),left:Math.max(0,n.x*zoom-35),behavior:'instant'});updatePosition();};
  open.onclick=()=>select(n.id,true);actions.append(locate,open);card.append(actions);pair.append(card);
 }
 body.append(pair,el('p',r.meaning,'connection-meaning'),el('small','Arrow = recorded relation from the upper card to the lower card; card numbers show trace order.','connection-direction-note'));
}
function inspectEdge(e){
 const reading=UnitReading.connection(layout,e);if(!reading)return;params.delete('guide');
 if(selected)connectionOrigin=selected;
 params.delete('focus_unit');params.set('focus_link',e.id);params.set('graph',payload.graph.id);
 if(connectionOrigin)params.set('link_from',connectionOrigin);else params.delete('link_from');
 history.replaceState(history.state,'','/semantic-map?'+params);selected=null;selectedEdge=e.id;drawEdges();$('.inspector-foot').hidden=true;$('#previous-unit').disabled=true;$('#next-unit').disabled=true;$('#selection-count').textContent=reading.direction+' · '+reading.label;$('#detail-body').scrollTop=0;$('#map-inspector').hidden=false;$('#detail-title').textContent='Connection evidence';const body=$('#detail-body');body.replaceChildren();
 appendInspectionReturn(body);appendConnectionFocus(body,reading);
 const rationale=el('details');rationale.append(el('summary','Saved rationale'));
 if(e.properties.explanation)rationale.append(el('p',e.properties.explanation));
 if(e.properties.assessment_text)rationale.append(el('p',e.properties.assessment_text));
 if(e.type==='parent_message')rationale.append(el('p','The capture code paired this model response with the dispatched action in the same episode turn.'));
 if(rationale.childElementCount>1)body.append(rationale);
 if(e.type==='recorded_recheck_of')body.append(el('h3','Recorded criterion comparison'),el('p',e.properties.comparable?'Criterion version, input scope, environment and captured stability are comparable.':'Comparability is not established: '+(e.properties.issues||[]).map(human).join(' · ')));
 if(e.properties.evidence?.length){const quotes=el('details');quotes.append(el('summary','Source quotes · '+e.properties.evidence.length));for(const span of e.properties.evidence)quotes.append(el('pre',span.text),el('small',span.source_pointer||span.event_id));body.append(quotes);}
 if(e.projection==='whole_source_event')body.append(el('p','Captured action–response identity, displayed through cards covering the complete source events.','evidence-note'));
 const raw=el('details');raw.append(el('summary','Full saved relationship'),el('pre',JSON.stringify(e.stored_source?payload.graph.edges.find(row=>row.id===e.id)||e:e.properties,null,2)));body.append(raw);
 revealInspector();requestAnimationFrame(()=>{sizeViewport();const v=$('#map-viewport');
  fit();const within=n=>n.y*zoom<v.scrollTop+v.clientHeight&&(n.y+n.height)*zoom>v.scrollTop;if(!within(reading.from)&&!within(reading.to)){const anchor=layout.byId.get(connectionOrigin)||reading.from;v.scrollTo({top:Math.max(0,(anchor.y-35)*zoom),left:Math.max(0,(anchor.x+anchor.width/2)*zoom-v.clientWidth/2),behavior:'instant'});}updatePosition();});}
function scale(value){const viewport=$('#map-viewport'),old=zoom,top=viewport.scrollTop,left=viewport.scrollLeft;zoom=Math.max(.25,Math.min(1.6,value));$('#map-svg').style.transform=`scale(${zoom})`;$('#map-space').style.width=layout.width*zoom+'px';$('#map-space').style.height=layout.height*zoom+'px';$('#zoom-label').textContent=Math.round(zoom*100)+'%';$('.lane-headings').style.width=layout.width*zoom+'px';if(zoom!==old){viewport.scrollTop=top*zoom/old;viewport.scrollLeft=left*zoom/old;}updatePosition();}
function fit(){if(!layout||zoomMode==='manual')return;const width=($('#map-viewport').clientWidth-16)/layout.width;
 // Fit a connection on desktop, but never turn that temporary adjustment
 // into an explicit fit-width preference that shrinks text after a resize.
 const readable=selectedEdge&&width>=.65?Math.min(1,width):Math.max(.8,Math.min(1,width));
 scale(zoomMode==='readable'?readable:width);$('#readable-map').setAttribute('aria-pressed',String(zoomMode==='readable'));$('#fit-map').setAttribute('aria-pressed',String(zoomMode==='fit'));}
function setCanvasFocus(expanded,save=true){if(save){params.set('canvas',expanded?'expanded':'page');history.replaceState(history.state,'','/semantic-map?'+params);}document.body.classList.toggle('canvas-focus',expanded);$('#focus-canvas').setAttribute('aria-pressed',String(expanded));$('#focus-canvas').textContent=expanded?'Exit expanded view ↙':'Expand canvas ⛶';requestAnimationFrame(()=>{sizeViewport();fit();updatePosition();});}
function positionMapKey(){
 const controls=$('#map-reading-controls'),inspector=$('#map-inspector');
 const overlay=innerWidth<1280&&!(innerWidth>=1100&&document.body.classList.contains('canvas-focus'));
 const inInspector=overlay&&!inspector.hidden&&!$('#unit-level-map').hidden;
 const parent=inInspector?inspector:$('#map-key-slot');
 if(controls.parentElement!==parent){if(inInspector)inspector.insertBefore(controls,$('#detail-body'));else parent.append(controls);}
 const compact=controls.clientWidth<680,options=$('#map-display-options'),key=$('section.map-key'),card=$('.card-content-control'),links=$('.connection-toolbar');
 const destination=compact?options.querySelector('.map-display-body'):key;
 if(card.parentElement!==destination)destination.append(card);
 if(links.parentElement!==destination)destination.append(links);
 options.hidden=!compact;
}
function sizeViewport(){
 positionMapKey();
 const v=$('#map-viewport');
 v.style.height=Math.max(240,innerHeight-Math.max(12,v.getBoundingClientRect().top)-$('#map-viewport').nextElementSibling.getBoundingClientRect().height-18)+'px';
 // The sticky inspector follows the viewport via CSS. A height measured from
 // the workbench's initial page offset becomes stale when the page scrolls.
}

function rememberMeasuredCase(kind,item){
 if(!receipt)return;const key=MeasurementCaseLinks.address(receipt.explanation,kind,item);if(!key)return;
 params.set('measure_case',key);for(const name of ['focus_unit','focus_link','link_from','inspect','inspect_case','guide','feedback_case'])params.delete(name);
 history.replaceState(history.state,'','/semantic-map?'+params);
}
function openMeasuredCase(key){
 const entry=MeasurementCaseLinks.find(receipt?.explanation,key);
 if(!entry){explainMeasurement();$('#detail-body').prepend(el('p','The requested case is not present in this saved measurement.','evidence-note'));return;}
 const handlers={analysis:explainAnalysisCase,anchor:explainAnchor,revision:explainRevisionEpisode,retry:explainRetryEpisode,feedback:explainFeedback};handlers[entry.kind](entry.item);
}
function explainRetryEpisode(e){
 rememberMeasuredCase('retry',e);const body=evidenceHeading('Recorded retry · '+human(e.retry_outcome));selected=null;
 proofNodes=new Set([e.failed_unit_id,e.retry_unit_id]);proofEdges=new Set();paintProof();drawEdges();
 const back=el('button','← All retry cases','relation-button');back.onclick=explainMeasurement;
 body.append(back,el('p',e.payload_changed===null?'Payload change unknown':e.payload_changed?'Dispatch payload changed':'Dispatch payload unchanged'),
  el('h3','Earlier attempt'),sourceButton(e.failed_unit_id),el('h3','Recorded retry'),sourceButton(e.retry_unit_id));
 const raw=el('details');raw.append(el('summary','Saved retry record'),el('pre',JSON.stringify(e,null,2)));body.append(raw);
 const anchor=layout.byId.get(e.failed_unit_id);if(anchor)$('#map-viewport').scrollTo({top:Math.max(0,anchor.y*zoom-50),left:0,behavior:'instant'});
 $('#selection-count').textContent='Measured retry · all '+layout.nodes.length+' cards retained';
}
function measuredValue(){const finding=CustomMonitorEvidence.status(receipt.explanation);if(finding)return finding;const v=receipt.measurement.value;if(v===null)return 'Unavailable';return receipt.explanation.unit==='fraction'?(v*100).toFixed(1)+'%':Number(v.toFixed(4)).toLocaleString();}
function prepareMeasurement(){proofNodes=new Set();proofEdges=new Set();anchorStatus=new Map();$('#measurement-context').hidden=!receipt&&!strategyReceipt&&!revisitReceipt;
 if(revisitReceipt){$('#measurement-label').textContent='Revisit patterns · saved attempt pair';$('#measurement-value').textContent='Inputs & feedback';$('#measurement-meaning').textContent='Exact source and graph version';$('#explain-measurement').textContent='Compare attempts';return;}
 if(strategyReceipt){$('#measurement-label').textContent='Strategy profile · saved episode';$('#measurement-value').textContent='Evidence path';$('#measurement-meaning').textContent='Original source and observer · all rollout cards retained';$('#explain-measurement').textContent='Explain episode';return;}
 $('#explain-measurement').textContent='Explain value';if(!receipt)return;
 const r=receipt.explanation;$('#measurement-label').textContent=receipt.monitor.name+' · saved measurement';$('#measurement-value').textContent=measuredValue();
 $('#measurement-meaning').textContent=r.basis==='custom_code'&&r.feedback?.summary?r.feedback.summary:r.basis==='recorded_graph_matches'&&r.denominator!==null?`${r.numerator} of ${r.denominator} anchors matched · ${r.not_established} not established`:(r.status==='available'?'Exact saved source and observer':r.reason||'Measurement unavailable');
 for(const c of [...r.cases,...(r.unavailable_windows||[])])anchorStatus.set(c.anchor,c.status);
 if(r.unavailable_windows?.length)$('#measurement-meaning').textContent+=` · ${r.unavailable_windows.length} excluded (order unresolved)`;
}
function paintProof(){for(const[id,g]of cardElements){const status=anchorStatus.get(id);g.classList.toggle('proof-match',status==='recorded_match');g.classList.toggle('proof-unknown',['not_established','order_unavailable'].includes(status));g.classList.toggle('proof-node',proofNodes.has(id));g.querySelector('.metric-anchor-badge')?.remove();if(status){const matched=status==='recorded_match',gap=status==='order_unavailable',badge=svg('g',{class:'metric-anchor-badge'});badge.append(svg('rect',{x:202,y:10,width:72,height:23,rx:4,fill:matched?'#eaf4ef':'#f4efe5'}),svg('text',{x:238,y:26,'text-anchor':'middle','font-size':12,fill:matched?'#4f8a74':'#a18c63'},matched?'MATCH':gap?'GAP':'NOT EST.'),svg('title',{},matched?'Recorded metric match':gap?'Source order unresolved; excluded from denominator':'Metric relationship not established'));g.append(badge);}}}
function evidenceHeading(title){$('#map-inspector').hidden=false;$('.inspector-foot').hidden=true;$('#detail-title').textContent=title;const body=$('#detail-body');body.replaceChildren();body.scrollTop=0;$('#previous-unit').disabled=true;$('#next-unit').disabled=true;revealInspector();return body;}
function explainStrategy(){if(!strategyReceipt)return;
 const e=Object.values(strategyReceipt.families).flat().find(e=>e.id===params.get('episode'));
 const body=evidenceHeading('Strategy episode');if(!e){body.append(el('p','Episode not found in this saved profile.'));return;}
 selected=null;const refs=new Set([...e.evidence_ids,...e.stages.flatMap(s=>[s.ref,s.event_id,...(s.refs||[])]).filter(Boolean)]);proofNodes=new Set();
 for(const n of layout.nodes)if(refs.has(n.id)||refs.has(n.id.replace(/^event:/,''))||refs.has(n.properties.source?.event_id))proofNodes.add(n.id);
 proofEdges=new Set(layout.edges.filter(edge=>edge.family!=='sequence'&&proofNodes.has(edge.source)&&proofNodes.has(edge.display_target||edge.target)).map(edge=>edge.id));paintProof();drawEdges();
 const back=el('a','← Strategy profiles');back.href=params.get('return_to')?.startsWith('/?view=strategies')?params.get('return_to'):'/?view=strategies';body.append(back,el('h3',e.category==='unknown'?(e.selected_retry!==undefined?'Dispatch comparison unresolved':'Assessment window unresolved'):human(e.category)),el('p','Saved observations, not a causal explanation. Highlighted connections are recorded graph relationships; the episode phases add no new graph edges. Multiple adjustment witnesses are grouped, not asserted to be sequential.','evidence-note'));
 if(e.reason)body.append(el('p',e.reason));
 for(const s of e.stages){body.append(el('h3',s.label));if(s.text)body.append(el('p',s.text));if(s.ref||s.event_id)body.append(sourceButton(s.ref||s.event_id));for(const id of s.refs||[])body.append(sourceButton(id));}
 for(const a of e.adjustments||[]){body.append(el('h3','Recorded adjustment path'),el('p',a.work),sourceButton(a.declaration_unit_id),sourceButton(a.execution_unit_id));}
 const detail=el('details');detail.append(el('summary','All episode evidence'));const seen=new Set();for(const id of refs)detail.append(sourceButton(id,seen));body.append(detail);
 const exportLink=el('a','Download profile and original evidence');exportLink.href='/api/strategies/observations/'+encodeURIComponent(strategyReceipt.id)+'?download=1';body.append(exportLink);
 const anchor=layout.nodes.find(n=>n.id===e.stages[0]?.ref||n.id==='event:'+e.anchor||n.properties.source?.event_id===e.anchor);if(anchor)$('#map-viewport').scrollTo({top:Math.max(0,anchor.y*zoom-50),left:0,behavior:'smooth'});
 $('#selection-count').textContent='Episode evidence · all '+layout.nodes.length+' cards retained';
}
function showReviewNotes(){const body=evidenceHeading('Saved source review');body.append(el('p','These notes describe known questions and limitations in this saved observation. They are retained with the selected outputs; they do not establish independent annotation accuracy.','evidence-note'));
 for(const [i,note]of (payload.graph.semantic_context?.review_notes||[]).entries()){body.append(el('h3','Review '+(i+1)));if(note.review_scope)body.append(el('small',note.review_scope));body.append(el('p',note.text));for(const id of note.unit_ids||[])body.append(sourceButton(id));const evidence=el('details');evidence.append(el('summary','Review evidence'));for(const ref of note.evidence||[])evidence.append(el('pre',ref.text),el('small',ref.source_pointer||ref.event_id));body.append(evidence);}}
function appendFeedbackSearch(body,n){
 const r=n.properties.feedback_reference_search;if(!r)return;
 const box=el('details',undefined,'feedback-reference-search');box.append(el('summary',`Feedback considered · ${r.selected.length} of ${r.eligible_prior_responses} prior responses`));
 box.append(el('p',`${r.omitted_responses} responses outside this candidate set. Selection: ${human(r.selection_status)}.`,'evidence-note'),
  el('p','Candidates are search results. Only selected references create assessment connections; omitted responses are not negative evidence.'));
 const linked=new Set(r.linked_feedback_units||[]);
 for(const c of r.selected){const target=layout.byId.get(c.feedback_unit_id),b=el('button',`${c.feedback_event_id} · ${linked.has(c.feedback_unit_id)?'Selected reference':'Considered only'} · ${human(c.method)}`,'relation-button');b.dataset.feedbackCandidate=c.feedback_unit_id;
  if(target){b.append(el('small',short(displayText(target),180)));b.onclick=()=>select(target.id,true);}else{b.disabled=true;b.append(el('small','Source card unavailable'));}box.append(b);}
 box.append(el('small',r.limit));body.append(box);
}
function appendPriorWorkSearch(body,n){
 if(n.kind!=='unit'||n.properties.actor!=='agent'||!['semantic','action'].includes(n.properties.kind))return;
 const graphId=payload.graph.id,box=el('section',undefined,'prior-work-search'),button=el('button','Find earlier work'),content=el('div');
 box.append(button,content);body.append(box);
 button.onclick=async()=>{
  button.disabled=true;content.replaceChildren(el('p','Searching saved unit text…','prior-work-note'));
  const url='/api/work-candidates?'+new URLSearchParams({graph:graphId,unit:n.id});
  try{
   const result=priorWorkResults.get(url)||await api(url);if(!box.isConnected||payload.graph.id!==graphId)return;
   priorWorkResults.set(url,result);if(priorWorkResults.size>32)priorWorkResults.delete(priorWorkResults.keys().next().value);
   const c=result.counts;content.replaceChildren(el('h3','Earlier work candidates'),el('p','These are search results, not established relationships. Compare the source before linking work.','prior-work-note'));
   content.append(el('p',`${c.prepared_pairs} ready to compare · ${c.eligible_pairs} eligible earlier units${c.already_observed_pairs?' · '+c.already_observed_pairs+' reusable comparisons':''} · ${c.omitted_pairs} outside shortlist`,'prior-work-counts'));
   const methods=new Map(result.searches.flatMap(s=>s.selected).map(s=>[s.unit_id,s.method]));
   for(const p of result.requests.flatMap(r=>r.priors)){
    const card=el('article',undefined,'prior-work-candidate'),target=L.text(p.content?.work_target)||L.text(p.content?.target)||p.source.text,
     open=el('button',short(target,220),'relation-button');open.onclick=()=>{select(p.id,true);const back=el('button','← Back to '+label(n)+' comparison','relation-button');back.onclick=()=>{select(n.id,true);$('#detail-body .prior-work-search>button')?.click();};$('#detail-body').prepend(back);};
    const prior=layout.byId.get(p.id),origin=prior?label(prior):'Record '+p.source.event_id;
    card.append(el('small',origin+' · '+human(p.activity)+' · '+(methods.get(p.id)==='lexical_match'?'Text match':'Recent')),open);
    const source=el('details');source.append(el('summary','Read exact contribution'),el('pre',p.source.text));card.append(source);content.append(card);
   }
   if(c.unavailable_pairs)content.append(el('p',`${c.unavailable_pairs} shortlisted comparisons need work-target or source review. Other comparisons remain available.`,'prior-work-note'));
   if(c.deferred_pairs)content.append(el('p',`${c.deferred_pairs} shortlisted comparisons exceed this export's request or byte budget.`,'prior-work-note'));
   if(!c.eligible_pairs)content.append(el('p','No eligible earlier contributions in this actor, trajectory and context.'));
   if(c.requests){const download=el('a','Export prepared comparisons');download.href=url+'&download=1';content.append(download,el('p',`${c.requests} prepared request${c.requests===1?'':'s'} · ${(c.request_bytes/1024).toFixed(1)} KB · no model calls made`,'prior-work-note'));}
  }catch(error){if(box.isConnected)content.replaceChildren(el('p',error.message,'prior-work-note'));}
  finally{if(box.isConnected)button.disabled=false;}
 };
}
function appendHistoryEvidence(body,id){
 const status=v=>v===true?'Matches':v===false?'Does not match':'Unknown';
 const source=id=>{const button=sourceButton(id),node=layout.byId.get(id);if(button.tagName==='BUTTON'&&node)button.replaceChildren(document.createTextNode('Open '+(node.properties.id||id)+' · '+human(node.properties.tool||node.properties.kind)));return button;};
 for(const evidence of L.historyEvidence(payload.graph,id)){
  const row=evidence.observation.properties,query=evidence.query.properties,box=el('section',undefined,'history-evidence');
  box.append(el('h3','History evidence'),el('strong',query.name),el('p','Recorded comparison: '+status(row.value),'history-evidence-status'),el('p','Uses the latest matching lookup available before this action. Measures recorded values, not action success.','history-evidence-note'));
  box.append(el('p',query.quantifier==='any'?'Match rule: at least one selected item matches every configured attribute.':'Match rule: every selected item matches every configured attribute.','history-evidence-note'));
  if(row.value===null)box.append(el('p',human(row.reason),'evidence-note'));
  const labels={uses_latest_matching_lookup:'Latest matching lookup',uses_recorded_return:'Recorded return',supersedes_prior_lookup_for_query:'Earlier lookup superseded',invalidated_by_recorded_attempt:'Intervening attempt invalidates this query'};
  const sources=el('details');sources.append(el('summary','Lookup history and source records'));
  for(const type of Object.keys(labels))for(const edge of evidence.edges)if(edge.type===type){sources.append(el('small',labels[type]),source(edge.target));}
  box.append(sources);
  const facts=new Map(evidence.facts.map(n=>[n.id,n.properties]));
  for(const item of row.items){const group=el('details',undefined,'history-evidence-item');group.append(el('summary',JSON.stringify(item.target_value)+' · '+status(item.value)),el('small','Selected at '+item.target_pointer));
   if(!item.checks.length)group.append(el('p',human(item.reason),'evidence-note'));
   for(const check of item.checks){const fact=facts.get(check.fact_id),card=el('div',undefined,'history-evidence-check');card.append(el('code',check.pointer),el('p','Recorded: '+(fact?JSON.stringify(fact.value):'unavailable')+' · expected: '+JSON.stringify(check.expected)+' · '+status(check.value)));if(fact)card.append(source('event:'+fact.event_id));group.append(card);}box.append(group);
  }
  const provenance=el('details');provenance.append(el('summary','Exact query, facts and relationships'),el('pre',JSON.stringify({query,observation:row,edges:evidence.edges},null,2)));box.append(provenance);body.append(box);
 }
}
function appendStateEvidence(body,id){
 const evidence=L.stateEvidence(payload.graph,id);if(!evidence.checks.length&&!evidence.snapshots.length&&!evidence.views.length)return;
 const box=el('section',undefined,'work-state-evidence');box.append(el('h3','Recorded state and checks'));
 for(const node of evidence.checks){const q=node.properties;box.append(el('strong',q.criterion_id),el('p','Recorded result: '+q.result+' · criterion version: '+(q.criterion_version||'not recorded')),
  el('p','Input stability: '+(q.state_stable===true?'producer reports held fixed':q.state_stable===false?'producer reports not held fixed':'not established')),
  el('p','Required objects: '+(q.required_objects?.join(', ')||'not recorded')),el('small',q.basis||'Producer capture'));
  for(const event of [q.action_id,q.result_event_id])if(event&&!['event:'+event,event].includes(id))box.append(sourceButton(event));
 }
 for(const row of evidence.snapshots){const s=row.node.properties,details=el('details');details.append(el('summary','Object versions · '+row.objects.length+' objects · '+s.event_id));
  if(s.environment)details.append(el('p','Environment: '+s.environment));
  for(const object of row.objects)details.append(el('strong',object.properties.object),el('pre',object.properties.version));box.append(details);
 }
 if(evidence.views.length)box.append(el('p',evidence.views.length+' recorded file views; these do not establish a complete environment snapshot.'));
 const raw=el('details');raw.append(el('summary','Exact state evidence'),el('pre',JSON.stringify(evidence,null,2)));box.append(raw);body.append(box);
}
function sourceButton(id,seen=null,brief=false){const n=layout.byId.get(id)||layout.byId.get('event:'+id);if(n){if(seen?.has(n.id))return document.createDocumentFragment();seen?.add(n.id);const b=el('button',brief?'Open '+label(n)+' ↗':label(n)+' · '+short(n.summary,150),'relation-button');b.onclick=()=>select(n.id,true);return b;}
 const eventId=id.replace(/^event:/,''),units=layout.nodes.filter(u=>u.properties.source?.event_id===eventId);
 if(units.length){const group=el('div');for(const u of units)group.append(sourceButton(u.id,seen,brief));return group;}
 return el('small','Source reference: '+id);}
function explainMeasurement(){if(!receipt)return;params.delete('measure_case');params.delete('feedback_case');history.replaceState(history.state,'','/semantic-map?'+params);proofNodes=new Set();proofEdges=new Set();paintProof();drawEdges();const r=receipt.explanation,body=evidenceHeading('Measurement evidence');
 body.append(el('h3',receipt.monitor.name),el('p',measuredValue()+' · '+(r.coverage?.recorded_returns!=null?(receipt.measurement.value===1?'matching return':'matching returns'):r.basis==='recorded_graph_matches'?'recorded-match fraction':'saved observation'),'measurement-headline'));
 const definition=el('details');definition.append(el('summary','How this is measured'),el('p',r.definition));body.append(definition);
 if(r.definition_notice)body.append(el('p',r.definition_notice.message,'evidence-note'));
 if(r.coverage?.procedure_compared!=null&&r.denominator==null)body.append(el('p',`${r.coverage.procedure_compared} / ${r.coverage.recurrences} recurrences compared · ${r.coverage.procedure_unknown} unresolved`,'evidence-note'));
 if(r.basis==='recorded_graph_matches'){
  body.append(el('p',r.denominator===null?r.reason||'No completed query':`${r.numerator} recorded matches / ${r.denominator} starting units. ${r.not_established} have no recorded match; they are not established as behavioral negatives.`,'evidence-note'));
  const omitted=r.unavailable_windows||[];if(omitted.length)body.append(el('p',`${omitted.length} windows excluded because source order is unresolved. They do not count as matches or negatives.`,'evidence-note'));
  const buttons=el('div',undefined,'evidence-filters');const list=el('div');
  const fill=filter=>{list.replaceChildren();for(const c of [...r.cases,...omitted].filter(c=>filter==='all'||c.status===filter)){const n=layout.byId.get(c.anchor),b=el('button',(n?label(n):c.anchor)+' · '+(c.status==='order_unavailable'?'Order unresolved':c.matches.length?'Recorded match':'Not established'),'relation-button '+(c.matches.length?'matched-case':'unknown-case'));if(n)b.append(el('small',n.summary));b.onclick=()=>explainAnchor(c);list.append(b);}};
  for(const [name,filter]of [['All anchors','all'],['Matched','recorded_match'],['Not established','not_established'],...(omitted.length?[['Order unresolved','order_unavailable']]:[])]){const b=el('button',name);b.onclick=()=>fill(filter);buttons.append(b);}body.append(buttons,list);fill('all');
 }else{
  const custom=CustomMonitorEvidence.render(r,{nodeButton:id=>layout.byId.has(id)?sourceButton(id,null,true):null});if(custom)body.append(custom);
  if(r.denominator!==null)body.append(el('p',`${r.numerator} / ${r.denominator} eligible observations`,'evidence-note'));
  for(const ref of r.source_refs||[]){const source=receipt.run.sources?.find(s=>s.id===ref.source_id);let value=source?.data;for(const token of ref.pointer.split('/').slice(1))value=value?.[token.replaceAll('~1','/').replaceAll('~0','~')];body.append(el('h3','Recorded producer result'),el('small',(source?.name||ref.source_id)+' #'+ref.pointer),el('pre',JSON.stringify(value,null,2)??'Source value unavailable'));}
  for(const ref of r.source_values||[])body.append(el('h3','Recorded source value'),el('small',ref.pointer),el('pre',JSON.stringify(ref.value,null,2)));
  if(r.basis==='analysis_projection'){
   if(r.coverage?.error_followup){const c=r.coverage.error_followup;body.append(el('p',`${c.reported_again} pairs report errors again · ${c.no_reported_error} have no reported error in fully inspected later responses · ${c.followup_unknown} have unresolved follow-up. ${c.no_prior_error} pairs have no earlier error report; ${c.unknown} have unresolved earlier reports.`,'evidence-note'));}
   if(r.coverage?.strata){
    body.append(el('h3','First recheck outcomes'),el('p','All visible failures in this rollout, grouped by captured inputs. Outcome is classified separately from input changes. Counts are descriptive; unchanged inputs do not mean no revision.','evidence-note'));
    const table=el('table',undefined,'retry-outcome-table'),head=el('tr');for(const text of ['Captured inputs','Passed','Failed','Unknown'])head.append(el('th',text));table.append(head);
    for(const s of r.coverage.strata){const row=el('tr');for(const text of [inputResponseLabel(s.input_response),s.numerator,s.failed,s.unknown])row.append(el('td',String(text)));table.append(row);}body.append(table);
    if(r.coverage.input_group!=='all')body.append(el('p',`${r.coverage.excluded_known_other_inputs} known other-group failures excluded from this measure · ${r.coverage.unknown_input_membership} with unresolved group membership retained as unknown.`,'evidence-note'));
   }
   if(r.coverage?.recorded_returns!=null)body.append(el('p',`${r.coverage.recorded_returns} saved return candidates · ${r.coverage.returns_with_reference} with supported references · ${r.coverage.returns_without_established_reference} unestablished${r.coverage.disputed_return_references?' · '+r.coverage.disputed_return_references+' disputed':''} · ${r.coverage.unresolved_work_switches} unresolved work switches.`,'evidence-note'));
   if(r.opportunities!=null)body.append(el('p',`${r.opportunities} recorded opportunities · ${r.unknown} unresolved`,'evidence-note'));
   if(r.coverage?.recorded_actions!=null)body.append(el('p',`${r.coverage.represented_actions}/${r.coverage.recorded_actions} actions represented · ${r.coverage.identity_reviewed} identity reviews`,'evidence-note'));
   if(r.analysis_cases.some(c=>c.feedback_timing)){
    const nodes=new Map(payload.graph.nodes.map(n=>[n.id,n]));let opened=false;
    for(const [state,title]of [[true,'After further actions'],[false,'No intervening actions'],[null,'Timing unknown']]){
     const cases=r.analysis_cases.filter(c=>c.taken===state),group=el('details',null,'feedback-timing-group');group.append(el('summary',title+' · '+cases.length));
     if(cases.length&&!opened){group.open=true;opened=true;}
     for(const c of cases){const row=c.record,a=nodes.get('event:'+row.action_event_ids[0]),response=nodes.get('event:'+row.response_event_id),action=layout.nodes.find(n=>n.properties.kind==='action'&&(n.properties.source?.event_id||n.properties.id)===row.action_event_ids[0]);
      const b=el('button',short(action?RolloutStory.operation(action).text:a?.properties.text||c.label,140),'relation-button');
      b.append(el('small',short(RolloutStory.preview(response?.properties.text||'').text,180)),el('small',state===null?'No comparable saved assessment':state?'First saved assessment after '+row.intervening_dispatches+' other dispatch'+(row.intervening_dispatches===1?'':'es'):'0 dispatches between response and saved assessment'));
      b.onclick=()=>explainAnalysisCase(c);group.append(b);
     }
     body.append(group);
    }
   }else for(const c of r.analysis_cases){const reference=Array.isArray(c.record?.references),b=el('button',reference?c.record.target:c.label,'relation-button');b.append(el('small',c.work_conflicts?.length?'Disputed work identity':reference?(c.record.references.length?'Reference found':'Reference not established'):human(c.status)));b.onclick=()=>explainAnalysisCase(c);body.append(b);}
   if(r.plan_id){const a=el('a','Inspect the saved analysis plan');a.href='/api/investigation-plans/'+encodeURIComponent(r.plan_id);body.append(a);}
  }
  if(r.retry_observation){const o=r.retry_observation;body.append(el('h3','Failure → retry → result'),el('p',o.scope));
   for(const e of o.episodes){body.append(el('h3',e.failed_event_id+' → '+e.retry_event_id),el('p',(e.payload_changed===null?'Payload change unknown':e.payload_changed?'Dispatch payload changed':'Dispatch payload unchanged')+' · '+human(e.retry_outcome)),sourceButton(e.failed_unit_id),sourceButton(e.retry_unit_id));}
   body.append(el('p',o.failed_calls_without_selected_retry.length+' failed calls have no selected retry; these are not established as abandoned.'));}
  if(r.revision_observation){const o=r.revision_observation;body.append(el('h3','Failure → stated change → action → retry result'),el('p',o.episodes.length+' selected chains · '+o.episodes.filter(e=>!['completed','failed','partial'].includes(e.retry_outcome)).length+' unknown outcomes'));
   for(const e of o.episodes){const b=el('button',e.failed_event_id+' → '+e.retry_event_id+' · '+human(e.retry_outcome),'relation-button');b.append(el('small',[...new Set(e.changes.map(c=>human(c.change_kind||c.scope)))].join(' + ')));b.onclick=()=>explainRevisionEpisode(e);body.append(b);}
   body.append(el('p',o.excluded_failed_pairs.length+' failed pairs lack a complete selected declaration/enactment chain; they are outside this conditional rate.'));}
  if(r.reason&&r.basis!=='custom_code')body.append(el('p',r.reason));if(r.diagnostic)body.append(CustomMonitorEvidence.renderDiagnostic(r.diagnostic,{nodeButton:sourceButton,events:payload.run.events,excerpts:r.diagnostic_excerpts}));
  if(r.feedback_assessment){const f=r.feedback_assessment,n=f.counts;body.append(el('h3','Every response group'),el('p',`${n.assessed} assessed · ${n.not_observed} not observed · ${n.unknown} unknown. ${n.calls_without_bound_visible_response} calls have no bound visible response.`));
   for(const o of f.observations){const b=el('button',o.action_event_id+' · '+feedbackStatus(o),'relation-button');b.onclick=()=>explainFeedback(o);body.append(b);}}
  if(r.evidence_ids.length&&!r.diagnostic?.candidates&&!r.revision_observation&&!r.analysis_cases?.some(c=>c.feedback_timing)){body.append(el('h3','Recorded evidence'));const seen=new Set();for(const id of r.evidence_ids)body.append(sourceButton(id,seen));}
 }
 const fresh=receipt.freshness;if(!fresh.current_measurement||!fresh.current_source){body.append(el('p','You are inspecting an earlier saved measurement. Its original evidence is retained.','evidence-note'));if(fresh.latest_value_id&&fresh.latest_value_id!==receipt.measurement.id){const a=el('a','Open the newer measurement');a.href='/semantic-map?run='+encodeURIComponent(payload.run.id)+'&value='+encodeURIComponent(fresh.latest_value_id);body.append(a);}}
 const a=el('a','Download measurement and evidence');a.href='/api/monitoring/values/'+encodeURIComponent(receipt.measurement.id)+'?download=1';a.className='evidence-download';body.append(a);
 const details=el('details');details.append(el('summary','Definition, version and limits'),el('pre',JSON.stringify({definition:receipt.monitor,measurement_id:receipt.measurement.id,graph_id:payload.graph.id,input_id:receipt.measurement.input_id,engine:r.engine_version,limitations:r.limitations,integrity:receipt.integrity},null,2)));body.append(details);
}
function inputResponseLabel(value){return ({recorded_relevant_change:'Recorded relevant input change',unchanged_captured_inputs:'Unchanged captured inputs',changed_inputs_without_recorded_edit:'Changed inputs · edit unestablished',unresolved_inputs:'Input comparison unknown'})[value]||human(value);}
function appendPlanDeclaration(body,snapshot){
 const box=el('section',undefined,'declared-plan-evidence');box.append(el('h3','Issued task list'),el('p','Agent-reported status. This does not establish tool acceptance or verified completion.','evidence-note'));
 const list=el('ol');for(const item of snapshot.items){const row=el('li');row.append(el('strong',item.text),el('p',human(item.status)+(item.status_basis==='documented_profile_default'?' · tool-schema default':' · reported')));if(item.native_id)row.append(el('small','Task '+item.native_id));if(item.notes)row.append(el('p',item.notes));list.append(row);}box.append(list);
 if(!snapshot.items.length)box.append(el('p','Empty list explicitly issued.'));
 box.append(el('small',snapshot.profile+' · source '+snapshot.event_id));body.append(box);
}
function explainRevisit(){
 const r=revisitReceipt?.rows.find(r=>r.id===params.get('revisit_case'));if(!r)return;
 const origin=params.get('return_to'),back=origin&&(origin.startsWith('/?view=strategies')||origin.startsWith('/semantic-map?'))?origin:'/?view=strategies&lens=revisit';
 explainAnalysisCase({id:r.id,label:r.episode.target,status:'Saved same-work pair',node_ids:r.node_ids,edge_ids:r.edge_ids,repeated_work:r},back);
}
function explainAnalysisCase(c,backTo=null){rememberMeasuredCase('analysis',c);const body=evidenceHeading(c.feedback_timing?'Feedback assessment timing':c.label),back=el(backTo?'a':'button',backTo?(backTo.startsWith('/semantic-map?')?'← Work path':'← Behavior distributions'):'← All measured cases');if(backTo)back.href=backTo;else back.onclick=explainMeasurement;body.append(back,el('p',c.feedback_timing&&c.taken===false?'No intervening actions':human(c.status),'evidence-note'));selected=null;proofNodes=new Set(c.entry_scope?.node_ids||c.node_ids);proofEdges=new Set(c.entry_scope?.edge_ids||c.edge_ids);paintProof();drawEdges();
 if(c.record?.check_history)body.append(EvaluationEvidence.delivery(c.record,payload.run.events,id=>sourceButton('event:'+id)));
 if(c.feedback_timing){params.set('feedback_case',c.id);params.delete('focus_unit');history.replaceState(history.state,'','/semantic-map?'+params);for(const n of layout.nodes)if(proofNodes.has('event:'+n.properties.source?.event_id))proofNodes.add(n.id);paintProof();}
 if(c.work_conflicts?.length){
  const warning=el('section',null,'wn-scope-warning');warning.append(el('h3','Measurement excluded: conflicting work assignments'),el('p','These saved claims disagree. This retrospective check does not choose which is correct or imply that the agent knew about the conflict.'));
  for(const conflict of c.work_conflicts){const item=el('details');item.append(el('summary',(conflict.membership_same?'Grouped as the same work':'Grouped as separate work')+' · pair says '+relationLabel(conflict.relation)));if(conflict.membership_same)item.append(el('h4','Assigned work target'),el('p',conflict.bindings[0]?.subject?.label||'Unresolved target'));for(const [i,b]of conflict.bindings.entries()){item.append(el('h4',i?'Later contribution':'Earlier contribution'));if(!conflict.membership_same)item.append(el('p',b.subject?.label||'Unresolved target'));item.append(el('pre',b.source.text),sourceButton(b.unit_id));}warning.append(item);}
  body.append(warning);
 }
 if(c.work_structure){
  const w=c.work_structure,a=el('a','Open this work in Plans & attempts →'),q=new URLSearchParams({run:payload.run.id,observer:payload.graph.observer,graph:payload.graph.id,level:'plans'});
  q.set(w.profile==='declared_tree'?'work_focus':w.profile==='work_outline'?'outline_focus':'plan_step',w.focus);if(w.profile==='work_outline')q.set('outline_view','focus');a.href='/semantic-map?'+q;body.append(a,el('p','This is a recorded witness. Unobserved work is not inferred to be ignored, and a decision is not proof of execution.','evidence-note'));
 }
 if(c.plan_declaration||c.declared_plan_change){const plan=el('button','Inspect this case in the plan map','relation-button');plan.onclick=()=>{params.set('plan_case',c.id);params.delete('plan_through');showPlanLevel();};body.append(plan);}
 const visitId=c.work_visit_id||c.work_visit?.id;
 if(visitId){const visit=el('button','Open work visit','relation-button');visit.onclick=()=>{params.set('work_visit',visitId);if(c.recurrence_order)params.set('recurrence_order',c.recurrence_order);else params.delete('recurrence_order');workNavigation=null;workRequest=null;showWorkLevel();};body.append(visit);}
 if(c.entry_scope){const s=c.entry_scope;body.append(el('h3','At work-switch entry'),el('p','This switch is measured at the first contribution of the visit. Later work remains in the full map but is excluded from the highlighted decision evidence. Work-identity annotations may still be retrospective.','evidence-note'),sourceButton(s.entry_unit_id),el('pre',s.cutoff.text));
  if(!s.order_known)body.append(el('p','Recorded execution order is unresolved.','evidence-note'));
  const earlier=el('details');earlier.append(el('summary','Earlier work witnesses'));for(const id of s.node_ids)if(id!==s.entry_unit_id)earlier.append(sourceButton(id));body.append(earlier);
 }else if(c.plan_declaration){if(c.initial_item)body.append(el('h3','Entry in the initial captured list'),el('p',c.initial_item.text),el('p','Recorded status: '+human(c.initial_item.status)+'. This does not establish when the agent formed its plan or completed the work.','evidence-note'));appendPlanDeclaration(body,c.plan_declaration);body.append(sourceButton(c.plan_declaration.event_id));}
 else if(c.declared_plan_change){const r=c.declared_plan_change;body.append(el('h3',r.before.text),el('p','Previously reported complete → '+(r.after?human(r.after.status):'unresolved'),'evidence-note'),el('p',r.reason?human(r.reason)+'. This case is excluded from the decidable denominator.':(r.identity==='native_id'?'Unique native task ID with unchanged text':'Unique exact item text')+' retained in adjacent lists. This measures the report, not actual work completion.'));
  for(const id of r.event_ids){for(const row of L.declaredPlans(payload.graph,'event:'+id))appendPlanDeclaration(body,row.snapshot);body.append(sourceButton(id));}
 }
 else if(c.repeated_work){
  const r=c.repeated_work,d=r.dispatch,e=r.episode;
  body.append(el('h3','Recorded inputs: '+(r.inputs_changed===null?'comparison unresolved':human(d.status))),el('p',d.basis==='recorded_fields'?'Tool names and native arguments.':d.basis==='recorded_text'?'Full recorded action text; native arguments unavailable.':'Comparable input records are unavailable.','field-note'));
  if(r.input_reasons.length)body.append(el('p',r.input_reasons.join(' · '),'evidence-note'));
  for(const change of d.changes){const box=el('details');box.append(el('summary',change.path||'Recorded input'),el('h4','Earlier'),el('pre',change.before.present?change.before.preview:'Not captured'),el('h4','Later'),el('pre',change.after.present?change.after.preview:'Not captured'));if(change.before.truncated||change.after.truncated)box.append(el('p','Preview shortened. Open the action below for the full record.'));body.append(box);}
  body.append(el('h3','Feedback: '+human(r.feedback.status)));if(r.feedback.reasons.length)body.append(el('p',r.feedback.reasons.join(' · '),'evidence-note'));
  body.append(el('p','Matching records can follow changes to files, state or prerequisites.','field-note'));
  const excerpt=(title,id)=>{const n=payload.graph.nodes.find(n=>n.id===id);body.append(el('h4',title),el('pre',short(n?.properties?.text||n?.properties?.source?.text||'Source text unavailable',600)),sourceButton(id));};
  excerpt('Earlier attempt',r.previous_node_id);for(const id of r.feedback.previous.node_ids)excerpt('Earlier feedback',id);
  if(e.intervening.length){const context=el('details');context.append(el('summary',e.intervening.length+' intervening operation'+(e.intervening.length===1?'':'s')));for(const row of e.intervening)context.append(sourceButton(row.unit_id||'event:'+row.event_id));body.append(context);}
  if(e.assessment_unit_ids.length){body.append(el('h4','Saved assessment before the revisit'));for(const id of e.assessment_unit_ids)body.append(sourceButton(id));}
  excerpt('Later attempt',r.current_node_id);for(const id of r.feedback.current.node_ids)excerpt('Later feedback',id);
 }
 else if(c.episode){const e=c.episode;body.append(el('p',e.interpretation));const open=(id,text)=>{const b=sourceButton(id,null,true);if(b.tagName==='BUTTON')b.textContent=text;else b.prepend(el('small',text));return b;};WorkReview.renderReason(body,c.adaptation?.stated_reason,open);WorkReview.renderErrorFollowup(body,c.adaptation?.error_followup,open);for(const card of e.cards){body.append(el('h3',card.role),el('p',short(card.label,400)),sourceButton(card.unit_id));}}
 else if(c.feedback_timing){
  const r=c.record,byId=new Map(payload.graph.nodes.map(n=>[n.id,n]));
  const excerpt=(heading,id)=>{const n=byId.get(id),raw=n?.properties.source?.text||n?.properties.text,section=el('section',null,'feedback-timing-source');section.append(el('h3',heading));
   if(raw){const cleaned=raw.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'');section.append(el(n.properties.kind==='semantic'?'p':'pre',short(n.properties.kind==='feedback'?RolloutStory.preview(cleaned).text:cleaned.replace(/^Running command:\s*/,''),700)));}
   section.append(sourceButton(id,null,true));body.append(section);
  };
  for(const id of r.action_event_ids)excerpt('Original action','event:'+id);
  excerpt('Returned feedback',r.response_unit_id||'event:'+r.response_event_id);
  if(r.intervening_action_event_ids.length){body.append(el('h3',r.intervening_action_event_ids.length+' actions recorded before the assessment'));for(const [i,id]of r.intervening_action_event_ids.entries())excerpt('Intervening action '+(i+1),'event:'+id);}
  if(r.assessment_unit_id){excerpt('Earliest eligible saved assessment',r.assessment_unit_id);body.append(el('p',r.intervening_dispatches===null?'Dispatch order is unresolved.':r.intervening_dispatches+' recorded intervening dispatch'+(r.intervening_dispatches===1?'':'es')+'.','evidence-note'));}
  if(r.parallel_groups.length)body.append(el('p','Parallel dispatches are counted individually; their mutual execution order is unknown.','evidence-note'));
  if(r.unknown_reasons.length)body.append(el('p',r.unknown_reasons.map(human).join(' · '),'evidence-note'));
  body.append(el('p',(r.assessment_unit_id?'Timing uses the earliest supported saved link. Earlier unannotated assessment may exist.':'No supported assessment link is saved for this response.')+' Missing links do not establish ignored feedback.','evidence-note'));
 }
 else if(c.history_evidence){appendHistoryEvidence(body,'event:'+c.record.action_id);body.append(sourceButton('event:'+c.record.action_id));}
 else if(c.record?.references){
  const row=c.record;
  body.append(el('p',row.work_conflicts?.length?'Saved reference links remain visible, but their work identity is disputed and excluded from this measure.':row.references.length?'Recorded references during this returned visit. Several links count as one matching return.':'No matching saved reference in this return. This does not establish that the behavior was absent.','evidence-note'));
  for(const link of row.references){const item=el('section');item.append(el('h3',link.label),el('small',link.relation_type),el('h4','Contribution during the return'),sourceButton(link.source_unit_id),el('h4','Earlier referent'),sourceButton(link.target_node_id));for(const id of link.node_ids)if(![link.source_unit_id,link.target_node_id].includes(id))item.append(el('h4','Recorded feedback origin'),sourceButton(id));body.append(item);}
  const proof=el('details');proof.append(el('summary','Return and reference witnesses'));for(const id of row.node_ids)proof.append(sourceButton(id));body.append(proof);
 }
 else if(c.next_check){
  const r=c.record,section=el('section',undefined,'recovery-window');
  section.append(el('h3','Failed criterion: '+r.criterion_id),el('p','Definition '+short(r.criterion_version||'not captured',40)+' · inputs: '+(r.required_objects.join(', ')||'not captured'),'evidence-note'),sourceButton('event:'+r.failure_action_id),sourceButton('event:'+r.failure_result_event_id));
  section.append(el('h3',inputResponseLabel(r.input_response)),el('p','First recorded same-criterion recheck only. Later successes do not change this result.','evidence-note'));
  if(!r.attempts.length)section.append(el('p','No subsequent same-criterion check is recorded.'));
  for(const a of r.attempts){
   section.append(el('h3','Recorded recheck result: '+human(a.result)),el('p',a.comparable?'Comparable criterion version, scope, environment and captured stability.':'Comparability unestablished: '+a.issues.map(human).join(' · '),'evidence-note'));
   for(const change of a.changes)section.append(el('p','Recorded edit retained in inputs: '+change.changed_inputs.join(', ')),sourceButton('event:'+change.action_id),sourceButton('event:'+change.result_event_id));
   section.append(sourceButton('event:'+a.action_id));if(a.result_event_id)section.append(sourceButton('event:'+a.result_event_id));
  }
  if(r.unknown_reasons.length)section.append(el('p','Unknown: '+r.unknown_reasons.map(human).join(' · '),'evidence-note'));
  section.append(el('p',r.feedback_reference_edge_ids.length?'An existing feedback reference precedes this first recheck.':'Feedback use is unestablished from saved references.','evidence-note'),el('p','Captured input changes do not establish a semantic revision or its causal effect.','evidence-note'));body.append(section);
 }
 else if(c.recovery_window){
  const r=c.record,section=el('section',undefined,'recovery-window');
  section.append(el('h3','Failed criterion: '+r.criterion_id),el('p','Definition '+short(r.criterion_version||'not captured',40)+' · inputs: '+(r.required_objects.join(', ')||'not captured'),'evidence-note'),sourceButton('event:'+r.failure_action_id),sourceButton('event:'+r.failure_result_event_id));
  section.append(el('p',r.value===true?'Comparable passing check found after a recorded input change.':r.window_closed?'Three-check window observed.':'Window incomplete: '+r.attempts.length+' of 3 recorded follow-up checks.','evidence-note'));
  for(const [i,a]of r.attempts.entries()){
   const row=el('div',undefined,'recovery-attempt');row.append(el('h3','Follow-up '+(i+1)+' · '+human(a.result)),el('p',a.comparable?'Same criterion version, input scope and environment; stable inputs captured.':'Comparison unavailable: '+a.issues.map(human).join(', '),'evidence-note'));
   for(const change of a.changes){row.append(el('p','Recorded change retained in these inputs: '+change.changed_inputs.join(', ')),sourceButton('event:'+change.action_id),sourceButton('event:'+change.result_event_id));}
   row.append(sourceButton('event:'+a.action_id));if(a.result_event_id)row.append(sourceButton('event:'+a.result_event_id));
   if(a.issues.length)row.append(el('p',a.issues.map(human).join(' · '),'evidence-note'));section.append(row);
  }
  if(r.unknown_reasons.length)section.append(el('h3','Why this remains unknown'),el('p',r.unknown_reasons.map(human).join(' · ')));
  section.append(el('p',r.feedback_reference_edge_ids.length?'An existing feedback reference is recorded before the selected recheck.':'Feedback reference is unestablished; absence of a link does not show that feedback was ignored.','evidence-note'));
  body.append(section);
 }
 else if(!c.work_conflicts?.length){const seen=new Set();for(const id of c.node_ids)body.append(sourceButton(id,seen));const d=el('details');d.append(el('summary','Recorded state, check and result'),el('pre',JSON.stringify(c.record,null,2)));body.append(d);}
 const anchor=layout.byId.get(c.entry_scope?.entry_unit_id)||layout.byId.get(c.episode?.current_unit_id)||layout.byId.get(c.node_ids[0])||layout.nodes.find(n=>c.node_ids.includes('event:'+n.properties.source?.event_id));
 if(anchor)requestAnimationFrame(()=>{if(c.feedback_timing){$('#map-workbench').scrollIntoView({block:'start',behavior:'instant'});sizeViewport();fit();}$('#map-viewport').scrollTo({top:Math.max(0,anchor.y*zoom-50),left:0,behavior:'instant'});updatePosition();});$('#selection-count').textContent='Measured episode · all '+layout.nodes.length+' cards retained';
}
function feedbackStatus(o){return o.value===1?'Assessed':o.value===0?'Not observed':'Unknown';}
function explainRevisionEpisode(e){rememberMeasuredCase('revision',e);const body=evidenceHeading(e.failed_event_id+' → '+e.retry_event_id+' · '+human(e.retry_outcome));selected=null;proofNodes=new Set();
 for(const id of e.evidence_ids){for(const n of layout.nodes)if(n.id===id||n.id==='event:'+id||n.properties.source?.event_id===id)proofNodes.add(n.id);}
 proofEdges=new Set(layout.edges.filter(edge=>edge.family!=='sequence'&&proofNodes.has(edge.source)&&proofNodes.has(edge.display_target||edge.target)).map(edge=>edge.id));paintProof();drawEdges();
 const back=el('button','← All retry chains','relation-button');back.onclick=explainMeasurement;body.append(back,el('p','The highlighted path is a saved observation. An attempted change can fail; operation completion is not verified task recovery.','evidence-note'),el('h3','Earlier failed operation'),sourceButton(e.failed_unit_id));
 for(const c of e.changes){body.append(el('h3',c.change_kind?'Stated '+human(c.change_kind):human(c.scope)));if(c.work)body.append(el('p',c.work));body.append(sourceButton(c.declaration_unit_id),el('h3','Matching dispatched attempt'),sourceButton(c.execution_unit_id));}
 body.append(el('h3','Next same-work attempt · '+human(e.retry_outcome)),sourceButton(e.retry_unit_id),el('h3','Returned evidence'));
 const seen=new Set();for(const id of e.evidence_ids.filter(id=>!layout.byId.has(id)))body.append(sourceButton(id,seen));
 const detail=el('details');detail.append(el('summary','Saved decisions and source identities'),el('pre',JSON.stringify(e,null,2)));body.append(detail);
 const anchor=layout.byId.get(e.failed_unit_id);if(anchor)$('#map-viewport').scrollTo({top:Math.max(0,anchor.y*zoom-50),left:0,behavior:'smooth'});$('#selection-count').textContent='Retry evidence · all '+layout.nodes.length+' cards retained';
}
function explainFeedback(o){rememberMeasuredCase('feedback',o);const body=evidenceHeading('Feedback assessment · '+feedbackStatus(o));selected=null;proofNodes=new Set([o.action_event_id,...o.response_event_ids,...(o.assessment_event_id?[o.assessment_event_id]:[])].map(id=>'event:'+id));proofEdges=new Set(payload.graph.edges.filter(e=>e.type==='assesses_response_group'&&e.properties.request_hash===o.request_hash).map(e=>e.id));paintProof();drawEdges();
 const back=el('button','← All response groups','relation-button');back.onclick=explainMeasurement;body.append(back,el('h3','Dispatched action'),sourceButton('event:'+o.action_event_id),el('h3','Bound feedback'));for(const id of o.response_event_ids)body.append(sourceButton('event:'+id));
 if(o.reason)body.append(el('p',o.reason,'evidence-note'));if(o.value===0)body.append(el('p','No expressed assessment was observed before the next dispatch. This does not establish lack of comprehension.','evidence-note'));
 body.append(el('h3',o.assessment_event_id?'Selected assessment expression':'Agent expressions in this window'));for(const id of o.assessment_event_id?[o.assessment_event_id]:o.expression_event_ids)body.append(sourceButton('event:'+id));if(!o.expression_event_ids.length)body.append(el('p','No recorded agent prose in this window.'));
 const detail=el('details');detail.append(el('summary','Window and saved decision'),el('pre',JSON.stringify(o,null,2)));body.append(detail);
 const anchor=layout.byId.get('event:'+o.action_event_id);if(anchor)$('#map-viewport').scrollTo({top:Math.max(0,anchor.y*zoom-50),left:0,behavior:'smooth'});$('#selection-count').textContent='Feedback evidence · all '+layout.nodes.length+' cards retained';
}
function explainAnchor(c){rememberMeasuredCase('anchor',c);const body=evidenceHeading(c.status==='order_unavailable'?'Source order unresolved':c.matches.length?'Recorded match':'Not established'),anchor=layout.byId.get(c.anchor);selected=null;proofNodes=new Set([c.anchor]);proofEdges=new Set();
 for(const m of c.matches){m.node_ids.forEach(id=>proofNodes.add(id));m.edge_ids.forEach(id=>proofEdges.add(id));}paintProof();drawEdges();
 const back=el('button','← All measurement anchors','relation-button');back.onclick=explainMeasurement;body.append(back,el('h3','Starting activity'),sourceButton(c.anchor));
 if(c.order_blocker){body.append(el('p','Window stopped: '+human(c.order_blocker.reason)+'. '+(c.matches.length?'The earlier recorded match is retained.':'Excluded from the denominator.'),'evidence-note'));for(const id of [c.order_blocker.from_unit,c.order_blocker.to_unit])if(id&&layout.byId.has(id))body.append(sourceButton(id));}
 else if(!c.matches.length)body.append(el('p','No saved relationship path met this rule in the inspected window. Incomplete annotations do not establish that the behavior was absent.','evidence-note'));
 for(const [i,m]of c.matches.entries()){
  body.append(el('h3','Witness '+(i+1)));for(const id of m.edge_ids){const e=payload.graph.edges.find(e=>e.id===id);const from=layout.byId.get(e.source),to=layout.byId.get(e.target);if(from&&to){const b=el('button',label(from)+' → '+relationLabel(e.type)+' → '+label(to),'relation-button');b.title=e.type;b.onclick=()=>inspectEdge(e);body.append(b);}}
 }
 const window=el('details');window.append(el('summary',(c.window_size??c.inspected_window.length)+' later agent units inspected (limit '+(c.requested_window??receipt.monitor.requirement.within_units)+')'));for(const id of c.inspected_window)window.append(sourceButton(id));body.append(window);
 if(anchor)$('#map-viewport').scrollTo({top:Math.max(0,anchor.y*zoom-50),left:0,behavior:'smooth'});$('#selection-count').textContent='Measurement witness · all '+layout.nodes.length+' cards retained';
}
function renderMini(){const mini=$('#minimap svg');mini.replaceChildren();mini.setAttribute('viewBox','0 0 '+layout.height+' 36');mini.setAttribute('preserveAspectRatio','none');for(const n of layout.nodes)mini.append(svg('rect',{x:n.y,y:2+n.lane*11,width:Math.max(12,n.height),height:8,fill:L.cardStyle(n).color,rx:1}));}
function updatePosition(){if(!layout)return;const v=$('#map-viewport'),height=layout.height*zoom;$('.lane-headings').style.transform=`translateX(${-v.scrollLeft}px)`;$('#mini-window').style.left=100*v.scrollTop/height+'%';$('#mini-window').style.width=Math.min(100,100*v.clientHeight/height)+'%';$('#minimap').setAttribute('aria-valuenow',Math.round(100*v.scrollTop/Math.max(1,height-v.clientHeight)));const shown=layout.nodes.filter(n=>n.y*zoom+n.height*zoom>=v.scrollTop&&n.y*zoom<=v.scrollTop+v.clientHeight);$('#map-position').textContent=shown.length?'Viewing '+(layout.nodes.indexOf(shown[0])+1)+'–'+(layout.nodes.indexOf(shown.at(-1))+1)+' of '+layout.nodes.length+' cards':'All '+layout.nodes.length+' cards loaded';}
function jumpMini(e){if(!layout)return;const box=$('#minimap').getBoundingClientRect();$('#map-viewport').scrollTop=(e.clientX-box.left)/box.width*layout.height*zoom-$('#map-viewport').clientHeight/2;}
$('#minimap').onpointerdown=e=>{jumpMini(e);$('#minimap').setPointerCapture(e.pointerId);};$('#minimap').onpointermove=e=>{if(e.buttons)jumpMini(e);};$('#minimap').onkeydown=e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();$('#map-viewport').scrollTop+=(e.key==='ArrowRight'?1:-1)*$('#map-viewport').clientHeight;}};
const compactMap=matchMedia('(max-width:650px)');compactMap.addEventListener('change',e=>{$('#evidence-guide-shell').open=!e.matches;});$('#evidence-guide-shell').addEventListener('toggle',()=>{sizeViewport();fit();});
$('#map-viewport').onscroll=updatePosition;let drag;
const viewport=$('#map-viewport');
viewport.addEventListener('wheel',event=>{
 if(!layout)return;
 if(event.ctrlKey||event.metaKey){event.preventDefault();const box=viewport.getBoundingClientRect(),old=zoom,x=event.clientX-box.left,y=event.clientY-box.top,left=viewport.scrollLeft,top=viewport.scrollTop;manualZoom(zoom*Math.exp(-event.deltaY*.002));const anchor=L.zoomAnchor(old,zoom,left,top,x,y);viewport.scrollTo(anchor.left,anchor.top);}
 else {event.preventDefault();const factor=event.deltaMode===1?18:event.deltaMode===2?viewport.clientHeight:1;viewport.scrollBy(event.shiftKey?event.deltaY*factor:event.deltaX*factor,event.shiftKey?0:event.deltaY*factor);}
},{passive:false});
viewport.addEventListener('keydown',event=>{if(event.target!==viewport)return;const distance={ArrowDown:90,ArrowUp:-90,PageDown:viewport.clientHeight*.85,PageUp:-viewport.clientHeight*.85}[event.key];if(distance){event.preventDefault();viewport.scrollTop+=distance;}if(event.key==='Home'||event.key==='End'){event.preventDefault();viewport.scrollTop=event.key==='Home'?0:viewport.scrollHeight;}});
$('#map-start').onclick=()=>{viewport.scrollTo({top:0,left:0});viewport.focus({preventScroll:true});};
$('#map-end').onclick=()=>{viewport.scrollTop=viewport.scrollHeight;viewport.focus({preventScroll:true});};
$('#map-page-up').onclick=()=>{viewport.scrollBy(0,-viewport.clientHeight*.85);viewport.focus({preventScroll:true});};
$('#map-page-down').onclick=()=>{viewport.scrollBy(0,viewport.clientHeight*.85);viewport.focus({preventScroll:true});};
$('#map-jump-form').onsubmit=event=>{event.preventDefault();const n=layout?.nodes.find(n=>n.ordinal===Number($('#map-jump').value));if(n)select(n.id,true,'instant');};
$('#connection-view').value=connectionMode;$('#connection-view').onchange=()=>{const mode=$('#connection-view').value;if(activeInspection)$('#close-detail').click();connectionMode=mode;params.set('links',connectionMode);history.replaceState(history.state,'','/semantic-map?'+params);drawEdges();};

$('#map-viewport').onpointerdown=e=>{if(e.target.closest('.unit-card,.edge-group[role=button]'))return;drag={x:e.clientX,y:e.clientY,left:$('#map-viewport').scrollLeft,top:$('#map-viewport').scrollTop};$('#map-viewport').setPointerCapture(e.pointerId);$('#map-viewport').classList.add('dragging');};
$('#map-viewport').onpointermove=e=>{if(!drag)return;$('#map-viewport').scrollTo(drag.left+drag.x-e.clientX,drag.top+drag.y-e.clientY);};$('#map-viewport').onpointerup=$('#map-viewport').onpointercancel=()=>{drag=null;$('#map-viewport').classList.remove('dragging');};
$('#map-search').oninput=()=>{const q=$('#map-search').value.trim().toLowerCase();searchMatches=layout.nodes.filter(n=>q&&(n.summary+' '+n.target+' '+n.activity+' '+L.text(n.properties.source?.text)).toLowerCase().includes(q)).map(n=>n.id);searchIndex=-1;for(const[id,g]of cardElements)g.classList.toggle('search-match',searchMatches.includes(id));$('#selection-count').textContent=q?searchMatches.length+' matching cards':'Select a card or a connection';};
$('#next-match').onclick=()=>{if(searchMatches.length){searchIndex=(searchIndex+1)%searchMatches.length;select(searchMatches[searchIndex],true);}};$('#map-search').onkeydown=e=>{if(e.key==='Enter')$('#next-match').click();};
$('#fit-map').onclick=()=>{zoomMode='fit';fit();};$('#readable-map').onclick=()=>{zoomMode='readable';fit();};const manualZoom=value=>{zoomMode='manual';$('#readable-map').setAttribute('aria-pressed','false');$('#fit-map').setAttribute('aria-pressed','false');scale(value);};$('#zoom-in').onclick=()=>manualZoom(zoom*1.2);$('#zoom-out').onclick=()=>manualZoom(zoom/1.2);$('#close-detail').onclick=()=>{clearInspection();$('#map-inspector').hidden=true;selected=null;selectedEdge=null;params.delete('guide');activeEvidenceGuide=null;params.delete('focus_unit');params.delete('focus_link');params.delete('link_from');connectionOrigin=null;params.delete('feedback_case');history.replaceState(history.state,'','/semantic-map?'+params);drawEdges();$('#selection-count').textContent='Select a card or a connection';sizeViewport();fit();};
function adjacent(delta){const index=layout.nodes.findIndex(n=>n.id===selected);select(layout.nodes[Math.max(0,Math.min(layout.nodes.length-1,index+delta))].id,true);}
function clearReceipt(keepTraining=false){if(!keepTraining)for(const key of ['schema','producer','experiment','id'])params.delete('training_'+key);document.querySelector('#investigation-return')?.remove();for(const key of ['inspect','inspect_case','guide','focus_link','link_from','feedback_case','measure_case','value','profile','revisit','revisit_case','episode','work_episode','work_visit','graph','focus_unit','review_monitor','review_value','plan_through','plan_case','work_focus','plan_step','outline_focus','outline_view','story_query','story_filter','story_moment'])params.delete(key);}
$('#previous-unit').onclick=()=>adjacent(-1);$('#next-unit').onclick=()=>adjacent(1);$('#map-run').onchange=()=>{clearReceipt();load($('#map-run').value);};$('#map-observer').onchange=()=>{clearReceipt(true);load($('#map-run').value,$('#map-observer').value);};$('#export-graph').onclick=()=>{const a=el('a');a.href='/api/graphs/'+encodeURIComponent(payload.graph.id)+'?download=1';a.download='rollout-graph.json';a.click();};
$('#explain-measurement').onclick=()=>revisitReceipt?explainRevisit():strategyReceipt?explainStrategy():explainMeasurement();
$('#show-review-notes').onclick=showReviewNotes;
$('#card-content').value=cardContent;$('#card-content').onchange=()=>{cardContent=$('#card-content').value;params.set('card_text',cardContent);history.replaceState(history.state,'','/semantic-map?'+params);for(const n of layout.nodes){const g=cardElements.get(n.id),text=g?.querySelector('.card-content');if(text){text.replaceChildren();wrapText(text,displayText(n),15,51,3,29);}const foot=g?.querySelector('.unit-target');if(foot)foot.textContent=cardFoot(n);}};
let mapContextOrigin=null;
function openMapContext(field='map-run'){mapContextOrigin=document.activeElement;$('.map-settings').open=true;const d=$('#map-context-dialog');if(!d.open)d.showModal();$('#'+field).focus();}
$('#choose-map-context').onclick=()=>openMapContext();
$('#close-map-context').onclick=()=>$('#map-context-dialog').close();
$('#map-context-dialog').addEventListener('close',()=>{mapContextOrigin?.focus({preventScroll:true});sizeViewport();fit();});
$('#map-display-options').addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();e.currentTarget.open=false;e.currentTarget.querySelector('summary').focus();}});
document.addEventListener('pointerdown',e=>{const options=$('#map-display-options');if(options.open&&!options.contains(e.target))options.open=false;});
$('#focus-canvas').onclick=()=>setCanvasFocus(!document.body.classList.contains('canvas-focus'));$('#map-context').addEventListener('toggle',()=>{sizeViewport();fit();});$('.map-settings').addEventListener('toggle',()=>{sizeViewport();fit();});
$('#jump-moment').onchange=()=>{if($('#jump-moment').value)select($('#jump-moment').value,true);};window.addEventListener('resize',()=>{sizeViewport();fit();updatePosition();});
new ResizeObserver(()=>{if(!$('#unit-level-map').hidden){sizeViewport();fit();updatePosition();}}).observe($('.map-shell'));
let detailOpen=false;new MutationObserver(()=>{const open=!$('#map-inspector').hidden,wasOpen=detailOpen;detailOpen=open;requestAnimationFrame(()=>{sizeViewport();if(open&&!wasOpen&&innerWidth<1280)$('#map-inspector').scrollIntoView({block:'nearest'});});}).observe($('#map-inspector'),{attributes:true,attributeFilter:['hidden']});
document.addEventListener('keydown',event=>{if(document.querySelector('dialog[open]'))return;if(event.key==='Escape'&&$('#map-inspector').hidden&&document.body.classList.contains('canvas-focus'))setCanvasFocus(false);if(event.key==='Escape'&&!$('#map-inspector').hidden){const id=selected;$('#close-detail').click();if(id)cardElements.get(id)?.focus();}});
(async()=>{try{const catalog=await api('/api/graphs');if(!params.has('run')&&!params.has('experiment')&&window.TrainingContext){const scope=await TrainingContext.forNavigation();for(const key of ['experiment','environment'])if(scope[key])params.set(key,scope[key]);}const runs=new Map();for(const g of (window.TrainingContext?TrainingContext.graphsForScope(catalog.graphs,Object.fromEntries(params),params.get('run')):catalog.graphs)){const old=runs.get(g.run_id),rank=x=>x.coverage.semantic_relations!=='unavailable'?2:x.observer==='source'?1:0;if(!old||rank(g)>rank(old))runs.set(g.run_id,g);}const sorted=[...runs.values()].sort((a,b)=>(a.observer==='source')-(b.observer==='source'));$('#map-run').replaceChildren(...ChoiceLabels.choices(sorted.map(g=>({id:g.run_id,label:runLabel(g)})),{fallback:'Rollout',noun:'Rollout'}).map(ChoiceLabels.option));const id=params.get('run')||sorted[0]?.run_id;if(id)await load(id,params.get('observer'));else {$('#map-title').textContent='No rollouts in this run';throw Error('No rollout maps match this run and environment. Switch the training run or connect rollout data.');}}catch(e){$('#map-error').hidden=false;$('#map-error').textContent=e.message;}})();
