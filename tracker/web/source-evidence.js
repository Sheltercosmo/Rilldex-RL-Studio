/* Source-bound retrieval; no inferred relations and no provider requests. */
(function(root){
 'use strict';
 function anchor(n){
  const p=n?.properties||{},s=p.source;
  if(s?.event_id&&Number.isInteger(s.start)&&Number.isInteger(s.end)&&s.end>s.start)return {event_id:s.event_id,start:s.start,end:s.end};
  // Python owns codepoint length. JavaScript string.length counts UTF-16 units.
  if(n?.kind==='event'&&p.id&&typeof p.text==='string'&&p.text.trim())return {event_id:p.id};
  return null;
 }
 function questions(text){
  return (text||'').split(/\r?\n/).map(s=>s.trim()).filter(Boolean).map((text,i)=>({id:'question-'+(i+1),text}));
 }
 function plan(graph,ref,text,questionText,strategy='source',cursor=null){
  const query={anchor:ref,limit:8,max_chars:16000};if(text?.trim())query.text=text.trim();
  const items=questions(questionText);if(items.length)query.questions=items;
  if(strategy!=='source')query.strategy=strategy;
  if(cursor)query.cursor={...cursor};
  return {schema:'investigation-plan/1',nodes:[{name:'evidence',op:'evidence_search',inputs:[],params:{run_id:graph.run_id,source_hash:graph.source_hash,query}}]};
 }
 function why(r,names={}){
  if(r.kind==='lexical_match')return 'Search match #'+r.rank;
  if(r.kind==='recorded_context_match')return 'Recorded tool context match #'+r.rank;
  if(r.kind==='recorded_user_request')return 'Recorded user request';
  if(r.kind==='matching_record_context')return 'Surrounding matching source record';
  if(r.kind==='preceding_source_record')return 'Adjacent earlier prose · not a semantic link';
  if(r.kind==='recorded_response')return 'Recorded response to '+r.of_event_id;
  if(r.kind==='recorded_dispatch')return 'Recorded dispatch for '+r.of_event_id;
  if(r.kind==='recorded_child_dispatch')return 'Dispatch in source message '+r.of_event_id;
  if(r.kind==='recorded_dispatch_group')return 'Command from the same source message as '+r.of_event_id+' · context, not a dependency';
  if(r.kind==='recorded_parent')return 'Source message for dispatch '+r.of_event_id;
  if(r.kind==='question_match')return names[r.question_id]?'Candidate for: '+names[r.question_id].slice(0,75):'Candidate for '+r.question_id.replace(/^question-/,'question ');
  return 'Additional source context';
 }
 function requestedPlan(graph,ref,ids=[],strategy='source',sourceTypes=['action','feedback','prose']){
  return {schema:'investigation-plan/1',nodes:[{name:'evidence',op:'requested_evidence',inputs:[],params:{run_id:graph.run_id,source_hash:graph.source_hash,graph_id:graph.id,query:{anchor:ref,question_ids:[...ids],source_types:[...sourceTypes],strategy,limit:8,max_chars:16000}}}]};
 }
 function scopeNote(packet){
  if(!packet.scope)return 'Same trajectory · session boundary not recorded in this search version.';
  const s=packet.scope;
  let text=s.anchor_order_established?'Same trajectory · '+(s.context_boundary==='recorded'?'same recorded session.':'session boundary not recorded.'):'Earlier record order is unavailable · only earlier text within this record is searchable.';
  const excluded=packet.coverage?.excluded_source_records?.length||0;
  if(excluded)text+=` ${excluded} records excluded by session or ordering checks.`;
  return text;
 }
 if(typeof module!=='undefined'){module.exports={anchor,plan,questions,why,scopeNote,requestedPlan};return;}
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
 function open(graph,n){
  const ref=anchor(n);if(!ref)return;
  const previous=document.activeElement,dialog=el('dialog',null,'source-evidence-dialog');dialog.setAttribute('aria-label','Earlier source evidence');
  const head=el('header'),title=el('h2','Earlier evidence'),close=el('button','Close');close.type='button';close.onclick=()=>dialog.close();head.append(title,close);dialog.append(head);
  dialog.append(el('p','Find earlier passages for a claim, target or artifact. Results are candidates to inspect, not verified claims.','source-evidence-intro'));
  const selected=el('details');selected.append(el('summary','Selected contribution · '+ref.event_id),el('pre',n.properties.source?.text||n.properties.text||''));dialog.append(selected);
  const form=el('form'),label=el('label','Claim, target or artifact'),input=el('input'),submit=el('button','Find earlier evidence');input.type='search';input.maxLength=6000;input.placeholder='Dataset name, acceptance criterion, reservation ID…';input.setAttribute('aria-label','Evidence search text');label.append(input);submit.type='submit';form.append(label,submit);dialog.append(form,el('small','Leave blank to search the selected contribution. A focused question often retrieves better evidence than an entire report.'));
  const questionBox=el('details'),questionLabel=el('label','Evidence questions · one per line'),questionInput=el('textarea');questionInput.rows=3;questionInput.maxLength=6000;questionInput.placeholder='What failed?\nWhat changed before the retry?\nWhat did the later check return?';questionInput.setAttribute('aria-label','Evidence questions');questionLabel.append(questionInput);questionBox.append(el('summary','Check several parts of a claim'),el('p','Up to eight questions share the same evidence budget. These searches replace the single search above and show missing candidates separately.'),questionLabel);form.append(questionBox);
  const strategyLabel=el('label','Search method'),strategy=el('select');strategy.setAttribute('aria-label','Evidence search method');for(const [value,text] of [['source','Source passages'],['source_and_calls','Source + recorded tool context']]){const option=el('option',text);option.value=value;strategy.append(option);}strategyLabel.append(strategy);questionBox.append(strategyLabel,el('small','Tool context also searches the recorded call and parent message. It can recover otherwise uninformative results, but can displace useful source matches.'));
  const terms=el('details',null,'source-evidence-terms'),termList=el('div'),termStatus=el('p'),loadTerms=el('button','Load recorded terms');loadTerms.type='button';
  terms.append(el('summary','Review against requested terms'),el('p','Reuse saved work, requirements, requested checks and attributed claims from this map. Choose up to eight; other terms stay unsearched. This does not judge compliance.'),loadTerms,termStatus,termList);form.append(terms);
  const kindsLabel=el('label','Candidate records'),kinds=el('select');kinds.setAttribute('aria-label','Requested term candidate records');for(const [value,text] of [['all','All visible record types'],['tools','Actions and returned results'],['prose','Prose records']]){const option=el('option',text);option.value=value;kinds.append(option);}kindsLabel.append(kinds);terms.insertBefore(kindsLabel,termList);
  let termInputs=[];
  function selectionChanged(){const count=termInputs.filter(i=>i.checked).length;input.disabled=questionInput.disabled=count>0;termStatus.textContent=count?`${count} selected · these terms replace the search text and manual questions.`:termInputs.length?`${termInputs.length} recorded terms · choose what to inspect.`:'No recorded terms available before this contribution.';}
  loadTerms.onclick=async()=>{
   loadTerms.disabled=true;termStatus.textContent='Loading terms at this source cutoff…';
   try{
    const response=await fetch('/api/investigation-plans',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(requestedPlan(graph,ref))});const body=await response.json();if(!response.ok)throw Error(body.error||'Could not load requested terms');if(!dialog.open)return;
    const catalog=body.outputs.evidence;termList.replaceChildren();termInputs=[];
    const names={work:'Requested work',requirement:'Requirement',requested_check:'Requested check',attributed_claim:'Attributed claim'};
    for(const q of catalog.questions){const row=el('div'),label=el('label'),check=el('input');check.type='checkbox';check.value=q.id;check.onchange=selectionChanged;termInputs.push(check);label.append(check,el('span',`${names[q.kind]} · ${q.text}`));const evidence=el('details');evidence.append(el('summary','Source of this term'),el('pre',q.evidence.map(r=>`${r.event_id}: ${r.text}`).join('\n\n')));row.append(label,evidence);termList.append(row);}
    const old=catalog.history.filter(r=>r.lifecycle!=='current');if(old.length){const history=el('details');history.append(el('summary',`${old.length} earlier or unavailable versions`));for(const r of old)history.append(el('p',`${r.lifecycle} · ${r.text}`));termList.append(history);}
    selectionChanged();if(catalog.coverage.unresolved_record_ids.length)termStatus.textContent+=' Some recorded versions lack usable source; older terms were not substituted.';if(catalog.coverage.missing_prerequisites.length)termStatus.textContent+=` ${catalog.coverage.missing_prerequisites.length} records need saved condition clauses.`;
    if(!catalog.questions.length)termStatus.textContent='This map has no usable saved terms before this contribution. Use a map containing extracted requested terms, or enter evidence questions above.';
   }catch(error){termStatus.textContent=error.message;}finally{loadTerms.disabled=false;}
  };
  const status=el('p',null,'source-evidence-status'),results=el('div',null,'source-evidence-results');status.setAttribute('role','status');dialog.append(status,results);
  const pager=el('nav',null,'source-evidence-pages'),back=el('button','Previous page'),next=el('button','Next candidates'),position=el('span');pager.setAttribute('aria-label','Evidence search pages');back.type=next.type='button';pager.append(back,position,next);dialog.insertBefore(pager,results);pager.hidden=true;
  let serial=0,current=null,pages=[],pageReviews=[],pageIndex=-1,searchPlan=null;
  function pageControls(busy=false){pager.hidden=!pages.length;back.disabled=busy||pageIndex<1;next.disabled=busy||!(pageIndex<pages.length-1||current?.pagination?.next_cursor);position.textContent='Page '+(pageIndex+1)+' · '+pages.length+' loaded';}
  async function search(cursor=null){
   const call=++serial;submit.disabled=true;status.textContent='Searching the earlier visible source…';pageControls(true);
   try{
    const selectedTerms=termInputs.filter(i=>i.checked).map(i=>i.value);
    if(!cursor){if(selectedTerms.length>8)throw Error('Select at most eight recorded terms per search.');const items=selectedTerms.length?[]:questions(questionInput.value);if(items.length>8)throw Error('Use at most eight evidence questions.');if(items.some(q=>q.text.length>2000))throw Error('Keep each evidence question within 2,000 characters.');}
    const candidatePlan=cursor?searchPlan:selectedTerms.length?requestedPlan(graph,ref,selectedTerms,strategy.value,kinds.value==='tools'?['action','feedback']:kinds.value==='prose'?['prose']:['action','feedback','prose']):plan(graph,ref,input.value,questionInput.value,strategy.value);
    const request=JSON.parse(JSON.stringify(candidatePlan));if(cursor)request.nodes[0].params.query.cursor=cursor;
    const response=await fetch('/api/investigation-plans',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});const body=await response.json();if(!response.ok)throw Error(body.error||'Evidence search failed');if(call!==serial||!dialog.open)return;
    if(!cursor){searchPlan=candidatePlan;pages=[];pageReviews=[];}const output=body.outputs.evidence,review=output.schema?.startsWith('requested-evidence-review/')?output:null;current=review?review.evidence:output;pages.push(current);pageReviews.push(review);pageIndex=pages.length-1;if(review&&!cursor)terms.open=false;render();
   }catch(error){if(call===serial)status.textContent=error.message;}finally{if(call===serial){submit.disabled=false;pageControls();}}
  }
  function render(){
    current=pages[pageIndex];results.replaceChildren();const c=current.coverage,p=current.pagination;
    const inspected=new Set(pages.flatMap(page=>page.matches.map(m=>m.event_id))).size,totalChars=pages.reduce((n,page)=>n+page.coverage.source_text_chars,0);
    status.textContent=`${inspected} / ${p?.candidates_total??c.lexically_matched_events} ranked candidates loaded · page ${pageIndex+1}: ${c.retained_events} records with context · ${c.source_text_chars.toLocaleString()} source characters · ${totalChars.toLocaleString()} across loaded pages`;
    const context=el('div',null,'source-evidence-context');
    context.append(el('small','Through '+ref.event_id+(ref.start!=null?' before character '+ref.start:' before this event')+' · lexical ranking, not confidence.'),el('small',scopeNote(current)));
    if(!current.query.questions?.length)context.append(el('small','Search: '+(current.query.text||'selected contribution')));
    context.append(el('small',p?.exhausted?'Ranked candidates exhausted; unmatched events and omitted passages may still matter.':'Continue the same search · 16,000 characters per page · context may repeat.'));if(current.dispatch_group_context?.enabled)context.append(el('small',current.dispatch_group_context.boundary));results.append(context);
    const review=pageReviews[pageIndex];if(review){const panel=el('section',null,'source-evidence-questions');panel.append(el('h3','Requested terms · review remains open'),el('p',`${review.coverage.searched_questions} / ${review.coverage.total_questions} terms searched. No satisfaction or truth verdict has been made.`),el('small','Primary candidate types: '+current.query.questions[0].source_types.join(', ')+'. Other types may appear as context.'));for(const q of review.questions.filter(q=>review.selected_question_ids.includes(q.id))){const row=el('div');row.append(el('strong',q.text),el('small',q.retrieval_status==='originating_request_only'?'Only the originating request matched on this page. Further evidence is still needed.':q.retrieval_status==='candidates_to_review'?`${q.candidate_event_ids.length} other source records to inspect · relevance and result not assessed.`:'No candidate retained on this page · refine the query or continue.'));if(q.candidate_event_ids?.length){const inspect=el('button','First candidate ↓','rs-text-button');inspect.type='button';inspect.onclick=()=>{const card=cards.get(q.candidate_event_ids[0]);card?.scrollIntoView({block:'start'});card?.focus({preventScroll:true});};row.append(inspect);}panel.append(row);}results.append(panel);}
    if(current.query.questions?.length&&!review){const summary=el('section',null,'source-evidence-questions');summary.append(el('h3','Evidence by question · this page'),el('p','Candidate passages need review. A match does not establish that a condition is satisfied.'));
     for(const q of current.questions||[]){const row=el('div');row.append(el('strong',q.text),el('small',q.status==='no_lexical_matches'?'No lexical candidates. Try another wording or inspect the source.':`${q.retained_match_event_ids.length} candidate records retained · ${q.omitted_match_event_ids.length} outside this page${q.status==='candidates_omitted'?' · continue candidates or narrow the search':''}`));summary.append(row);}results.append(summary);}
    const cards=new Map(),jumpLabel=el('label','Jump to evidence'),jump=el('select');jump.setAttribute('aria-label','Jump to evidence');jump.append(el('option','Choose a record…'));jump.firstChild.value='';
    for(const record of current.records){const excerpt=record.fragments.map(f=>f.text).join(' ').replace(/\s+/g,' ').slice(0,90),option=el('option',`${record.event_id} · ${record.kind} · ${excerpt}`);option.value=record.event_id;jump.append(option);}
    jump.onchange=()=>{const card=cards.get(jump.value);if(card){card.scrollIntoView({block:'start'});card.focus({preventScroll:true});}};jumpLabel.append(jump);results.append(jumpLabel);
    if(!current.matches.length)results.append(el('strong','No lexical matches. This does not establish that the evidence is absent. Try a recorded name, identifier or different wording.'));
    const questionNames=Object.fromEntries((current.questions||[]).map(q=>[q.id,q.text]));
    for(const record of current.records){
     const card=el('article'),heading=el('div'),name=el('strong',`${record.event_id} · ${record.actor} · ${record.kind}`),link=el('a','Open source record ↗');card.tabIndex=-1;cards.set(record.event_id,card);const q=new URLSearchParams({run:graph.run_id,observer:'source',level:'story',story_moment:'event:'+record.event_id,return_to:location.pathname+location.search});link.href='/semantic-map?'+q;heading.append(name,link);card.append(heading,el('small',record.reasons.map(reason=>why(reason,questionNames)).join(' · ')+(record.copied_context?' · copied history':'')));
     for(const fragment of record.fragments){card.append(el('pre',fragment.text),el('small',`Source characters ${fragment.start}–${fragment.end}`));}
     if(record.omitted_text_chars)card.append(el('small',`${record.omitted_text_chars.toLocaleString()} readable characters from this record are omitted; open the source for full context.`));results.append(card);
    }
    const info=el('details');info.append(el('summary','Search scope and omitted evidence'),el('p',current.boundary),el('p',current.selection),el('pre',JSON.stringify({query_terms:current.query_terms,coverage:c},null,2)));results.append(info);
    const download=el('button','Download loaded evidence pages');download.type='button';download.onclick=()=>{const bundle={schema:'source-evidence-pages/1',search_id:p?.search_id,pages,requested_term_reviews:pageReviews.filter(Boolean),total_source_characters:totalChars,boundary:'Candidates loaded, not adjudicated answers. Repeated context is counted again in the total character cost.'};const url=URL.createObjectURL(new Blob([JSON.stringify(bundle,null,2)],{type:'application/json'})),a=el('a');a.href=url;a.download='earlier-evidence-'+ref.event_id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};results.append(download);pageControls();
  }
  back.onclick=()=>{if(pageIndex>0){pageIndex--;render();}};
  next.onclick=()=>{if(pageIndex<pages.length-1){pageIndex++;render();}else if(current?.pagination?.next_cursor)search(current.pagination.next_cursor);};
  form.onsubmit=e=>{e.preventDefault();search();};dialog.addEventListener('close',()=>{serial++;dialog.remove();previous?.focus();},{once:true});document.body.append(dialog);dialog.showModal();search();
 }
 function append(host,graph,n){if(!anchor(n))return;const b=el('button','Find earlier evidence','rs-text-button');b.type='button';b.onclick=()=>open(graph,n);host.append(b);}
 root.SourceEvidence={anchor,plan,open,append};
})(typeof globalThis!=='undefined'?globalThis:this);
