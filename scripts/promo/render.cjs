/* Deterministic motion design. All chart values are from the saved product tour.
 * No model calls, browser capture, or fabricated benchmark results.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { createCanvas, loadImage, GlobalFonts } = require('@napi-rs/canvas');
const { smoothPoints } = require('../../tracker/web/trainer-telemetry.js');
const { createEnding } = require('./ending.cjs');
const { createStructureScene } = require('./structure-scene.cjs');
const ROOT = path.resolve(__dirname, '../..');
const STRUCTURE = JSON.parse(fs.readFileSync(path.join(__dirname, 'structure-data.json'), 'utf8'));
const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, 'tour-data.json'), 'utf8'));
if (DATA.synthetic !== true || DATA.runs.length !== 3) throw new Error('Expected the explicitly labeled, three-run tour fixture.');
const args = process.argv.slice(2);
const arg = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
const WIDTH = Number(arg('--width', 1920)), HEIGHT = Math.round(WIDTH * 9 / 16);
const FPS = Number(arg('--fps', 60)), SPEED = 1.5, STORY_DURATION = 90, DURATION = STORY_DURATION / SPEED;
const OUT = path.resolve(ROOT, arg('--output', 'outputs/rilldex-promo'));
if (WIDTH % 2 || HEIGHT % 2 || ![24, 25, 30, 60].includes(FPS)) throw new Error('Use even 16:9 dimensions and 24/25/30/60 fps.');
fs.mkdirSync(OUT, { recursive: true });
GlobalFonts.registerFromPath(path.join(ROOT, 'tracker/web/geist-sans.woff2'), 'Geist');
GlobalFonts.registerFromPath(path.join(ROOT, 'tracker/web/geist-mono.woff2'), 'Geist Mono');
const C = { bg: '#f6f8fc', ink: '#111e33', muted: '#53647d', line: '#d5deeb', blue: '#3159dc', teal: '#007c6d', orange: '#bf5529', purple: '#7855b6', dark: '#060a12' };
const colors = [C.blue, C.teal, C.orange];
const CHAPTERS = [
  { start: 0, end: 8.5, name: 'Introduction', draw: intro },
  { start: 8.5, end: 18.5, name: 'Training overview', draw: overview },
  { start: 18.5, end: 28.5, name: 'Unit map', draw: unitMap },
  { start: 28.5, end: 42.5, name: 'Plans & attempts', draw: plans },
  { start: 42.5, end: 52.5, name: 'Execution timeline', draw: execution },
  { start: 52.5, end: 64.5, name: 'Run comparison', draw: comparison },
  { start: 64.5, end: 72.5, name: 'Behavior comparison', draw: behavior },
  { start: 72.5, end: 90, name: 'Rilldex', draw: outro }
];
const canvas = createCanvas(WIDTH, HEIGHT);
let g = canvas.getContext('2d'), logo, logoLight, mark, agentSurface, consoleSurface, toolSurfaces, waveField, wavePixels, wavePoints, headline, halo, ending, softStars;
const BAYER = [0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5];
const REACH_DELAY=.4, REACH_DURATION=2;
// Stagger the starts while several tentacles are still reaching.
const INTRO_TOOLS = [
  { name:'Terminal',x:1035,y:273,start:1.25,port:[100,0],pts:[[1200,414],[1150,393],[1190,290]] },
  { name:'Browser',x:1654,y:253,start:1.9,port:[-100,0],pts:[[1450,414],[1510,385],[1495,270]] },
  { name:'Code',x:1740,y:547,start:2.55,port:[-100,0],pts:[[1458,490],[1535,488],[1560,547]] },
  { name:'Tests',x:1565,y:805,start:3.2,port:[-70,-46],pts:[[1448,535],[1518,597],[1480,700]] },
  { name:'Files',x:1050,y:805,start:3.85,port:[70,-46],pts:[[1202,535],[1138,597],[1155,700]] }
];
const connectedAt=item=>item.start+REACH_DELAY+REACH_DURATION;
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const ease = v => { v = clamp(v); return 1 - (1 - v) ** 3; };
const smooth = v => { v = clamp(v); return v * v * (3 - 2 * v); };
const ramp = (t, delay = 0, duration = 0.8) => ease((t - delay) / duration);
const lerp = (a, b, t) => a + (b - a) * t;
function alpha(v, fn) { if (v <= 0) return; g.save(); g.globalAlpha *= clamp(v); fn(); g.restore(); }
function enter(t, delay, fn, distance = 22) {
  const p = ramp(t, delay); if (!p) return;
  g.save(); g.globalAlpha *= p; g.translate(0, (1 - p) * distance); fn(p); g.restore();
}
function box(x, y, w, h, fill = '#fff', border = C.line, radius = 18, shadow = false) {
  g.save(); g.beginPath(); g.roundRect(x, y, w, h, radius);
  if (shadow) { g.shadowColor = '#203c6b0b'; g.shadowBlur = 30; g.shadowOffsetY = 10; }
  if (fill) { g.fillStyle = fill; g.fill(); }
  g.shadowColor = 'transparent';
  if (border) { g.strokeStyle = border; g.lineWidth = 1.3; g.stroke(); }
  g.restore();
}
function text(s, x, y, size = 24, color = C.ink, weight = 400, align = 'left', mono = false) {
  // Skia's CSS font parser accepts the standard hundred-step weights.
  g.font = `${Math.round(weight / 100) * 100} ${size}px "${mono ? 'Geist Mono' : 'Geist'}"`;
  g.textAlign = align; g.textBaseline = 'alphabetic'; g.fillStyle = color;
  g.fillText(String(s), x, y);
}
function lines(items, x, y, size = 24, color = C.ink, weight = 400, leading = 32) {
  items.forEach((s, i) => text(s, x, y + i * leading, size, color, weight));
}
function line(x, y, xx, yy, color = C.line, width = 1, dash = []) {
  g.save(); g.beginPath(); g.moveTo(x, y); g.lineTo(xx, yy); g.strokeStyle = color; g.lineWidth = width; g.setLineDash(dash); g.stroke(); g.restore();
}
function circle(x, y, r, fill, stroke, width = 1) {
  g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2);
  if (fill) { g.fillStyle = fill; g.fill(); }
  if (stroke) { g.strokeStyle = stroke; g.lineWidth = width; g.stroke(); }
}
function pill(s, x, y, color = C.blue, fill = '#edf1ff', width) {
  g.font = '500 19px Geist'; const w = width || g.measureText(s).width + 28;
  box(x, y, w, 36, fill, null, 9); text(s, x + 14, y + 25, 19, color, 500); return w;
}
function button(s, x, y, w = 220, emphasis = false) {
  box(x, y, w, 46, emphasis ? C.blue : '#fff', emphasis ? C.blue : C.line, 10);
  text(s, x + 16, y + 30, 20, emphasis ? '#fff' : C.blue, 550);
}
function bg(dark = false) {
  g.fillStyle = dark ? C.dark : C.bg; g.fillRect(0, 0, 1920, 1080);
  const gradient = g.createRadialGradient(1450, 190, 0, 1450, 190, 1350);
  gradient.addColorStop(0, dark ? '#17396342' : '#e8efff70'); gradient.addColorStop(1, dark ? '#080f2000' : '#f6f8fc00');
  g.fillStyle = gradient; g.fillRect(0, 0, 1920, 1080);
}
function top(name, kind = 'SIMULATED DEMO') {
  g.drawImage(logo, 84, 40, 184, 43.3);
  line(292, 47, 292, 77, '#cfd7e6'); text(name, 316, 70, 20, C.muted, 500);
  text(kind, 1832, 68, 16, C.muted, 500, 'right');
  line(84, 107, 1836, 107, '#dfe6f0');
}
function heading(t, eyebrow, title, subtitle) {
  enter(t, 0.08, () => text(eyebrow, 86, 161, 17, C.blue, 600));
  enter(t, 0.18, () => text(title, 84, 224, 54, C.ink, 600));
  enter(t, 0.3, () => text(subtitle, 87, 270, 23, C.muted));
}
function footer(note) { text(note, 88, 992, 17, C.muted); }
function progress(t, dark = false) {
  const names = ['Training', 'Unit map', 'Plans', 'Execution', 'Compare', 'Behavior'];
  names.forEach((n, i) => {
    const ch = CHAPTERS[i + 1], x = 87 + i * 291, p = clamp((t - ch.start) / (ch.end - ch.start));
    line(x, 1033, x + 255, 1033, dark ? '#29354b' : '#dce3ee', 2);
    if (p) line(x, 1033, x + 255 * p, 1033, dark ? '#70a9ff' : C.blue, 2.5);
    text(n, x, 1062, 15, p > 0 && p < 1 ? (dark ? '#d8e8ff' : C.blue) : (dark ? '#6d7e99' : C.muted), 500);
  });
}
function ripple(x, y, t, color = C.blue, max = 60) {
  if (t < 0 || t > 1.6) return;
  const p = t / 1.6; alpha((1 - p) * .65, () => circle(x, y, 10 + ease(p) * max, null, color, 2));
}
function cursor(x, y, t) {
  alpha(ramp(t), () => { g.save(); g.translate(x, y); g.beginPath(); g.moveTo(0, 0); g.lineTo(0, 26); g.lineTo(7, 19); g.lineTo(13, 31); g.lineTo(18, 28); g.lineTo(12, 16); g.lineTo(23, 16); g.closePath(); g.fillStyle = C.ink; g.strokeStyle = '#fff'; g.lineWidth = 2.5; g.fill(); g.stroke(); g.restore(); });
}
function icon(type, x, y, col = '#a9caff', width = 2) {
  g.save(); g.translate(x, y); g.strokeStyle = col; g.lineWidth = width; g.lineCap = 'round'; g.lineJoin = 'round';
  const p = (...v) => { g.beginPath(); for (let i = 0; i < v.length; i += 2) i ? g.lineTo(v[i], v[i + 1]) : g.moveTo(v[i], v[i + 1]); g.stroke(); };
  if (type === 'Terminal') { p(0, 0, 7, 7, 0, 14); p(13, 15, 25, 15); }
  if (type === 'Browser') { g.strokeRect(-1, -3, 28, 23); p(-1, 3, 27, 3); circle(3, 0, .7, col); circle(7, 0, .7, col); }
  if (type === 'Code') { p(6, -1, -1, 7, 6, 15); p(20, -1, 27, 7, 20, 15); p(16, -4, 10, 19); }
  if (type === 'Tests') { g.beginPath(); g.arc(12, 7, 14, 0, Math.PI * 2); g.stroke(); p(5, 7, 10, 12, 19, 2); }
  if (type === 'Files') { p(-1, 19, -1, -2, 10, -2, 14, 3, 27, 3, 27, 19, -1, 19); }
  g.restore();
}
function bezier(points, p) {
  const [a, b, c, d] = points, q = 1 - p;
  return [q*q*q*a[0] + 3*q*q*p*b[0] + 3*q*p*p*c[0] + p*p*p*d[0], q*q*q*a[1] + 3*q*q*p*b[1] + 3*q*p*p*c[1] + p*p*p*d[1]];
}
function roundedDistance(x,y,w,h,r) {
  const qx=Math.abs(x-w/2)-(w/2-r),qy=Math.abs(y-h/2)-(h/2-r);
  return Math.hypot(Math.max(qx,0),Math.max(qy,0))+Math.min(Math.max(qx,qy),0)-r;
}
function ditherSurface(w,h,r,agent=false) {
  // Cache geometry, never the illumination: every frame has a moving light field.
  const pad=32,out=createCanvas(w+pad*2,h+pad*2),c=out.getContext('2d');
  const layer=createCanvas(out.width,out.height),lc=layer.getContext('2d');
  const pixels=lc.createImageData(out.width,out.height),cells=[];
  for(let row=0;row<Math.floor(out.height/4);row++)for(let col=0;col<Math.floor(out.width/4);col++){
    const x=col*4-pad,y=row*4-pad,d=roundedDistance(x,y,w,h,r);
    cells.push({x,y,nx:x/w,ny:y/h,d,edge:Math.exp(-Math.abs(d)/4.5),
      threshold:(BAYER[(row%4)*4+col%4]+.5)/16,
      shadow:.23*Math.exp(-Math.max(0,roundedDistance(x-7,y-12,w,h,r))/13),
      offset:(row*4*out.width+col*4)*4});
  }
  return {out,c,layer,lc,pixels,cells,w,h,r,pad,agent};
}
function animateSurface(surface,t,phase=0) {
  const {out,c,layer,lc,pixels,cells,w,h,r,pad,agent}=surface,buffer=pixels.data;
  buffer.fill(0);
  const sweep=t*1.05+phase;
  for(const p of cells){
    let density=p.shadow,col=[40,66,95],cellSize=3;
    if(p.d<=0){
      // Contiguous light, a narrow dither transition, and a dark lower-right plane.
      // Full 4px cells let the lit face become solid instead of uniform confetti.
      const shade=.9*p.nx**3+.58*p.ny**4+.065*Math.sin(sweep+p.ny*2);
      density=agent ? 1-smooth((shade-.30)/.43)
        : .012+.025*(1+Math.sin(p.nx*5-sweep))+.84*Math.exp(-Math.abs(p.d)/8)*(1-p.nx*.55)*(1-p.ny*.5);
      col=agent?(surface.console?[119,151,190]:[171,220,249]):[161,210,248];
      cellSize=agent?4:3;
      if(p.d>-(agent?3.5:6.5)&&(p.x<r||p.y<r)){density=Math.max(density,agent?.82:.94);col=agent?[207,238,255]:[201,232,255];cellSize=4;}
    }
    if(p.threshold>=density)continue;
    for(let yy=0;yy<cellSize;yy++)for(let xx=0;xx<cellSize;xx++){
      const o=p.offset+(yy*out.width+xx)*4;
      buffer[o]=col[0];buffer[o+1]=col[1];buffer[o+2]=col[2];buffer[o+3]=255;
    }
  }
  c.clearRect(0,0,out.width,out.height);c.fillStyle=agent?'#11263b':'#0c1b2b';
  c.beginPath();c.roundRect(pad,pad,w,h,r);c.fill();
  lc.putImageData(pixels,0,0);c.drawImage(layer,0,0);
  if(!agent){
    c.save();c.strokeStyle='#b7dfff';c.lineWidth=2.5;c.lineCap='round';
    c.beginPath();c.moveTo(pad+w-r,pad+1);c.lineTo(pad+r,pad+1);
    c.quadraticCurveTo(pad+1,pad+1,pad+1,pad+r);c.lineTo(pad+1,pad+h-r);c.stroke();c.restore();
  }
  return out;
}
function makeHeadline(){
  const mask=createCanvas(840,300),mc=mask.getContext('2d'),out=createCanvas(840,300),c=out.getContext('2d');
  mc.fillStyle=mc.strokeStyle='#fff';mc.lineWidth=4;mc.lineJoin='round';mc.textBaseline='alphabetic';
  // Explicitly strengthen the outlines: this bundled font has a single registered face.
  for(const [label,size,y] of [['Reward went up.',96,105],['Did the agent improve?',76,215]]){
    mc.font=`900 ${size}px Geist`;mc.strokeText(label,4,y);mc.fillText(label,4,y);
  }
  return {mask,out,c};
}
function introHeadline(t){
  const {mask,out,c}=headline;
  c.clearRect(0,0,out.width,out.height);c.globalCompositeOperation='source-over';c.drawImage(mask,0,0);
  c.globalCompositeOperation='source-in';
  const ink=c.createLinearGradient(0,0,0,300);ink.addColorStop(0,'#f0f7ff');ink.addColorStop(.532,'#f0f7ff');ink.addColorStop(.533,'#b2e1ff');ink.addColorStop(1,'#b2e1ff');
  c.fillStyle=ink;c.fillRect(0,0,840,300);
  c.globalCompositeOperation='destination-out';c.fillStyle='#000';
  for(let y=0;y<300;y+=4)for(let x=0;x<840;x+=4){
    const band=Math.max(0,Math.sin(x*.011+y*.025-t*.38));
    const density=1-.43*band**3,threshold=(BAYER[((y/4)%4)*4+(x/4)%4]+.5)/16;
    if(threshold>density)c.fillRect(x,y,3,3);
  }
  c.globalCompositeOperation='source-over';g.drawImage(out,80,300);
}
function leftHalo(t){
  const data=halo.pixels.data,pulse=.93+.07*Math.sin(t*.46);
  for(let i=0;i<halo.points.length;i++){
    const p=halo.points[i],o=i*4;
    const density=p.strength*pulse*(.85+.15*Math.sin(p.along*.006-t*.35));
    const lit=p.threshold<density;
    data[o]=65;data[o+1]=128;data[o+2]=213;data[o+3]=lit?Math.round(38*p.strength*ramp(t,.15,1.3)):0;
  }
  halo.ctx.putImageData(halo.pixels,0,0);
  g.save();g.imageSmoothingEnabled=false;g.drawImage(halo.out,0,0,1000,1080);g.restore();
}
function agentPose(t){
  return {x:1325+6*Math.sin(t*.82),y:517+10*Math.sin(t*1.12),
    angle:.022*Math.sin(t*.84),scale:1+.008*Math.sin(t*1.7)};
}
function agentPoint(point,pose){
  const x=(point[0]-1325)*pose.scale,y=(point[1]-517)*pose.scale;
  return [pose.x+x*Math.cos(pose.angle)-y*Math.sin(pose.angle),pose.y+x*Math.sin(pose.angle)+y*Math.cos(pose.angle)];
}
function toolPose(item,i,t){
  const p=ramp(t,item.start);
  return {x:item.x+8*Math.sin(t*.91+i*1.15),y:item.y+11*Math.cos(t*1.05+i*.95)+(1-p)*9,
    angle:.018*Math.sin(t*.87+i),opacity:p};
}
function toolPort(item,card){
  const [x,y]=item.port;
  return [card.x+x*Math.cos(card.angle)-y*Math.sin(card.angle),card.y+x*Math.sin(card.angle)+y*Math.cos(card.angle)];
}
function globalWaves(t) {
  const field=wavePixels.data,active=INTRO_TOOLS.map((v,i)=>({i,age:t-connectedAt(v)})).filter(v=>v.age>0&&v.age<5.6);
  for(let i=0;i<wavePoints.length;i++){
    const p=wavePoints[i];
    // Every global front has a physical source: the tool port at first contact.
    let light=0;
    for(const event of active){
      const radius=event.age*440,delta=(p.dist[event.i]-radius)/(24+radius*.035);
      light+=Math.exp(-delta*delta)*(.98-.105*event.age);
    }
    const density=clamp(light*.8),o=i*4;
    const lit=p.threshold<density;
    field[o]=lit?70:0;field[o+1]=lit?145:0;field[o+2]=lit?222:0;
    field[o+3]=lit?Math.round((85+clamp(light)*90)*.52*lerp(.55,1,smooth((p.x-620)/400))):0;
  }
  waveField.getContext('2d').putImageData(wavePixels,0,0);
  g.save();g.imageSmoothingEnabled=false;g.drawImage(waveField,0,0,1920,1080);g.restore();
}
function pixelStar(x,y,size,opacity,color='#badfff'){
  alpha(opacity,()=>{
    g.fillStyle=color;
    g.fillRect(x-size/2,y-2,size,4);g.fillRect(x-2,y-size/2,4,size);
    if(size>12){g.fillRect(x-4,y-4,8,8);}
  });
}
function starSprite(ctx,x,y,size,color='#9fcfff',highlight='#edf8ff'){
  const sprite=['000010000','000010000','000111000','001222100','111222111','001222100','000111000','000010000','000010000'];
  const cell=Math.max(1,Math.round(size/9));
  const left=Math.round(x/cell)*cell-4*cell,top=Math.round(y/cell)*cell-4*cell;
  for(let row=0;row<sprite.length;row++)for(let col=0;col<sprite[row].length;col++){
    const bit=sprite[row][col];if(bit==='0')continue;
    ctx.fillStyle=bit==='2'?highlight:color;
    ctx.fillRect(left+col*cell,top+row*cell,cell,cell);
  }
}
function introDecor(t){
  // Only four dim, defocused accents; crisp sprites dominate the field.
  softStars.forEach(({x,y,surface},i)=>{
    const tick=Math.floor(t*1.1+i*1.73),twinkle=.74+.26*Math.sin(tick*.9+i);
    alpha(.19*twinkle*ramp(t,.3+i%3*.15),()=>g.drawImage(surface,x-48,y-48));
  });
  const stars=[[949,170,15],[1468,178,11],[1826,397,15],[1739,715,11],[1247,886,14],[940,602,10],[1552,918,9],
    [656,332,15],[850,534,12],[58,594,9],[675,684,11],[480,238,10],[218,184,18],
    [384,112,18],[568,160,26],[744,106,8],[819,230,11],[1061,132,18],[1218,205,8],
    [1340,104,12],[1618,118,10],[1785,171,20],[1856,92,8],[941,369,9],[1857,603,11],
    [1860,802,12],[1775,935,24],[1625,988,8],[1438,926,16],[1083,963,10],[930,840,22],
    [761,933,10],[578,847,18],[339,902,10],[135,829,20],[70,931,8],[427,806,8],
    [676,970,8],[1023,697,8],[1153,171,8],[334,225,8]];
  // Slow, stepped twinkles keep the empty margins alive without crossing the copy.
  const frames=[.38,.38,.50,.70,.92,.92,.70,.50,.38,.30,.30,.30];
  stars.forEach(([x,y,s],i)=>{
    const blink=frames[Math.floor(t*.85+i*2.618)%frames.length];
    alpha(blink*ramp(t,.35+i%4*.12),()=>starSprite(g,x,y,s,i%3?'#aad8ff':'#80afe5'));
  });
  const pinpoints=[[122,145],[314,157],[456,181],[662,220],[887,95],[1012,215],[1115,80],
    [1292,147],[1516,111],[1714,96],[1832,262],[1890,472],[1793,654],[1807,844],
    [1668,955],[1480,866],[1325,970],[1174,911],[1010,886],[853,974],[695,815],
    [493,923],[258,821],[208,950],[51,747],[824,790],[968,478],[1131,367]];
  pinpoints.forEach(([x,y],i)=>alpha((.16+frames[Math.floor(t*.65+i*1.7)%frames.length]*.20)*ramp(t,.4),()=>{
    g.fillStyle='#9dbfe5';g.fillRect(x,y,i%5===0?3:2,i%5===0?3:2);
  }));
  [[1069,419],[1601,654],[1346,868]].forEach(([x,y],i)=>alpha(.28*ramp(t,1+i*.25),()=>{
    for(let n=0;n<13;n++){
      g.fillStyle='#75b5ec';g.fillRect(x+n*3,y+Math.round(Math.sin(n*.65-t*1.1+i)*4/3)*3,3,3);
    }
  }));
}
function drawReach(points,p,attached){
  // Arc-length reveal makes the leading tip visibly travel instead of fading in a wire.
  if(p<=0)return;
  const samples=[{pos:points[0],distance:0}];let distance=0;
  for(let n=1;n<=180;n++){
    const pos=bezier(points,n/180),previous=samples[n-1].pos;
    distance+=Math.hypot(pos[0]-previous[0],pos[1]-previous[1]);samples.push({pos,distance});
  }
  const target=distance*smooth(p);let tip=points[0];
  for(const s of samples){
    if(s.distance>target)break;tip=s.pos;
    const packet=attached>0?Math.exp(-(((s.distance/distance-(attached%2.4)/2.4)*14)**2)):0;
    alpha(.68+packet*.32,()=>{g.fillStyle='#82c7fb';g.fillRect(Math.round(s.pos[0]/4)*4,Math.round(s.pos[1]/4)*4,4,4);});
  }
  if(p<1){g.fillStyle='#ddf4ff';g.fillRect(Math.round(tip[0]/4)*4-2,Math.round(tip[1]/4)*4-2,8,8);}
}
function contactPulse(item,i,t){
  const age=t-connectedAt(item);if(age<0||age>1.2)return;
  const [x,y]=toolPort(item,toolPose(item,i,connectedAt(item)));
  alpha(1-age/1.2,()=>{
    circle(x,y,5,'#d9f8ff');
    for(let n=0;n<36;n++){
      const a=n*Math.PI/18,r=8+age*74;
      g.fillStyle='#b5e7ff';g.fillRect(Math.round((x+Math.cos(a)*r)/4)*4,Math.round((y+Math.sin(a)*r)/4)*4,3,3);
    }
    pixelStar(x+14,y-13,12,.8);
  });
}
function gameState(t){
  // Finish the same short level within the quicker introduction, keeping stepped motion.
  const time=Math.floor(t*13/CHAPTERS[0].end*4)/4,worldX=10+340*clamp((time-.7)/10.5);
  const jumps=[{at:3.2,duration:1.3,height:31,coin:100},{at:6.35,duration:1.5,height:37,coin:202},{at:9.25,duration:1.3,height:32,coin:296}];
  let jump=0;
  for(const event of jumps){
    const p=(time-event.at+event.duration/2)/event.duration;
    if(p>0&&p<1)jump=Math.max(jump,Math.sin(p*Math.PI)*event.height);
  }
  const won=time>=11.2;
  if(won&&time>11.4&&time<12.25)jump=12*Math.sin((time-11.4)/.85*Math.PI);
  return {time,worldX:Math.round(worldX/3)*3,camera:Math.floor(clamp(worldX-62,0,224)/3)*3,
    jump:Math.round(jump/3)*3,jumps,score:jumps.filter(e=>time>e.at+.15).length,won};
}
function retroConsole(t){
  // An original early-2000s handheld: D-pad, two buttons and a tiny moving platformer.
  const x=1325,y=662;
  g.drawImage(animateSurface(consoleSurface,t,.4),x-200,y-118);
  box(x-101,y-67,202,116,'#0d2131',null,11);
  box(x-88,y-55,176,92,'#b7d2ad',null,3);
  g.save();g.beginPath();g.rect(x-88,y-55,176,92);g.clip();
  const ink='#335746',game=gameState(t),screen=world=>x-88+world-game.camera;
  const playerX=screen(game.worldX),playerY=y+15-game.jump;
  g.fillStyle='#8eaf83';
  for(const world of [45,175,315]){
    const cloud=x-88+world-game.camera*.45;
    g.fillRect(cloud,y-26,21,3);g.fillRect(cloud+6,y-32,12,6);
  }
  g.fillStyle=ink;
  for(const [a,b] of [[0,178],[210,400]]){
    g.fillRect(screen(a),y+30,b-a,3);
    for(let world=a;world<b;world+=15)g.fillRect(screen(world),y+35,6,2);
  }
  for(const world of [88,282]){g.fillRect(screen(world),y+18,12,12);g.fillRect(screen(world+3),y+15,6,3);}
  const walking=Math.floor(game.time*4)%2;
  const sprite=game.won?['10101','11111','10101','11111','01010']
    :['11111','10101','11111',game.jump?'10101':'01110',game.jump?'10001':walking?'11001':'10011'];
  sprite.forEach((row,yy)=>[...row].forEach((bit,xx)=>{if(bit==='1')g.fillRect(playerX+xx*3,playerY+yy*3,3,3);}));
  for(const event of game.jumps){
    const age=game.time-event.at-.15,coinX=screen(event.coin),coinY=y-13;
    if(age<=0){const width=walking?3:6;g.fillRect(coinX-width/2,coinY-6,width,12);}
    else if(age<.65)pixelStar(coinX,coinY,12,1-age/.65,ink);
  }
  g.fillStyle=ink;g.fillRect(screen(367),y-7,3,37);
  g.fillRect(screen(370),y-7+(game.won?walking*3:0),12,9);
  text(String(game.score).padStart(2,'0'),x-77,y-36,11,ink,500,'left',true);
  [0,1,2].forEach(i=>{g.fillStyle=i<game.score?ink:'#8eaf83';g.fillRect(x+55+i*8,y-44,5,5);});
  if(game.won){text('CLEAR',x,y-34,11,ink,600,'center',true);pixelStar(playerX-7,playerY-7,9,.7,ink);}
  g.restore();
  // The console and agent share the same light direction and dithered shadow.
  const press=!game.won&&walking?2:0;
  box(x-143,y-12,32,11,'#162e43',null,2);box(x-133,y-23,11,33,'#162e43',null,2);
  box(x-132,y-21+press,9,9,'#254b67',null,1);
  circle(x+127,y-4,9,'#254c6c');circle(x+145,y-23,9,game.jump>0?'#87b8d6':'#386d93');
  box(x-25,y+64,19,4,'#27425e',null,2);box(x+9,y+64,19,4,'#27425e',null,2);
  for(let i=0;i<3;i++)line(x+126+i*6,y+48,x+130+i*6,y+57,'#314e68',2);
  // Small block hands rest on the controls and tap along with the screen animation.
  box(x-161,y-4+press,17,22,'#b6e4ff',null,5);
  box(x+151,y-3+(game.jump>0?2:0),17,22,'#83bada',null,5);
}
function intro(t) {
  bg(true);
  leftHalo(t);
  globalWaves(t);
  introDecor(t);
  enter(t, .1, () => g.drawImage(logoLight, 88, 56, 221, 52));
  enter(t,.3,()=>text('RILLDEX  /  RL OBSERVABILITY',91,281,20,'#9ad2ff',600));
  enter(t,.55,()=>introHeadline(t));
  enter(t,.9,()=>lines(['Trace training changes to agent actions,','failures and retries.'],90,626,25,'#bdcde2',400,40));
  enter(t,1.2,()=>text('TRAINING SIGNALS  /  ROLLOUT EVIDENCE  /  BEHAVIOR CHANGE',91,754,16,'#8eafd7',500));
  const pose=agentPose(t);
  for (const [i,item] of INTRO_TOOLS.entries()) {
    const connect=clamp((t-item.start-REACH_DELAY)/REACH_DURATION),attached=t-connectedAt(item);
    const card=toolPose(item,i,t),origin=agentPoint(item.pts[0],pose);
    const dx=origin[0]-item.pts[0][0],dy=origin[1]-item.pts[0][1];
    const pts=[origin,[item.pts[1][0]+dx,item.pts[1][1]+dy],
      [item.pts[2][0]+card.x-item.x,item.pts[2][1]+card.y-item.y],toolPort(item,card)];
    drawReach(pts,connect,attached);
    alpha(card.opacity, () => {
      g.save();g.translate(card.x,card.y);g.rotate(card.angle);
      g.drawImage(animateSurface(toolSurfaces[i],t,i*.65),-132,-78);
      icon(item.name,-74,-8,'#e0f1ff',2.7);
      text(item.name,-29,9,23,'#f4f9ff',600);
      if(attached>0){circle(81,-28,2.7+Math.sin(t*2+i)*.6,'#a7eddf');}
      g.restore();
    });
    contactPulse(item,i,t);
  }
  enter(t, .45, () => {
    g.save();g.translate(pose.x,pose.y);g.rotate(pose.angle);g.scale(pose.scale,pose.scale);g.translate(-1325,-517);
    // Minimal mascot: a compact silhouette and two plain eyes. No modeled facial features.
    g.drawImage(animateSurface(agentSurface,t),1157,338);
    const blink=Math.max(...[2.15,5.9,6.3,10.4].map(at=>Math.exp(-(((t-at)/.09)**2))));
    const eyeH=28*(1-blink)+4*blink,lookX=Math.sin(t*.85)*2;
    for(const x of [1286,1360])box(x-6+lookX,462-eyeH/2,12,eyeH,'#102639',null,2);
    // Two short arms hold the console while the longer tool connections grow behind them.
    g.save();g.strokeStyle='#9cd0ed';g.lineWidth=9;g.lineCap='round';
    g.beginPath();g.moveTo(1211,530);g.bezierCurveTo(1182,558,1163,596,1171,659);g.stroke();
    g.strokeStyle='#5f93b8';g.beginPath();g.moveTo(1438,530);g.bezierCurveTo(1470,557,1500,594,1480,657);g.stroke();g.restore();
    retroConsole(t);
    g.restore();
    text('ROLLOUT AGENT',pose.x,800+Math.sin(t*1.12)*4,14,'#92afd0',500,'center',true);
  }, 12);
  enter(t,1.3,()=>{text('LIVE OR SAVED ROLLOUTS',90,995,16,'#a5b9d6',500);text('RILLDEX RL STUDIO',1830,995,16,'#a5b9d6',500,'right');});
}
const series = DATA.runs.map(r => ({ ...r, streams: r.series.map(s => ({ ...s, smooth: smoothPoints(s.points, 50) })) }));
const stream = (i, group) => series[i].streams.find(s => s.group === group);
function curve(points, x, y, maxStep, color, width, opacity = 1) {
  alpha(opacity, () => {
    g.beginPath(); let open = false;
    for (const p of points) { if (p.step > maxStep) break; if (p.value == null) { open = false; continue; } const xx = x(p.step), yy = y(p.value); open ? g.lineTo(xx, yy) : g.moveTo(xx, yy); open = true; }
    g.strokeStyle = color; g.lineWidth = width; g.lineJoin = 'round'; g.lineCap = 'round'; g.stroke();
  });
}
function plot({ x, y, w, h, group, p, runs = [0,1,2], axes = true, cursorStep, shade = 0, labels = true }) {
  const domain = group === 'reward' ? [.15,.9] : [.0025,.24];
  const log = group === 'mismatch', tr = v => log ? Math.log10(v) : v;
  const xx = v => x + v / 1800 * w, yy = v => y + h - (tr(v)-tr(domain[0]))/(tr(domain[1])-tr(domain[0])) * h;
  const ticks = log ? [.003,.01,.03,.1,.2] : [.2,.4,.6,.8];
  for (const tick of ticks) { line(x, yy(tick), x+w, yy(tick)); if (axes) text(log ? tick : Math.round(tick*100)+'%', x-14, yy(tick)+6, 17, C.muted, 400, 'right'); }
  for (const v of [0,450,900,1350,1800]) {
    line(xx(v), y, xx(v), y+h, '#eef1f6');
    if (labels) text(v.toLocaleString('en-US'), xx(v), y+h+29, 17, C.muted, 400, 'center');
  }
  if (shade) alpha(shade*.06, () => box(xx(1200), y, xx(1425)-xx(1200), h, C.blue, null, 0));
  g.save(); g.beginPath(); g.rect(x-3, y-3, w+6, h+6); g.clip();
  runs.forEach(i => curve(stream(i,group).points, xx, yy, 1800*p, colors[i], 1.5, .19));
  runs.forEach(i => curve(stream(i,group).smooth, xx, yy, 1800*p, colors[i], 3.6));
  g.restore();
  if (cursorStep != null) {
    line(xx(cursorStep), y, xx(cursorStep), y+h, '#8391aa', 1.4, [5,6]);
    runs.forEach(i => { const point = stream(i,group).points.find(p => p.step === cursorStep); if (point) circle(xx(cursorStep), yy(point.value), 5.4, colors[i], '#fff', 2); });
  }
  return { x: xx, y: yy };
}
function overview(t) {
  bg(); top('Training overview');
  heading(t, 'TRAINING', 'Catch the shift while training runs.', 'Read outcomes, trainer signals and behavior in one workspace.');
  enter(t, .4, () => {
    box(84, 311, 1752, 62, '#fff', C.line, 13);
    circle(110,342,4,C.teal); text('Recovered run', 127, 350, 21, C.ink, 550);
    ['Summary','Training','Behavior','Execution'].forEach((s,i) => text(s, 677+i*165,350,20,i===0?C.blue:C.muted,i===0?600:450));
    line(677,371,766,371,C.blue,3);
    text('50-step EMA  ·  Native metric definitions', 1808,350,18,C.muted,400,'right');
  });
  const p = smooth((t-.9)/4.8), step = Math.floor(p*600)*3;
  ['reward','mismatch'].forEach((group,i) => enter(t,.65+i*.12, () => {
    const x = 84+i*890, w = 862, s = stream(1,group), idx = Math.min(600,Math.floor(p*600));
    box(x,394,w,542,'#fff',C.line,19,true);
    text(group==='reward'?'Generated success':'Trainer–sampler probability gap',x+27,438,23,C.ink,600);
    pill(group==='reward'?'Generated episodes':'Sampled probability gap',x+27,459,C.muted,'#f1f4f8');
    text(group==='reward'?(s.points[idx].value*100).toFixed(1)+'%':s.points[idx].value.toFixed(4),x+27,554,48,C.ink,600);
    text(`${idx+1} / ${idx+1} logs measured  ·  step ${step.toLocaleString('en-US')}`,x+27,584,18,C.muted);
    plot({x:x+85,y:615,w:735,h:181,group,p,runs:[1]});
    text('Training step  ·  faint: raw  ·  bold: EMA',x+85,854,17,C.muted);
    line(x,877,x+w,877); text('Definition & sources',x+25,912,19,C.muted);
    text('Open linked rollouts →',x+w-25,912,20,C.blue,550,'right');
  }));
  if(t>7) { const x=lerp(1570,1650,ease((t-7)/.7)), y=lerp(839,906,ease((t-7)/.7)); cursor(x,y,t-7); ripple(1650,906,t-7.8,C.blue,50); }
  footer('Simulated demo · 256 generated episodes per log');
}
function comparison(t) {
  bg(); top('Run comparison');
  heading(t,'COMPARE','Pinpoint where runs diverge.','Select one interval. Follow it across signals and runs.');
  enter(t,.4,()=>{
    box(84,310,1752,57,'#fff',C.line,13);
    series.forEach((r,i)=>{const x=110+i*314;line(x,339,x+24,339,colors[i],4);text(r.label,x+37,346,20,C.ink,550);});
    text('Faint: raw  ·  Bold: 50-step EMA',1810,346,19,C.muted,400,'right');
  });
  const p=smooth((t-.85)/4.6), selected=ramp(t,5.7,.75);
  enter(t,.55,()=>{
    box(84,388,1240,561,'#fff',C.line,19,true);
    text('Generated success',112,428,24,C.ink,600);
    text('256 generated episodes / log',1293,427,18,C.muted,400,'right');
    plot({x:174,y:455,w:1118,h:150,group:'reward',p,cursorStep:selected?1335:undefined,shade:selected,labels:false});
    text('Trainer–sampler probability gap',112,663,23,C.ink,600);
    text('Mean absolute difference · log scale',1293,663,18,C.muted,400,'right');
    plot({x:174,y:691,w:1118,h:176,group:'mismatch',p,cursorStep:selected?1335:undefined,shade:selected});
    text('Training step',732,931,17,C.muted,400,'center');
  });
  enter(t,.8,()=>{
    box(1344,388,492,561,'#fff',C.line,19,true);
    text('POINT INSPECTION',1373,427,15,C.muted,600);
    text(selected?'Step 1,335':'Compare three runs',1372,480,34,C.ink,600);
    text(selected?'Raw values · same recorded step':'Same interval · three runs',1373,513,18,C.muted);
    series.forEach((r,i)=>{
      const y=552+i*94;line(1374,y,1392,y,colors[i],4);text(r.label,1405,y+6,20,C.ink,550);
      const reward=stream(i,'reward').points.find(p=>p.step===1335).value,gap=stream(i,'mismatch').points.find(p=>p.step===1335).value;
      alpha(selected,()=>{text((reward*100).toFixed(1)+'%',1373,y+45,31,colors[i],600);text(gap.toFixed(4),1607,y+45,31,colors[i],600);text('Generated success',1374,y+69,16,C.muted);text('Mean gap',1608,y+69,16,C.muted);});
    });
    alpha(selected,()=>text('Degrading run: lower success, larger gap',1373,838,18,C.orange,500));
    line(1373,850,1805,850);button('Inspect updates →',1373,875,224,true);
  });
  footer('Simulated demo · 1,733 logs · probability difference, not KL');
}
function execution(t) {
  bg();top('Execution timeline');
  heading(t,'EXECUTION','Find where training time goes.','Follow parallel workers, timeouts and retries to their rollouts.');
  const p=smooth((t-.85)/5), now=180*p;
  const xx=v=>287+v/180*1005;
  enter(t,.4,()=>{
    box(84,311,1752,57,'#fff',C.line,13);
    text('00:00 – 03:00',110,347,22,C.ink,600);
    text('50 operations',365,347,20,C.muted);text('7 linked metric logs',627,347,20,C.muted);
    pill('1 failed attempt',952,322,C.orange,'#fff0e9');text('Shared execution clock',1810,347,19,C.muted,400,'right');
  });
  enter(t,.55,()=>{
    box(84,390,1240,557,'#fff',C.line,19,true);
    for(const v of[0,30,60,90,120,150,180]){text(Math.floor(v/60)+':'+String(v%60).padStart(2,'0'),xx(v),431,17,C.muted,400,'center');line(xx(v),451,xx(v),801,'#edf0f6');}
    const lanes=['Sampler 1','Sampler 2','Sampler 3','Sampler 4','Verifier','Learner','Weight sync'];
    lanes.forEach((name,i)=>{
      const y=474+i*49;text(name,110,y+6,20,C.ink,i>=5?550:400);line(287,y+25,1292,y+25,'#f0f3f8');
      for(const r of DATA.executions.filter(e=>e.context.worker===name)){
        if(r.timing.start>now)continue;
        const failed=r.state==='failed',retry=!!r.retry_of,pending=r.timing.end==null;
        const end=Math.min(r.timing.end??180,now), w=xx(end)-xx(r.timing.start), col=failed?C.orange:({inference:C.blue,verification:C.teal,learner_update:C.purple,weight_sync:'#7d8ca4'}[r.kind]);
        alpha(pending?.35:.82,()=>box(xx(r.timing.start),y-13,w,26,col,null,5));
        if(pending){g.save();g.beginPath();g.rect(xx(r.timing.start),y-13,w,26);g.clip();for(let j=xx(r.timing.start)-26;j<xx(end);j+=9)line(j,y+13,j+26,y-13,'#9fb6eb',2);g.restore();}
        if(failed||retry){box(xx(r.timing.start)-3,y-16,w+6,32,null,col,7);if(w>75)text(failed?'Timeout':'Retry',xx(r.timing.start)+w/2,y+5,14,'#fff',600,'center');}
      }
    });
    if(p<1)line(xx(now),449,xx(now),800,C.blue,1.4);
    line(109,821,1293,821);text('Generation throughput',110,855,19,C.ink,550);text('tokens / second',110,881,16,C.muted);
    const throughput=DATA.throughput,py=v=>906-(v-2000)/2000*58;
    for(const v of[2000,4000]){line(388,py(v),1292,py(v));text(v/1000+'k',373,py(v)+5,15,C.muted,400,'right');}
    curve(throughput,v=>388+v/180*904,py,now,C.blue,3);
  });
  const fail=DATA.executions.find(r=>r.id==='request-18-a1'),retry=DATA.executions.find(r=>r.id==='request-18-a2');
  enter(t,2.7,()=>{
    box(1344,390,492,557,'#fff',C.line,19,true);
    text('OPERATION DETAILS',1373,430,15,C.muted,600);text('Request 18',1373,483,34,C.ink,600);text('Sampler 2 · Attempt 1',1373,520,20,C.muted);
    pill('Failed · timeout',1373,543,C.orange,'#fff0e9');
    text((fail.timing.end-fail.timing.start).toFixed(1)+' s',1373,640,42,C.ink,600);text('Recorded attempt duration',1374,672,19,C.muted);
    line(1373,698,1806,698);
    text('Timed out → retried',1374,735,23,C.ink,600);text('Attempt 2 · Completed',1374,773,21,C.teal,550);
    text((retry.timing.end-retry.timing.start).toFixed(1)+' s · same source rollout',1374,807,19,C.muted);
    button('Open rollout →',1373,865,225,true);
  });
  footer('Simulated demo · 50 operations · shared execution clock');
}
function connector(points,t,delay,col=C.blue,label,lx,ly,dash=[]) {
  const p=ramp(t,delay,.7);if(!p)return;
  g.save();g.beginPath();points.forEach((v,i)=>i?g.lineTo(v[0],v[1]):g.moveTo(v[0],v[1]));
  const lengths=points.slice(1).map((v,i)=>Math.hypot(v[0]-points[i][0],v[1]-points[i][1]));const length=lengths.reduce((a,b)=>a+b,0);
  g.strokeStyle=col;g.lineWidth=2.3;g.setLineDash([length*p,length+10]);g.stroke();g.restore();
  if(p>.99){const a=points[points.length-2],b=points.at(-1),angle=Math.atan2(b[1]-a[1],b[0]-a[0]);g.save();g.translate(...b);g.rotate(angle);g.beginPath();g.moveTo(0,0);g.lineTo(-9,-5);g.lineTo(-9,5);g.closePath();g.fillStyle=col;g.fill();g.restore();}
  if(label)alpha(p,()=>{g.font='500 15px Geist';const w=g.measureText(label).width;box(lx-w/2-7,ly-18,w+14,25,'#fff',null,4);text(label,lx,ly,15,col,500,'center');});
}
function mapCard(t,delay,{x,y,w=476,h=181,kind,num,body,foot,color,fill}){
  enter(t,delay,()=>{
    box(x,y,w,h,fill,color+'55',14,true);box(x,y,5,h,color,null,[14,0,0,14]);
    text(`#${num}  ·  ${kind}`,x+24,y+33,16,color,600);
    lines(body,x+24,y+70,21,C.ink,450,28);
    text(foot,x+24,y+h-21,16,C.muted);
  },15);
}
function unitMap(t){
  bg();top('Unit map','PUBLIC TRACE · SELECTED RELATIONSHIPS');
  heading(t,'UNIT MAP','Open the attempt behind the error.','Follow the failed action, the revision and the next tool result.');
  enter(t,.4,()=>box(84,314,1752,624,'#fff',C.line,20,true));
  const xs=[118,717,1316],ys=[403,676];
  enter(t,.5,()=>{['IDEAS & CONTRIBUTIONS','ACTIONS','RETURNED FEEDBACK'].forEach((s,i)=>text(s,xs[i],366,17,[C.blue,C.teal,C.orange][i],600));});
  const cards=[
    {x:xs[0],y:ys[0],num:38,kind:'ORIENT',body:['Interprets scikit-learn as absent.','Calls for installing the package.'],foot:'Assesses feedback #37',color:C.blue,fill:'#f3f5ff'},
    {x:xs[1],y:ys[0],num:39,kind:'CONSTRUCT',body:['pip install scikit-learn seaborn','matplotlib pandas'],foot:'Response #40',color:C.teal,fill:'#effaf7'},
    {x:xs[2],y:ys[0],num:40,kind:'FEEDBACK',body:['Could not install packages.','OSError: [Errno 13]','Permission denied.'],foot:'Assessed by #41',color:C.orange,fill:'#fff7ed'},
    {x:xs[0],y:ys[1],num:41,kind:'ORIENT',body:['Identifies a permission issue.','Proposes retrying with --user.'],foot:'Assesses feedback #40',color:C.blue,fill:'#f3f5ff'},
    {x:xs[1],y:ys[1],num:42,kind:'CONSTRUCT',body:['pip install --user scikit-learn','seaborn matplotlib pandas'],foot:'Response #43 · Returns to #39',color:C.teal,fill:'#effaf7'},
    {x:xs[2],y:ys[1],num:43,kind:'FEEDBACK',body:["Cannot perform a '--user' install.",'User site-packages are not','visible in this virtualenv.'],foot:'Assessed by #50',color:C.orange,fill:'#fff7ed'}
  ];
  connector([[594,494],[717,494]],t,1.1,'#718198','recorded with',655,477);
  connector([[1316,494],[1193,494]],t,1.7,C.blue,'response to',1254,477);
  connector([[356,676],[356,628],[1554,628],[1554,584]],t,2.4,'#b44976','assesses feedback',956,630);
  connector([[594,767],[717,767]],t,3.1,'#718198','recorded with',655,750);
  connector([[1316,767],[1193,767]],t,3.7,C.blue,'response to',1254,750);
  connector([[1193,822],[1241,822],[1241,553],[1193,553]],t,4.3,'#7754c1','retry',1241,662);
  cards.forEach((c,i)=>mapCard(t,.65+i*.63,c));
  enter(t,5,()=>{pill('2 attempts',116,885,C.ink,'#f1f4f8');pill('Changed command',272,885,C.teal,'#effaf7');pill('Error persisted',517,885,C.orange,'#fff1e8');text('Open exact source records →',1797,909,20,C.blue,550,'right');});
  footer('Public OpenHands trace · linked source records');
}
function planCard(t,delay,x,y,{type,title,status,stats,depth,green=false,w=450}){
  enter(t,delay,()=>{
    box(x,y,w,183,green?'#f2faf7':'#f4f6ff',green?'#c8e2d9':'#ccd7f0',16,true);
    text(type,x+23,y+31,16,green?C.teal:C.blue,600);text(depth,x+w-23,y+31,15,C.muted,500,'right');
    lines(title,x+23,y+68,22,C.ink,550,29);text(status,x+23,y+132,18,green?C.teal:C.blue,500);
    text(stats,x+23,y+162,17,C.muted);
  });
}
let drawStructure;
function plans(t){
  if(!drawStructure)drawStructure=createStructureScene({g,C,bg,top,heading,box,text,line,circle,pill,alpha,enter,smooth,lerp,footer});
  drawStructure(t);
}

function behavior(t){
  bg();top('Behavior comparison');
  heading(t,'BEHAVIOR','Measure what followed the failure.','Compare changes of approach, repeat errors and unresolved follow-up.');
  enter(t,.4,()=>{box(84,312,1752,58,'#fff',C.line,13);text('Procedure changes',110,349,22,C.ink,550);text('Same task & configuration',474,349,20,C.muted);text('Equal rollout weight',929,349,20,C.muted);text('Save comparison →',1807,349,20,C.blue,550,'right');});
  enter(t,.55,()=>{
    box(84,391,1240,558,'#fff',C.line,19,true);
    text('What followed an earlier error?',112,438,26,C.ink,600);
    [['Error reported again',C.orange],['No error reported',C.teal],['Unresolved','#a5afc1']].forEach(([s,col],i)=>{circle(120+i*377,477,6,col);text(s,136+i*377,484,19,C.muted);});
    text('Earlier · steps 0–2',488,543,21,C.ink,550);text('Later · steps 3–5',906,543,21,C.ink,550);
    const kinds=['Same procedure','Changed settings / inputs','Different procedure','Procedure unknown'];
    kinds.forEach((label,i)=>{
      const y=589+i*82;text(label,112,y+16,20,C.ink,500);
      [DATA.behavior.earlier.rows[i],DATA.behavior.later.rows[i]].forEach((r,j)=>{
        const x=488+j*418,p=ramp(t,.9+i*.32+j*.22,1.25),w=347;let offset=0;
        if(!r.total){box(x,y-7,w,28,'#f0f3f8',null,5);text('No eligible pairs',x,y+45,16,C.muted);}
        else{['reported_again','no_reported_error','followup_unknown'].forEach((key,k)=>{const share=r.shares[key]||0;box(x+offset*p,y-7,w*share*p,28,[C.orange,C.teal,'#a5afc1'][k],null,1);offset+=w*share;});text(r.total+' eligible '+(r.total===1?'pair':'pairs')+' · '+r.eligible_rollouts+' rollout',x,y+45,16,C.muted);}
      });
    });
    text('Within each approach · unresolved follow-up remains in the denominator',112,925,17,C.muted);
  });
  enter(t,1.25,()=>{
    box(1344,391,492,558,'#fff',C.line,19,true);
    text('MEASUREMENT CONTEXT',1374,432,15,C.muted,600);
    text('7 / 7',1374,495,44,C.ink,600);text('Rollouts with saved observations',1374,530,20,C.muted);
    line(1374,556,1806,556);text('7 → 5',1374,614,39,C.ink,600);text('Pairs following an earlier error',1374,650,19,C.muted);
    text('2 later pairs excluded',1374,703,23,C.ink,550);text('No earlier error was reported.',1374,735,19,C.muted);
    line(1374,762,1806,762);button('Inspect paired attempts →',1374,790,310,true);
    lines(['No error reported does not','establish successful recovery.'],1374,881,19,C.muted,400,28);
  });
  footer('7 authored rollouts · earlier and later windows');
}
function outro(t){
  // Give the completed end card three extra seconds of still reading time.
  ending.draw(g,Math.min(t,13-1/FPS*SPEED));
}
function drawFrame(t){
  t *= SPEED;
  g.resetTransform();g.clearRect(0,0,WIDTH,HEIGHT);g.scale(WIDTH/1920,HEIGHT/1080);
  let index=CHAPTERS.findIndex(c=>t>=c.start&&t<c.end);if(index<0)index=7;
  const chapter=CHAPTERS[index],local=t-chapter.start,blend=.65;
  if(index&&local<blend){
    CHAPTERS[index-1].draw(CHAPTERS[index-1].end-CHAPTERS[index-1].start-.001);
    const p=smooth(local/blend);g.save();g.globalAlpha=p;g.translate(0,(1-p)*18);chapter.draw(local);g.restore();
  }else chapter.draw(local);
  if(index>0&&index<7)alpha(ramp(local,.5),()=>progress(t));
  if(t<.45){g.fillStyle=`rgba(8,15,32,${1-smooth(t/.45)})`;g.fillRect(0,0,1920,1080);}
  // Keep the closing logo, copy and GitHub link readable on the final frame.
}
async function init(){
  const svg=fs.readFileSync(path.join(ROOT,'tracker/web/rilldex-logo.svg'),'utf8');
  logo=await loadImage(Buffer.from(svg));logoLight=await loadImage(Buffer.from(svg.replaceAll('#05081d','#edf5ff')));
  mark=await loadImage(fs.readFileSync(path.join(ROOT,'tracker/web/rilldex-mark.svg')));
  ending=createEnding({createCanvas,logo:logoLight,data:DATA});
  headline=makeHeadline();
  softStars=[[852,158,27,4],[1715,360,27,4],[1640,908,36,5],[252,785,27,4]].map(([x,y,size,blur])=>{
    const surface=createCanvas(96,96),c=surface.getContext('2d');
    c.filter=`blur(${blur}px)`;
    starSprite(c,48,48,size,'#9fceff','#bfdfff');
    return {x,y,surface};
  });
  const haloOut=createCanvas(250,270),haloCtx=haloOut.getContext('2d');
  halo={out:haloOut,ctx:haloCtx,pixels:haloCtx.createImageData(250,270),points:[]};
  for(let row=0;row<270;row++)for(let col=0;col<250;col++){
    const dx=col*4+100,dy=row*4+140,along=dx*.58+dy*.815,across=dx*.815-dy*.58;
    // Let the corner light fade away above the copy, without a rectangular backing.
    const cornerFade=(1-smooth((row*4-100)/180))*(1-smooth((col*4-300)/420));
    const strength=.62*Math.exp(-((across/(105+along*.19))**2))*Math.exp(-along/1150)*cornerFade;
    halo.points.push({along,strength,threshold:(BAYER[(row%4)*4+col%4]+.5)/16});
  }
  agentSurface=ditherSurface(272,204,30,true);
  consoleSurface=ditherSurface(336,172,27,true);consoleSurface.console=true;
  toolSurfaces=INTRO_TOOLS.map(()=>ditherSurface(200,92,22));
  waveField=createCanvas(480,270);wavePixels=waveField.getContext('2d').createImageData(480,270);wavePoints=[];
  const origins=INTRO_TOOLS.map((item,i)=>toolPort(item,toolPose(item,i,connectedAt(item))));
  for(let row=0;row<270;row++)for(let col=0;col<480;col++)wavePoints.push({x:col*4,y:row*4,threshold:(BAYER[(row%4)*4+col%4]+.5)/16,dist:origins.map(([x,y])=>Math.hypot(col*4-x,row*4-y))});
}
async function preview(){
  const times=[7.7,5.7,7,12.7,7,7.7,5,11].map((t,i)=>(CHAPTERS[i].start+t)/SPEED);
  const contact=createCanvas(1440,1620),cg=contact.getContext('2d');cg.fillStyle=C.bg;cg.fillRect(0,0,1440,1620);
  for(let i=0;i<times.length;i++){
    drawFrame(times[i]);const png=canvas.toBuffer('image/png');fs.writeFileSync(path.join(OUT,`${String(i+1).padStart(2,'0')}-${CHAPTERS[i].name.toLowerCase().replaceAll(/[^a-z]+/g,'-')}.png`),png);
    const x=(i%2)*720,y=Math.floor(i/2)*405;cg.drawImage(await loadImage(png),x,y,720,405);
  }
  fs.writeFileSync(path.join(OUT,'contact-sheet.png'),contact.toBuffer('image/png'));
  const motion=createCanvas(1920,2160),mg=motion.getContext('2d');
  for(const [i,time] of [.9,1.5,2.1,2.6,3.2,3.7,4.3,5.1].entries()){
    drawFrame(time);const png=canvas.toBuffer('image/png');
    mg.drawImage(await loadImage(png),(i%2)*960,Math.floor(i/2)*540,960,540);
    if(i<4)fs.writeFileSync(path.join(OUT,`connection-${i+1}.png`),png);
  }
  for(const [name,time] of [['structure-detail',2.9],['structure-lines',7.8],['structure-monitor',12.7]]){drawFrame((CHAPTERS[3].start+time)/SPEED);fs.writeFileSync(path.join(OUT,name+'.png'),canvas.toBuffer('image/png'));}
  fs.writeFileSync(path.join(OUT,'intro-motion.png'),motion.toBuffer('image/png'));
  const endingContact=createCanvas(1440,1620),ec=endingContact.getContext('2d');
  for(const [i,time] of [.6,1.3,2.1,2.65,3.25,3.9,4.8,7.4].entries()){
    drawFrame(CHAPTERS.at(-1).start/SPEED+time);const png=canvas.toBuffer('image/png');
    fs.writeFileSync(path.join(OUT,`ending-${i+1}.png`),png);
    ec.drawImage(await loadImage(png),(i%2)*720,Math.floor(i/2)*405,720,405);
  }
  fs.writeFileSync(path.join(OUT,'ending-motion.png'),endingContact.toBuffer('image/png'));
  for(const [name,time] of [['wave-early',2.6],['wave-wide',3.7],['wave-late',5.1]]){
    drawFrame(time);fs.writeFileSync(path.join(OUT,name+'.png'),canvas.toBuffer('image/png'));
  }
  drawFrame((CHAPTERS[0].end-1)/SPEED);fs.writeFileSync(path.join(OUT,'poster.png'),canvas.toBuffer('image/png'));
  drawFrame(DURATION-1/FPS);fs.writeFileSync(path.join(OUT,'last-frame.png'),canvas.toBuffer('image/png'));
  fs.copyFileSync(path.join(__dirname,'preview.html'),path.join(OUT,'index.html'));
  console.log(JSON.stringify({preview:OUT,frames:times}));
}
async function render(){
  const file=path.join(OUT,'rilldex-product-tour.mp4');
  const ff=spawn('ffmpeg',['-hide_banner','-loglevel','warning','-y','-f','rawvideo','-pixel_format','rgba','-video_size',`${WIDTH}x${HEIGHT}`,'-framerate',String(FPS),'-i','pipe:0','-an','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-metadata','title=Rilldex RL Studio — Product Tour','-metadata','comment=Animated product demonstration. Simulated metrics and public trace excerpts are labeled in each scene.',file],{stdio:['pipe','ignore','pipe']});
  let stderr='';ff.stderr.on('data',d=>{stderr+=d.toString();});ff.stdin.on('error',()=>{});
  const finished=once(ff,'close');
  for(let frame=0;frame<DURATION*FPS;frame++){
    if(ff.exitCode!=null)throw new Error(stderr||'FFmpeg exited early');
    drawFrame(frame/FPS);
    if(!ff.stdin.write(Buffer.from(canvas.data())))await once(ff.stdin,'drain');
    if(frame%(FPS*5)===0)console.log(`Rendered ${frame/FPS}s / ${DURATION}s`);
  }
  ff.stdin.end();const[code]=await finished;if(code!==0)throw new Error(stderr);
  fs.writeFileSync(path.join(OUT,'chapters.json'),JSON.stringify({duration:DURATION,fps:FPS,width:WIDTH,height:HEIGHT,speed:SPEED,chapters:CHAPTERS.map(({draw,start,end,...c})=>({...c,start:start/SPEED,end:end/SPEED})),provenance:DATA.provenance},null,2));
  console.log(JSON.stringify({video:file,seconds:DURATION,width:WIDTH,height:HEIGHT,bytes:fs.statSync(file).size}));
}
(async()=>{await init();await preview();if(!args.includes('--preview'))await render();})().catch(e=>{console.error(e);process.exitCode=1;});
