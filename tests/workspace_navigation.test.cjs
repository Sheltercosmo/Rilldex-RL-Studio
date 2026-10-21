const {test}=require('node:test');
const assert=require('node:assert/strict');
const N=require('../tracker/web/workspace-navigation.js');
const current='http://localhost:8810/semantic-map?run=example&level=units';
test('returns preserve exact filters and section anchors',()=>{
 const from='/connections?analysis_function=relation_counts#analysis-code';
 assert.equal(N.destination(current,{explicit:from}),from);
 assert.equal(N.destination(current,{arrival:'/runs?experiment=training&search=failed#results'}),'/runs?experiment=training&search=failed#results');
 assert.equal(N.destination(current,{referrer:'http://localhost:8810/investigate?saved=study'}),'/investigate?saved=study');
});
test('unsafe, external and non-page returns use a safe fallback',()=>{
 for(const explicit of ['//other.example/','https://other.example/runs','javascript:alert(1)','/api/export','/\\other.example/runs','http://user:pass@localhost:8810/runs']){
  assert.equal(N.destination(current,{explicit}),'/runs',explicit);
 }
 assert.equal(N.destination(current,{explicit:current}),'/runs');
 assert.equal(N.destination('http://localhost:8810/connections'),'/');
});
test('section deep links resolve their containing panel, not the Setup fallback',()=>{
 assert.equal(N.captureView('#directory-section'), 'watch');
 assert.equal(N.captureView('#telemetry-section'), 'code');
 assert.equal(N.captureView('#execution-section'), 'code');
 assert.equal(N.captureView('#capture-bundle-receive'), 'import');
 assert.equal(N.captureView('#analysis-table-tools',['outputs']), 'outputs');
 assert.equal(N.captureView('#native-analysis-result',['outputs'],true), 'outputs');
 assert.equal(N.captureView('#integration-catalog',['code']), 'code');
 assert.equal(N.captureView('',[],true), 'readiness');
 assert.equal(N.captureView('#missing',[]), 'setup');
});
