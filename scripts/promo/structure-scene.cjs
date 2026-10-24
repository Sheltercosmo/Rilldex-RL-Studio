'use strict';
const {nodeType}=require('../../tracker/web/structure-lines.js');
const DATA=require('./deep-structure-data.json');

// A tidy tree: distance is structural depth, not event time or inferred causality.
function geometry(data=DATA){
 const nodes=new Map(data.nodes.map(n=>[n.id,{...n}])),children=new Map();
 for(const e of data.links){if(!children.has(e.target))children.set(e.target,[]);children.get(e.target).push(e.source);}
 let leaf=0;
 function place(id,depth){const n=nodes.get(id),kids=children.get(id)||[];n.x=24+depth*196;n.depth=depth;n.width=164;n.y=kids.length?kids.map(k=>place(k,depth+1)).reduce((a,b)=>a+b,0)/kids.length:leaf++*22;return n.y;}
 data.roots.forEach(id=>place(id,0));
 return {nodes,links:data.links,relations:data.relations,levels:1+Math.max(...[...nodes.values()].map(n=>n.depth)),leaves:leaf};
}
function createStructureScene(h){
 const {g,C,bg,top,heading,box,text,line,circle,pill,alpha,enter,smooth,lerp,footer}=h;
 const graph=geometry(),focus=new Set(DATA.focus),selected=DATA.focus.map(id=>graph.nodes.get(id));
 const centerX=selected.reduce((a,n)=>a+n.x+n.width/2,0)/selected.length,centerY=selected.reduce((a,n)=>a+n.y,0)/selected.length;
 return function(t){
  bg();top('Plans & attempts','SIMULATED ROLLOUT · STRUCTURE DEMO');
  heading(t,'WORK STRUCTURE','Reveal how an agent organizes and carries out work.','Follow branches, revisions and repeated work. See their structure shift through training.');
  const compact=smooth((t-3.4)/1.1),zoom=smooth((t-4.1)/2.5),reveal=smooth((t-4.2)/2.4);
  enter(t,.2,()=>{
   box(84,305,1752,645,'#fff',C.line,20,true);
   text(zoom<.5?'FOCUS · CROSS-VALIDATION / ONE FOLD':`${graph.nodes.size} WORK ITEMS · ${graph.levels} LEVELS · ONE ROLLOUT`,116,345,16,C.blue,600);
   pill(compact>.5?'Structure lines':'Detailed map',1603,319,C.blue,'#edf2ff',190);
  });
  const scale=lerp(2,1,zoom),tx=lerp(960-centerX*2,166,zoom),ty=lerp(620-centerY*2,407,zoom);
  g.save();g.beginPath();g.rect(108,379,1704,506);g.clip();g.translate(tx,ty);g.scale(scale,scale);
  for(const e of graph.links){const a=graph.nodes.get(e.target),b=graph.nodes.get(e.source),inside=focus.has(a.id)&&focus.has(b.id);alpha(inside?1:reveal,()=>{
   const x=a.x+a.width,ex=b.x;g.beginPath();g.moveTo(x,a.y);g.bezierCurveTo(x+16,a.y,ex-16,b.y,ex,b.y);g.strokeStyle=nodeType(b).color;g.globalAlpha*=.48;g.lineWidth=1.2;g.stroke();
  });}
  for(const n of graph.nodes.values()){
   const active=focus.has(n.id),color=nodeType(n).color,p=active?smooth((t-.6-DATA.focus.indexOf(n.id)*.22)/.7):reveal;
   alpha(p,()=>{
    alpha(1-compact,()=>{box(n.x,n.y-25,n.width,50,'#fff',color,7);text(nodeType(n).label.toUpperCase(),n.x+9,n.y-9,8.5,color,600);text(n.label,n.x+9,n.y+9,11.5,C.ink,550);});
    alpha(compact,()=>{
     line(n.x,n.y,n.x+n.width,n.y,color,1.6);
     text(n.label,n.x+7,n.y-7,14,C.ink,active?650:450);
    });
   });
  }
  // A return is drawn as a dashed relationship, never as extra nesting.
  alpha(reveal,()=>{const a=graph.nodes.get('fix'),b=graph.nodes.get('render');g.save();g.setLineDash([4,4]);g.strokeStyle=C.orange;g.lineWidth=1.3;g.beginPath();g.moveTo(a.x+a.width,a.y);g.lineTo(a.x+a.width+14,a.y);g.lineTo(a.x+a.width+14,a.y+19);g.lineTo(b.x+82,a.y+19);g.lineTo(b.x+82,b.y+4);g.stroke();g.restore();});
  g.restore();
  alpha(reveal,()=>{
   ['objective','subgoal','approach','plan','plan_step'].forEach((kind,i)=>{const type=nodeType({kind:['objective','subgoal','approach'].includes(kind)?'outline_item':kind,work_kind:kind});line(116+i*147,373,130+i*147,373,type.color,2);text(type.label,136+i*147,378,13,C.muted,500);});
   text('Root = depth 0 · deepest step = depth 7',1794,378,13,C.muted,450,'right');
   for(let depth=0;depth<8;depth++)text('D'+depth,190+depth*196,900,11,C.muted,500);
  });
  enter(t,8.4,()=>{line(116,915,1804,915,C.line);circle(124,934,4,C.teal);text('Monitor depth, returns and declared-order departures',138,939,16,C.ink,550);text('Set a threshold → inspect the finding',1789,939,15,C.blue,550,'right');},5);
  footer('Authored structure demo · solid: parentage · dashed: return after change · color: node type');
 };
}
module.exports={createStructureScene,geometry};
