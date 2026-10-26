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

test('workflow navigation keeps drilldowns in their parent and selects exactly one destination',()=>{
 const routes=[['/','', 'overview'],['/','?view=health&signals_compare=B','signals'],['/','?view=strategies&lens=procedure','behavior'],['/','?comparison=saved','behavior'],['/','?view=execution','execution'],['/semantic-map','?run=r&plan_episode=e','rollouts'],['/source','?run=r','rollouts'],['/','?view=experiments','library'],['/monitors','?view=reward','reward']];
 for(const [path,query,key]of routes){const groups=N.groups(path,query),active=groups.flatMap(g=>g.items).filter(x=>x.active);assert.deepEqual(active.map(x=>x.id),[key]);assert.equal(groups.filter(g=>g.active).length,1);}
 const map=N.groups('/semantic-map','?run=r');assert.equal(map.find(g=>g.id==='training').active,false);assert.equal(map.find(g=>g.id==='workspace').active,false);
 assert(!map.flatMap(g=>g.items).some(i=>i.href==='/semantic-map'),'A rollout map is a drilldown, not a competing global destination');
});

test('search exposes nested features without adding global feature menus',()=>{
 const shortcuts=N.shortcuts();
 for(const path of ['/?view=execution','/?view=health','/?view=strategies&lens=procedure','/?view=measures&measure_family=revision'])assert(shortcuts.some(r=>r[2]===path));
 assert.equal(N.title('/?view=execution'),'Execution timeline');
 assert.equal(N.title('/?view=health&signals_compare=other'),'Signals & comparison');
 assert.equal(N.title('/?view=experiments'),'Runs & projects');
});
