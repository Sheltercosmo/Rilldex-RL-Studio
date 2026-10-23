const test=require('node:test'),assert=require('node:assert/strict');
const {configChanges}=require('../tracker/web/run-capture.js');
test('configuration changes preserve missing, null, false and nested identities',()=>{
 const changes=configChanges({lr:0,enabled:false,unknown:null,nested:{value:1},'nested / value':2},
   {lr:.01,enabled:false,added:null,nested:{value:2},'nested / value':2});
 assert.equal(changes.length,4);
 assert.deepEqual(changes.find(c=>c.path[0]==='lr'),{path:['lr'],before:0,after:.01,beforePresent:true,afterPresent:true});
 const missing=changes.find(c=>c.path[0]==='unknown');assert.equal(missing.afterPresent,false);assert.equal(missing.before,null);
 assert.ok(changes.some(c=>c.path.join('.')==='nested.value'));
 assert.ok(!changes.some(c=>c.path[0]==='nested / value'));
});
test('configuration key order does not create changes and empty snapshots stay explicit',()=>{
 assert.deepEqual(configChanges({objects:[{b:2,a:1}]},{objects:[{a:1,b:2}]}),[]);
 assert.equal(configChanges({},{}).length,0);assert.equal(configChanges({},{lr:1}).length,1);
 assert.equal(configChanges({nested:{}},{nested:null}).length,1);
});
