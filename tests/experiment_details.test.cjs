const test=require('node:test'),assert=require('node:assert/strict');
const {fields,executionURL,trainerURL}=require('../tracker/web/experiment-details.js');
test('settings preserve zero, false, null, arrays and explicit empty maps',()=>{
 assert.deepEqual(fields({lr:0,enabled:false,scheduler:{warmup:10},stops:['a','b'],unknown:null,empty:{}}),[
  ['lr','0'],['enabled','false'],['scheduler / warmup','10'],['stops','["a","b"]'],['unknown','null'],['empty','{}']]);
});
test('trainer stream navigation retains exact worker and session despite special characters',()=>{
 const u=new URL(trainerURL('run / 1',{producer:'rank?2',session:'restart/#1',clock:'environment_timesteps'},'CartPole-v1'),'http://local');
 assert.equal(u.searchParams.get('experiment'),'run / 1');
 assert.deepEqual(JSON.parse(u.searchParams.get('signals_session')),['rank?2','restart/#1']);
 assert.equal(u.searchParams.get('signals_clock'),'environment_timesteps');assert.equal(u.searchParams.get('environment'),'CartPole-v1');
});
test('execution navigation preserves exact producer, operation and clock',()=>{
 const u=new URL(executionURL('job / a',{producer:'rank?1',id:'update#42',record:{timing:{clock:'a/b'}}}),'http://local');
 assert.equal(u.searchParams.get('experiment'),'job / a');
 assert.deepEqual(JSON.parse(u.searchParams.get('execution_focus')),['rank?1','update#42']);
 assert.equal(u.searchParams.get('execution_clock'),'a/b');
});
