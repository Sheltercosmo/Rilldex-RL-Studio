'use strict';

// Original pixel artwork, rendered on the same clock as the product tour.
const FONT = {
  A:'01110/10001/10001/11111/10001/10001/10001',B:'11110/10001/10001/11110/10001/10001/11110',
  C:'01111/10000/10000/10000/10000/10000/01111',D:'11110/10001/10001/10001/10001/10001/11110',
  E:'11111/10000/10000/11110/10000/10000/11111',F:'11111/10000/10000/11110/10000/10000/10000',
  G:'01111/10000/10000/10111/10001/10001/01111',H:'10001/10001/10001/11111/10001/10001/10001',
  I:'11111/00100/00100/00100/00100/00100/11111',J:'00111/00010/00010/00010/10010/10010/01100',
  K:'10001/10010/10100/11000/10100/10010/10001',L:'10000/10000/10000/10000/10000/10000/11111',
  M:'10001/11011/10101/10101/10001/10001/10001',N:'10001/11001/10101/10011/10001/10001/10001',
  O:'01110/10001/10001/10001/10001/10001/01110',P:'11110/10001/10001/11110/10000/10000/10000',
  Q:'01110/10001/10001/10001/10101/10010/01101',R:'11110/10001/10001/11110/10100/10010/10001',
  S:'01111/10000/10000/01110/00001/00001/11110',T:'11111/00100/00100/00100/00100/00100/00100',
  U:'10001/10001/10001/10001/10001/10001/01110',V:'10001/10001/10001/10001/10001/01010/00100',
  W:'10001/10001/10001/10101/10101/11011/10001',X:'10001/10001/01010/00100/01010/10001/10001',
  Y:'10001/10001/01010/00100/00100/00100/00100',Z:'11111/00001/00010/00100/01000/10000/11111',
  '0':'01110/10001/10011/10101/11001/10001/01110','1':'00100/01100/00100/00100/00100/00100/01110',
  '2':'01110/10001/00001/00010/00100/01000/11111','3':'11110/00001/00001/01110/00001/00001/11110',
  '4':'00010/00110/01010/10010/11111/00010/00010','5':'11111/10000/10000/11110/00001/00001/11110',
  '6':'01111/10000/10000/11110/10001/10001/01110','7':'11111/00001/00010/00100/01000/01000/01000',
  '8':'01110/10001/10001/01110/10001/10001/01110','9':'01110/10001/10001/01111/00001/00001/11110',
  '.':'00000/00000/00000/00000/00000/00110/00110','/':'00001/00001/00010/00100/01000/10000/10000',
  '-':'00000/00000/00000/11111/00000/00000/00000',':':'00000/00100/00100/00000/00100/00100/00000',
  ',':'00000/00000/00000/00000/00110/00100/01000',
  '>':'10000/01000/00100/00010/00100/01000/10000',' ':'00000/00000/00000/00000/00000/00000/00000'
};
const BAYER=[0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5];
const clamp=x=>Math.max(0,Math.min(1,x));
const smooth=x=>{x=clamp(x);return x*x*(3-2*x);};
const mix=(a,b,p)=>a+(b-a)*p;
const bands=['#f2f9ff','#d7f3ff','#91d9ff','#4ba9ff','#3475e5','#3155ac','#28407a'];
const subtitleBands=['#ffffff','#f0faff','#d9f2ff','#b5e5ff','#98d6ff','#7dc6fa','#6bb6ef'];

