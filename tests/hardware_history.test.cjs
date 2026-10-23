const test=require('node:test'),assert=require('node:assert/strict');
const {segments,units}=require('../tracker/web/hardware-history.js');
test('sensor gaps break lines even when intermediate points are reduced',()=>{
 const p=[{segment:0,value:1},{segment:0,value:2},{segment:8,value:3},{segment:9,value:4}];
 assert.deepEqual(segments(p),[p.slice(0,2),[p[2]],[p[3]]]);assert.deepEqual(segments([]),[]);
});
test('missing values are unavailable and bytes retain their physical unit',()=>{
 assert.equal(units(null,'%'),'Unavailable');assert.equal(units(0,'%'),'0 %');assert.equal(units(2**30,'bytes'),'1 GiB');
});
