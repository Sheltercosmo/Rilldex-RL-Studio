'use strict';
(()=>{
 const $=id=>document.getElementById(id),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 for(const ids of [
  {form:'deployment-form',root:'deploy-root',button:'deploy-detect',result:'deploy-discovery-result',mode:'deploy-mode',pattern:'deploy-pattern',producer:'deploy-producer',experiment:'deploy-experiment',format:'deploy-format'},
  {form:'connection-form',root:'root',button:'source-detect',result:'source-discovery-result',mode:'collection-mode',pattern:'export-pattern',producer:'producer',experiment:'collection-experiment',format:'format'}
 ]){
  let sequence=0;
  const host=$(ids.result),button=$(ids.button);
  $(ids.root).addEventListener('input',()=>{sequence++;host.replaceChildren();});
  if(ids.form==='deployment-form')$('deploy-case').addEventListener('change',()=>{sequence++;host.replaceChildren();});
  button.onclick=async()=>{
   const root=$(ids.root).value.trim(),request=++sequence;
   if(!root){host.replaceChildren(el('p','Enter the output directory or cloud prefix first.'));return;}
   button.disabled=true;host.replaceChildren(el('p','Reading a bounded sample…'));
   try{
    const response=await fetch('/api/connections/discover',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({root})});
    const r=await response.json();if(request!==sequence)return;if(!response.ok)throw Error(r.error||'Source discovery failed');
    host.replaceChildren();
    const title=r.status==='empty'?'No output to identify yet':r.status==='mixed'?'Several capture layouts found':r.routes.length?'Source layout detected':'No supported trajectory decoded in this sample';
    host.append(el('h3',title),el('p',`${r.sampled_files} files sampled · ${r.candidate_files} candidate files seen${r.incomplete?' · discovery is incomplete':''}`,'muted'));
    if(r.status==='empty')host.append(el('p','Choose the layout your job will write, or detect again after its first output. An empty folder does not identify a framework.'));
    if(r.status==='mixed')host.append(el('p','Choose the source you intend to follow. Collecting the same trajectory from several layouts can count it twice.'));
    for(const route of r.routes){
     const card=el('article',undefined,'discovery-route');card.append(el('strong',route.label),el('p',`${route.files_decoded} sampled files · ${Object.keys(route.formats).join(', ')}`));
     card.append(el('small','Examples: '+route.examples.join(' · ')));
     if(route.pattern)card.append(el('p','Suggested filename rule: '+route.pattern));
     if(route.pattern&&!/[?*\[]/.test(route.pattern))card.append(el('small','Only this filename is followed, including in subdirectories. Other filenames require another rule.'));
     if(route.producers.length)card.append(el('p','Recorded producer: '+route.producers.join(', ')));
     if(route.experiments.length)card.append(el('p','Recorded experiment: '+route.experiments.join(', ')));
     if(route.mode==='import'){const a=el('a','Open file import');a.href='#snapshot-section';card.append(el('p','This file contains a bundle. Use a complete-file import to retain its records.'),a);}
     else if(route.applicable){const apply=el('button','Use this layout');apply.type='button';apply.onclick=()=>{
      $(ids.mode).value=route.mode;$(ids.mode).dispatchEvent(new Event('change',{bubbles:true}));
      if(route.pattern)$(ids.pattern).value=route.pattern;
      if(ids.format)$(ids.format).value='auto';
      if(route.producers.length===1)$(ids.producer).value=route.producers[0];
      if(route.experiments.length===1&&!$(ids.experiment).value.trim())$(ids.experiment).value=route.experiments[0];
      $(ids.form).dispatchEvent(new Event('input',{bubbles:true}));
      if(ids.pattern==='deploy-pattern'&&route.pattern)$(ids.pattern).closest('details').open=true;
      apply.textContent='Layout applied';host.append(el('p','Settings updated. Check the source before connecting. The collector validates records as they arrive.','muted'));
     };card.append(apply);}
     else card.append(el('p',route.producers.length>1?'Multiple recorded producers require separate source connections or offline worker bundles. Do not rename them to a shared identity.':'This layout overlaps unresolved or different files. Select a narrower output directory or an explicit filename rule, then check the source.'));
     host.append(card);
    }
    const unresolved=r.samples.filter(s=>s.status!=='decoded');
    if(unresolved.length){const details=el('details');details.open=!r.routes.length;details.append(el('summary',`${unresolved.length} unresolved or unfinished sample items`));for(const row of unresolved)details.append(el('p',`${row.path}${row.line?' · line '+row.line:''}: ${row.detail}`));host.append(details);}
    if(r.cloud?.errors?.length)for(const error of r.cloud.errors)host.append(el('p',error.path+': '+error.error));
    host.append(el('small',r.note,'muted'));
   }catch(e){if(request===sequence)host.replaceChildren(el('p',e.message));}finally{button.disabled=false;}
  };
 }
})();
