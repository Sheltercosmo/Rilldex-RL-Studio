const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const context={window:{}};
vm.runInNewContext(fs.readFileSync(require.resolve('../tracker/web/details.js'),'utf8'),context);
const lanes=t=>JSON.parse(JSON.stringify(context.window.trackerDetails.goalLanes(t)));
const assignment=(id,session=null,order=true)=>({event_id:id,trajectory_id:'main',context_id:session,
  goal_id:'same-goal',status:'decided',order_known:order});
const continued=(id,previous)=>({event_id:id,kind:'continue',previous_event_id:previous});

test('goal timeline separates interleaved sessions even when identifiers match',()=>{
  const t={assignments:[assignment('a','one'),assignment('b','two'),assignment('c','one')],
    transitions:[continued('c','a')]};
  const before=JSON.stringify(t),out=lanes(t);
  assert.equal(out.length,2);
  assert.deepEqual(out[0].segments[0].ids,['a','c']);
  assert.deepEqual(out[1].segments[0].ids,['b']);
  assert.equal(JSON.stringify(t),before);
});

test('unknown order stays visible instead of merging into an apparently continuous card',()=>{
  const t={assignments:[assignment('a'),assignment('b',null,false),assignment('c'),assignment('d')],
    transitions:[{event_id:'b',kind:'focus_observed_order_unknown'},
      {event_id:'c',kind:'focus_reobserved'},continued('d','c')]};
  assert.deepEqual(lanes(t)[0].segments.map(s=>s.ids),[['a'],['b'],['c','d']]);
  assert.equal(lanes(t)[0].segments[1].order_known,false);
});

test('missing adjacency evidence cannot merge two observations of the same goal',()=>{
  const t={assignments:[assignment('a'),assignment('b')],transitions:[continued('b','missing')]};
  assert.equal(lanes(t)[0].segments.length,2);
  t.transitions=[continued('b','a')];
  assert.equal(lanes(t)[0].segments.length,1);
});
