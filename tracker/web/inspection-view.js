(function(root){
 'use strict';
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const brief=(v,max=220)=>{const text=String(v||'').replace(/\s+/g,' ');return text.length>max?text.slice(0,max)+'…':text;};
 function render(body,layout,group,item,callbacks){
  const R=root.UnitReading;
  body.replaceChildren(el('h2',group.title,'connection-question'),el('p',group.description,'inspection-intro'));
  if(!group.cases.length){
   body.append(el('p',group.empty,'inspection-gaps'));
   if(group.id==='failed-checks'){
    const button=el('button','Load recorded checks'),status=el('p',undefined,'inspection-intro');status.setAttribute('role','status');
    button.onclick=async()=>{button.disabled=true;status.textContent='Loading captured checks…';try{const result=await callbacks.checks();if(!result.checks)status.textContent='No structured checks or recognized test results are recorded in this rollout.';else if(!result.failed_checks)status.textContent=result.checks+' recorded checks; none report failure.';}catch(e){status.textContent=e.message;}finally{button.disabled=false;}};
    body.append(button,el('p','Uses captured checks and recognized test results. No model calls.','inspection-intro'),status);
   }
   return;
  }
  const index=group.cases.indexOf(item),nav=el('div',undefined,'inspection-nav'),previous=el('button','←'),next=el('button','→'),label=el('label','Case'),select=el('select');
  select.setAttribute('aria-label','Inspection case');previous.setAttribute('aria-label','Previous inspection case');next.setAttribute('aria-label','Next inspection case');
  if(index<0){const missing=el('option','Select an available case');missing.value='';select.append(missing);}
  for(const [i,c]of group.cases.entries()){
   const option=el('option',(i+1)+' / '+group.cases.length+' · '+brief(c.title,52)+' · '+c.attempts.map(a=>R.ref(a.node)).join(' / '));option.value=c.id;select.append(option);
  }
  select.value=item?.id||'';select.onchange=()=>callbacks.open(select.value);
  previous.disabled=index<=0;next.disabled=index<0||index>=group.cases.length-1;
  previous.onclick=()=>callbacks.open(group.cases[index-1].id);next.onclick=()=>callbacks.open(group.cases[index+1].id);
  label.append(select);nav.append(previous,label,next);body.append(nav);
  if(!item){body.append(el('p','The linked case is unavailable in this saved graph. Select a case above.','inspection-gaps'));return;}
  const stats=root.InspectionPaths.summary(item),overview=el('div',undefined,'inspection-path-summary');
  overview.append(el('strong',stats.attempts+' linked attempts'+(stats.truncated?' shown':'')),el('span',stats.checks?'Recorded checks: '+stats.failed+' failed · '+stats.passed+' passed · '+stats.unknown+' unknown':'Check outcomes not recorded'),el('span',stats.feedbackUses+' feedback-use links · '+stats.changes+' change links'));
  body.append(overview);
  const nodeButton=(n,text)=>{const button=el('button',text||R.ref(n)+' · '+brief(n.activity,40),'inspection-node-button');button.onclick=()=>callbacks.unit(n.id);return button;};
  const jump=el('div',undefined,'inspection-attempt-index');jump.setAttribute('aria-label','Jump to an attempt');
  for(const [i,a]of item.attempts.entries()){
   const outcomes=[...new Set(a.checks.map(n=>n.properties.result))];jump.append(nodeButton(a.node,'Attempt '+(i+1)+(outcomes.length?' · '+outcomes.join(', '):'')));
  }
  body.append(jump);
  const showText=(host,n)=>{const text=R.evidenceText(n);host.append(el('p',brief(text,350)));if(text.length>350){const d=el('details');d.append(el('summary','Full text'),el('pre',text));host.append(d);}};
  const attempts=el('div',undefined,'inspection-attempts');
  for(const [i,a]of item.attempts.entries()){
   const card=el('section',undefined,'inspection-attempt');card.append(el('h3','Attempt '+(i+1)),nodeButton(a.node));showText(card,a.node);
   card.append(el('small','Returned feedback · '+a.responses.length+' unit link'+(a.responses.length===1?'':'s')+(a.captured_responses?.length?' · '+a.captured_responses.length+' call-level result'+(a.captured_responses.length===1?'':'s'):'')));
   if(!a.responses.length&&!a.captured_responses?.length)card.append(el('small','No attached result'));
   for(const n of a.responses){card.append(nodeButton(n));showText(card,n);}
   for(const r of a.captured_responses||[]){const d=el('details');d.append(el('summary','Captured call feedback'),el('p','Whole-call result; not assigned to one split or partial unit.'),el('pre',r.response.properties.text||''),el('small',r.response.properties.source_pointer||r.response.id));card.append(d);}
   for(const check of a.checks){const p=check.properties;card.append(el('small','Recorded '+p.result+' · '+p.criterion_id));}
   attempts.append(card);
  }
  body.append(attempts);
  if(item.attempts.length===2){
   const [a,b]=item.attempts.map(a=>a.node),raw=n=>String(n.properties?.source?.text??n.properties?.text??'');
   if(raw(a)&&raw(b))body.append(el('p',raw(a)===raw(b)?'Action text is identical. Results and recorded context may differ.':'Action text differs. Open either attempt for the full source.','inspection-intro'));
  }
  for(const n of item.nodes.filter(n=>n.lane===0)){body.append(nodeButton(n));showText(body,n);}
  const links=el('section',undefined,'inspection-links');links.append(el('h3','Saved relationships'));
  if(!item.edges.length)links.append(el('p','Check attachments are shown below. No additional unit relationships are saved.','inspection-intro'));
  for(const e of item.edges){
   const button=el('button',R.sentence(layout,e),'inspection-edge-button');button.onclick=()=>callbacks.edge(e);links.append(button);
   if(e.type==='recorded_recheck_of')links.append(el('small',e.properties?.comparable===true?'Recorded criterion, input scope and environment are comparable.':'Check comparability is not established.','inspection-record'));
  }
  body.append(links);
  if(item.checks.length){const checks=el('details');checks.append(el('summary','Recorded checks · '+item.checks.length));for(const n of item.checks){const p=n.properties;checks.append(el('p',p.criterion_id+' · '+p.result+' · '+(p.basis||'Producer record'),'inspection-record'),el('pre',JSON.stringify(p,null,2)));}body.append(checks);}
  if(item.gaps.length)body.append(el('p',item.gaps.join(' '),'inspection-gaps'));
  body.append(el('p','These are saved links and reported check results. A retry alone does not establish task recovery.','inspection-intro'));
 }
 root.InspectionView={render};
})(globalThis);
