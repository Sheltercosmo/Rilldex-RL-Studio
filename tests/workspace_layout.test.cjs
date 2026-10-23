'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {viewPath,cleanPins,togglePin,researchGroup,researchView,investigationPanel}=require('../tracker/web/workspace-layout.js');
test('pins retain exact evidence revisions and selection while dropping recursive return paths',()=>{
 const path=viewPath('/semantic-map?run=r&return_to=%2Finvestigate%3Fsaved%3Di&graph=g&observer=o#unit-4');
 assert.equal(path,'/semantic-map?graph=g&observer=o&run=r#unit-4');
 assert.equal(viewPath('/?view=health&experiment=A%20B&compare=C'), '/?compare=C&experiment=A+B&view=health');
});
test('pins cannot navigate to external pages, executable URLs or API endpoints',()=>{
 for(const path of ['https://other.test/','//other.test/','javascript:alert(1)','/api/workspace/snapshot','/\\other.test','/\nmonitors'])assert.equal(viewPath(path),null,path);
 assert.equal(viewPath('http://localhost:1/monitors','http://localhost:1'),' /monitors'.trim());
});
test('pin toggle preserves other views, deduplicates and bounds persisted data',()=>{
 const a={label:' Outcome changes ',path:'/investigate?saved=a'},b={label:'Loss',path:'/?view=health'};
 assert.deepEqual(togglePin([b],a),[{label:'Outcome changes',path:a.path},b]);
 assert.deepEqual(togglePin([a,b],a),[b]);
 assert.deepEqual(cleanPins([a,a,null,{label:'Wrong',path:'//other.test'},b]),[{label:'Outcome changes',path:a.path},b]);
 const rows=Array.from({length:12},(_,i)=>({label:'Review '+i,path:'/investigate?saved='+i}));
 assert.equal(togglePin(rows,a).length,12);assert.equal(togglePin(rows,a)[0].path,a.path);
 assert.deepEqual(cleanPins({}),[]);
});
test('saved research links reveal their containing view before navigating',()=>{
 const sections=[{id:'research-section-0'},{id:'case-behavior'},{id:'ii-compare-rollout-cases'},{id:'investigation-checks'}];
 assert.equal(researchView({},sections),'summary');
 assert.equal(researchView({hash:'#case-behavior'},sections),'summary');
 assert.equal(researchView({hash:'#ii-compare-rollout-cases'},sections),'evidence');
 assert.equal(researchView({hash:'#check-123'},sections.map(s=>({...s,containsTarget:s.id==='investigation-checks'}))),'checks');
 assert.equal(researchView({hash:'#research-all'},sections),'all');
 assert.equal(researchView({panel:'checks'},sections),'checks');
 assert.equal(researchView({caseSelection:true},sections),'evidence');
 assert.equal(researchView({hash:'#research-summary',panel:'checks',caseSelection:true},sections),'summary');
 assert.equal(researchView({hash:'#%invalid'},sections),'summary');
 assert.equal(researchGroup('ii-hypothesis-follow-up'),'checks');
});
test('metric investigations open a linked check even without a panel query',()=>{
 assert.equal(investigationPanel({hash:'#check-abc'}),'checks');
 assert.equal(investigationPanel({hash:'#research-checks',panel:'comparison'}),'checks');
 assert.equal(investigationPanel({hash:'#investigation-process',panel:'focus'}),'process');
 assert.equal(investigationPanel({panel:'notes'}),'notes');
 assert.equal(investigationPanel({hash:'#other',panel:'invalid'}),'comparison');
});
