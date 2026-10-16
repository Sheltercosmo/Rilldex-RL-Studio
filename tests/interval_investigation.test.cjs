const test=require('node:test');
const assert=require('node:assert/strict');
const {range,evidenceCases,receiptLabel}=require('../tracker/web/interval-investigation.js');
test('brush direction does not change the interval',()=>{
 assert.deepEqual(range(12,8),range(8,12));
 assert.deepEqual(range(8,12),{baseline:[3,7],current:[8,12]});
});
test('step zero never invents a negative reference coordinate',()=>{
 assert.deepEqual(range(0,2),{baseline:null,current:[0,2]});
 assert.deepEqual(range(1,8),{baseline:[0,0],current:[1,8]});
});
test('analysis projection evidence is visible when graph matches are empty',()=>{
 const recovery={label:'Failure followed by changed check',record:{failure_action_id:'e1',attempts:[]}};
 assert.deepEqual(evidenceCases({cases:[],analysis_cases:[recovery]}),[recovery]);
 assert.deepEqual(evidenceCases({cases:[{anchor:'unit:a'}]}),[{anchor:'unit:a'}]);
 assert.deepEqual(evidenceCases({details:{note:'Custom scalar'}}),[]);
});
test('unresolved evidence differs from a missing receipt or inapplicable task',()=>{
 const p={value:null,value_id:'receipt',unknown_opportunities:2,status:'unavailable'};
 assert.equal(receiptLabel(p),'Unresolved evidence · 2 opportunities');
 assert.equal(receiptLabel({...p,value_id:null}),'No receipt at capture');
 assert.equal(receiptLabel({...p,unknown_opportunities:0,opportunities:0}),'No eligible opportunities');
 assert.equal(receiptLabel({...p,status:'error'}),'Measurement error');
 assert.equal(receiptLabel({...p,value:0},'fraction'),'0.0%');
});
