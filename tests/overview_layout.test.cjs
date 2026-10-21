const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../tracker/web/monitoring.js'),'utf8');
const context={module:{exports:{}},URLSearchParams};
vm.runInNewContext(source.slice(0,source.indexOf('const chartCohorts')),context);
const {mode,href,previews}=context.module.exports;
test('overview separates combined summary from focused views and preserves legacy evidence routes',()=>{
 assert.equal(mode('').section,'summary');
 assert.equal(mode('?view=health').panel,'signals');
 assert.equal(mode('?view=health&health_panel=diagnostics').panel,'diagnostics');
 assert.equal(mode('?view=health&health_mode=reward_relationships').panel,'diagnostics');
 assert.equal(mode('?monitor=abc').panel,'measures');
 assert.equal(mode('?comparison=saved').panel,'measures');
 assert.equal(mode('?view=measures').section,'behavior');
 assert.equal(mode('?view=strategies&detail=episodes').panel,'profiles');
 assert.equal(mode('?view=execution').section,'execution');
 assert.equal(mode('?view=training').section,'samples');
});
test('navigation retains explicit scope and encodes arbitrary experiment names',()=>{
 const url=new URL(href('measures',{experiment:'run / a&b',environment:'terminal'},{availability:'missing'}),'http://local');
 assert.equal(url.searchParams.get('experiment'),'run / a&b');
 assert.equal(url.searchParams.get('environment'),'terminal');
 assert.equal(url.searchParams.get('availability'),'missing');
 assert.equal(url.searchParams.get('view'),'measures');
 assert.equal(href('',{experiment:'',environment:''}),'/');
});
test('summary previews prioritize measured behavior and outcomes without dropping the missing catalog',()=>{
 const monitor=(id,group,available,metric,enabled=true)=>({id,group,coverage:{available},metric,enabled});
 const rows=[monitor('length','Training',5,'agent_text_chars'),monitor('empty','Behavior',0),monitor('recovery','Behavior',5),monitor('success','Training',5,'recorded_success'),monitor('paused','Behavior',5,null,false)];
 assert.deepEqual(Array.from(previews(rows),m=>m.id),['recovery','success','length']);
 assert.equal(rows.length,5);
 assert.deepEqual(Array.from(previews([rows[1]]),m=>m.id),['empty']);
});
