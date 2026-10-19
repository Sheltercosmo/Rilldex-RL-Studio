'use strict';
const RewardChecks=(()=>{
 function commands({database='study.sqlite',directory='reward-scan',experiment='',protocol='search',mode='run',budget=20,shell='powershell',selection=null,retryFailed=false}){
  if(!['source','chains','search','requirements'].includes(protocol)||!['run','watch'].includes(mode)||!['powershell','bash'].includes(shell))throw Error('Select a scan mode, check type and shell.');
  if(!/^\d+$/.test(String(budget))||!Number.isInteger(Number(budget))||Number(budget)>100000)throw Error('Call budget must be a whole number from 0 to 100,000.');
  const quote=v=>{v=String(v);if(!v.trim()||/[\r\n\0]/.test(v))throw Error('Use a nonempty, single-line path or experiment.');return "'"+v.replaceAll("'",shell==='powershell'?"''":"'\"'\"'")+"'";};
  const base='rilldex --db '+quote(database)+' monitor-rollouts ',folder=quote(directory);
  let scope=' --protocol '+protocol,targets=' --all-latest';
  if(selection?.kind==='explicit_latest'){
   if(mode==='watch')throw Error('A saved list of rollout IDs supports batch resume only.');
   if(!selection.run_ids?.length)throw Error('The saved rollout selection is empty.');
   targets=selection.run_ids.map(id=>' --run-id '+quote(id)).join('');
  }else{
   const exp=selection?selection.experiment:experiment;if(exp)scope+=' --experiment '+quote(exp);
   for(const adapter of selection?.adapters||[])scope+=' --adapter '+quote(adapter);
  }
  return {preview:base+'plan '+folder+scope+targets,run:base+mode+' '+folder+scope+(mode==='run'?targets:'')+' --max-new-calls '+Number(budget)+(retryFailed?' --retry-failed':''),status:base+'status '+folder};
 }
 function openScan({database='study.sqlite',experiment='',directory='reward-scan',protocol='search',selection=null,retryFailed=false}={}){
  document.getElementById('reward-scan-dialog')?.remove();
  const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  const modal=el('dialog');modal.id='reward-scan-dialog';modal.className='reward-scan-dialog';modal.setAttribute('aria-labelledby','reward-scan-title');
  const head=el('div');head.className='dialog-head';const title=el('h2','Scan setup & budget');title.id='reward-scan-title';const close=el('button','Close');close.type='button';close.onclick=()=>modal.close();head.append(title,close);modal.append(head);
  modal.append(el('p','Generate a worker command to run beside your database. This setup does not start scans or spend model calls.'));
  const form=el('div');form.className='reward-scan-fields';const inputs={};
  function field(key,label,value,choices){const wrap=el('label',label),input=el(choices?'select':'input');input.id='reward-scan-'+key;if(choices)for(const [v,text]of choices){const o=el('option',text);o.value=v;input.append(o);}input.value=value;wrap.append(input);form.append(wrap);inputs[key]=input;return input;}
  field('database','Database path',database);field('directory','Scan workspace · keep this to resume',directory);
  field('experiment',selection?.kind==='explicit_latest'?'Saved rollout selection':'Experiment · blank includes all',selection?.kind==='explicit_latest'?selection.run_ids.length+' selected rollout'+(selection.run_ids.length===1?'':'s'):selection?.experiment||(experiment==='__unassigned__'?'':experiment));
  field('protocol','Checks',protocol,[['search','Common reward-hacking behaviors'],['requirements','Task-specific requirement conflicts'],...(selection?[['chains','Evidence chains'],['source','Source diagnostics']]:[])]);
  field('mode','Collection mode','run',[['run','Scan existing rollouts'],['watch','Backfill, then follow new rollouts']]);
  const budget=field('budget','New model calls per worker launch',20);budget.type='number';budget.min='0';budget.max='100000';budget.step='1';
  field('shell','Terminal',typeof navigator!=='undefined'&&/Win/.test(navigator.platform)?'powershell':'bash',[['powershell','PowerShell · Windows / Linux / macOS'],['bash','Bash / zsh · Linux / macOS']]);
  if(selection){for(const k of ['database','directory','experiment','protocol'])inputs[k].disabled=true;if(selection.kind==='explicit_latest')inputs.mode.disabled=true;}
  const retryLabel=el('label'),retry=el('input');retry.type='checkbox';retry.checked=retryFailed;retry.id='reward-scan-retry';retryLabel.className='check-label';retryLabel.append(retry,el('span','Retry failed rollouts'));form.append(retryLabel);
  modal.append(form);const note=el('p','0 uses cached decisions only. The budget is shared across rollouts and the entire watch session. When it is exhausted, rerun with the same workspace to continue. A changed experiment or check type needs a different workspace.');note.className='field-note';modal.append(note,el('p','Environment filters apply to charts only. Configure Jev credentials and your proxy in the worker environment; no keys are stored by this form.'));
  const outputs={},feedback=el('p');feedback.setAttribute('role','status');
  for(const [key,label]of [['preview','1. Preview coverage · no model calls'],['run','2. Run or resume'],['status','3. Inspect scan progress']]){const block=el('section'),h=el('h3',label),pre=el('pre'),code=el('code'),copy=el('button','Copy');copy.type='button';copy.setAttribute('aria-label','Copy '+label);pre.append(code);block.append(h,pre,copy);modal.append(block);outputs[key]={code,copy};copy.onclick=async()=>{try{await navigator.clipboard.writeText(code.textContent);feedback.textContent='Command copied.';}catch{feedback.textContent='Copy unavailable. Select the command text instead.';}};}
  function update(){try{const values=Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.value]));const c=commands({...values,selection,retryFailed:retry.checked});for(const [k,v]of Object.entries(outputs)){v.code.textContent=c[k];v.copy.disabled=false;}feedback.textContent='';}catch(e){for(const v of Object.values(outputs)){v.code.textContent='';v.copy.disabled=true;}feedback.textContent=e.message;}}
  form.addEventListener('input',update);form.addEventListener('change',update);modal.append(feedback);document.body.append(modal);update();window.WorkspaceDialog?.prepare(modal);modal.showModal();
 }
 async function render(host,{api,scope,onChange,onCustom,database=()=> 'study.sqlite'}){
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
   const actions=el('div',null,'custom-code-actions'),add=el('button','Add selected checks'),custom=el('button','Custom reward detector'),scan=el('button','Scan setup & budget'),status=el('span');
   scan.type='button';scan.onclick=()=>openScan({database:database(),experiment:scope().experiment});
   add.type=custom.type='button';status.setAttribute('role','status');
   add.onclick=async()=>{add.disabled=true;try{
    const checks=inputs.filter(input=>input.checked).map(input=>input.value);
    if(!checks.length){status.textContent='Select at least one check.';return;}
    const result=await api('/api/monitoring/reward-checks',{checks,observer:select.value,population:scope()});
    status.textContent=`${result.added.length} added · ${result.existing.length} already configured`;await onChange();
   }catch(error){status.textContent=error.message;}finally{add.disabled=false;}};
   custom.onclick=onCustom;actions.append(add,scan,custom,status);
   host.append(note,label,grid,actions);
   if(!data.observers.length){const link=el('a','Configure diagnostic collection →');link.href='/connections#question-section';host.append(link);}
  }catch(error){host.textContent=error.message;}
 }
 return {render,commands,openScan};
})();
if(typeof module!=='undefined')module.exports=RewardChecks;