function pixels(g,label,cx,y,size,{progress=1,color,shadow=true,palette=bands}={}){
  if(progress<=0)return;
  const width=(label.length*6-1)*size,left=Math.round(cx-width/2);
  for(const [i,ch] of [...label.toUpperCase()].entries()){
    const rows=(FONT[ch]||FONT[' ']).split('/');
    for(let row=0;row<7;row++)for(let col=0;col<5;col++){
      if(rows[row][col]!=='1'||(i*6+col)/(label.length*6)>progress)continue;
      const x=left+(i*6+col)*size,yy=y+row*size;
      if(shadow){g.fillStyle='#15263d';g.fillRect(x+size,yy+size,size,size);}
      g.fillStyle=color||palette[row];g.fillRect(x,yy,size,size);
    }
  }
}
function label(g,s,x,y,size=18,color='#a9bbd2',align='left'){
  g.font=`400 ${size}px "Geist Mono"`;g.fillStyle=color;g.textAlign=align;g.fillText(s,x,y);
}
function stroke(g,points,color,width=2){
  if(points.length<2)return;g.beginPath();points.forEach(([x,y],i)=>i?g.lineTo(x,y):g.moveTo(x,y));
  g.strokeStyle=color;g.lineWidth=width;g.stroke();
}
function stepped(g,x,y,w,h,color,step=8){
  g.fillStyle=color;g.fillRect(x+step,y,w-step*2,h);g.fillRect(x,y+step,w,h-step*2);
}
function dither(g,x,y,w,h,color,density=.5,cell=4){
  g.fillStyle=color;
  for(let yy=0;yy<h;yy+=cell)for(let xx=0;xx<w;xx+=cell){
    const fade=(1-yy/h)*density;
    if((BAYER[((yy/cell)%4)*4+(xx/cell)%4]+.5)/16<fade)g.fillRect(x+xx,y+yy,cell-1,cell-1);
  }
}
function actor(g,x,y,time,{clear=false,scale=4}={}){
  const stride=Math.floor(time*10)%2;
  stepped(g,x-4*scale,y-6*scale,8*scale,7*scale,'#a6dfff',scale);
  g.fillStyle='#58a3db';g.fillRect(x+2*scale,y-5*scale,2*scale,5*scale);
  g.fillStyle='#102335';g.fillRect(x-2*scale,y-4*scale,scale,2*scale);g.fillRect(x+scale,y-4*scale,scale,2*scale);
  g.fillStyle='#a6dfff';
  g.fillRect(x-6*scale,y-(clear?7:3)*scale,2*scale,scale);
  g.fillRect(x+4*scale,y-(clear?7:3)*scale,2*scale,scale);
  g.fillRect(x-3*scale,y+scale,2*scale,(stride?1:2)*scale);
  g.fillRect(x+scale,y+scale,2*scale,(stride?2:1)*scale);
}

function makeDungeon(){
  const cols=52,rows=19,tiles=Array.from({length:rows},()=>Array(cols).fill(false));
  function room(x,y,w,h){for(let yy=y;yy<y+h;yy++)for(let xx=x;xx<x+w;xx++)tiles[yy][xx]=true;}
  [[2,8,11,8],[21,2,11,7],[39,8,11,8],[12,10,5,3],[14,4,3,8],[15,4,7,3],[25,5,3,8],[26,10,14,3]].forEach(r=>room(...r));
  const waypoints=[[5,11],[15,11],[15,5],[26,5],[26,11],[45,11]],path=[];
  for(let i=1;i<waypoints.length;i++){
    const [a,b]=[waypoints[i-1],waypoints[i]],length=Math.abs(a[0]-b[0])+Math.abs(a[1]-b[1]);
    for(let j=0;j<length;j++)path.push([mix(a[0],b[0],j/length),mix(a[1],b[1],j/length)]);
  }
  path.push(waypoints.at(-1));return {tiles,cols,rows,path};
}

