const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../tracker/web/measurement-review.js'),'utf8');

test('saved citation metadata never becomes client-controlled evidence on revision',()=>{
 const checked=[{event_id:'event1',start:0,end:4,text:'🧪abc'},
  {input_name:'check',input:{value:false}},
  {evaluation_id:'report1',report_hash:'original'},
  {evaluator_input:'check',evaluation_ids:['report1']}];
 const c=vm.createContext({document:{querySelectorAll:()=>[]},Map,JSON});
 vm.runInContext(source.slice(source.indexOf('const citationRef='),source.indexOf('function citationCount(')),c);
 c.records=checked;
 const keys=vm.runInContext('records.map(citationRef)',c);
 assert.deepEqual(JSON.parse(JSON.stringify(keys)),[
  {event_id:'event1',start:0,end:4},{input_name:'check'},{evaluation_id:'report1'},{evaluator_input:'check'}]);
 c.document.querySelectorAll=()=>[...keys,keys[0]].map(ref=>({dataset:{ref:JSON.stringify(ref)}}));
 assert.equal(c.selectedCitations().length,4,'duplicate full-source and excerpt citations are sent once');
});

test('binary comparison describes unresolved and outside-scope results without implying a negative',()=>{
 const c=vm.createContext({current:{},sample:{review_kind:'rollout_condition'}});
 vm.runInContext(source.slice(source.indexOf('function label('),source.indexOf('function summary(')),c);
 assert.equal(c.label(true),'Condition present');assert.equal(c.label(false),'Condition absent');
 assert.equal(c.label(null),'Unresolved');c.current.predicted_scope='outside';
 assert.equal(c.label(null),'Not applicable');
});
