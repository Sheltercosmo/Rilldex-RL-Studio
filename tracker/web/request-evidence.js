/* Saved request/check evidence. Never completion or a passing-test score. */
(()=>{
 const make=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
 const names={attempts:'Attempts check',prepares:'Prepares check',none:'No correspondence selected',unresolved:'Unresolved',sufficient:'Answering evidence supplied',partial:'Partial answering evidence',no_answer:'No answer in this response'};
 const kinds={requested_check:'Requested check',requirement:'Requirement',attributed_claim:'Attributed claim'};
 const coverage={unreviewed:'Not reviewed',positive_links_only:'Review coverage unknown',partial_saved_review:'Partly reviewed',complete_saved_review:'Saved review available',no_recorded_dispatch_opportunity:'No recorded check opportunity'};
 function render(host,data,open){
  const box=make('section',undefined,'rs-request-evidence');box.setAttribute('aria-label','Requested checks and evidence');
  box.append(make('h3','Requested checks & evidence'),make('p','Connect each requested check to its attempts and returned evidence. Answer availability is separate from a passing check or completed task.'));
  if(!data?.rows.length){box.append(make('p','No source-bound requested clauses are saved for this observation set. Check coverage is unknown.','rs-missing'));host.append(box);return;}
  if(data.counts.unrepresented_actions)box.append(make('p',`${data.counts.unrepresented_actions} of ${data.counts.native_actions} recorded actions have no semantic action unit. Review counts below cannot establish full rollout coverage.`,'rs-missing'));
  if(data.excluded.length)box.append(make('p',`${data.excluded.length} saved links or decisions have incompatible source bindings and are excluded.`,'rs-missing'));
  const controls=make('label'),history=make('input'),body=make('div');history.type='checkbox';history.checked=true;controls.append(history,make('span','Include superseded and withdrawn terms'));controls.className='rs-request-history';box.append(controls,body);host.append(box);
  function source(parent,label,record){
   const b=make('button',label+' · '+record.event_id,'rs-text-button');b.type='button';b.onclick=()=>open(record.node_id);parent.append(b);
  }
  function row(item){
   const detail=make('details',undefined,'rs-request-row'),summary=make('summary'),title=make('div');
   title.append(make('span',kinds[item.clause.kind]+' · '+item.state,'rs-eyebrow'),make('strong',item.clause.text));summary.append(title);
   if(item.clause.kind==='requested_check'){
    const stats=make('div',undefined,'rs-request-counts'),c=item.counts,d=c.dispatch_choices,r=c.response_choices;
    const measures=[[d.attempts,'observed attempt','observed attempts'],[d.prepares,'preparatory action','preparatory actions'],[r.sufficient,'answering response','answering responses'],[r.partial,'partial response','partial responses'],[r.no_answer,'response without an answer','responses without an answer'],[(d.unresolved||0)+(r.unresolved||0),'unresolved decision','unresolved decisions']];
    for(const [count,singular,plural] of measures)if(count)stats.append(make('span',`${count} ${count===1?singular:plural}`));
    if(!measures.some(([count])=>count))stats.append(make('span',c.dispatch_reviewed||c.response_reviewed?'No matching check or answer selected':'No saved check decisions'));
    stats.append(make('small',`${c.dispatch_reviewed}/${c.dispatch_opportunities} dispatches reviewed · ${c.response_reviewed}/${c.response_opportunities} responses reviewed`));summary.append(stats);
    title.append(make('span',coverage[item.coverage]||'Coverage unknown','rs-missing'));
   }else summary.append(make('span','Not evaluated by the check observer','rs-missing'));
   detail.append(summary);source(detail,'Requested in',item.origin);
   if(item.clause.kind!=='requested_check'){detail.append(make('p',item.clause.kind==='requirement'?'This requested restriction needs its own applicable check or evidence. It is not marked satisfied.':'This is an attributed assertion. Repetition and tool echoes do not establish its truth.'));return detail;}
   const notes={unreviewed:'No check-correspondence review is saved. Zero observed links is not zero checking behavior.',positive_links_only:'Only positive links were retained in this older graph. Negative and unresolved review coverage is unknown.',partial_saved_review:'Some eligible operations or responses have no saved judgment.',complete_saved_review:'All represented opportunities have saved judgments; unresolved choices remain visible. This does not establish semantic accuracy.',no_recorded_dispatch_opportunity:'No represented dispatch has this check in its prior requested context.'};
   detail.append(make('p',notes[item.coverage]||'Coverage unavailable.'));
   if(item.excluded?.length)detail.append(make('p',`${item.excluded.length} saved decisions for this check were excluded because their source bindings could not be established.`,'rs-missing'));
   if(item.latest_response_choice)detail.append(make('p','Latest reviewed response: '+names[item.latest_response_choice]+'. '+(item.counts.response_choices.sufficient||item.counts.response_choices.partial?'Earlier evidence remains attached to this request version; it is not a current-world-state assertion.':'The reviewed responses are shown below.')));
   if(item.attempts_without_recorded_response)detail.append(make('p',`${item.attempts_without_recorded_response} observed attempts have no uniquely bound recorded response in this snapshot.`));
   const actions=new Map(item.dispatches.map(d=>[d.action_unit_id,{dispatch:d,responses:[]}]));
   for(const r of item.responses){if(!actions.has(r.action_unit_id))actions.set(r.action_unit_id,{dispatch:null,responses:[]});actions.get(r.action_unit_id).responses.push(r);}
   for(const value of [...actions.values()].sort((a,b)=>(a.dispatch||a.responses[0]).action.index-(b.dispatch||b.responses[0]).action.index)){
    const first=value.dispatch||value.responses[0],card=make('div',undefined,'rs-request-attempt');
    card.append(make('strong',value.dispatch?names[value.dispatch.choice]:'Dispatch correspondence unreviewed'),make('pre',first.action.text));source(card,'Open action',first.action);
    for(const r of value.responses){const response=make('div',undefined,'rs-request-response');response.append(make('strong',names[r.choice]),make('pre',r.response.text));source(response,'Open response',r.response);if(r.response.excerpt_truncated)response.append(make('small','Excerpt; open the response for full content.'));card.append(response);}
    if(!value.responses.length)card.append(make('small','No reviewed response for this action and check.'));
    detail.append(card);
   }
   return detail;
  }
  const draw=()=>{body.replaceChildren();const rows=data.rows.filter(r=>history.checked||r.state==='requested'),checks=rows.filter(r=>r.clause.kind==='requested_check'),other=rows.filter(r=>r.clause.kind!=='requested_check');
   body.append(make('p',`${checks.length} requested-check versions · ${other.length} other terms and claims. Counts describe this saved source snapshot.`,'rs-request-summary'));
   for(const item of checks)body.append(row(item));
   if(other.length){const terms=make('details',undefined,'rs-request-other');terms.append(make('summary',`Other terms & claims (${other.length})`));for(const item of other)terms.append(row(item));body.append(terms);}
   if(!rows.length)body.append(make('p','No current clauses in this snapshot. Include historical terms to inspect earlier requests.'));
  };history.onchange=draw;draw();
 }
 window.RequestEvidence={render};
})();
