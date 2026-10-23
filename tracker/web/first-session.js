/* First data and feature availability use recorded facts, never model inference. */
(function(root){
 'use strict';
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 function features(host,data){
  const grid=el('div',undefined,'feature-readiness');
  for(const f of data.features){const card=el('div',undefined,'feature-readiness-item'),link=el('a',f.label+' →');link.href=f.url;
   const labels={available:'Inputs available',needs_source:'Needs a source',needs_metadata:'Needs training metadata',awaiting_annotations:'Awaiting annotations',needs_telemetry:'Needs trainer logs',needs_timing:'Needs timing records'};
   card.append(link,el('span',labels[f.state]||'Needs input','readiness-state '+f.state),el('p',f.detail));grid.append(card);}
  host.append(grid);
 }
 function render(host,data){
  host.replaceChildren();host.hidden=!data;if(!data)return;
  document.body.classList.toggle('workspace-empty',data.empty);
  if(data.empty){
   host.append(el('h2','Start with a rollout'),el('p','Inspect saved traces, follow an active job, or open a small example. Collection and source inspection need no model credentials.'));
   const choices=el('div',undefined,'first-session-choices');
   const example=el('button',undefined,'first-session-choice');example.type='button';example.append(el('strong','Open an example'),el('span','A test-worker failure, retry and successful result. Synthetic data; no API calls.'));
   example.onclick=async()=>{example.disabled=true;const status=el('p','Opening example…');host.append(status);try{const r=await fetch('/api/example',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}),result=await r.json();if(!r.ok)throw Error(result.error||'Example unavailable');location.assign(result.url);}catch(e){status.textContent=e.message;example.disabled=false;}};
   choices.append(example);
   for(const [label,detail,url]of [['Import saved rollouts','Preview your files, then inspect their source records.','/connections#snapshot-section'],['Connect a running experiment','Collect existing outputs and follow new arrivals.','/connections#directory-section']]){const a=el('a',undefined,'first-session-choice');a.href=url;a.append(el('strong',label),el('span',detail));choices.append(a);}
   host.append(choices);return;
  }
  if(data.example){
   const note=el('div',undefined,'example-finding');note.append(el('strong','Example finding · a worker failure, followed by a successful retry'),el('p','The first test never started. The retry returned “4 tests passed.” Inspect the source calls and results, or follow the two attempts on Execution. All timings and outcomes in this example are authored.'));
   const source=el('a','Inspect test calls & results →');source.href='/semantic-map?'+new URLSearchParams({run:data.example_run,observer:'source',level:'units'});note.append(source);host.append(note);
  }
  const details=el('details');details.append(el('summary','Available analysis'));features(details,data);host.append(details);
 }
 root.FirstSession={render,features};
})(typeof window==='undefined'?globalThis:window);