function dungeon(g,t,map){
  const {tiles,cols,rows,path}=map,cell=28,x0=232,y0=236;
  const p=clamp((t-.12)/1.68),at=p*(path.length-1),index=Math.floor(at),next=Math.min(index+1,path.length-1);
  const px=mix(path[index][0],path[next][0],at-index),py=mix(path[index][1],path[next][1],at-index);
  pixels(g,t<1.9?'ONE MORE ROLLOUT':'STAGE CLEAR',960,122,5,{color:t<1.9?'#8eafd0':'#ffe3a1'});
  label(g,'AGENT 01',234,204,17,'#62809f');label(g,'FINAL ROOM',1688,204,17,'#62809f','right');
  const flicker=.96+.04*Math.sin(Math.floor(t*12)*2.3);
  for(let row=0;row<rows;row++)for(let col=0;col<cols;col++){
    const floor=tiles[row][col];
    const wall=!floor&&[-1,0,1].some(dy=>[-1,0,1].some(dx=>tiles[row+dy]?.[col+dx]));
    if(!floor&&!wall)continue;
    const dist=Math.hypot(col-px,row-py),visited=path.slice(0,index+1).some(([xx,yy])=>Math.hypot(col-xx,row-yy)<4);
    const light=Math.max(visited?.35:.10,Math.max(0,1-dist/7)*flicker),x=x0+col*cell,y=y0+row*cell;
    g.fillStyle=floor?`rgba(25,45,66,${.25+light*.7})`:`rgba(80,111,144,${.07+light*.23})`;g.fillRect(x,y,cell,cell);
    if(wall){
      g.fillStyle=`rgba(153,182,207,${light*.35})`;
      for(let by=4;by<24;by+=7)for(let bx=5;bx<24;bx+=7)if((bx+by+col)%3)g.fillRect(x+bx,y+by,3,3);
    }else{g.fillStyle=`rgba(128,161,197,${.15+light*.4})`;g.fillRect(x+13,y+13,3,3);}
  }
  for(let i=0;i<index;i++){
    const [x,y]=path[i];g.fillStyle='#cca567';g.globalAlpha*=.45;g.fillRect(x0+x*cell+12,y0+y*cell+12,4,4);g.globalAlpha/=.45;
  }
  for(const [x,y] of [[12,11],[26,8]]){
    const open=px>x||index>path.findIndex(v=>v[0]===x&&v[1]===y);
    label(g,open?'/':'+',x0+x*cell+7,y0+y*cell+23,23,'#d2b37d');
  }
  // Warm exit light and a raised flag echo the handheld game's finish.
  const ex=x0+45*cell+14,ey=y0+11*cell+14;
  dither(g,ex-42,ey-118,84,152,'#93642f',.65,4);
  g.fillStyle='#3b2c20';g.fillRect(ex-20,ey-38,40,60);g.fillStyle='#ffc572';g.fillRect(ex-16,ey-34,5,52);g.fillRect(ex-16,ey-34,32,5);
  if(t>1.8){g.fillStyle='#e6c584';g.fillRect(ex+33,ey-58,4,83);g.fillStyle='#92d6be';g.fillRect(ex+37,ey-58,28,18);}
  const jump=t>1.8&&t<2.15?Math.sin((t-1.8)/.35*Math.PI)*40:0;
  actor(g,x0+px*cell+14,y0+py*cell+14-jump,t,{clear:t>=1.8});
  if(t>1.85){
    for(let i=0;i<12;i++){
      const a=i*Math.PI/6,dist=26+(t-1.85)*85;
      g.fillStyle=i%2?'#a7dfff':'#e8bf75';g.fillRect(ex+Math.cos(a)*dist,ey-20+Math.sin(a)*dist,4,4);
    }
  }
}

