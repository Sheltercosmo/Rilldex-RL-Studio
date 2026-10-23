const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../tracker/web/monitoring.js'),'utf8');
const context={module:{exports:{}},URLSearchParams};
vm.runInNewContext(source.slice(0,source.indexOf('const chartCohorts')),context);
const {mode,href,previews,mapHref,scopeQuery}=context.module.exports;
test('overview separates combined summary from focused views and preserves legacy evidence routes',()=>{
 assert.equal(mode('').section,'summary');
 assert.equal(mode('?view=experiments').section,'library');
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
 assert.equal(href('',{experiment:'',environment:''}),'/?scope=all');
});
test('the visible population is serialized for pins, reloads and return links',()=>{
 const q=new URLSearchParams(scopeQuery('?view=health&experiment=old&signals_compare=B&signals_compare=C',{experiment:'run / a&b',environment:'terminal'}));
 assert.equal(q.get('experiment'),'run / a&b');assert.equal(q.get('environment'),'terminal');
 assert.deepEqual(q.getAll('signals_compare'),['B','C']);assert.equal(q.get('view'),'health');
 assert.equal(scopeQuery('?experiment=old&environment=terminal',{}),'');
 assert.equal(scopeQuery('?view=measures&experiment=old',{experiment:''}),'?view=measures');
});
test('summary previews prioritize measured behavior and outcomes without dropping the missing catalog',()=>{
 const monitor=(id,group,available,metric,enabled=true)=>({id,group,coverage:{available},metric,enabled});
 const rows=[monitor('length','Training',5,'agent_text_chars'),monitor('empty','Behavior',0),monitor('recovery','Behavior',5),monitor('success','Training',5,'recorded_success'),monitor('paused','Behavior',5,null,false)];
 assert.deepEqual(Array.from(previews(rows),m=>m.id),['recovery','success','length']);
 assert.equal(rows.length,5);
 assert.deepEqual(Array.from(previews([rows[1]]),m=>m.id),['empty']);
});
test('map entry pins its advertised graph while explicit source and measurements retain their scope',()=>{
 const run={id:'run / 1',default_map:{id:'g-latest',observer:'semantic'}};
 const read=options=>new URL(mapHref(run,options),'http://local').searchParams;
 const entry=read({returnTo:'/?experiment=job&view=measures'});
 assert.equal(entry.get('graph'),'g-latest');assert.equal(entry.get('observer'),'semantic');
 assert.equal(entry.get('return_to'),'/?experiment=job&view=measures');
 const source=read({observer:'source'});assert.equal(source.get('observer'),'source');assert.equal(source.has('graph'),false);
 const receipt=read({observer:'earlier',valueId:'receipt'});assert.equal(receipt.get('observer'),'earlier');assert.equal(receipt.get('value'),'receipt');assert.equal(receipt.has('graph'),false);
 assert.equal(read().get('level'),'units');assert.equal(read().get('run'),'run / 1');
});
