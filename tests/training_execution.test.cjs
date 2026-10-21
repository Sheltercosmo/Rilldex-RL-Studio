const {test}=require('node:test');
const assert=require('node:assert/strict');
const {model,boundsFor,zoomRange,readout,plotData}=require('../tracker/web/training-execution.js');
const key=(p,i)=>JSON.stringify([p,i]);
const log={id:key('trainer','log'),producer:'trainer',record:{session:'s',clock:'update',split:'train',objective:'test',population:'native batch',framework:'custom',framework_version:'1',step:50,metrics:{gap:{label:'Gap',group:'mismatch',unit:'nats',definition:'Actual gap',value:.2,status:'recorded'}}}};
const span=(id,start,end,clock='time')=>({id:key('worker',id),producer:'worker',record:{kind:'learner_update',context:{worker:'learner'},timing:{clock,start,end},telemetry:[{producer:'trainer',id:'log'}]}});
test('curve point uses its explicit execution boundary, never numeric learner step',()=>{
 const result=model({executions:[span('u',2,3)],logs:[log],selection:{clock:'time'}});
 assert.equal(result.series[0].points[0].time,3);assert.equal(result.series[0].points[0].step,50);
});
test('ambiguous or unfinished execution references do not invent curve positions',()=>{
 for(const executions of [[span('u',2,null)],[span('u',2,3),span('v',4,5)]]){
  const result=model({executions,logs:[log],selection:{clock:'time'}});assert.equal(result.series.length,0);assert.equal(result.unplaced,1);
 }
});
test('foreign clocks are never overlaid, and unknown scalars remain selectable',()=>{
 const result=model({executions:[span('u',2,3),span('v',100,101,'foreign')],logs:[{...log,record:{...log.record,metrics:{custom:{label:'Custom',group:'other',unit:'native',value:2,status:'recorded'}}}}],selection:{clock:'time'}});
 assert.equal(result.lanes[0].rows.length,1);assert.equal(result.series[0].group,'other');
 assert.equal(model({executions:[span('u',2,3),span('v',2,3,'foreign')],logs:[log]}).series.length,0);
});
test('an absent metric breaks the curve instead of connecting over missing logs',()=>{
 const second=span('v',4,5);second.record.telemetry=[{producer:'trainer',id:'second'}];
 const result=model({executions:[span('u',2,3),second],logs:[log,{...log,id:key('trainer','second'),record:{...log.record,metrics:{}}}],selection:{clock:'time'}});
 assert.equal(result.series[0].points.length,2);assert.equal(result.series[0].points[1].status,'missing');assert.equal(result.series[0].points[1].value,null);
});

test('separate telemetry receipts at the same update do not manufacture missing points',()=>{
 const executions=[span('u',2,3),span('v',4,5)],logs=[];
 for(const [i,e]of executions.entries()){
  e.record.telemetry=[{producer:'trainer',id:'native'+i},{producer:'trainer',id:'comparison'+i}];
  logs.push({...log,id:key('trainer','native'+i),record:{...log.record,metrics:{loss:{...log.record.metrics.gap,label:'Loss',group:'loss'}}}},
            {...log,id:key('trainer','comparison'+i)});
 }
 const result=model({executions,logs,selection:{clock:'time'}});
 assert.equal(result.series.length,2);
 for(const series of result.series){assert.equal(series.points.length,2);assert.ok(series.points.every(p=>p.status==='recorded'));}
});

test('zoom keeps absolute timestamps within the chosen clock, including zero-length runs',()=>{
 const bounds=boundsFor({clocks:[{clock:'utc',start:1000,end:1600}],selection:{clock:'utc',start:1400,end:1500},executions:[]});
 assert.equal(bounds.origin,1000);assert.deepEqual(zoomRange(bounds,.5),{start:1425,end:1475});
 assert.deepEqual(zoomRange(bounds,20),{start:1000,end:1600});
 assert.deepEqual(zoomRange(bounds,1,1600),{start:1500,end:1600});
 assert.deepEqual(zoomRange({fullLo:0,fullHi:0,lo:0,hi:0},2),{start:0,end:0});
});

test('readout never borrows another operation or conceals a latest missing value',()=>{
 const series={points:[{time:1,value:4,execution:'a'},{time:2,value:6,execution:'b'},{time:3,value:null,execution:'c'}]};
 assert.equal(readout(series,null).point,null);assert.equal(readout(series,'unlogged').point,null);
 assert.equal(readout(series,'b').delta,2);assert.equal(readout(series,'b').point.value,6);
 assert.equal(readout(series,'a').delta,null);assert.equal(readout(series,'c').measured,2);
});

test('EMA keeps raw evidence and resets at missing observations',()=>{
 const points=[1,3,null,10,20].map((value,time)=>({value,time,execution:'u'+time}));
 const chart=plotData(points,{alpha:.5});
 assert.deepEqual(chart.raw,points);assert.deepEqual(chart.trend.map(p=>p.value),[1,2,null,10,15]);
 assert.equal(chart.trend[1].execution,'u1');assert.equal(chart.hi,20);
 assert.deepEqual(plotData(points).trend,points);
 assert.throws(()=>plotData(points,{alpha:2}));
});
test('log scales break at nonpositive values and count rather than clamp them',()=>{
 const chart=plotData([.001,.01,0,-1,null,.1,1].map(value=>({value})),{alpha:.5,log:true});
 assert.equal(chart.omitted,2);assert.equal(chart.lo,-3);assert.equal(chart.hi,0);
 assert.deepEqual(chart.raw.map(p=>p.value),[.001,.01,null,null,null,.1,1]);
 assert.equal(chart.trend[5].value,.1);
 assert.ok(Math.abs(chart.trend[1].value-.0055)<1e-12); // EMA in original units, then log axis.
});
test('constant and entirely missing curves have finite bounds',()=>{
 for(const log of [true,false])for(const values of [[],[null],[0],[.001,.001]]){
  const chart=plotData(values.map(value=>({value})),{log});
  assert.ok(Number.isFinite(chart.lo)&&Number.isFinite(chart.hi)&&chart.lo<chart.hi);
 }
});
