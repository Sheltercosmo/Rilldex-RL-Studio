const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

test('overview covers conventional native metrics without substituting unrelated definitions',()=>{
 const {previewSignals,compactValue}=require('../tracker/web/trainer-telemetry.js');
 const row=(group,native_key)=>({group,native_key,recorded:4,context:{framework:'stable-baselines3',objective:'ppo'}});
 const rows=[row('other','rollout/ep_len_mean'),row('reward','eval/mean_reward'),row('reward','rollout/ep_rew_mean'),...['throughput','loss','entropy','kl','clipping'].map(g=>row(g,g))];
 assert.deepEqual(previewSignals(rows).map(s=>s.group),['reward','throughput','loss','entropy','clipping','kl']);
 assert.equal(previewSignals(rows)[0].native_key,'rollout/ep_rew_mean');
 assert.deepEqual(previewSignals([]),[]);
 assert.deepEqual(previewSignals([rows[0]]).map(s=>s.group),['other']);
 assert.equal(compactValue(-0.0000000018626),'-1.86e-9');
 assert.equal(compactValue(0),'0');
});

test('native control trainers use their objective and metric meanings',()=>{
 const {comparable,expectedGroups,defaultSeries}=require('../tracker/web/trainer-telemetry.js');
 const ppo={native_key:'train/loss',group:'loss',context:{framework:'stable-baselines3',objective:'ppo'}};
 const dqn={...ppo,context:{...ppo.context,objective:'dqn'}};
 assert.equal(comparable(ppo,dqn),false);
 assert.equal(comparable({...ppo,group:'reward',native_key:'rollout/ep_rew_mean'},{...dqn,group:'reward',native_key:'rollout/ep_rew_mean'}),true);
 assert.ok(expectedGroups([ppo]).includes('kl'));
 assert.deepEqual(expectedGroups([dqn]),['reward','throughput','loss']);
 const row=(native_key)=>({native_key,group:'reward',recorded:100});
 assert.equal(defaultSeries([row('eval/success_rate'),row('rollout/ep_rew_mean'),row('rollout/success_rate')]).native_key,'rollout/ep_rew_mean');
});

test('a reset session is selected once across charts, using receipt order rather than the largest step',()=>{
 const {captureSessions,selectSession}=require('../tracker/web/trainer-telemetry.js');
 const row=(session,key,first,start,end)=>({id:session+key,context:{session,producer:'worker'},native_key:key,full_range:{start,end,first_received_record:first}});
 const series=[row('old','loss',1,100,200),row('new','loss',20,0,50),row('old','reward',1,100,200),row('new','reward',20,0,50)];
 assert.deepEqual(selectSession(series).map(s=>s.context.session),['new','new']);
 const sessions=captureSessions(series);assert.equal(sessions[1].label,'Session 2 · worker · steps 0–50');
 assert.deepEqual(selectSession(series,sessions[0].id).map(s=>s.context.session),['old','old']);
 assert.equal(selectSession(series,'*').length,4);
});

test('session scopes use exact worker identities and retain selected sessions outside the inventory page',()=>{
 const {sessionParams,knownSessions}=require('../tracker/web/trainer-telemetry.js');
 assert.deepEqual(sessionParams(),{session_mode:'latest'});assert.deepEqual(sessionParams('*'),{session_mode:'all'});
 assert.deepEqual(sessionParams(JSON.stringify(['worker-a','same-name'])),{session_mode:'all',producer:'worker-a',session:'same-name'});
 assert.throws(()=>sessionParams('not-json'));assert.throws(()=>sessionParams('["", "x"]'));
 const row=(ordinal)=>({ordinal,producer:'worker',session:'s'+ordinal,start:0,end:10});
 const known=knownSessions({session_inventory:{rows:[row(120)],total:120},session_selection:{selected:row(5)}});
 assert.deepEqual(known.map(s=>s.ordinal),[5,120]);assert.equal(known[0].label,'Session 5 · worker · steps 0–10');
});

test('default charts choose reward, mean entropy and regional clipping over ancillary statistics',()=>{
 const {defaultSeries}=require('../tracker/web/trainer-telemetry.js');
 const row=(native_key,group,unit='native',recorded=256)=>({native_key,group,unit,recorded});
 assert.equal(defaultSeries([row('frac_reward_zero_std','reward','fraction'),row('rewards/format/mean','reward'),row('reward','reward')]).native_key,'reward');
 assert.equal(defaultSeries([row('entropy/max','entropy'),row('entropy/min','entropy'),row('entropy/mean','entropy')]).native_key,'entropy/mean');
 assert.equal(defaultSeries([row('clip_ratio/high_max','clipping','fraction'),row('clip_ratio/region_mean','clipping','fraction')]).native_key,'clip_ratio/region_mean');
 assert.equal(defaultSeries([row('completions/clipped_ratio','tokens','fraction'),row('completions/mean_length','tokens')]).native_key,'completions/mean_length');
 assert.equal(defaultSeries([row('eval_reward_std','reward'),row('eval_reward','reward')]).native_key,'eval_reward');
 assert.equal(defaultSeries([row('reward','reward','native',0),row('rewards/format/mean','reward')]).native_key,'rewards/format/mean');
});

test('native metrics return when revisiting overview without new log values',async()=>{
 const listeners=new Map();
 const node=()=>({hidden:true,children:[],dataset:{},style:{},setAttribute(){},removeAttribute(){},contains(){return false;},querySelector(){return null;},querySelectorAll(){return [];},append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;}});
 const host=node(),location={pathname:'/',search:''};
 const document={hidden:false,getElementById:()=>null,querySelector:s=>s==='#trainer-telemetry'?host:s==='#experiment'?{options:[]}:null,createElement:node,addEventListener(){}};
 const requests=[];
 const context={document,location,URLSearchParams,Map,innerWidth:1440,window:{addEventListener:(name,fn)=>listeners.set(name,fn)},
  setInterval(){},fetch:async url=>{requests.push(url);return{ok:true,json:async()=>({records:0,series:[]})};}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../tracker/web/trainer-telemetry.js'),'utf8'),context);
 const scope=async()=>{listeners.get('jev:scope')({detail:{experiment:'run-a'}});await new Promise(setImmediate);};
 await scope();assert.equal(host.hidden,false);assert.ok(host.children.length>0);
 location.search='?view=distribution';await scope();assert.equal(host.hidden,true);
 location.search='';await scope();assert.equal(host.hidden,false);
 assert.equal(requests.length,2);assert.ok(requests.every(url=>url.includes('experiment=run-a')));
});

test('full-run statistics and EMA do not get recomputed from plot representatives',()=>{
 const {seriesStats,trendPoints}=require('../tracker/web/trainer-telemetry.js');
 const series={points:[{step:0,value:0},{step:5000,value:10}],trend_points:[{step:0,value:0},{step:5000,value:3}],
  representation:{reduced:true},stats:{recorded:5001,coordinates:5001,last:{step:5000,value:10},delta:10}};
 assert.equal(seriesStats(series,null).measured,5001);
 assert.equal(seriesStats(series,null).total,5001);
 assert.equal(trendPoints(series,10).at(-1).value,3);
});
