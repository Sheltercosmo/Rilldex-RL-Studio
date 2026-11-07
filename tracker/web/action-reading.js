(function(root){
 'use strict';
 const labels={explore:'Gather information',apply:'Apply approach',verify:'Check an expected result',coordinate:'Coordinate',report:'Report',mixed:'Combined purposes',repeat:'Repeat operation',parameter_change:'Adjust settings or inputs',method_change:'Change method',gather_information:'Gather more information',continue:'Continue approach',not_applicable:'No earlier feedback',unresolved:'Unresolved'};
 function display(field){return field?.status==='decided'?labels[field.value]||field.value.replaceAll('_',' '):field?.status==='not_applicable'?'No earlier feedback':'Unresolved';}
 function el(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}
 async function api(run,event,read=false){const url='/api/action-reading',r=await fetch(read?url:url+'?'+new URLSearchParams({run,event}),read?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run,event})}:undefined),value=await r.json();if(!r.ok)throw Error(value.error||'Action reading unavailable');return value;}
 function attach(host,run,event,{onSource}={}){
  if(!event||event.kind!=='action'||event.actor!=='agent'||event.copied_context)return;
  const box=el('details',undefined,'action-reading'),heading=el('summary','Action reading'),content=el('div',undefined,'ar-content');box.append(heading,content);host.append(box);
  let loaded=false,busy=false;
  function render(data){
   content.replaceChildren();
   if(data.status==='uninspected')content.append(el('p','Read this action’s purpose and how it follows earlier feedback.','ar-note'));
   else{
    const grid=el('dl',undefined,'ar-values');
    for(const [key,title] of [['mode','Purpose'],['feedback_response','After feedback']]){const cell=el('div'),field=data.fields[key];cell.dataset.kind=field?.status==='decided'?field.value:'unresolved';cell.append(el('dt',title),el('dd',display(field)));grid.append(cell);}
    content.append(grid);
    if(data.status==='outdated')content.append(el('p','The saved reading needs refresh.','ar-note'));
    if(data.reviewed)content.append(el('p','Includes your saved review.','ar-note'));
    const sources=el('div',undefined,'ar-sources');
    for(const [id,title] of [[data.previous_action,'Previous action'],...data.previous_feedback.map(id=>[id,'Earlier feedback'])])if(id&&onSource){const button=el('button',title);button.type='button';button.onclick=()=>onSource(id);sources.append(button);}
    if(sources.childNodes.length)content.append(sources);
    const evidence=el('details',undefined,'ar-evidence');evidence.append(el('summary','Evidence & definition'),el('p',data.scope,'ar-note'));
    if(data.feedback_support?.status!=='available')evidence.append(el('p',data.feedback_support?.reason,'ar-note'));
    evidence.append(el('p',`${data.model} · ${data.harness}`,'ar-note'),el('pre',JSON.stringify({choices:data.fields,provenance:data.provenance},null,2)));content.append(evidence);
   }
   if(!data.reusable){const action=el('button',data.status==='uninspected'?'Read this action':'Refresh action reading','ar-read');action.type='button';action.disabled=!data.configured;content.append(action);
    const status=el('p',data.configured?'Uses one Jev request for this action.':'Configure Jev in Connections to read actions.','ar-note');status.setAttribute('role','status');content.append(status);
    if(!data.configured){const link=el('a','Open model setup');link.href='/connections#model-section';content.append(link);}
    action.onclick=async()=>{if(busy)return;busy=true;action.disabled=true;status.textContent='Reading action and preceding feedback…';try{const value=await api(run,event.id,true);if(box.isConnected)render(value);}catch(error){if(box.isConnected){status.textContent=error.message;action.disabled=false;}}finally{busy=false;}};
   }
  }
  box.addEventListener('toggle',async()=>{if(!box.open||loaded)return;loaded=true;content.textContent='Loading saved reading…';try{const data=await api(run,event.id);if(box.isConnected)render(data);}catch(error){if(box.isConnected)content.textContent=error.message;loaded=false;}});
 }
 const exports={attach,display};if(typeof module!=='undefined'&&module.exports)module.exports=exports;else root.ActionReading=exports;
})(typeof window!=='undefined'?window:globalThis);
