'use strict';
(()=>{
 const $=s=>document.querySelector(s), el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 let current=null,sequence=0;
 const form=$('#deployment-form'),result=$('#deployment-result'),status=$('#deploy-status');
 const shell=$('#deploy-shell');if(/Win/.test(navigator.platform))shell.value='powershell';
 async function api(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||'Request failed');return data;}
 function fields(){
  const c=$('#deploy-case').value,offline=c==='offline';
  for(const [id,hide] of [['deploy-root-label',offline],['deploy-mode-label',offline],['deploy-host-label',c!=='remote'],['deploy-stage-label',['docker','notebook','offline'].includes(c)],['deploy-producer-label',offline]])$('#'+id).hidden=hide;
  $('#deploy-root').required=!offline;
  $('#deploy-collector-shell-label').hidden=c!=='remote';
  $('#deploy-snapshot-label').hidden=offline||$('#deploy-mode').value!=='snapshots';
  $('#deploy-discovery').hidden=!['local','cloud'].includes(c);
  $('#deploy-pattern-label').hidden=offline||$('#deploy-mode').value==='native';
  $('#capture-bundle-receive').open=offline;
 }
 function invalidate(){sequence++;current=null;result.replaceChildren();status.textContent='Settings changed. Show the setup again for updated commands.';}
 form.addEventListener('input',invalidate);
 $('#deploy-mode').addEventListener('change',()=>{$('#deploy-pattern').value='';fields();});
 $('#deploy-case').addEventListener('change',()=>{
  const c=$('#deploy-case').value;
  $('#deploy-pattern').value='';
  $('#deploy-root').value=c==='cloud'?'s3://my-bucket/run-a/outputs':c==='docker'?(shell.value==='powershell'?'C:/jobs/run-a/outputs':'/jobs/run-a/outputs'):'./outputs';
  fields();invalidate();
 });
 function render(plan){
  result.replaceChildren();result.append(el('h3',plan.title));
  const actions=el('div',undefined,'form-actions');
  const download=el('button','Save setup instructions');download.type='button';download.onclick=()=>{
   const text=[plan.title,plan.install,...plan.steps.flatMap(s=>[s.title+' — '+s.where,s.code]),'Resume: '+plan.resume,...plan.constraints].join('\n\n');
   const url=URL.createObjectURL(new Blob([text],{type:'text/plain'})),a=el('a');a.href=url;a.download='rilldex-setup.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };actions.append(download);
  const manual=el('details',undefined,'deployment-manual');manual.append(el('summary',plan.launch_file?'Manual installation, UI launch & deployment details':'Deployment instructions'),el('p',plan.install,'muted'));
  if(plan.launch_file){const save=el('button','Download launch file');save.type='button';save.onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(plan.launch_file,null,2)+'\n'],{type:'application/json'})),a=el('a');a.href=url;a.download='job.rilldex.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};actions.prepend(save);}
  if(plan.connection){const use=el('button','Use this source in the current workspace');use.type='button';use.onclick=()=>{
   const c=plan.connection;$('#collection-mode').value=c.mode;$('#collection-mode').dispatchEvent(new Event('change'));
   $('#root').value=c.root;$('#producer').value=c.producer;$('#collection-experiment').value=c.metadata.experiment;
   $('#format').value=c.format||'auto';$('#metadata').value='{}';$('#connection-form').dispatchEvent(new Event('input',{bubbles:true}));
   if(c.pattern)$('#export-pattern').value=c.pattern;
   if(c.snapshot_state)$('#snapshot-state').value=c.snapshot_state;
   location.hash='directory-section';$('#root').focus();
  };actions.append(use);}
  manual.append(actions);
  if(plan.launch_file){
   const quick=el('article',undefined,'workflow-package'),intro=el('div'),runner=el('div',undefined,'workflow-run'),button=el('button','Download runnable workflow','primary'),notice=el('p',undefined,'workflow-footnote');button.type='button';notice.setAttribute('role','status');
   const batch=plan.stage==='after',cadenceLabel=el('label','Export cadence in follow mode'),cadence=el('select'),ops=el('div',undefined,'workflow-operations');cadence.setAttribute('aria-label','Capture workflow export cadence');
   for(const [value,label] of [[60,'Every minute · small scopes'],[300,'Every 5 minutes · recommended'],[900,'Every 15 minutes · larger scopes']]){const option=el('option',label);option.value=value;cadence.append(option);}cadence.value='300';cadenceLabel.append(cadence);
   intro.append(el('span','CAPTURE → ANALYZE → EXPORT','eyebrow'),el('h3',batch?'Replay a completed job':'Follow existing and new rollouts'),el('p',batch?'One batch collects available records and publishes saved SQL results and an indexed dataset. Incomplete records remain explicitly pending.':'Start before or during training. Missing directories wait; existing records catch up; new records follow. Saved SQL and dataset exports run on a separate schedule.'),el('p','Unzip on the collector host. Review source and database paths in rilldex.json. Keep the live database on local disk.'));
   runner.append(cadenceLabel,button,el('pre','python run.py --check\npython run.py'+(batch?'':' --follow'),'code'),el('small','Python 3.11+ · Capture polls every '+(plan.launch_file.source.interval||10)+'s between operations. Exports use the cadence above; large operations can delay the next poll.'));
   button.onclick=async()=>{button.disabled=true;notice.textContent='Bundling config, runner and local runtime…';try{const r=await fetch('/api/workflows/package',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({launch:plan.launch_file,publish_interval:Number(cadence.value)})});if(!r.ok){const e=await r.json();throw Error(e.error||'Packaging failed');}const url=URL.createObjectURL(await r.blob()),a=el('a');a.href=url;a.download='rilldex-capture-workflow.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);notice.textContent='Ready. Local capture and SQL need no installation. S3/GCS needs the generated requirements and host credentials. Nothing has been started.';}catch(e){notice.textContent=e.message;}finally{button.disabled=false;}};
   for(const [title,command,detail] of [['Check progress','python run.py status','Shows waiting input, export errors and the last complete dataset.'],['Resume safely','python run.py'+(batch?'':' --follow'),'Ctrl+C or SIGTERM stops. Repeat the command with the same folder and database.'],['Open the workspace','python run.py ui','Uses your selected port ('+plan.launch_file.port+'). Add --open locally, or use your SSH tunnel.']]){const item=el('div');item.append(el('strong',title),el('code',command),el('small',detail));ops.append(item);}
   quick.append(intro,runner,ops,notice,el('p','results/latest.json identifies the last complete export. results/status.json reports runner health. Failed analysis keeps accepted data and the previous export; follow mode retries on the next publication cycle.','workflow-footnote'));result.append(quick);
   manual.append(el('p','Already installed? Use the launch file for an interactive collector without automatic dataset publication.'),el('pre',plan.launch_command+' --check\n'+plan.launch_command,'code'));
  }else manual.open=true;
  plan.steps.forEach((s,i)=>{const card=el('article',undefined,'deployment-step'),top=el('div',undefined,'section-top'),copy=el('button','Copy');copy.type='button';copy.setAttribute('aria-label','Copy '+s.title);copy.onclick=async()=>{try{await navigator.clipboard.writeText(s.code);copy.textContent='Copied';}catch{copy.textContent='Select command to copy';}};
   const heading=el('div');heading.append(el('small',s.where),el('h4',(i+1)+'. '+s.title));top.append(heading,copy);card.append(top,el('pre',s.code,'code'));manual.append(card);
  });
  const restart=el('div',undefined,'deployment-resume');restart.append(el('h4','Stop and resume'),el('p',plan.resume));manual.append(restart);
  const first=el('div',undefined,'deployment-next');first.append(el('h4','After launch, open the new workspace'));
  if(!plan.browser_url)first.append(el('p','Use the browser address printed by launch, then open Connections, Rollouts and the Dashboard.'));
  else for(const [i,href] of ['/connections#worker-section','/runs','/'].entries()){const a=el('a',plan.first_value[i]);a.href=plan.browser_url+href;first.append(a);}manual.append(first);result.append(manual);
  const details=el('details');details.append(el('summary','Evidence requirements and deployment limits'));for(const text of plan.constraints)details.append(el('p',text));result.append(details);
 }
 form.onsubmit=async e=>{e.preventDefault();const request=++sequence;status.textContent='Preparing setup…';
  const body={case:$('#deploy-case').value,shell:shell.value,collector_shell:$('#deploy-collector-shell').value,stage:$('#deploy-stage').value,mode:$('#deploy-mode').value,format:$('#deploy-format').value,snapshot_state:$('#deploy-snapshot-state').value,root:$('#deploy-root').value,experiment:$('#deploy-experiment').value,database:$('#deploy-database').value,host:$('#deploy-host').value,port:Number($('#deploy-port').value)};
  if($('#deploy-producer').value.trim())body.producer=$('#deploy-producer').value.trim();
  if($('#deploy-mode').value!=='native'&&$('#deploy-pattern').value.trim())body.pattern=$('#deploy-pattern').value.trim();
  try{const plan=await api('/api/setup/plan',body);if(request!==sequence)return;current=plan;render(plan);status.textContent=plan.launch_file?'Ready. Download a runnable workflow, or expand the manual deployment options.':'Ready. Follow the instructions for your environment.';}catch(e){if(request===sequence){result.replaceChildren();status.textContent=e.message;}}
 };
 $('#capture-bundle-choose').onclick=()=>$('#capture-bundle-file').click();
 $('#capture-bundle-file').onchange=()=>{$('#capture-bundle-selection').textContent=$('#capture-bundle-file').files[0]?.name||'No file selected';$('#capture-bundle-receipt').hidden=true;};
 $('#capture-bundle-import').onclick=async()=>{
  const file=$('#capture-bundle-file').files[0],button=$('#capture-bundle-import'),out=$('#capture-bundle-status');
  if(!file){out.textContent='Choose an exported worker capture bundle first.';return;}
  if(file.size>14*1024*1024){out.textContent='Use the CLI for bundles larger than 14 MiB.';return;}
  $('#capture-bundle-receipt').hidden=true;button.disabled=true;out.textContent='Validating all packets, then receiving…';
  try{const base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});
   const r=await api('/api/capture/import',{base64});const receipt=$('#capture-bundle-receipt');receipt.hidden=!r.acknowledgments.length;receipt.onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify({schema:'jev-capture-receipts/1',acknowledgments:r.acknowledgments})],{type:'application/json'})),a=el('a');a.href=url;a.download='worker.receipts.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};out.textContent=`${r.accepted} new packets · ${r.already_present} already received · ${r.failed} failed. `+(r.complete?'Open Rollouts to inspect captured cases.':'Some packets failed; retry after resolving the listed conflicts. ')+r.errors.map(e=>e.packet+': '+e.error).join(' ');
  }catch(e){out.textContent=e.message;}finally{button.disabled=false;}
 };
 fields();
})();
