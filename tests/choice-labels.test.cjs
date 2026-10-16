const {test}=require('node:test');
const assert=require('node:assert/strict');
const labels=require('../tracker/web/choice-labels.js');

test('friendly resource names hide implementation hashes without changing IDs',()=>{
 const id='work-outline-3fb955e1d4fbe6e22406';
 const [r]=labels.choices([{id}]);
 assert.equal(r.label,'Work outline');assert.equal(r.id,id);
 assert.ok(r.title.includes(id));
 assert.equal(labels.name('source'),'Recorded source');
 assert.equal(labels.name('work-state/6'),'Work state');
 assert.equal(labels.name('aa00112233445566'), 'Saved set');
 assert.equal(labels.name('x','API / JSONL capture'), 'API / JSONL capture');
});
test('duplicate human names remain distinguishable and stable when reordered',()=>{
 const rows=[{id:'outline-b',label:'Reviewed plan'},{id:'outline-a',label:'Reviewed plan'}];
 const result=labels.choices(rows),reversed=labels.choices([...rows].reverse());
 assert.notEqual(result[0].label,result[1].label);
 for(const item of result)assert.equal(item.label,reversed.find(r=>r.id===item.id).label);
 assert.equal(labels.choices([{id:'a',label:'Unique name'}])[0].label,'Unique name');
 assert.equal(labels.choices([{id:'v/1'},{id:'v/2'}])[0].label,'V · Set 1');
});
test('generated provenance chains stay in details while qualifications stay visible',()=>{
 const full='Reviewed work outline · Plan stages and result evidence · development';
 const [row]=labels.choices([{id:'work-outline-aa00112233445566',label:full}]);
 assert.equal(row.label,'Reviewed work outline · development');
 assert.ok(row.title.includes(full));
 assert.equal(labels.name('custom',full),full);
});
test('rollouts use task and training context rather than source hashes',()=>{
 assert.equal(labels.rollout({metadata:{task_id:'django__django-123',training_step:4,rollout_n:2}}),'django__django-123 · Step 4 · Repeat 2');
 assert.equal(labels.rollout({metadata:{task_id:'prompt-sha256:aa00112233445566',environment:'arithmetic'}}),'Arithmetic');
 assert.equal(labels.rollout({id:'aa00112233445566'}),'Rollout');
});
test('option presentation keeps its exact query value and technical title',()=>{
 global.document={createElement:()=>({})};
 const id='monitor-aa00112233445566';
 const row=labels.choices([{id,label:'Recovery after revision',suffix:'12 rollouts'}])[0];
 const option=labels.option(row);
 assert.equal(option.value,id);assert.equal(option.textContent,'Recovery after revision · 12 rollouts');
 assert.ok(option.title.includes(id));delete global.document;
});
