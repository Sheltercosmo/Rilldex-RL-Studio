const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

test('native metrics return when revisiting overview without new log values',async()=>{
 const listeners=new Map();
 const node=()=>({hidden:true,children:[],append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;}});
 const host=node(),location={pathname:'/',search:''};
 const document={hidden:false,querySelector:()=>host,createElement:node,addEventListener(){}};
 const requests=[];
 const context={document,location,URLSearchParams,Map,window:{addEventListener:(name,fn)=>listeners.set(name,fn)},
  setInterval(){},fetch:async url=>{requests.push(url);return{ok:true,json:async()=>({records:0,series:[]})};}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../tracker/web/trainer-telemetry.js'),'utf8'),context);
 const scope=async()=>{listeners.get('jev:scope')({detail:{experiment:'run-a'}});await new Promise(setImmediate);};
 await scope();assert.equal(host.hidden,false);assert.equal(host.children.length,2);
 location.search='?view=distribution';await scope();assert.equal(host.hidden,true);
 location.search='';await scope();assert.equal(host.hidden,false);
 assert.equal(requests.length,2);assert.ok(requests.every(url=>url.includes('experiment=run-a')));
});
