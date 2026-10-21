const {test}=require('node:test');
const assert=require('node:assert/strict');
const {comparable,smoothPoints,intervalStats,defaultSeries}=require('../tracker/web/trainer-telemetry.js');
const series={native_key:'mismatch',unit:'nats',reduction:'token mean',definition:'sampled k3 before exclusion',group:'mismatch',context:{clock:'learner_update',split:'train',population:'consumed batch',environment:'SWE',framework:'custom',session:'first',objective:'IPO'}};
test('run comparisons permit different objectives but preserve definitions and populations',()=>{
 assert.equal(comparable(series,{...series,context:{...series.context,objective:'IcePop',session:'second'}}),true);
 for(const [field,value]of [['unit','probability'],['definition','reference KL'],['reduction','sequence mean']])assert.equal(comparable(series,{...series,[field]:value}),false);
 for(const [field,value]of [['clock','generation_batch'],['split','evaluation'],['population','admitted batch'],['environment','math']])assert.equal(comparable(series,{...series,context:{...series.context,[field]:value}}),false);
});
test('EMA half-life depends on step distance rather than logging frequency',()=>{
 const sparse=smoothPoints([{step:0,value:0},{step:10,value:1}],10);
 const dense=smoothPoints([{step:0,value:0},...Array.from({length:10},(_,i)=>({step:i+1,value:1}))],10);
 assert.equal(sparse[1].value,.5);assert.ok(Math.abs(dense.at(-1).value-.5)<1e-12);
});
test('interval selection does not restart the trend; missing values do',()=>{
 const points=[{step:0,value:0},{step:10,value:1},{step:20,value:1},{step:30,value:null},{step:40,value:10}];
 const trend=smoothPoints(points,10);
 assert.equal(intervalStats(trend,[20,40]).first.value,.75);
 assert.equal(trend.at(-1).value,10);assert.equal(points[2].value,1);
 const stats=intervalStats(points,[10,30]);assert.equal(stats.finite.length,2);assert.equal(stats.rows.length,3);assert.equal(stats.last.step,20);
});
test('empty intervals and zero values remain distinguishable',()=>{
 const points=[{step:0,value:0},{step:10,value:null}];
 assert.equal(intervalStats(points,[1,9]).last,undefined);
 assert.equal(intervalStats(points,[0,10]).last.value,0);
 assert.equal(intervalStats(points,[0,10]).delta,null);
});
test('comparison defaults select a meaningful gap rather than a token counter',()=>{
 const count={native_key:'comparison/compared_tokens',unit:'tokens',recorded:100};
 const gap={native_key:'comparison/mean_probability_gap',unit:'probability',recorded:90};
 assert.equal(defaultSeries([count,gap]),gap);
});
