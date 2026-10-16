'use strict';
// Display names are separate from values used by URLs, queries and saved records.
(function(root){
 const opaque=value=>/^(?:[a-z][a-z0-9_-]*[:/-])?[a-f0-9]{12,}$/i.test(String(value||''));
 function name(id,label,fallback='Saved set'){
  if(label&&label!==id){
   // Generated observation labels append their entire upstream provenance chain.
   // Keep the set name and qualification here; preserve the full label in details.
   if(/^(procedure-review|work-mentions|work-outline)-/.test(id)&&/^(Reviewed procedures|Source-reviewed local work|Reviewed work outline) · /.test(label)){
    const parts=String(label).split(' · '),status=parts.slice(1).filter(p=>/^(development|experimental\b|partial experiment)/i.test(p));
    return [parts[0],...new Set(status)].join(' · ');
   }
   return String(label);
  }
  if(id==='source')return 'Recorded source';
  if(!id)return fallback;
  const stem=String(id).replace(/[-_:][a-f0-9]{12,}$/i,'').replace(/\/\d+$/,'');
  if(opaque(stem)||/^(saved|observer|graph|monitor)$/i.test(stem))return fallback;
  const text=stem.replace(/[_-]+/g,' ').trim();
  return text?text[0].toUpperCase()+text.slice(1):fallback;
 }
 function choices(rows,{fallback='Saved set',noun='Set'}={}){
  const items=rows.map(r=>({...r,id:String(r.id),detail:r.detail||r.label||String(r.id),label:name(r.id,r.label,fallback)})),groups=new Map();
  for(const r of items){const key=r.label.toLocaleLowerCase();if(!groups.has(key))groups.set(key,new Set());groups.get(key).add(r.id);}
  return items.map(r=>{
   const ids=[...groups.get(r.label.toLocaleLowerCase())].sort();
   const disambiguator=ids.length>1?' · '+noun+' '+(ids.indexOf(r.id)+1):'';
   return {...r,label:r.label+disambiguator+(r.suffix?' · '+r.suffix:''),
    title:[r.detail||r.label,'Identifier: '+r.id].join('\n')};
  });
 }
 function option(row){const o=document.createElement('option');o.value=row.id;o.textContent=row.label;o.title=row.title||'Identifier: '+row.id;return o;}
 function rollout(run){
  const m=run.metadata||{},task=m.task_id;
  const label=task&&!opaque(task)?String(task):name(m.environment,null,'Rollout');
  return label+(m.training_step!=null?' · Step '+m.training_step:'')+(m.rollout_n!=null?' · Repeat '+m.rollout_n:'');
 }
 const api={name,choices,option,rollout};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.ChoiceLabels=api;
})(typeof window!=='undefined'?window:globalThis);
