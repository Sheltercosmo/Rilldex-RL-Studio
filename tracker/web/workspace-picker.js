/* Changing views never redirects an existing collector to another database. */
window.WorkspacePicker={install(host){
 const css=document.createElement('link');css.rel='stylesheet';css.href='/workspace-picker.css';document.head.append(css);
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const button=(text,action)=>{const n=el('button',text);n.type='button';n.onclick=action;return n;};
 const currentView=()=>location.pathname+location.search+location.hash;
 const label=el('strong','Local workspace'),hint=el('span','Switch workspace');
 const trigger=button('',show);trigger.className='workspace-picker-trigger';trigger.setAttribute('aria-label','Switch workspace');trigger.append(label,hint);host.replaceChildren(trigger);host.classList.add('workspace-picker-host');
 fetch('/api/workspace-identity').then(r=>r.json()).then(w=>{label.textContent=w.label||w.name;trigger.title=w.name;}).catch(()=>{});
 let dialog,rows=[],catalog,busy=false;
 async function request(path,value){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)}),v=await r.json();if(!r.ok)throw Error(v.error||'Workspace request failed');return v;}
 async function show(){
  if(dialog?.open)return;
  dialog=el('dialog',undefined,'workspace-picker-dialog');dialog.setAttribute('aria-label','Workspaces');
  const head=el('div',undefined,'workspace-picker-head'),close=button('Close',()=>dialog.close());head.append(el('h2','Workspaces'),close);
  const body=el('div',undefined,'workspace-picker-body'),search=el('input'),list=el('div',undefined,'workspace-picker-list'),status=el('p',undefined,'workspace-picker-status');
  search.type='search';search.placeholder='Find a workspace…';search.setAttribute('aria-label','Find a workspace');status.setAttribute('role','status');status.textContent='Loading workspaces…';
  body.append(search,list,status);dialog.append(head,body);document.body.append(dialog);dialog.onclose=()=>{dialog.remove();trigger.focus();};dialog.showModal();search.focus();
  async function open(options){
   if(busy)return;busy=true;status.textContent='Opening workspace…';dialog.setAttribute('aria-busy','true');
   try{const result=await request('/api/workspaces/open',{...options,current_view:currentView()});location.assign(result.url);}
   catch(error){status.textContent=error.message;busy=false;dialog.removeAttribute('aria-busy');}
  }
  function render(){
   list.replaceChildren();const term=search.value.toLowerCase();
   for(const row of rows.filter(r=>(r.name+' '+r.path).toLowerCase().includes(term))){
    const card=el('article',undefined,'workspace-picker-row');if(row.current)card.classList.add('is-current');
    const title=el('div',undefined,'workspace-picker-row-title');title.append(el('h3',row.name),el('span',{current:'Current',open:'Open',closed:'Closed',missing:'File missing',opening:'Opening'}[row.state],'workspace-picker-state'));
    card.append(title,el('p',row.path,'workspace-picker-path'));
    const actions=el('div',undefined,'workspace-picker-actions');
    if(!row.current&&row.state!=='missing'){
     const go=button('Open',()=>open({id:row.id}));go.disabled=!catalog.can_open||row.state==='opening';go.setAttribute('aria-label','Open '+row.name);actions.append(go);
    }
    if(['closed','missing'].includes(row.state))actions.append(button('Remove from recents',async()=>{try{await request('/api/workspaces/forget',{id:row.id});rows=rows.filter(r=>r.id!==row.id);render();status.textContent='Removed from recents. Database files are unchanged.';}catch(e){status.textContent=e.message;}}));
    if(actions.childElementCount)card.append(actions);list.append(card);
   }
   if(!list.childElementCount)list.append(el('p','No matching workspaces.'));
  }
  search.oninput=render;
  try{
   const response=await fetch('/api/workspaces');catalog=await response.json();if(!response.ok)throw Error(catalog.error);rows=catalog.rows;render();status.textContent='';
   const add=el('details',undefined,'workspace-picker-add');add.append(el('summary','Open or create a workspace'));
   if(!catalog.can_open){add.append(el('p','For container deployments, start a separate server for each workspace.'));body.append(add);return;}
   const form=el('form'),modeLabel=el('label','Action'),mode=el('select');mode.setAttribute('aria-label','Action');mode.append(new Option('Open existing','open'),new Option('Create workspace','create'));modeLabel.append(mode);
   const pathLabel=el('label','Database path'),path=el('input');path.required=true;path.placeholder='study.sqlite';pathLabel.append(path);
   const nameLabel=el('label','Workspace name'),name=el('input');name.maxLength=120;nameLabel.append(name);nameLabel.hidden=true;
   const submit=el('button','Open workspace');submit.type='submit';mode.onchange=()=>{nameLabel.hidden=mode.value!=='create';submit.textContent=mode.value==='create'?'Create workspace':'Open workspace';};
   form.append(modeLabel,pathLabel,el('p','Paths are on this server. Relative paths start in '+catalog.path.replace(/[/\\][^/\\]+$/,''),'workspace-picker-note'),nameLabel,submit);
   form.onsubmit=e=>{e.preventDefault();open({path:path.value,create:mode.value==='create',...(mode.value==='create'&&name.value.trim()?{name:name.value.trim()}:{})});};
   add.append(form);body.append(add,el('p','Each workspace keeps its projects, comparisons and capture endpoint. Switching leaves collection running. Workspaces opened here close when their launching server stops.','workspace-picker-note'));
  }catch(error){status.textContent=error.message;}
 }
 window.addEventListener('pagehide',()=>{fetch('/api/workspaces/view',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({view:currentView()}),keepalive:true}).catch(()=>{});});
}};
