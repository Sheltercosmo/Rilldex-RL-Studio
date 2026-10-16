'use strict';
const ContinuationStudies = (() => {
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const number=n=>n===null||n===undefined?'—':n.toLocaleString('en-US');
 const percent=n=>n===null||n===undefined?'—':(100*n).toFixed(1)+'%';
 const points=n=>n===null||n===undefined?'—':(n>=0?'+':'')+(100*n).toFixed(1)+' pp';
 const studyKey=s=>JSON.stringify([s.producer,s.design.id]);
 let sequence=0;
 function download(value){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=el('a');a.href=url;a.download='continuation-evidence.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 function sourceLink(run,text){const a=el('a',text);a.href='/semantic-map?'+new URLSearchParams({run,level:'units'});return a;}
 function detail(row,arm){
  document.querySelector('.cs-dialog')?.remove();const d=el('dialog',undefined,'cs-dialog'),close=el('button','Close');close.onclick=()=>d.close();
  const head=el('div',undefined,'cs-dialog-head');head.append(el('h2',arm+' continuation'),close);d.append(head,el('p',row.sample.producer+' / '+row.sample.id));
  d.append(el('p',row.eligible?(row.outcome?'Verifier success':'Verifier failure'):'Excluded from the comparison: '+row.issues.join(', ').replaceAll('_',' ')));
  d.append(el('p','Generated tokens: '+number(row.generated_tokens)),el('p','Recorded training stages: '+(row.training_stages.join(', ').replaceAll('_',' ')||'Unavailable')));
  if(row.run_id)d.append(sourceLink(row.run_id,'Open unit map'));
  const evidence=el('details');evidence.append(el('summary','Sampling and record evidence'),el('pre',JSON.stringify(row,null,2)));d.append(evidence);
  d.addEventListener('close',()=>d.remove());document.body.append(d);d.showModal();
 }
 function ratePlot(arms,narrow=false){
  const width=narrow?340:620,plotWidth=narrow?195:400,left=narrow?55:98;
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${width} 150`);svg.setAttribute('role','img');svg.setAttribute('aria-label','Success rates before and after the selected span, on a zero to one hundred percent scale');
  svg.classList.add(narrow?'cs-narrow':'cs-wide');
  const add=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text!==undefined)n.textContent=text;svg.append(n);return n;};
  const x=v=>left+plotWidth*v;
  for(const p of [0,.25,.5,.75,1]){add('line',{x1:x(p),x2:x(p),y1:10,y2:114,class:'cs-grid'});add('text',{x:x(p),y:138,'text-anchor':'middle'},100*p+'%');}
  ['before','after'].forEach((arm,i)=>{const a=arms[arm],y=29+i*56;add('text',{x:4,y:y+5},arm==='before'?'Before':'After');
   if(a.rate!==null){add('rect',{x:x(0),y:y-10,width:plotWidth*a.rate,height:20,rx:3,class:'cs-rate '+arm});
    if(a.interval){add('line',{x1:x(a.interval[0]),x2:x(a.interval[1]),y1:y,y2:y,class:'cs-ci'});for(const p of a.interval)add('line',{x1:x(p),x2:x(p),y1:y-8,y2:y+8,class:'cs-ci'});}
   }
   add('text',{x:left+plotWidth+12,y:y+5},a.rate===null?'—':percent(a.rate));
  });return svg;
 }
 function draw(root,payload,scope,reload){
  root.replaceChildren();const top=el('div',undefined,'cs-heading');top.append(el('div'));top.firstChild.append(el('h2','Continuation experiments'),el('p','Compare outcomes sampled from the prefixes before and after a selected span.'));
  const guide=el('a','Capture guide');guide.href='/integration-guide#continuation-experiments';top.append(guide);
  const importButton=el('button','Import study design'),input=el('input');input.type='file';input.accept='.json,application/json';input.hidden=true;
  importButton.onclick=()=>input.click();input.onchange=async()=>{if(!input.files[0])return;importButton.disabled=true;try{const body=JSON.parse(await input.files[0].text()),r=await fetch('/api/continuation-studies',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),v=await r.json();if(!r.ok)throw Error(v.error||'Import failed');await reload();}catch(e){const p=el('p',e.message,'th-error');top.append(p);}finally{importButton.disabled=false;}};top.append(importButton,input);root.append(top);
  if(!payload.studies.length){root.append(el('p','No continuation studies in this scope. Import an immutable study design, then send its samples and binary verifier scores through training-records/2. Results update as those records arrive.','th-empty'));const code=el('pre','python -m rilldex --db PATH continuation-studies import study.json\npython -m rilldex --db PATH training-records import samples-and-scores.json');root.append(code);return;}
  const controls=el('div',undefined,'cs-controls'),label=el('label','Study'),select=el('select');label.append(select);const current=new URLSearchParams(location.search).get('continuation_study');
  payload.studies.forEach(s=>{const o=el('option',s.design.label);o.value=studyKey(s);select.append(o);});
  if(payload.studies.some(s=>studyKey(s)===current))select.value=current;
  const selected=()=>payload.studies.find(s=>studyKey(s)===select.value)||payload.studies[0];
  const exportButton=el('button','Export displayed evidence');exportButton.onclick=()=>download(selected());controls.append(label,exportButton);
  const pagination=el('div',undefined,'cs-pagination');pagination.append(el('span',`${payload.offset+1}–${payload.offset+payload.studies.length} of ${payload.total} studies`));
  for(const [title,offset,disabled]of [['Previous',payload.offset-payload.limit,payload.offset===0],['Next',payload.offset+payload.limit,payload.offset+payload.limit>=payload.total]]){const b=el('button',title);b.disabled=disabled;b.onclick=()=>{const u=new URL(location.href);u.searchParams.set('continuation_offset',offset);u.searchParams.delete('continuation_study');history.replaceState(null,'',u);reload();};pagination.append(b);}controls.append(pagination);root.append(controls);
  const content=el('div');root.append(content);select.onchange=()=>{const u=new URL(location.href);u.searchParams.set('continuation_study',select.value);history.replaceState(null,'',u);renderStudy(content,selected());};renderStudy(content,selected());
 }
 function renderStudy(root,s){
  root.replaceChildren();const d=s.design,b=s.arms.before,a=s.arms.after;
  const badge=el('p',d.confirmation_of?'Confirmation · '+String(s.confirmation_status).replaceAll('_',' '):d.selection==='retrospective'?'Discovery · window selected retrospectively':d.selection==='prospective'?'Prospective window':'Window selection timing unknown','cs-status');root.append(badge);
  root.append(el('p',`${s.experiment} · ${d.task_id} · policy ${d.policy_version}`,'th-coverage'));
  if(s.unplanned_samples.length)root.append(el('p',`${s.unplanned_samples.length} additional declared samples fall outside this fixed design and are excluded.`,'cs-status'));
  const stats=el('div',undefined,'cs-stats');for(const [title,value,note]of [
   ['After − before',points(s.difference),s.interval?'Nominal 95% interval: '+points(s.interval[0])+' to '+points(s.interval[1]):'Interval unavailable'],
   ['Selected span',number(s.span_tokens)+' tokens',s.prefix_verified?'Prefix boundaries match the master tokens':'Declared interval; master match unavailable'],
   ['Probe generation',number(a.generated_tokens+b.generated_tokens)+' tokens',`${a.cost_coverage+b.cost_coverage} / ${a.expected+b.expected} samples have token costs; excludes prefill and judging`]
  ]){const card=el('article');card.append(el('span',title),el('strong',value),el('p',note));stats.append(card);}root.append(stats);
  if(s.issues.length){const issues=el('div',undefined,'cs-alert');issues.append(el('strong','Comparison unavailable'));for(const issue of s.issues)issues.append(el('p',issue));root.append(issues);}
  const chart=el('section',undefined,'th-panel cs-plot');chart.append(el('h3','Continuation success'),ratePlot(s.arms),ratePlot(s.arms,true),el('p',`Before: ${b.successes} / ${b.observed} eligible, ${b.expected} planned. After: ${a.successes} / ${a.observed} eligible, ${a.expected} planned.`));
  chart.append(el('p',s.interval?'Lines show nominal 95% intervals, conditional on this selected window.':'Partial rates describe eligible received results only; no interval is shown without complete compatible evidence and declared independent draws.','th-coverage'));root.append(chart);
  const map=el('section',undefined,'cs-map');map.append(el('h3','Sampling branches'));
  const master=el('div',undefined,'cs-master');master.append(el('strong','Selected trajectory'),el('span',d.master.id));if(s.master.run_id)master.append(sourceLink(s.master.run_id,'Open unit map'));map.append(master);
  const branches=el('div',undefined,'cs-branches');for(const arm of ['before','after']){const group=s.arms[arm],gate=d.arms[arm],branch=el('section',undefined,'cs-branch '+arm),head=el('div',undefined,'cs-gate');head.append(el('strong',arm==='before'?'Before the span':'After the span'),el('span','Prefix: '+number(gate.prefix_tokens)+' tokens'),el('span',group.observed+' / '+group.expected+' eligible outcomes'));branch.append(head);
   const grid=el('div',undefined,'cs-draws');group.cases.forEach((row,i)=>{const state=row.eligible?(row.outcome?'success':'failure'):'unknown',button=el('button',(i+1)+' · '+(state==='success'?'Pass':state==='failure'?'Fail':'—'),'cs-draw '+state);button.setAttribute('aria-label',(arm==='before'?'Before':'After')+' continuation '+(i+1)+': '+(state==='unknown'?'unavailable':state));button.title=row.sample.id;button.onclick=()=>detail(row,arm==='before'?'Before':'After');grid.append(button);});branch.append(grid);branches.append(branch);}map.append(branches,el('p','Each tile is one planned continuation. Open it for the rollout map, sampling evidence and recorded training use.','th-coverage'));root.append(map);
  const methods=el('details',undefined,'cs-methods');methods.append(el('summary','Design, interpretation and evidence'),el('p',s.interpretation),el('p',s.interval_method),el('p','State restoration fidelity and sampling settings are producer declarations. Fresh identities do not independently prove fresh execution. No training weights are changed.'),el('pre',JSON.stringify(d,null,2)));root.append(methods);
 }
 async function load(root,scope){const seq=++sequence;root.classList.add('continuation-studies');root.replaceChildren(el('p','Loading continuation evidence…'));const filters={limit:10,offset:Math.max(0,Number(new URLSearchParams(location.search).get('continuation_offset'))||0)};for(const k of ['experiment','environment'])if(scope[k])filters[k]=scope[k];
  try{const r=await fetch('/api/continuation-studies?'+new URLSearchParams(filters)),v=await r.json();if(seq!==sequence||!root.isConnected)return;if(!r.ok)throw Error(v.error||'Continuation evidence unavailable');draw(root,v,scope,()=>load(root,scope));}catch(e){if(seq===sequence)root.replaceChildren(el('p',e.message,'th-error'));}
 }
 return {load};
})();
