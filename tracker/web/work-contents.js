/* Work descriptions stay inside their source unit. Links never imply hierarchy. */
(()=>{
 'use strict';
 const modes={proposed:'Proposed',asserted:'Source claim',hypothetical:'Possibility'},
  names={purpose:'Intended purpose',before:'Stated order',condition:'Condition for',response_to:'In response to'};
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 async function load(graph,unitId,progress=false){
  const response=await fetch((progress?'/api/work-content-extractions?':'/api/work-mentions?')+new URLSearchParams({graph:graph.id,unit:unitId}));
  const data=await response.json();if(!response.ok)throw Error(data.error||'Work contents unavailable');return data;
 }
 function quote(ref,label='Source wording'){
  const d=el('details',null,'wc-quote');d.append(el('summary',label),el('blockquote',ref.text));return d;
 }
 function componentAudit(box,row){
  const c=row.component_checks;if(!c)return;
  const panel=el('details',null,'wc-component-audit'),labels=new Map(c.mentions.map(m=>[m.id,m.label]));
  const checkNames={faithful_single:'Selected as faithful',compound:'Bundled work',wrong_attribution_or_mode:'Attribution or modality mismatch',unsupported_meaning:'Meaning not supported',unresolved:'Unresolved',supported:'Selected as supported',reversed:'Opposite direction selected',wrong_endpoint:'Endpoint mismatch',not_expressed:'Relationship not expressed'};
  panel.append(el('summary','Automated component checks · experimental'),el('p',c.limit,'wc-note'),
   el('p',`${c.mentions.filter(m=>m.retained).length}/${c.mentions.length} descriptions and ${c.links.filter(l=>l.retained).length}/${c.links.length} relationships retained by these checks. Completeness selection: ${c.coverage_choice.replaceAll('_',' ')}. This is a model judgment; source review takes precedence.`,'wc-note'));
  for(const m of c.mentions){const item=el('div',null,'wc-component-row');item.append(el('strong',m.label),el('p',checkNames[m.choice]+' · '+(m.retained?'retained by check':'withheld by check')),quote(m.evidence));panel.append(item);}
  for(const l of c.links){const item=el('div',null,'wc-component-row');item.append(el('strong',(labels.get(l.source)||l.source)+' → '+(labels.get(l.target)||l.target)),el('p',(names[l.type]||l.type)+' · '+checkNames[l.choice]+' · '+(l.retained?'retained by check':!l.endpoints_retained?'withheld: an endpoint was not retained':'withheld by check')),quote(l.evidence));panel.append(item);}
  box.append(panel);
 }
 function render(box,data,unitId,openUnit){
  box.replaceChildren();const row=data.rows.find(r=>r.unit_id===unitId),head=el('div',null,'wc-heading');
  head.append(el('h3','Work in this contribution'));box.append(head);
  if(!row||row.status==='unobserved'){box.append(el('p','Work contents have not been annotated for this unit.','wc-note'));return;}
  if(openUnit){const b=el('button','Unit at record '+(row.event_index+1)+' ↗','wc-open-unit');b.onclick=()=>openUnit(unitId);head.append(b);}
  if(row.status!=='selected'){
   box.append(el('p',row.status==='withheld'?'The selected reading was withheld after source review. It is not used for map relationships.':row.status==='no_suitable_candidate'?'The proposed reading was rejected. Local work relationships remain unresolved.':'No local reading was resolved for this contribution.','wc-note'));
   if(row.review)box.append(el('p',row.review.reason,'wc-note'));
   if(row.source)box.append(quote(row.source,'Read this contribution'));componentAudit(box,row);return;
  }
  const reading=row.reading,labels=new Map(reading.mentions.map((m,i)=>[m.id,String.fromCharCode(65+i)]));
  box.append(el('p','Descriptions within one activity unit. Proposed work and source claims do not establish execution or success.','wc-note'));
  if(row.component_checks?.status==='partial')box.append(el('p','Partial reading: some proposed contents were withheld or completeness was not established. Missing work must not be interpreted as absent behavior.','wc-note'));
  const cards=el('div',null,'wc-cards');
  for(const mention of reading.mentions){
   const card=el('article',null,'wc-card wc-'+mention.mode),meta=el('div',null,'wc-card-meta');
   meta.append(el('b',labels.get(mention.id),'wc-letter'),el('span',modes[mention.mode]));
   const label=el('p');for(const [i,part]of mention.label.split(/`([^`]+)`/).entries())label.append(i%2?el('code',part):document.createTextNode(part));
   card.append(meta,label,quote(mention.evidence));cards.append(card);
  }
  if(reading.mentions.length)box.append(cards);else box.append(el('p',row.component_checks?.status==='partial'?'No proposed work description survived these checks; this does not establish that the contribution contains no work.':'The selected reading identifies no separately described work in this contribution.','wc-note'));
  if(reading.links.length){
   const links=el('div',null,'wc-links');links.setAttribute('aria-label','Relationships within this contribution');
   for(const link of reading.links){
    const a=reading.mentions.find(m=>m.id===link.source),b=reading.mentions.find(m=>m.id===link.target),line=el('details',null,'wc-link'),summary=el('summary');
    summary.append(el('b',labels.get(link.source)),el('span',names[link.type]+' →'),el('b',labels.get(link.target)));
    summary.setAttribute('aria-label',a.label+' · '+names[link.type]+' · '+b.label);
    line.append(summary,el('p',a.label+' → '+b.label),el('blockquote',link.evidence.text));links.append(line);
   }
   box.append(el('h4','Expressed relationships'),links);
  }
  const provenance=el('details',null,'wc-provenance');provenance.append(el('summary','Reading & coverage'),el('p',reading.reading),
   el('p',`${data.counts.published_units} of ${data.counts.observed_units} requested contributions have a published reading (${data.counts.selected_units} selected before review). This is not whole-rollout coverage.`),
   el('p','Proposed by '+data.provenance.producer+' · selected by '+data.provenance.selector+'. No work identity or parentage is inferred here.'));
  if(data.provenance.review)provenance.append(el('p','Source review by '+data.provenance.review.author+'. '+data.provenance.review.basis));
  componentAudit(box,row);
  box.append(provenance);
 }
 function append(host,graph,unitId,openUnit){
  const node=graph.nodes.find(n=>n.id===unitId),p=node?.properties;
  if(!graph.semantic_context?.work_mentions&&!(p?.kind==='semantic'&&p?.status==='selected'&&['agent','user'].includes(p?.actor)))return;
  const box=el('section',null,'work-contents');box.setAttribute('aria-label','Local work contents');box.append(el('p','Loading work contents…','wc-note'));host.append(box);
  let data=null,choice=null,stamp=null,busy=false,timer=null;
  const statuses={running:'Saved progress',complete:'Complete',budget_reached:'Budget limit reached',needs_review:'Review needed',retry_required:'Retry needed'};
  const time=value=>new Date(value).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  function paint(){
   if(!box.isConnected||!data)return;
   const opened=new Set([...box.querySelectorAll('details[open][data-key]')].map(n=>n.dataset.key));
   const entries=(data.extractions||[]).filter(r=>r.unit_id===unitId);
   if(choice===null){const wanted=new URLSearchParams(location.search).get('work_extraction');choice=entries.some(e=>e.id===wanted)?wanted:entries[0]?.id||'legacy';}
   if(choice==='legacy'&&entries.length&&!data.rows?.some(r=>r.unit_id===unitId&&r.status==='selected'))choice=entries[0].id;
   const entry=entries.find(e=>e.id===choice);
   if(!entry){render(box,data,unitId,openUnit);}
   else {
    box.replaceChildren();const head=el('div',null,'wc-heading');head.append(el('h3','Work in this contribution'),el('span',statuses[entry.status]||entry.status,'wc-status'));box.append(head);
    const v=entry.view,c=v.counts;
    box.append(el('p',`${c.contents} work items · ${c.inspected}/${c.features} attributes inspected · saved ${time(entry.updated_at)}`,'wc-note'));
    if(entry.status==='budget_reached')box.append(el('p','Resume the same extraction directory with a higher lifetime budget. Saved decisions are reused.','wc-note'));
    if(!c.contents)box.append(el('p',entry.stage==='contents'?'No content proposal has been saved yet.':'The generator returned no work contents. This does not establish that the unit contains no work.','wc-note'));
    const cards=el('div',null,'wc-cards'),contentCards=new Map(),labels=new Map(v.contents.map((item,i)=>[item.id,String.fromCharCode(65+i)]));
    for(const content of v.contents){
     const card=el('article',null,'wc-card wc-'+content.mode),meta=el('div',null,'wc-card-meta');
     card.tabIndex=-1;contentCards.set(content.id,card);
     meta.append(el('b',String.fromCharCode(65+v.contents.indexOf(content)),'wc-letter'),el('span',modes[content.mode]),el('span',content.kind));
     card.append(meta,el('p',content.expression.text.length>260?content.expression.text.slice(0,260)+'…':content.expression.text));
     const source=quote(content.expression);source.dataset.key=content.id+':source';card.append(source);
     const features=el('div',null,'wc-attachments');
     for(const f of content.features){
      const item=el('details',null,'wc-attachment'+(f.status==='unresolved'?' wc-uncertain':'')),summary=el('summary');
      item.dataset.key=content.id+':'+f.feature_id;
      summary.append(el('b',f.type.charAt(0).toUpperCase()+f.type.slice(1)),el('span',f.expression.text),el('small',f.status==='applies'?'Attached':'Unresolved'));
      item.append(summary,el('blockquote',f.expression.text));features.append(item);
     }
     if(content.features.length)card.append(features);
     cards.append(card);
    }
    box.append(cards);
    if(v.relations){
     const r=v.relations,c=r.counts,relationships=el('div',null,'wc-local-relations');
     relationships.append(el('h4','Local relationships'));
     if(!c)relationships.append(el('p','Relationship inspection has not started.','wc-note'));
     else{
      const checked=c.supported+c.unsupported+c.unresolved;
      relationships.append(el('p',`${c.supported} selected · ${c.unresolved} unresolved · ${checked}/${checked+c.pending} checks inspected`,'wc-note'));
      const words={purpose:'serves the aim',before:'comes before',condition:'is a condition for',response_to:'responds to'};
      for(const link of r.links.filter(row=>['supported','unresolved'].includes(row.status))){
       const item=el('details',null,'wc-link'+(link.status==='unresolved'?' wc-uncertain':''));item.dataset.key='relation:'+link.id;
       item.append(el('summary',`${labels.get(link.source)} → ${labels.get(link.target)} · ${words[link.type]}${link.status==='unresolved'?' · unresolved':''}`));
       const ends=el('div',null,'wc-relation-ends');
       for(const [id,role]of [[link.source,'From'],[link.target,'To']]){
        const content=v.contents.find(row=>row.id===id),button=el('button',`${role} ${labels.get(id)} · ${content.expression.text}`,'wc-open-unit');button.type='button';
        button.onclick=()=>{contentCards.forEach(card=>card.classList.remove('wc-focused'));const card=contentCards.get(id);card.classList.add('wc-focused');card.scrollIntoView({block:'nearest'});card.focus({preventScroll:true});};ends.append(button);
       }
       item.append(ends,el('blockquote',r.source.text));relationships.append(item);
      }
      if(!c.supported&&!c.unresolved)relationships.append(el('p',c.pending?'No links selected so far. Uninspected pairs remain pending.':'No links selected among these work items and the four inspected relationship types.','wc-note'));
     }
     box.insertBefore(relationships,cards);
    }
    if(c.pending)box.append(el('p',`${c.pending} attributes still await attachment decisions.`,'wc-note'));
    const coverage=el('details',null,'wc-provenance');coverage.dataset.key='coverage';coverage.append(el('summary','Extraction details'),
     el('p','Contents and their modes are generated interpretations. Attachments are model selections. Neither establishes execution or success.'));
    for(const f of v.features){const row=el('p');row.append(el('strong',f.type+' · '),document.createTextNode(f.expression.text+' · '+(f.status==='pending'?'Not inspected':f.status==='outside_inventory'?'No selected owner':f.status==='selected'?'Inspected':'Partly unresolved')));coverage.append(row);}
    const units=el('a','Read saved records with Python');units.href='/integration-guide#data-access';coverage.append(units);box.append(coverage);
   }
   const tools=el('div',null,'wc-tools'),refresh=el('button','Refresh','wc-open-unit');refresh.type='button';refresh.onclick=()=>poll(true);
   if(entries.length){
    const select=el('select');select.setAttribute('aria-label','Work extraction');
    entries.forEach((e,i)=>{const option=el('option',`${i===0?'Latest · ':''}${time(e.updated_at)} · ${statuses[e.status]||e.status}`);option.value=e.id;select.append(option);});
    if(data.rows?.some(r=>r.unit_id===unitId&&r.status==='selected')){const option=el('option','Saved map reading');option.value='legacy';select.append(option);}
    select.value=choice;select.onchange=()=>{choice=select.value;paint();};tools.append(select);
   }
   tools.append(refresh);box.append(tools);
   {
    const usage=el('details',null,'wc-provenance');usage.dataset.key='start';
    usage.append(el('summary',entries.length?'Run or resume with Python':'Extract with Python'),el('p','Configure the models, then run against the database serving this map. Replace study.sqlite with its path. Results appear here as they are saved.'));
    const setup=el('a','Model setup →');setup.href='/connections#model-section';usage.append(setup);
    const code=el('code',`from rilldex import Workspace\n\nworkspace = Workspace("study.sqlite")\nresult = workspace.extract_work_contents(\n    ${JSON.stringify(graph.id)},\n    ${JSON.stringify(unitId)},\n    "./content-pilot",\n    candidate_calls=4, decision_calls=12, input_bytes=100000,\n    relations=True,\n)`),pre=el('pre');pre.append(code);usage.append(pre,
     el('p','Use a separate directory for each unit. Resume the same directory to reuse saved responses; budgets are lifetime totals.'));
    box.append(usage);
   }
   for(const node of box.querySelectorAll('details[data-key]'))node.open=opened.has(node.dataset.key);
  }
  async function poll(force=false){
   if(!box.isConnected)return;
   if(busy)return;
   if(!force&&document.hidden){timer=setTimeout(poll,5000);return;}
   busy=true;clearTimeout(timer);
   try{
    const next=await load(graph,unitId,!!data);if(!box.isConnected)return;
    if(!data)data=next;else data.extractions=next.extractions;
    const nextStamp=JSON.stringify((data.extractions||[]).map(e=>[e.id,e.revision]));
    if(stamp!==nextStamp){stamp=nextStamp;paint();}
    box.querySelector('.wc-load-error')?.remove();
   }catch(error){if(box.isConnected){box.querySelector('.wc-load-error')?.remove();box.append(el('p',error.message,'wc-note wc-load-error'));}}
   finally{busy=false;if(box.isConnected)timer=setTimeout(poll,5000);}
  }
  poll(true);
 }
 function appendReferences(host,graph,refs,openUnit){
  const units=graph.semantic_context?.work_mentions?.packet?.units||[];
  for(const unit of units){const s=unit.source;
   if(refs.some(ref=>ref.event_id===s.event_id&&ref.start<s.end&&s.start<ref.end))append(host,graph,unit.unit_id,openUnit);
  }
 }
 window.WorkContents={append,appendReferences};
})();
