const {test}=require('node:test');
const assert=require('node:assert/strict');
const {model}=require('../tracker/web/evaluation-evidence.js');
const {deliveryModel}=require('../tracker/web/evaluation-evidence.js');

test('delivery conflicts retain separate checks; pending results have no visible verdict',()=>{
 const m=deliveryModel({status:'conflicting_check_results',requirement:{criterion_id:'acceptance'},check_history:[
  {action_id:'a',result_event_id:'b',result:'failed',availability:'recorded_before_delivery',applicability:'matching_inputs'},
  {action_id:'c',result_event_id:'d',result:'passed',availability:'recorded_before_delivery',applicability:'matching_inputs'},
  {action_id:'e',result_event_id:null,result:'unknown',availability:'pending_at_delivery',applicability:'unknown'}]});
 assert.equal(m.conflict,true);assert.deepEqual(m.history.map(h=>h.label),['failed','passed','Pending at delivery']);
 assert.match(m.title,/disagree/);assert.equal(m.history[2].result_event_id,null);
});

test('reward role remains independent of check verdict and zero score',()=>{
 const r=model({available:true,status:'complete',components:[{id:'DB',role:'reward',value:1},{id:'ACTION',role:'diagnostic',value:0}],criteria:[
  {description:'One',role:'reward',met:true},{description:'Two',role:'diagnostic',met:false},{description:'Three',role:'reward',met:null}]});
 assert.equal(r.components[1].role,'Diagnostic only');assert.equal(r.components[1].name,'Action matching');assert.equal(r.components[1].score,0);
 assert.deepEqual(r.checks.map(c=>c.verdict),['Not met','Unknown','Met']);assert.equal(r.checks[0].role,'Diagnostic only');
});
test('missing scores and checks do not become zero or passing',()=>{
 const r=model({available:true,components:[{id:'custom',role:'reward',value:null}],criteria:[{description:'Unknown',role:'reward'}]});
 assert.equal(r.components[0].score,'Not recorded');assert.equal(r.checks[0].verdict,'Unknown');assert.equal(model({available:false}).available,false);
});
