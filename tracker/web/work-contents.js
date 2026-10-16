/* Work descriptions stay inside their source unit. Links never imply hierarchy. */
(()=>{
 'use strict';
 const cache=new Map(),modes={proposed:'Proposed',asserted:'Source claim',hypothetical:'Possibility'},
  names={purpose:'Intended purpose',before:'Stated order',condition:'Condition for',response_to:'In response to'};
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 async function load(graph){
  if(!cache.has(graph.id)){
   const promise=fetch('/api/work-mentions?'+new URLSearchParams({graph:graph.id})).then(async response=>{
    const data=await response.json();if(!response.ok)throw Error(data.error||'Work contents unavailable');return data;
   }).catch(error=>{cache.delete(graph.id);throw error;});
   cache.set(graph.id,promise);if(cache.size>12)cache.delete(cache.keys().next().value);
  }
  return cache.get(graph.id);
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
  if(!row){box.append(el('p','Work contents have not been annotated for this unit.','wc-note'));return;}
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
  if(!graph.semantic_context?.work_mentions)return;
  const box=el('section',null,'work-contents');box.setAttribute('aria-label','Local work contents');box.append(el('p','Loading work contents…','wc-note'));host.append(box);
  load(graph).then(data=>{if(box.isConnected)render(box,data,unitId,openUnit);}).catch(error=>{if(box.isConnected)box.replaceChildren(el('p',error.message,'wc-note'));});
 }
 function appendReferences(host,graph,refs,openUnit){
  const units=graph.semantic_context?.work_mentions?.packet?.units||[];
  for(const unit of units){const s=unit.source;
   if(refs.some(ref=>ref.event_id===s.event_id&&ref.start<s.end&&s.start<ref.end))append(host,graph,unit.unit_id,openUnit);
  }
 }
 window.WorkContents={append,appendReferences};
})();
