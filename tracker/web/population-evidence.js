/* Evidence availability is not population closure or task success. */
(()=>{
 const make=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
 const percent=n=>n==null?'—':(100*n).toFixed(1)+'%';
 const number=n=>n==null?'—':Number(n.toFixed(3)).toLocaleString();
 const button=(label,fn)=>{const e=make('button',label);e.type='button';e.onclick=fn;return e;};
 const readinessSelection=new Map();
 function outcomeReadiness(d){
  const box=make('section');box.className='population-evidence outcome-readiness';box.setAttribute('aria-label','Can this curve be interpreted?');
  box.append(make('h3','Can this curve be interpreted?'));
  const rows=(d?.cohorts||[]).filter(r=>r.outcome_support);
  if(!rows.length){box.append(make('p',d?.reason||'Scheduled membership is not recorded. Arrived traces cannot reveal work still pending.'));return box;}
  box.append(make('p','Experiment workload, independent of the training-sample selector below. Check outcome coverage before comparing performance.'));
  const groups=new Map();for(const r of rows){const key=JSON.stringify([r.producer,r.coordinate.clock,r.coordinate.basis,r.context]);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r);}
  const streams=[...groups.values()],controls=make('div'),chart=make('div'),detail=make('div');controls.className='outcome-controls';chart.className='outcome-chart';detail.className='outcome-detail';
  const selectionKey=JSON.stringify([d.experiment,d.environment]),saved=readinessSelection.get(selectionKey);
  let streamIndex=Math.max(0,streams.findIndex(g=>g.some(r=>r.id===saved?.id&&r.producer===saved?.producer))),selected=null;
  const streamSelect=make('select'),cohortSelect=make('select');
  const label=(text,select)=>{const l=make('label');l.append(make('span',text),select);return l;};
  streams.forEach((g,i)=>{const r=g[0],o=make('option',`${r.context.environment||'All declared environments'} · ${r.coordinate.clock} / ${r.coordinate.basis} · stream ${i+1}`);o.value=String(i);streamSelect.append(o);});
  controls.append(label('Generation stream',streamSelect),label('Inspect cohort',cohortSelect));box.append(controls,chart,detail);
  const drawDetail=r=>{
   selected=r;cohortSelect.value=r.id;detail.replaceChildren();const s=r.outcome_support,stats=make('div');stats.className='outcome-stats';
   for(const [name,value,note]of [['Recorded success',percent(s.observed_rate),`${s.known} / ${s.declared} outcomes known`],['Unknown outcomes',String(s.unknown),`${r.generation_states.admitted} generation pending · ${r.complete_captures}/${r.declared} complete captures`],['Possible final fraction',s.lower==null?'Membership open':`${percent(s.lower)}–${percent(s.upper)}`,'All unknown outcomes assigned failure or success; not a confidence interval']]){const card=make('div');card.append(make('span',name),make('strong',value),make('small',note));stats.append(card);}
   detail.append(make('h4',r.label+' · '+r.coordinate.basis+' '+r.coordinate.index),stats);
   const stopped=(r.generation_states.failed||0)+(r.generation_states.cancelled||0);
   const message=!r.sealed?'Membership can still grow. Compare a fixed cohort after scheduling closes.':s.unknown?`This point is provisional. Inspect the missing task groups and revisit the same generation coordinate after late evidence arrives.${stopped?' '+stopped+' executions failed or were cancelled; their task outcomes may remain unknown.':''}`:'All declared task outcomes are available. Compare like-for-like task and policy groups before attributing a change to training.';
   detail.append(make('p',message));
   for(const selection of r.outcome_selection||[]){if(selection.groups.length<2)continue;const table=make('table'),head=make('tr'),wrap=make('div');wrap.className='population-table';for(const t of [selection.field.replaceAll('_',' '),'Outcomes / declared','Share: declared → observed','Recorded success'])head.append(make('th',t));table.append(head);
    for(const g of selection.groups.slice(0,8)){const tr=make('tr');tr.append(make('td',g.value||'Unrecorded'),make('td',`${g.known} / ${g.declared}`),make('td',`${percent(g.declared_share)} → ${percent(g.observed_share)}`),make('td',percent(g.success_rate)));table.append(tr);}wrap.append(table);detail.append(wrap);if(selection.groups.length>8)detail.append(make('small',`First 8 of ${selection.groups.length} groups; inspect members or query cohort_readiness() for all groups.`));}
   const actions=make('div');actions.className='comparison-actions';const members=button('Inspect this cohort',()=>{const q=new URLSearchParams({experiment:d.experiment,cohort:r.id,producer:r.producer,members:'1'});if(d.environment)q.set('environment',d.environment);fetch('/api/generation-cohorts?'+q).then(async response=>{const value=await response.json();if(!response.ok)throw Error(value.error||response.statusText);if(selected!==r||!box.isConnected)return;const previous=detail.querySelector('.declared-cohorts');previous?.remove();const panel=declaredCohorts(value,{inspectMembers:true});panel.open=true;detail.append(panel);}).catch(error=>{if(selected===r&&box.isConnected)detail.append(make('p',error.message));});});
   actions.append(members);const a=make('a','Compare behavior measures');a.href='/?'+new URLSearchParams({experiment:d.experiment,...(d.environment?{environment:d.environment}:{}),view:'measures'});actions.append(a);detail.append(actions);
  };
  const draw=()=>{
   const all=streams[streamIndex],rs=all.slice(-32);chart.replaceChildren();cohortSelect.replaceChildren();for(const r of [...all].reverse()){const o=make('option',`${r.label} · ${r.coordinate.index} · ${r.outcome_support.known}/${r.declared} outcomes`);o.value=r.id;cohortSelect.append(o);}
   const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 720 190');svg.setAttribute('role','img');svg.setAttribute('aria-label','Outcome coverage and success by declared generation coordinate');
   const add=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;svg.append(n);return n;};
   const lo=rs[0].coordinate.index,hi=rs.at(-1).coordinate.index,x=r=>hi===lo?370:48+640*(r.coordinate.index-lo)/(hi-lo),y=v=>154-132*v;
   for(const v of [0,.5,1]){add('line',{x1:48,x2:688,y1:y(v),y2:y(v),stroke:'#e2e8f0'});add('text',{x:3,y:y(v)+4,fill:'#546278','font-size':12},percent(v));}
   const coverage=rs.filter(r=>r.outcome_support.coverage!==null);add('polyline',{points:coverage.map(r=>`${x(r)},${y(r.outcome_support.coverage)}`).join(' '),fill:'none',stroke:'#365eed','stroke-width':2});
   for(const r of rs){const s=r.outcome_support;if(s.lower!==null)add('line',{x1:x(r),x2:x(r),y1:y(s.lower),y2:y(s.upper),stroke:'#64748b','stroke-width':3,opacity:.5});
    if(s.observed_rate!==null){const n=add('circle',{cx:x(r),cy:y(s.observed_rate),r:5,fill:s.complete?'#0f766e':'white',stroke:'#0f766e','stroke-width':2,tabindex:0,role:'button','aria-label':`${r.label}: ${percent(s.observed_rate)} success, ${s.known}/${s.declared} outcomes`});const title=document.createElementNS(ns,'title');title.textContent=`${r.label} · ${s.known}/${s.declared} outcomes`;n.append(title);n.onclick=()=>choose(r);n.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(r);}};}
   }
   add('text',{x:48,y:180,fill:'#546278','font-size':12},String(lo));add('text',{x:688,y:180,'text-anchor':'end',fill:'#546278','font-size':12},String(hi));chart.append(svg,make('small',`Generation coordinate · last ${rs.length} of ${all.length} cohorts in this stream. Blue: outcome coverage. Teal: recorded success (hollow = provisional). Gray: possible fraction across fixed declared membership.`));drawDetail(all.find(r=>r.id===(selected?.id||saved?.id))||all.at(-1));
  };
  const choose=r=>{readinessSelection.set(selectionKey,{id:r.id,producer:r.producer});if(readinessSelection.size>20)readinessSelection.delete(readinessSelection.keys().next().value);drawDetail(r);};
  streamSelect.value=String(streamIndex);streamSelect.onchange=()=>{streamIndex=Number(streamSelect.value);selected=null;draw();choose(selected);};cohortSelect.onchange=()=>choose(streams[streamIndex].find(r=>r.id===cohortSelect.value));draw();
  if(d.truncated)box.append(make('p','Cohort display limit reached. Use cohort_readiness() with a narrower generation window to load more records.'));
  if(d.overlapping_members)box.append(make('p','Some cohorts share rollout identities; points are not independent samples.'));
  return box;
 }
 function declaredCohorts(d,{observer='source',alignment=[],inspectMembers=false}={}){
  const box=make('details');box.className='population-evidence declared-cohorts';box.dataset.panel='cohorts';
  const cohorts=[...(d?.cohorts||[])].reverse();box.dataset.scope=JSON.stringify([d?.experiment,d?.environment]);
  box.append(make('summary',cohorts.length?`Declared workload · ${d.distinct_delivered_rollouts==null?d.distinct_declared_rollouts.toLocaleString()+' rollouts declared':d.distinct_delivered_rollouts.toLocaleString()+'/'+d.distinct_declared_rollouts.toLocaleString()+' rollouts delivered'} · ${cohorts.length} cohorts`:'Declared workload · membership not recorded'));
  if(!cohorts.length){box.append(make('p',d?.reason||'Select an experiment. Trace arrivals alone cannot reveal work still pending.'));const a=make('a','Record scheduler membership with Python');a.href='/connections#data-access-section';box.append(a);return box;}
  box.append(make('p','Read each cohort independently: membership → generation → delivered sources → available outcomes. Sealed membership does not mean scores or observations are complete.'));
  if(d.truncated)box.append(make('p','Bounded view: showing the highest declared coordinates within the cohort/member limit. Narrow the clock or window with code; these counts do not cover the entire experiment.'));
  if(d.overlapping_members)box.append(make('p',`${d.overlapping_members} rollout identities occur in multiple cohorts. Do not add cohort totals.`));
  if(alignment.some(a=>a.status!=='matching_clock'))box.append(make('p','Some declaration clocks cannot be aligned with the source chart. Their window labels refer only to declared coordinates, not matching learner updates.'));
  const host=make('div'),cases=make('section');cases.className='declared-members';cases.setAttribute('aria-live','polite');let page=0;
  const showMembers=(members,label,pinned)=>{
   let memberPage=0;const draw=()=>{cases.replaceChildren(make('h4',label),make('p',pinned?'Membership and receipts frozen with this comparison.':'Current membership and source snapshot loaded on request.'));
    const wrap=make('div'),table=make('table'),head=make('tr');wrap.className='population-table';for(const text of ['Rollout / task','Generation','Source / clock','Outcome','Observation'])head.append(make('th',text));table.append(head);
    for(const m of members.slice(memberPage*25,(memberPage+1)*25)){
     const row=make('tr'),identity=make('td'),text=m.context.task_id||m.rollout_id;
     if(m.run_id){const a=make('a',text);a.href='/semantic-map?'+new URLSearchParams({run:m.run_id,observer,return_to:location.pathname+location.search});identity.append(a);}else identity.append(make('span',text));
     identity.append(make('small',`${m.producer} · ${m.rollout_id} · ${m.attempts.length} reported attempts`));
     const outcome=m.outcome.verified_success==null?'Success unknown':m.outcome.verified_success?'Verified success':'Verified failure';
     row.append(identity,make('td',m.generation_state),make('td',`${m.source_status.replaceAll('_',' ')} · ${m.coordinate_alignment.replaceAll('_',' ')}`),make('td',`${outcome} · reward ${number(m.outcome.recorded_reward)}`),make('td',`${m.measurement_status.replaceAll('_',' ')}${m.measurement?.value==null?'':' · '+number(m.measurement.value)}`));
     table.append(row);
    }wrap.append(table);cases.append(wrap);if(members.length>25){const pager=make('div');pager.className='pager';const back=button('Previous members',()=>{memberPage--;draw();}),next=button('Next members',()=>{memberPage++;draw();});back.disabled=memberPage===0;next.disabled=(memberPage+1)*25>=members.length;pager.append(back,make('span',`${memberPage*25+1}–${Math.min((memberPage+1)*25,members.length)} / ${members.length}`),next);cases.append(pager);}
   };draw();cases.scrollIntoView({block:'nearest',behavior:'smooth'});
  };
  const inspect=async r=>{
   if(r.members){showMembers(r.members,r.label,true);return;}
   cases.textContent='Loading declared members…';
   try{const q=new URLSearchParams({experiment:d.experiment,cohort:r.id,producer:r.producer,members:'1'});if(d.environment)q.set('environment',d.environment);if(d.monitor)q.set('monitor',d.monitor);
    const response=await fetch('/api/generation-cohorts?'+q),data=await response.json();if(!response.ok)throw Error(data.error||response.statusText);
    const current=data.cohorts[0];if(!current)throw Error('No declared cohort in this scope');showMembers(current.members,current.label,false);
   }catch(error){cases.textContent=error.message;}
  };
  const draw=()=>{
   host.replaceChildren();const wrap=make('div'),table=make('table'),head=make('tr');wrap.className='population-table';
   for(const text of ['Cohort / coordinate','Membership & generation','Sources / declared','Available outcomes','Evidence'])head.append(make('th',text));table.append(head);
   for(const r of cohorts.slice(page*8,(page+1)*8)){
    const row=make('tr'),name=make('td'),generation=make('td'),sources=make('td'),outcomes=make('td'),evidence=make('td');
    name.append(make('strong',r.label),make('small',`${r.coordinate.clock} · ${r.coordinate.basis} ${r.coordinate.index}${r.windows.length?' · '+r.windows.join(', '):''}`));
    const config=Object.entries(r.context).map(([k,v])=>`${k.replaceAll('_',' ')}: ${v}`).join(' · ');if(config)name.append(make('small',config));
    const aligned=alignment.find(a=>a.id===r.id&&a.producer===r.producer);if(aligned&&aligned.status!=='matching_clock')name.append(make('small',aligned.status.replaceAll('_',' ')));
    generation.append(make('strong',`${r.sealed?'Sealed':'Open'} · ${r.generation_states.admitted} pending`),make('small',Object.entries(r.generation_states).filter(([k,n])=>k!=='admitted'&&n).map(([k,n])=>`${n} ${k}`).join(' · ')||'No terminal generation reports'));
    if(r.membership_scope==='environment subset')generation.append(make('small',`Environment subset · ${r.whole_cohort_pending} pending in whole cohort`));
    sources.append(make('strong',`${r.delivered} / ${r.declared}`),make('small',`${r.complete_captures} complete captures${r.source_conflicts?' · '+r.source_conflicts+' conflicts':''}`));
    outcomes.append(make('strong',`Success ${percent(r.verified_success_rate)}`),make('small',`${r.success_available}/${r.declared} outcomes · reward ${number(r.recorded_reward_mean)} (${r.reward_available}/${r.declared})`));
    if(d.monitor)evidence.append(make('strong',`Measure ${number(r.monitor_value)}`),make('small',`${r.measured}/${r.declared} declared rollouts measured`));
    const mix=make('details');mix.append(make('summary','Task delivery mix'));for(const t of r.task_mix.slice(0,20))mix.append(make('small',`${t.task_id||'Task not recorded'}: ${t.delivered}/${t.declared} delivered${d.monitor?' · '+t.measured+' measured':''}`));if(r.task_mix.length>20)mix.append(make('small','First 20 task groups; code access retains all groups.'));evidence.append(mix,button('Inspect members',()=>inspect(r)));row.append(name,generation,sources,outcomes,evidence);table.append(row);
   }wrap.append(table);host.append(wrap);
   if(cohorts.length>8){const pager=make('div');pager.className='pager';const back=button('Previous cohorts',()=>{page--;draw();}),next=button('Next cohorts',()=>{page++;draw();});back.disabled=page===0;next.disabled=(page+1)*8>=cohorts.length;pager.append(back,make('span',`${page*8+1}–${Math.min((page+1)*8,cohorts.length)} / ${cohorts.length}`),next);host.append(pager);}
  };draw();box.append(host,cases);
  if(inspectMembers&&cohorts.length===1&&cohorts[0].members)showMembers(cohorts[0].members,cohorts[0].label,false);
  box.append(make('p','Means use available outcomes only; missing outcomes remain unknown. Generation failure is not verified task failure. Shorter responses are not a difficulty label.'));
  const link=make('a','Query declared populations with code');link.href='/connections?'+new URLSearchParams({analysis_table:'generation_cohorts',analysis_experiment:d.experiment})+'#data-access-section';box.append(link);return box;
 }
 function readinessText(r){return !r?'Capture state not retained':`${r.measured}/${r.observed} observed sources measured · ${r.unfinished} unfinished captures · ${r.completed_unmeasured+r.imported_unmeasured} arrived without a value`+(r.failed_capture?` · ${r.failed_capture} failed captures`:'');}
 function executionContext(d){
  const box=make('details'),groups=d?.groups||[],total=d?.observed_attempts||0,unfinished=groups.reduce((n,g)=>n+g.unfinished,0);box.className='population-evidence';
  box.append(make('summary',!d?.available?'Execution context · '+(d?.reason||'Not available'):!total?'Execution context · no lifecycle reports':`Execution context · ${unfinished} unfinished / ${total} reported attempts`));
  box.append(make('p',total?'Latest reported states, not live heartbeats. '+d.scope:'Batch imports cannot reveal unreported or queued work. Send rollout execution reports from the scheduler to inspect the observed workload.'));
  if(total){
   if(d.latest_received_at)box.append(make('p','Latest report received '+new Date(d.latest_received_at).toLocaleString()));
   const wrap=make('div'),table=make('table'),head=make('tr');wrap.className='population-table';for(const label of ['Context','Reported states','Share: all → completed','Completed duration / output'])head.append(make('th',label));table.append(head);
   for(const g of groups.slice(0,30)){
    const row=make('tr'),context=Object.entries(g.context).filter(([,v])=>v!=null).map(([k,v])=>k.replaceAll('_',' ')+': '+v).join(' · ')||'Context not recorded',states=Object.entries(g.states).filter(([,n])=>n).map(([k,n])=>n+' '+k).join(' · '),duration=g.completed_duration_ms,tokens=g.completed_output_tokens;
    row.append(make('td',context),make('td',states),make('td',percent(g.observed_share)+' → '+percent(g.completed_share)),make('td',`Median ${duration.p50==null?'—':duration.p50+' ms'} (${duration.measured}/${duration.eligible} measured) · ${tokens?.p50==null?'—':tokens.p50+' tokens'} (${tokens?.measured||0}/${tokens?.eligible||0})`));table.append(row);
   }wrap.append(table);box.append(wrap);
   if(groups.length>30)box.append(make('p',`Showing 30 of ${groups.length} contexts; all groups are available through code analysis.`));
   box.append(make('p','Completed means execution ended, not task success. Shares compare completed with all reported attempts, including retries. Token length is not a difficulty label; unreported work and final population size remain unknown.'));
  }
  const link=make('a','Inspect lifecycle data with code');link.href='/connections?analysis_table=executions'+(d?.experiment?'&analysis_experiment='+encodeURIComponent(d.experiment):'')+'#data-access-section';box.append(link);return box;
 }
 function review(d){
  const box=make('section');box.className='population-evidence';box.append(make('h4','Population coverage'),make('p','Counts below show received rollouts, measured values and declared workload. Undeclared workload remains unknown.'));
  for(const check of d.review||[]){const row=make('details');row.append(make('summary',check.title),make('p',check.evidence),make('p',check.next_check));box.append(row);}
  const links=make('div');links.className='comparison-actions';for(const [label,view]of [['Training samples','training'],['Training health','health']]){const a=make('a',label);a.href='/?'+new URLSearchParams({experiment:d.scope.experiment,...(d.scope.environment?{environment:d.scope.environment}:{}),view});links.append(a);}box.append(links);return box;
 }
 function mixDetails(r){
  const detail=make('details');detail.append(make('summary','Measured population mix'));
  for(const mix of r.selection){detail.append(make('strong',mix.field.replaceAll('_',' ')));for(const g of mix.groups.slice(0,20))detail.append(make('small',`${g.value==null?'Not recorded':typeof g.value==='object'?JSON.stringify(g.value):g.value}: ${g.measured}/${g.observed} measured`));if(mix.groups.length>20)detail.append(make('small','First 20 groups; download evidence for all groups.'));}return detail;
 }
 function coverageSeries(s){return {...s,points:s.points.map(p=>({...p,value:p.value==null?0:1,numerator:null,denominator:null})),bins:s.bins.map(b=>({...b,value:b.readiness?.measurement_coverage??null,numerator:null,denominator:null}))};}
 window.PopulationEvidence={readinessText,executionContext,declaredCohorts,outcomeReadiness,review,mixDetails,coverageSeries};
})();