function pixelArea(g,points,{x,y,w,h,min,max,start=0,end,cut=end,color,density=1}){
  // Keep the recorded history fixed; only new samples extend the right edge.
  const cell=5,visible=points.filter(v=>v.step<=cut);
  if(!visible.length)return;
  let index=0;g.fillStyle=color;
  const span=end-start;
  const first=Math.max(0,Math.ceil((visible[0].step-start)/span*w/cell)*cell);
  const last=Math.min(w,(Math.min(cut,visible.at(-1).step)-start)/span*w);
  for(let xx=first;xx<=last;xx+=cell){
    const step=start+xx/w*span;
    while(index+1<visible.length&&visible[index+1].step<=step)index++;
    const a=visible[index],b=visible[Math.min(index+1,visible.length-1)];
    const value=mix(a.value,b.value,clamp((step-a.step)/(b.step-a.step||1)));
    const height=clamp((value-min)/(max-min))*h;
    const edge=Math.floor((h-height)/cell)*cell;
    for(let yy=edge;yy<h;yy+=cell){
      const depth=(yy-edge)/Math.max(cell,h-edge);
      const ink=(.94-.71*depth)*density;
      if((BAYER[((yy/cell)%4)*4+(xx/cell)%4]+.5)/16<ink)g.fillRect(x+xx,y+yy,3,3);
    }
    g.fillRect(x+xx,y+edge,cell,2);
  }
}
function dashboard(g,t,data){
  const fade=smooth((t-4.2)/1.1)*.86;if(!fade)return;
  g.save();g.globalAlpha*=fade;
  // Replay recent fixture windows so updates are visible at film scale.
  // Training steps and execution seconds remain separate clocks.
  const elapsed=Math.max(0,t-4.5),tick=Math.min(4,Math.floor(elapsed/.85));
  const advance=tick===0?0:tick-1+smooth((elapsed-tick*.85)/.45);
  const step=Math.round(1080+advance*105),now=90+advance*18,start=step-360,end=step+60,timeStart=now-60,timeEnd=now+10;
  const pulse=tick>0?1-smooth((elapsed-tick*.85)/.38):0;
  const x=144,w=1632,top=721;
  label(g,'TRAINING / RECOVERED RUN',x,top,17,'#c4d6e9');label(g,'SIMULATED REPLAY',x+w,top,15,'#a2b7ce','right');
  g.fillStyle=pulse>0?'#a4efd2':'#62a78f';g.fillRect(987,top-11,6,6);
  label(g,'RECENT WINDOW / STEP '+step.toLocaleString('en-US'),1005,top,14,'#b9cee4');
  const reward=data.runs[1].series.find(s=>s.group==='reward').points;
  const gap=data.runs[1].series.find(s=>s.group==='mismatch').points;
  const latest=(points,cut)=>points.filter(v=>v.step<=cut).at(-1);
  const rv=latest(reward,step),gv=latest(gap,step),tv=latest(data.throughput,now);
  const cards=[['GENERATED SUCCESS',rv?(rv.value*100).toFixed(1)+'%':'—','#66bdff',reward,0,1],
    ['TRAINER / SAMPLER GAP',gv?gv.value.toFixed(4):'—','#bd96ef',gap,0,.045],
    ['GENERATION',tv?tv.value.toLocaleString('en-US')+' tok/s':'—','#6ed6b0',data.throughput,1800,4000]];
  cards.forEach(([title,value,color,points,min,max],i)=>{
    const xx=x+i*416;stepped(g,xx,top+18,384,134,'#263b53',5);stepped(g,xx+1,top+19,382,132,'#0d1725',4);
    if(pulse){g.save();g.globalAlpha*=pulse*.55;g.strokeStyle=color;g.lineWidth=2;g.strokeRect(xx+1,top+19,382,132);g.restore();}
    label(g,title,xx+18,top+43,14,'#c1d1e3');label(g,value,xx+18,top+76,28,'#f1f6fd');
    pixelArea(g,points,{x:xx+18,y:top+85,w:347,h:60,min,max,start:i===2?timeStart:start,end:i===2?timeEnd:end,cut:i===2?now:step,color});
  });
  const completed=data.executions.filter(v=>v.state==='completed'&&v.timing.end<=now).length;
  const rx=x+1248;stepped(g,rx,top+18,384,134,'#263b53',5);stepped(g,rx+1,top+19,382,132,'#0d1725',4);
  if(pulse){g.save();g.globalAlpha*=pulse*.55;g.strokeStyle='#6fc2ff';g.lineWidth=2;g.strokeRect(rx+1,top+19,382,132);g.restore();}
  label(g,'OPERATIONS',rx+18,top+43,14,'#c1d1e3');label(g,completed+' / '+data.executions.length,rx+18,top+82,31,'#f1f6fd');
  label(g,'completed',rx+18,top+110,16,'#b5c8dc');
  // A segmented, stippled ring records completion; running work never counts as complete.
  const cx=rx+302,cy=top+86,r=45;
  for(let i=0;i<50;i++){
    const a=-Math.PI/2+i/50*Math.PI*2,active=i<completed;
    g.save();g.translate(cx,cy);g.rotate(a);g.fillStyle=active?'#6fc2ff':'#203449';g.fillRect(-2,-r,4,12);
    if(active){g.fillStyle='#0d1725';for(let yy=0;yy<12;yy+=4)if((i+yy/4)%2)g.fillRect(-2,-r+yy,2,2);}
    g.restore();
  }
  label(g,Math.round(completed/data.executions.length*100)+'%',cx,cy+7,20,'#def0ff','center');
  const plotY=top+196,plotH=105;
  label(g,'GENERATED SUCCESS / RECENT STEPS',x,top+180,15,'#b9cee4');
  [['Steady','#66bdff'],['Recovered','#6ed6b0'],['Degrading','#eeae6a']].forEach(([name,color],i)=>{g.fillStyle=color;g.fillRect(x+560+i*142,top+173,12,2);label(g,name,x+580+i*142,top+180,12,color);});
  for(const yy of[plotY,plotY+50,plotY+100])stroke(g,[[x,yy],[x+990,yy]],'#23364d',1);
  // Larger fill cells, rather than thin smooth curves, carry the closing visual.
  data.runs.forEach((run,i)=>{
    const pts=run.series.find(s=>s.group==='reward').points;
    pixelArea(g,pts,{x,y:plotY,w:990,h:plotH,min:.15,max:.9,start,end,cut:step,color:['#66bdff','#6ed6b0','#eeae6a'][i],density:[.7,.5,.4][i]});
  });
  label(g,start.toLocaleString('en-US'),x,1043,12,'#7f9bb8');label(g,end.toLocaleString('en-US'),x+990,1043,12,'#7f9bb8','right');
  const lx=1218,lw=558;label(g,`ASYNC WORKERS / ${Math.round(timeStart)}–${Math.round(timeEnd)} s`,lx,top+180,15,'#b9cee4');
  for(const [i,worker] of ['Sampler 1','Sampler 2','Sampler 3','Sampler 4','Learner'].entries()){
    const yy=plotY+i*23;label(g,worker.replace('Sampler ','S'),lx,yy+11,12,'#a7bfd8');
    for(const e of data.executions.filter(e=>e.context.worker===worker&&e.timing.start<now&&(e.timing.end??now)>timeStart)){
      const from=Math.max(timeStart,e.timing.start),xx=lx+80+(from-timeStart)/(timeEnd-timeStart)*(lw-80),ww=(Math.min(e.timing.end??now,now)-from)/(timeEnd-timeStart)*(lw-80);
      const color=e.state==='failed'&&e.timing.end<=now?'#eeae6a':'#7baee9';
      g.fillStyle=color;
      for(let bx=0;bx<ww;bx+=5)for(let by=0;by<15;by+=5){
        if((BAYER[(by/5)*4+(Math.floor(bx/5)%4)]+.5)/16<.82-by*.035)g.fillRect(xx+bx,yy+by,3,3);
      }
    }
  }
  g.fillStyle='#a1d7ff';g.fillRect(lx+80+(now-timeStart)/(timeEnd-timeStart)*(lw-80),plotY,2,109);
  g.restore();
}

