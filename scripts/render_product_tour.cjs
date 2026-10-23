/* Focused, self-contained SVG product views from the saved tour fixture.
 * Uses the application's smoothing and execution grouping; no raster editing.
 */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {smoothPoints,comparable}=require('../tracker/web/trainer-telemetry.js');
const {model}=require('../tracker/web/training-execution.js');
const data=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
assert.equal(data.synthetic,true);
const out=path.resolve(__dirname,'../docs/assets/demo');
const brand=fs.readFileSync(path.resolve(__dirname,'../tracker/web/rilldex-logo.svg'),'utf8').replace(/<svg[^>]*>/,'<svg x="44" y="30" width="132" height="31" viewBox="0 0 340 80">');
const ink='#172339',muted='#65748a',blue='#355cdb',teal='#008d7b',orange='#ce653b',line='#e3e8f1';
const colors=[blue,teal,orange],esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const text=(x,y,s,size=19,color=ink,weight=400,extra='')=>`<text x="${x}" y="${y}" font-size="${size}" fill="${color}" font-weight="${weight}" ${extra}>${esc(s)}</text>`;
const rect=(x,y,w,h,fill='#fff',stroke='none',r=16,extra='')=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${fill}" stroke="${stroke}" ${extra}/>`;
const rule=(x,y,x2,y2,color=line,width=1,extra='')=>`<path d="M${x} ${y}L${x2} ${y2}" fill="none" stroke="${color}" stroke-width="${width}" ${extra}/>`;
function frame(title,subtitle,section,h){
 return `<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="${h}" viewBox="0 0 1440 ${h}" role="img" aria-labelledby="title desc"><title id="title">${esc(title)}</title><desc id="desc">${esc(subtitle)} Synthetic product demonstration, not measured training results.</desc><defs><pattern id="pending" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M0 8L8 0" stroke="#b1c2f1" stroke-width="2"/></pattern></defs>${rect(0,0,1440,h,'#f6f8fc','none',24)}<g font-family="Segoe UI,Arial,sans-serif">${brand}${text(193,55,'/  '+section,15,muted)}${text(1396,55,'SIMULATED DEMO',14,muted,600,'text-anchor="end" letter-spacing="1.4"')}${text(44,116,title,38,ink,650)}${text(46,153,subtitle,20,muted)}`;
}
function finish(s,name,h,note){
 s+=text(44,h-27,note,15,muted)+text(1396,h-27,'RILLDEX RL STUDIO',12,muted,600,'text-anchor="end" letter-spacing="1.5"')+'</g></svg>';
 fs.writeFileSync(path.join(out,name),s);
}
function curve(points,x,y){
 let d='',open=false;
 for(const p of points){if(p.value==null){open=false;continue;}d+=(open?'L':'M')+x(p.step).toFixed(2)+' '+y(p.value).toFixed(2);open=true;}
 return d;
}
function chart(title,subtitle,group,top,domain,ticks,log=false){
 const left=135,right=1006,bottom=top+195,x=v=>left+v/1800*(right-left);
 const tr=v=>log?Math.log10(v):v;
 const y=v=>bottom-(tr(v)-tr(domain[0]))/(tr(domain[1])-tr(domain[0]))*(bottom-top);
 const streams=data.runs.map(r=>r.snapshot.series.find(s=>s.group===group));
 assert.ok(streams.every(s=>comparable(s,streams[0])));
 assert.ok(streams.every(s=>s.points.every(p=>p.value==null||p.value>=domain[0]&&p.value<=domain[1])), 'Never clip raw measurements out of the tour chart');
 let s=text(76,top-47,title,22,ink,650)+text(76,top-20,subtitle,16,muted);
 for(const t of ticks){s+=rule(left,y(t),right,y(t))+text(left-16,y(t)+6,group==='reward'?Math.round(t*100)+'%':String(t),17,muted,400,'text-anchor="end"');}
 for(const v of [0,300,600,900,1200,1500,1800])s+=rule(x(v),top,x(v),bottom,'#edf0f6');
 s+=`<defs><clipPath id="clip-${group}"><rect x="${left}" y="${top}" width="${right-left}" height="${bottom-top}"/></clipPath></defs><g clip-path="url(#clip-${group})">`;
 streams.forEach((series,i)=>{
  s+=`<path d="${curve(series.points,x,y)}" fill="none" stroke="${colors[i]}" stroke-opacity=".17" stroke-width="1.4"/>`;
 });
 streams.forEach((series,i)=>{
  s+=`<path d="${curve(smoothPoints(series.points,50),x,y)}" fill="none" stroke="${colors[i]}" stroke-width="3.5" stroke-linejoin="round"/>`;
 });
 s+='</g>'+rule(x(1335),top,x(1335),bottom,'#8794ac',1.3,'stroke-dasharray="5 6"');
 streams.forEach((series,i)=>{
  const v=series.points.find(p=>p.step===1335).value;
  s+=`<circle cx="${x(1335)}" cy="${y(v)}" r="4.5" fill="${colors[i]}" stroke="#fff" stroke-width="1.5"/>`;
 });
 for(const v of [0,300,600,900,1200,1500,1800])s+=text(x(v),bottom+31,v.toLocaleString('en-US'),17,muted,400,'text-anchor="middle"');
 return s;
}

