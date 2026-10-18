'use strict';
const RewardChecks=(()=>{
 async function render(host,{api,scope,onChange,onCustom}){
  host.replaceChildren();
  try{
   const data=(await api('/api/monitoring/options')).reward_checks;
   if(!data){host.textContent='Restart the collector to load reward-check setup.';return;}
   const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text)n.textContent=text;if(cls)n.className=cls;return n;};
   const note=el('p','Select saved measures to add their charts. Experimental behavior signals are not confirmed reward-hacking rates.','field-note');
   const label=el('label','Diagnostic observations'),select=el('select');label.append(select);
   const placeholder=el('option',data.observers.length?'Select a saved protocol':'No saved diagnostic observations');placeholder.value='';select.append(placeholder);
   for(const row of data.observers){const version=row.protocol_version?.split('/').pop();const option=el('option',row.label+(version?` · v${version}`:''));option.value=row.id;select.append(option);}
   if(data.observers.length===1)select.value=data.observers[0].id;
   const grid=el('div',null,'reward-check-list'),inputs=[];
   for(const row of data.checks){
    const item=el('label',null,'reward-check-option'),input=el('input');input.type='checkbox';input.value=row.id;
    item.title=row.description;
    input.disabled=row.observer_type==='diagnostic'&&!data.observers.length;
    const text=el('span'),name=el('strong',row.name),help=el('small',row.requires);text.append(name,help);item.append(input,text);grid.append(item);inputs.push(input);
    input.rewardCheck={row,item,name,help};
   }
   const describe=()=>{const observer=data.observers.find(row=>row.id===select.value);for(const input of inputs){const {row,item,name,help}=input.rewardCheck;const definition=observer?.checks?.[row.id];name.textContent=definition?.name||row.name;item.title=definition?.description||row.description;
    const unsupported=row.observer_type==='diagnostic'&&(!observer||(row.id!=='requirement_conflict'&&!definition));
    input.disabled=unsupported;if(unsupported)input.checked=false;
    help.textContent=unsupported?'Select an observer that provides this check.':row.requires;
   }};
   select.addEventListener('change',describe);describe();
   const actions=el('div',null,'custom-code-actions'),add=el('button','Add selected checks'),custom=el('button','Custom reward detector'),status=el('span');
   add.type=custom.type='button';status.setAttribute('role','status');
   add.onclick=async()=>{add.disabled=true;try{
    const checks=inputs.filter(input=>input.checked).map(input=>input.value);
    if(!checks.length){status.textContent='Select at least one check.';return;}
    const result=await api('/api/monitoring/reward-checks',{checks,observer:select.value,population:scope()});
    status.textContent=`${result.added.length} added · ${result.existing.length} already configured`;await onChange();
   }catch(error){status.textContent=error.message;}finally{add.disabled=false;}};
   custom.onclick=onCustom;actions.append(add,custom,status);
   host.append(note,label,grid,actions);
   if(!data.observers.length){const link=el('a','Configure diagnostic collection →');link.href='/connections#question-section';host.append(link);}
  }catch(error){host.textContent=error.message;}
 }
 return {render};
})();
if(typeof module!=='undefined')module.exports=RewardChecks;
