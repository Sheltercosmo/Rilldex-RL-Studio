'use strict';
(()=>{
 const root=document.querySelector('#training-setup');if(!root)return;
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const result=root.querySelector('[data-result]'),status=root.querySelector('[data-status]'),input=root.querySelector('input');
 let sequence=0;
 async function check(body,example=false){const seq=++sequence;result.replaceChildren();status.textContent='Reading training settings…';try{
  const r=await fetch('/api/training-setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),d=await r.json();if(seq!==sequence)return;if(!r.ok)throw Error(d.error||'Could not read settings.');
  status.textContent=example?'Example configuration · no training data loaded':(d.status==='ready'?'Settings recognized · no training data loaded':'Settings need review · no training data loaded');
  root.querySelector('.section-top a').href='/integration-guide#'+(['openrlhf','slime'].includes(d.framework)?'native-rl-settings':'training-setup');
  result.append(el('h3',(d.monitoring_plan?.framework||d.framework)+' · '+d.label.split(' · ')[0]));const grid=el('dl',undefined,'setup-facts');
  const names={none:'No policy ratio; correction weights are separate',unknown:'Not recorded',group_relative:'Rewards within a prompt group',critic:'Learned value estimates',return:'Reward returns',hard_gate:'Clipped policy objective',capped:'Capped importance weights',smooth:'Smooth weights',token:'Per token',sample:'Per sample',sequence:'Per sequence',turn:'Per generated turn',synchronous:'Synchronous',asynchronous:'Asynchronous','seq-mean-token-mean':'Equal weight per sequence','token-mean':'Mean over active tokens'};
  for(const [name,value] of [['Credit assignment',d.profile.estimator],['Credit unit',d.profile.credit_unit],['Policy ratio',d.profile.ratio_unit],['Loss averaging',d.profile.reduction],['Execution mode',d.profile.scheduling]]){grid.append(el('dt',name),el('dd',names[value]||String(value).replaceAll('_',' ')));}result.append(grid);
  for(const issue of d.issues)result.append(el('p',issue.message,'setup-notice'));
  result.append(el('h3','Your monitoring priorities'),el('p','Selected from these RL settings. Existing metrics become available when their required records arrive; no per-metric tuning is needed.','setup-estimator'));const cards=el('div',undefined,'setup-monitors');
  for(const group of d.monitoring_plan?.groups||[]){const card=el('article');card.dataset.monitoringGroup=group.id;card.append(el('small',group.basis,'setup-basis'),el('h4',group.title),el('p',group.why));
   const list=el('ul');for(const m of group.monitors){const item=el('li');item.append(el('strong',m.label));const detail=el('details');detail.append(el('summary',m.state==='capture_pending'?'Capture requirements':'Required records'),el('p',m.reason),el('p',m.requires));item.append(detail);list.append(item);}card.append(list);const link=el('a','Open '+(group.id==='selection'||group.id==='freshness'?'training data':'training health')+' →');link.href=group.href;card.append(link);cards.append(card);}result.append(cards);
  const axes=el('details',undefined,'setup-axes');axes.append(el('summary','Which timeline should I use?'));for(const axis of d.monitoring_plan?.time_axes||[])axes.append(el('strong',axis.label),el('p',axis.meaning));result.append(axes);
  result.append(el('p',d.boundary,'muted'));
  const detail=el('details');detail.append(el('summary','Recognized settings and source'));const source=el('a','Pinned framework implementation');source.href=d.source.url;source.target='_blank';source.rel='noopener';detail.append(source,el('pre',JSON.stringify(d.settings,null,2)));result.append(detail);
  const actions=el('div',undefined,'form-actions'),download=el('button','Download setup report');download.type='button';download.onclick=()=>{const u=URL.createObjectURL(new Blob([JSON.stringify({...d,example},null,2)],{type:'application/json'})),a=el('a');a.href=u;a.download='training-setup.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};actions.append(download);const a=el('a','Open training health →');a.href='/?view=health';actions.append(a);result.append(actions);
 }catch(e){if(seq===sequence)status.textContent=e.message;}}
 input.onchange=async()=>{const f=input.files[0];if(!f)return;const u=new URL(location.href);u.searchParams.delete('setup_example');history.replaceState(null,'',u);try{if(f.size>1024*1024)throw Error('Use a resolved settings export under 1 MiB.');await check(JSON.parse(await f.text()));}catch(e){++sequence;result.replaceChildren();status.textContent=e.message;}};
 root.querySelector('[data-choose]').onclick=()=>input.click();
 const chooser=root.querySelector('#setup-example'),preview=root.querySelector('[data-preview]');
 async function loadExamples(){try{
  const r=await fetch('/api/training-setup');if(!r.ok)throw Error('Configuration examples are unavailable');const d=await r.json();chooser.replaceChildren();
  for(const row of d.examples){const o=el('option',row.label);o.value=row.id;chooser.append(o);}
  preview.disabled=false;
  chooser.onchange=()=>{++sequence;result.replaceChildren();status.textContent='Select Preview settings to inspect this configuration.';const u=new URL(location.href);u.searchParams.delete('setup_example');history.replaceState(null,'',u);};
  preview.onclick=()=>{const u=new URL(location.href);u.searchParams.set('setup_example',chooser.value);history.replaceState(null,'',u);return check(d.examples.find(x=>x.id===chooser.value).request,true);};
  const saved=new URLSearchParams(location.search).get('setup_example');if(d.examples.some(x=>x.id===saved)){chooser.value=saved;await preview.onclick();}
 }catch(e){chooser.replaceChildren(el('option',e.message));}}

 loadExamples();
})();