let s=frame('Compare runs. Find the change.','Follow task outcomes and policy mismatch on the same training-step axis.','TRAINING SIGNALS',1050);
s+=rect(44,184,1352,62,'#fff',line,14);
data.runs.forEach((r,i)=>{const x=69+i*255;s+=rule(x,215,x+28,215,colors[i],4)+text(x+41,222,r.label,19,ink,600);});
s+=text(1372,222,'Faint: raw  ·  Bold: 50-step EMA',17,muted,400,'text-anchor="end"');
s+=rect(44,266,1002,638,'#fff',line,18);
s+=chart('Task success','256 generated episodes per log · fixed synthetic task mixture','reward',345,[.15,.9],[.2,.4,.6,.8]);
s+=chart('Trainer–sampler probability gap','Mean absolute difference over 256 aligned sampled tokens · log scale','mismatch',665,[.0025,.24],[.003,.01,.03,.1,.2],true);
s+=rect(1066,266,330,638,'#fff',line,18)+text(1090,304,'POINT INSPECTION',13,muted,650,'letter-spacing="1.4"');
s+=text(1090,348,'Step 1,335',30,ink,650)+text(1090,379,'Raw values · same recorded step',16,muted);
data.runs.forEach((r,i)=>{
 const y=420+i*123,success=r.snapshot.series.find(s=>s.group==='reward').points.find(p=>p.step===1335).value;
 const gap=r.snapshot.series.find(s=>s.group==='mismatch').points.find(p=>p.step===1335).value;
 s+=rule(1090,y-4,1111,y-4,colors[i],4)+text(1121,y+2,r.label,19,ink,600);
 s+=text(1090,y+41,(success*100).toFixed(1)+'%',29,colors[i],650)+text(1245,y+41,gap.toFixed(4),27,colors[i],650);
 s+=text(1090,y+66,'Task success',15,muted)+text(1245,y+66,'Mean gap',15,muted);
 if(i<2)s+=rule(1090,y+88,1372,y+88);
});
s+=rule(1090,783,1372,783)+text(1090,815,'Inspect updates →',20,blue,650)+text(1090,850,'Open the recorded logs and',16,muted)+text(1090,873,'linked rollout evidence.',16,muted);
for(const [i,label,desc]of [[0,'Compare runs','Shared definitions and colors'],[1,'Select an interval','One range across every signal'],[2,'Inspect the evidence','From an update to its rollouts']]){
 const x=60+i*456;s+=text(x,949,'0'+(i+1),15,blue,650)+text(x+38,950,label,20,ink,600)+text(x+38,978,desc,16,muted);
}
finish(s,'run-comparison.svg',1050,'Seeded simulation · 1,733 recorded logs · gap ≠ KL · final degraded-run sample at step 1,590');

