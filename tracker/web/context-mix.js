(function(root){
 'use strict';
 const palette={system:'#7460c7',developer:'#a674c2',user:'#3c76d8',assistant:'#35a59d',tool:'#e6a34b',tools:'#d77979',summary:'#6a91aa',memory:'#859657',retrieval:'#d18c55',other:'#96a0ad'};
 function cells(blocks,max=288){
  const total=blocks.reduce((s,b)=>s+b.chars,0);if(!total)return [];
  const size=Math.max(1,Math.ceil(total/max)),out=[];let offset=0,index=0;
  for(let start=0;start<total;start+=size){const end=Math.min(total,start+size),parts=[];
   while(index<blocks.length&&offset+blocks[index].chars<=start){offset+=blocks[index++].chars;}
   let p=offset;for(let i=index;i<blocks.length&&p<end;i++){const b=blocks[i],length=Math.max(0,Math.min(p+b.chars,end)-Math.max(p,start));if(length)parts.push({id:b.id,category:b.category,length});p+=b.chars;}
   out.push({start,end,parts});
  }return out;
 }
 const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
 const number=n=>n.toLocaleString();
 async function api(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined),data=await r.json();if(!r.ok)throw Error(data.error||'Context scan unavailable');return data;}
 function attach(host,run,event){
  if(!event||!['agent','assistant'].includes(event.actor))return;
  const button=el('button','Scan context','context-scan-trigger');button.type='button';button.title='Inspect the input mixture for this step';
  button.onclick=()=>open(run,event);host.append(button);
 }
 async function open(run,event){
  document.querySelector('.context-mix-dialog')?.close();document.querySelector('.context-mix-dialog')?.remove();
  const dialog=el('dialog',undefined,'context-mix-dialog'),head=el('header'),titleWrap=el('div'),title=el('h2','Context mix');title.id='context-mix-title';dialog.setAttribute('aria-labelledby',title.id);
  titleWrap.append(el('small','STEP '+event.id),title);const close=el('button','Close');close.type='button';close.onclick=()=>dialog.close();head.append(titleWrap,close);
  const content=el('div',undefined,'cm-content');content.append(el('p','Scanning recorded input…','cm-status'));content.setAttribute('aria-live','polite');dialog.append(head,content);document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
  try{const data=await api('/api/context-mix?'+new URLSearchParams({run,event:event.id}));if(!dialog.isConnected)return;content.removeAttribute('aria-live');content.replaceChildren();if(!data.available){content.append(el('p',data.reason));return;}render(content,data);}
  catch(error){content.replaceChildren(el('p',error.message,'cm-status'));}
 }
 function render(host,data){
  const top=el('div',undefined,'cm-top'),badge=el('span',data.basis==='captured_request'?'Captured model request':'Recorded history · request not captured','cm-basis');
  top.append(badge,el('span',number(data.total_chars)+' characters · '+data.blocks.length+' blocks','cm-count'));host.append(top);
  const note=el('p',data.basis==='captured_request'?'Input before the selected step. Select a tile to inspect its source.':'History before the selected step. The harness may have sent a different input. Select a tile to inspect its source.','cm-intro');host.append(note);
  if(data.previous){const p=data.previous;host.append(el('p',`Since ${p.event_id}: ${data.total_chars-p.chars>=0?'+':''}${number(data.total_chars-p.chars)} characters · ${p.added_blocks} added / ${p.removed_blocks} removed or rewritten blocks`,'cm-delta'));}
  const layout=el('div',undefined,'cm-layout'),left=el('div',undefined,'cm-map-side'),right=el('section',undefined,'cm-source');right.setAttribute('aria-label','Selected context block');layout.append(left,right);host.append(layout);
  const matrix=el('div',undefined,'cm-matrix');matrix.setAttribute('aria-label','Context composition, in recorded order');left.append(matrix);
  const tiles=cells(data.blocks),tileButtons=[];let chosen=data.blocks[0]?.id;
  const choose=(id,inspect=true)=>{chosen=id;for(const [button,tile] of tileButtons){const selected=tile.parts.some(p=>p.id===id);button.classList.toggle('is-selected',selected);button.setAttribute('aria-pressed',String(selected));}showBlock(id);if(inspect&&window.matchMedia('(max-width:720px)').matches)right.scrollIntoView({block:'nearest',behavior:'smooth'});};
  tiles.forEach((tile,i)=>{const b=el('button',undefined,'cm-cell');b.type='button';b.tabIndex=i===0?0:-1;const primary=tile.parts.reduce((a,p)=>p.length>a.length?p:a,tile.parts[0]);let sum=0;const stops=[];for(const p of tile.parts){const start=sum;sum+=100*p.length/(tile.end-tile.start);stops.push(`${palette[p.category]} ${start}% ${sum}%`);}b.style.background='linear-gradient(90deg,'+stops.join(',')+')';b.title=`Characters ${number(tile.start+1)}–${number(tile.end)} · ${[...new Set(tile.parts.map(p=>data.blocks.find(b=>b.id===p.id).label))].join(' / ')}`;b.setAttribute('aria-label',b.title);b.onclick=()=>choose(primary.id);b.onfocus=()=>{for(const [button] of tileButtons)button.tabIndex=button===b?0:-1;};b.onkeydown=e=>{const step={ArrowRight:1,ArrowLeft:-1,ArrowDown:24,ArrowUp:-24}[e.key]||0;if(step){e.preventDefault();tileButtons[Math.max(0,Math.min(tiles.length-1,i+step))][0].focus();}};tileButtons.push([b,tile]);matrix.append(b);});
  if(!tiles.length)matrix.append(el('p','No input blocks captured.'));
  const scale=el('div',undefined,'cm-scale');scale.append(el('span','Input start'),el('span','Latest context →'));left.append(scale,el('p','Area represents character volume. A tile can contain multiple colors.','cm-caption'));
  const legend=el('div',undefined,'cm-legend');for(const row of data.totals){const item=el('button');item.type='button';const swatch=el('i');swatch.style.background=palette[row.category];item.append(swatch,el('span',row.label),el('strong',`${(row.chars/Math.max(1,data.total_chars)*100).toFixed(1)}%`));item.onclick=()=>choose(data.blocks.find(b=>b.category===row.category).id);legend.append(item);}left.append(legend);
  const checks=el('div',undefined,'cm-checks');checks.append(el('h3',data.findings.length?'Inspection cues':'No composition cues found'));
  if(!data.findings.length)checks.append(el('p','This scan checks composition and repetition; it does not rule out a harness problem.'));
  for(const f of data.findings){const item=el('div',undefined,'cm-finding');item.append(el('strong',f.title),el('p',f.description));if(f.block_ids.length){const b=el('button','Inspect blocks');b.type='button';let n=0;b.onclick=()=>choose(f.block_ids[n++%f.block_ids.length]);item.append(b);}checks.append(item);}left.append(checks);
  function showBlock(id){
   right.replaceChildren();const index=data.blocks.findIndex(b=>b.id===id),block=data.blocks[index];if(!block)return;
   const nav=el('div',undefined,'cm-block-nav');const prev=el('button','←'),next=el('button','→');prev.setAttribute('aria-label','Previous context block');next.setAttribute('aria-label','Next context block');prev.disabled=index===0;next.disabled=index===data.blocks.length-1;prev.onclick=()=>choose(data.blocks[index-1].id);next.onclick=()=>choose(data.blocks[index+1].id);nav.append(el('small',`BLOCK ${index+1} / ${data.blocks.length}`),prev,next);right.append(nav);
   const heading=el('h3',block.label);heading.style.borderColor=palette[block.category];right.append(heading,el('p',`${number(block.chars)} characters · ${(100*block.chars/Math.max(1,data.total_chars)).toFixed(1)}% of context`,'cm-caption'),el('code',block.source_pointer,'cm-pointer'));
   const text=el('pre',block.text,'cm-block-text');text.tabIndex=0;right.append(text);
   const review=el('button','Review this block with Jev','cm-review');review.type='button';review.disabled=!data.jev_available;
   const status=el('p',data.jev_available?'Sends this block, recorded instructions and the selected action to Jev.':'Jev review: set JEV_API_KEY on the server to enable.','cm-caption');status.setAttribute('role','status');right.append(review,status);
   review.onclick=async()=>{review.disabled=true;status.textContent='Reviewing this block…';try{const result=await api('/api/context-mix/review',{run:data.run_id,event:data.event_id,block:block.id});if(chosen!==id||!right.isConnected)return;status.textContent=result.value.replaceAll('_',' ')+'. '+result.scope;const detail=el('details');detail.append(el('summary','Model scores · '+result.model));for(const [key,value] of Object.entries(result.probabilities))detail.append(el('p',`${key.replaceAll('_',' ')}: ${(100*value).toFixed(1)}%`));right.append(detail);}catch(error){if(chosen===id)status.textContent=error.message;}finally{review.disabled=false;}};
  }
  if(chosen)choose(chosen,false);
  const foot=el('footer');foot.append(el('span',data.measurement));const download=el('a','Export scan');download.href='/api/context-mix?'+new URLSearchParams({run:data.run_id,event:data.event_id,download:'1'});foot.append(download);host.append(foot);
 }
 const apiObject={cells,palette,attach};if(typeof module!=='undefined'&&module.exports)module.exports=apiObject;else root.ContextMix=apiObject;
})(typeof window!=='undefined'?window:globalThis);
