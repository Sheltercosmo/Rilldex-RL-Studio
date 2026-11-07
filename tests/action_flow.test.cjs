const {test}=require('node:test');
const assert=require('node:assert/strict');
const {groups,markers}=require('../tracker/web/action-flow.js');

test('flow preserves all actions and context lanes without ordering parallel members',()=>{
 const actions=[['a',1,'first',['a','b'],false],['b',2,'first',['a','b'],false],['c',3,'second',['c'],true]].map(([event_id,number,lane_id,dispatch_group,order_known])=>({event_id,number,lane_id,dispatch_group,order_known}));
 const result=groups({actions,lanes:[{id:'first',action_ids:['a','b']},{id:'second',action_ids:['c']}]});
 assert.equal(result[0].batches.length,1);assert.equal(result[0].batches[0].unordered,true);
 assert.equal(result[1].batches[0].unordered,false);
 assert.deepEqual(result.flatMap(l=>l.batches.flatMap(b=>b.actions.map(a=>a.event_id))),['a','b','c']);
});

test('change markers require a decided response; repetition and task relation stay distinct',()=>{
 const base={fields:{feedback_response:{value:'method_change',status:'unresolved'}},scope:'unresolved'};
 assert.deepEqual(markers(base),[]);
 assert.deepEqual(markers({...base,same_dispatch_as:'earlier'}).map(m=>m.kind),['match']);
 const decided={...base,fields:{feedback_response:{value:'method_change',status:'decided'}},scope:'outside'};
 assert.deepEqual(markers(decided).map(m=>m.kind),['change','scope']);
 assert.deepEqual(markers({...decided,fields:{feedback_response:{value:'continue',status:'decided'}},scope:'connected'}),[]);
});

test('a saved work return is distinct from a command match',()=>{
 const a={fields:{},scope:'unresolved',work_returns:['episode-1']};
 assert.deepEqual(markers(a).map(m=>m.kind),['return']);
 assert.deepEqual(markers({...a,same_dispatch_as:'earlier'}).map(m=>m.kind),['match','return']);
 assert.deepEqual(markers({...a,work_returns:[]}),[]);
});