const execution=data.execution,view=model(execution);
const ordered=['Sampler 1','Sampler 2','Sampler 3','Sampler 4','Verifier','Learner','Weight sync'];
const left=226,right=1016,x=v=>left+v/180*(right-left);
const kindColor={inference:blue,verification:teal,learner_update:'#8464bb',weight_sync:'#7d8ca4'};
s=frame('See the work behind each update','Parallel workers, retries and learner updates share one recorded execution clock.','EXECUTION',992);
s+=rect(44,184,1352,58,'#fff',line,14)+text(67,220,'00:00 – 03:00',20,ink,650);
s+=text(278,220,execution.counts.executions+' operations',18,muted)+text(479,220,'7 linked metric logs',18,muted)+text(735,220,'1 failed attempt',18,orange,600)+text(1371,220,'Shared wall-time clock',17,muted,400,'text-anchor="end"');
s+=rect(44,262,1002,650,'#fff',line,18);
s+=text(70,301,'Execution timeline',22,ink,650)+text(1016,300,'Select an operation to inspect',16,muted,400,'text-anchor="end"');
for(const v of [0,30,60,90,120,150,180]){s+=text(x(v),339,Math.floor(v/60)+':'+String(v%60).padStart(2,'0'),16,muted,400,'text-anchor="middle"')+rule(x(v),353,x(v),727,'#edf0f6');}
ordered.forEach((name,i)=>{
 const y=375+i*53,lane=view.lanes.find(l=>l.label===name);assert.ok(lane);
 s+=text(72,y+7,name,18,ink,i>=5?600:400)+rule(left,y+26,right,y+26,'#f0f3f8');
 lane.rows.forEach(e=>{
  const r=e.record,t=r.timing,failed=r.state==='failed',pending=t.end==null,retry=!!r.retry_of;
  const col=failed?orange:kindColor[r.kind],w=x(Math.min(t.end??180,180))-x(t.start);
  s+=rect(x(t.start),y-13,w,26,pending?'url(#pending)':col,'none',5,`fill-opacity="${failed||retry?'.95':'.72'}"`);
  if(pending)s+=rect(x(t.start),y-13,w,26,'none',blue,5,'stroke-dasharray="4 3"');
  if(failed||retry)s+=rect(x(t.start)-3,y-16,w+6,32,'none',col,7,'stroke-width="1.7"');
  if(failed)s+=text(x(t.start)+w/2,y+5,'Timeout',13,'#fff',600,'text-anchor="middle"');
  if(retry)s+=text(x(t.start)+w/2,y+5,'Retry · done',13,'#fff',600,'text-anchor="middle"');
 });
});
for(const[i,label,col]of [[0,'Inference',blue],[1,'Verification',teal],[2,'Learner update','#8464bb'],[3,'Weight sync','#7d8ca4']]){
 const xx=76+i*245;s+=rect(xx,758,12,12,col,'none',3)+text(xx+21,771,label,15,muted);
}
s+=rule(70,795,1020,795)+text(73,829,'Generation',18,ink,600)+text(73,853,'throughput',18,ink,600)+text(73,878,'tokens / second',15,muted);
const series=view.series.find(s=>s.group==='throughput');assert.equal(series.points.length,7);
const throughput=series.points.map(p=>({...p,step:p.time})),tx=x,ty=v=>878-(v-2000)/2000*54;
for(const v of [2000,4000])s+=rule(left,ty(v),right,ty(v))+text(left-12,ty(v)+5,v/1000+'k',14,muted,400,'text-anchor="end"');
s+=`<path d="${curve(throughput,tx,ty)}" fill="none" stroke="${blue}" stroke-width="2.5"/>`;
throughput.forEach(p=>s+=`<circle cx="${tx(p.step)}" cy="${ty(p.value)}" r="3.5" fill="${blue}"/>`);
s+=text(1016,902,'Positioned at the linked learner update',14,muted,400,'text-anchor="end"');
s+=rect(1066,262,330,650,'#fff',line,18)+text(1090,301,'OPERATION DETAILS',13,muted,650,'letter-spacing="1.4"');
s+=text(1090,347,'Request 18',29,ink,650)+text(1090,380,'Sampler 2 · Attempt 1',18,muted);
s+=rect(1090,402,162,34,'#fff0e9','none',8)+text(1102,425,'Failed · timeout',16,orange,650);
const failure=execution.executions.find(e=>e.record.id==='request-18-a1').record;
const retry=execution.executions.find(e=>e.record.id==='request-18-a2').record;
assert.equal(retry.retry_of.id,failure.id);assert.ok(execution.executions.find(e=>e.record===failure).run_id);
s+=text(1090,480,((failure.timing.end-failure.timing.start)).toFixed(1)+' s',32,ink,650)+text(1090,507,'Recorded attempt duration',16,muted);
for(const[y,label,value]of [[551,'Backend',failure.configuration.backend],[590,'Policy',failure.configuration.policy_version],[629,'Source rollout','rollout-18']]){
 s+=text(1090,y,label,16,muted)+text(1372,y,value,17,ink,600,'text-anchor="end"');
}
s+=rule(1090,654,1372,654)+text(1090,687,'Linked retry',20,ink,650)+text(1090,721,'Attempt 2 · Completed',18,teal,600);
s+=text(1090,751,(retry.timing.end-retry.timing.start).toFixed(1)+' s · same source rollout',16,muted);
s+=rule(1090,781,1372,781)+text(1090,816,'Open source rollout →',20,blue,650)+text(1090,851,'Request completion does not',16,muted)+text(1090,876,'establish task success.',16,muted);
finish(s,'execution-timeline.svg',992,'Seeded simulation · hatched spans are unfinished · recorded retry relationship · no inferred end times');
// The overview retains the detailed chart-panel treatment used in the app.
const selected=data.runs[1],selectedSeries=selected.snapshot.series;
s=frame('Follow one run in detail','Inspect native metrics, measurement coverage and the rollouts behind each update.','OVERVIEW',990);
s+=rect(44,184,1352,70,'#fff',line,14)+text(68,214,'TRAINING RUN',12,muted,650,'letter-spacing="1.2"')+text(68,240,selected.label+'  ⌄',20,ink,650);
['Summary','Training','Behavior','Execution','Training data'].forEach((label,i)=>{const xx=465+i*169;s+=text(xx,228,label,18,i===0?blue:muted,i===0?650:400);if(i===0)s+=rule(xx,252,xx+93,252,blue,3);});
s+=text(46,302,'Training signals',24,ink,650)+text(1392,302,'Open training comparison →',18,blue,600,'text-anchor="end"');
s+=text(46,337,'Chart options  ·  50-step EMA',17,muted)+text(434,337,'601 recorded logs',17,muted)+text(1392,337,'Faint: raw  ·  Bold: EMA',17,muted,400,'text-anchor="end"');
const reward=selectedSeries.find(q=>q.group==='reward'),gap=selectedSeries.find(q=>q.group==='mismatch');
[[reward,'Outcome','Task success','fraction'],[gap,'Policy mismatch','Mean absolute sampled probability gap','probability difference']].forEach(([series,label,subtitle,unit],i)=>{
 const xx=44+i*686,latest=series.points.at(-1),values=series.points.map(p=>p.value),lo=Math.min(...values),hi=Math.max(...values);
 s+=rect(xx,366,666,520,'#fff',line,16)+text(xx+26,406,label,24,ink,650)+text(xx+638,405,'Options',16,muted,400,'text-anchor="end"')+text(xx+26,441,subtitle,17,muted);
 s+=rule(xx+27,465,xx+27,552,blue,4)+text(xx+43,495,latest.value.toFixed(4),32,ink,650);
 s+=text(xx+43,524,selected.label+' · '+unit,16,muted)+text(xx+43,548,series.points.length+'/'+series.points.length+' measured · latest at '+latest.step,15,muted);
 const px=v=>xx+83+v/1800*545,py=v=>742-(v-lo)/(hi-lo||1)*158;
 [0,1,2].forEach(k=>{const value=lo+(hi-lo)*k/2,yy=py(value);s+=rule(xx+83,yy,xx+628,yy,'#e6eaf1')+text(xx+69,yy+5,value.toFixed(i?3:2),14,muted,400,'text-anchor="end"');});
 [0,450,900,1350,1800].forEach(step=>s+=rule(px(step),584,px(step),742,'#e6eaf1')+text(px(step),769,step.toLocaleString('en-US'),14,muted,400,'text-anchor="middle"'));
 s+=`<path d="${curve(series.points,px,py)}" fill="none" stroke="${blue}" stroke-width="1.3" stroke-opacity=".17"/><path d="${curve(smoothPoints(series.points,50),px,py)}" fill="none" stroke="${blue}" stroke-width="3"/>`;
 s+=rule(xx+26,792,xx+640,792)+text(xx+27,824,'Inspect updates',18,blue,650)+text(xx+244,824,'Compare linked rollouts',18,blue,600)+text(xx+27,864,'▸ Definition & sources',16,muted);
});
s+=text(46,929,'Behavior maps →',19,blue,600)+text(420,929,'Saved comparisons →',19,blue,600)+text(890,929,'Execution timeline →',19,blue,600);
finish(s,'training-overview.svg',990,'Authored training simulation · focused product panels · native populations and metric definitions retained');