function createEnding({createCanvas,logo,data}){
  const map=makeDungeon(),raster=createCanvas(204,48),c=raster.getContext('2d');
  c.drawImage(logo,0,0,204,48);const rgba=c.getImageData(0,0,204,48).data,cells=[];
  for(let y=0;y<48;y++)for(let x=0;x<204;x++){
    const o=(y*204+x)*4;if(rgba[o+3]<110)continue;
    const brand=x<49,col=brand?`rgb(${rgba[o]},${rgba[o+1]},${rgba[o+2]})`:bands[Math.min(6,Math.floor(y/48*7))];
    cells.push({x,y,col});
  }
  function draw(g,storyTime){
    const t=storyTime/1.5;
    g.fillStyle='#060a12';g.fillRect(0,0,1920,1080);
    if(t<2.95){
      g.save();g.globalAlpha*=1-smooth((t-2.35)/.6);dungeon(g,t,map);g.restore();
      // The cleared stage disappears in ordered pixels, not a full-screen flash.
      if(t>2.35){
        const p=clamp((t-2.35)/.6);g.fillStyle='#060a12';
        for(let y=0;y<1080;y+=12)for(let x=0;x<1920;x+=12)if((BAYER[((y/12)%4)*4+(x/12)%4]+.5)/16<p)g.fillRect(x,y,12,12);
      }
    }
    dashboard(g,t,data);
    const scan=clamp((t-2.8)/1.1),left=552,top=132,cell=4;
    if(scan>0){
      for(const p of cells){
        const edge=scan*220-(p.y%4)*1.5;if(p.x>edge)continue;
        g.fillStyle='#142640';g.fillRect(left+p.x*cell+5,top+p.y*cell+6,cell,cell);
      }
      for(const p of cells){
        const edge=scan*220-(p.y%4)*1.5;if(p.x>edge)continue;
        g.fillStyle=edge-p.x<3&&scan<1?'#f5fcff':p.col;g.fillRect(left+p.x*cell,top+p.y*cell,cell,cell);
      }
      if(scan<1){g.fillStyle='#8bdfff';g.fillRect(left+scan*816,top-7,2,206);}
    }
    pixels(g,'FIND FAILURE PATTERNS.',960,357,6,{progress:clamp((t-3.55)/.5),palette:subtitleBands});
    pixels(g,'CHOOSE YOUR NEXT EXPERIMENT.',960,423,6,{progress:clamp((t-3.8)/.55),palette:subtitleBands});
    pixels(g,'LIVE OR SAVED ROLLOUTS. DASHBOARD, PYTHON OR SQL.',960,493,4,{progress:clamp((t-4.1)/.6),shadow:false,palette:subtitleBands});
    const pop=clamp((t-4.55)/.4);
    if(pop>0){
      const back=1+2.3*(pop-1)**3+1.3*(pop-1)**2,scale=.82+.18*back;
      g.save();g.globalAlpha*=smooth(pop);g.translate(960,587);g.scale(scale,scale);g.translate(-960,-587);
      stepped(g,620,551,680,84,'#12213d',8);stepped(g,620,543,680,84,'#507bd5',8);stepped(g,624,547,672,76,'#1b3865',6);
      dither(g,628,551,664,12,'#7bbaff',.5,4);
      dither(g,628,604,664,15,'#7bbaff',.23,4);
      pixels(g,'EXPLORE ON GITHUB >',960,565,4,{color:'#e6f5ff',shadow:false});g.restore();
    }
    if(t>4.9){
      g.save();g.globalAlpha*=smooth((t-4.9)/.4);
      label(g,'github.com/Sheltercosmo/Rilldex-RL-Studio',960,680,23,'#a6bedc','center');g.restore();
    }
    if(t>3){
      for(const [i,[x,y]] of [[377,185],[1513,324],[458,486],[1471,575],[1621,139]].entries()){
        const frames=[.12,.12,.35,.65,.35,.12,0,0],a=frames[Math.floor(t*1.2+i*2)%frames.length];
        g.save();g.globalAlpha*=a*smooth(t-3);g.fillStyle='#91badf';g.fillRect(x-6,y-2,12,4);g.fillRect(x-2,y-6,4,12);g.restore();
      }
    }
  }
  return {draw};
}
module.exports={createEnding};