if(process.argv[3]){
 const authored=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));assert.equal(authored.synthetic,true);
 const d=authored.snapshot,f=d.approach_followup,statuses=['reported_again','no_reported_error','followup_unknown'];
 const fills=[orange,teal,'#a5afc1'];
 s=frame('Compare attempts and their follow-up','Inspect how recorded approaches and later responses differ across two saved windows.','BEHAVIOR',952);
 s+=rect(44,184,1352,60,'#fff',line,14)+text(68,221,'Procedure changes',20,ink,650)+text(371,221,'Same task & configuration',18,muted)+text(828,221,'Equal rollout weight',18,muted)+text(1370,221,'Save latest comparison',18,blue,650,'text-anchor="end"');
 s+=rect(44,266,1002,555,'#fff',line,18)+text(70,305,'What followed an earlier error?',24,ink,650);
 [['Error reported again',orange],['No error reported',teal],['Unresolved',fills[2]]].forEach(([label,color],i)=>{const xx=72+i*290;s+=rect(xx,329,12,12,color,'none',3)+text(xx+22,341,label,17,muted);});
 s+=text(366,390,'Earlier · steps 0–2',18,ink,600)+text(698,390,'Later · steps 3–5',18,ink,600);
 f.earlier.rows.forEach((row,i)=>{
  const yy=436+i*85;const short=['Same procedure','Changed settings / inputs','Different procedure','Procedure unknown'][i];
  s+=text(70,yy+9,short,18,ink,600);
  [f.earlier.rows[i],f.later.rows[i]].forEach((r,j)=>{
   const xx=366+j*332,w=286;let offset=0;
   if(!r.total)s+=rect(xx,yy-14,w,27,'#f1f4f8','none',4)+text(xx,yy+36,'No eligible pairs',15,muted);
   else{
    for(let k=0;k<statuses.length;k++){const fraction=r.shares[statuses[k]];if(fraction)s+=rect(xx+offset,yy-14,w*fraction,27,fills[k],'none',0);offset+=w*(fraction||0);}
    s+=text(xx,yy+36,`${r.total} eligible ${r.total===1?'pair':'pairs'} · ${r.eligible_rollouts} rollout`,15,muted);
   }
  });
 });
 s+=text(70,800,'Within each approach · unresolved follow-up remains in the denominator',16,muted);
 s+=rect(1066,266,330,555,'#fff',line,18)+text(1090,305,'MEASUREMENT CONTEXT',13,muted,650,'letter-spacing="1.2"');
 s+=text(1090,359,d.observed_rollouts+' / '+d.population,35,ink,650)+text(1090,390,'Rollouts with saved observations',16,muted);
 s+=rule(1090,415,1372,415)+text(1090,453,'7 → 5',31,ink,650)+text(1090,485,'Pairs following an earlier error',16,muted);
 s+=text(1090,531,'2 later pairs excluded',20,ink,600)+text(1090,559,'No earlier error was reported.',16,muted);
 s+=rule(1090,589,1372,589)+text(1090,625,'Inspect matching pairs →',19,blue,650)+text(1090,657,'Open the earlier action, change',16,muted)+text(1090,682,'and subsequent response.',16,muted);
 s+=text(1090,733,'No error reported does not',16,muted)+text(1090,758,'establish successful recovery.',16,muted);
 s+=text(68,863,'Save latest comparison',20,ink,650)+text(414,863,'Capture latest evidence',20,ink,650)+text(866,863,'Keep both for review',20,ink,650);
 s+=text(68,892,'Fixed membership and observations',16,muted)+text(414,892,'Refresh the same windows explicitly',16,muted)+text(866,892,'Return to the exact supporting pairs',16,muted);
 finish(s,'behavior-comparison.svg',952,'Authored behavior examples · aggregated by the product pipeline · no model calls or measured accuracy claim');
}
console.log(JSON.stringify({logs:data.runs.map(r=>r.snapshot.records),operations:execution.counts.executions,behavior:!!process.argv[3]}));
