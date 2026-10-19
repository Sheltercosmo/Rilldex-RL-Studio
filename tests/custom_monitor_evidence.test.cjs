const {test}=require('node:test');
const assert=require('node:assert/strict');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.textContent='';}
 append(...children){this.children.push(...children);}
}
global.document={createElement:tag=>new Element(tag)};
const {render,status,renderDiagnostic}=require('../tracker/web/custom-monitor-evidence.js');
const text=n=>[n.textContent,...n.children.map(text)].join('\n');
const sample=()=>({basis:'custom_code',feedback:{summary:'Recorded check failed',next_check:'Inspect this artifact'},
 details:{detector:{schema:'reward-detector/1',status:'flagged',reward_definition:'reward/v2',stage:'reward_disagreement'},custom:{key:1}},
 input_values:[{name:'passed',pointer:'/raw/check/passed',value:false},{name:'score',pointer:'/outcome/recorded_reward',value:0}],
 source_excerpts:[{citation:{role:'action',text:'<script>untrusted text</script>',source_pointer:'/steps/1',start:0,end:31},actor:'agent',kind:'action',tool:'write_file',node_ids:['unit-2']}],evidence_ids:[]});
test('requirement conflict shows the actual instruction and action with map links',()=>{
 const ids=[],result=renderDiagnostic({selection:'flagged',candidates:[{requirement:{event_id:'u',display_text:'Preserve all data'},candidate:{event_id:'a',text:'<script>return gzipBytes(nil)</script>'}}]},
  {events:[{id:'a',actor:'agent',kind:'action',text:'<script>return gzipBytes(nil)</script>'}],nodeButton:id=>{ids.push(id);return new Element('button');}});
 assert.deepEqual(ids,['event:a','event:u']);
 for(const label of ['Task requirement','Flagged source','Preserve all data','return gzipBytes(nil)','bugs or shortcuts'])assert.ok(text(result).includes(label));
 assert.equal(JSON.stringify(result).includes('"tag":"script"'),false);
 assert.match(text(renderDiagnostic({selection:'no_candidate_selected',candidates:[]})),/No conflict candidate/);
 assert.match(text(renderDiagnostic({selection:'flagged',candidates:[],scan_complete:false,scanned_pages:1,total_pages:65})),/Partial scan · 1 \/ 65/);
 assert.equal(status({diagnostic:{value:1,scan_complete:false}}),'Flagged');
 assert.equal(status({diagnostic:{value:0}}),'No candidate selected');
 assert.equal(status({diagnostic:{value:null,scan_complete:false}}),'Scan pending');
});
test('grouped records retain the requirement paired to each distinct selected passage',()=>{
 const result=renderDiagnostic({candidates:[
  {requirement:{id:'q1',text:'Keep bytes'},candidate:{id:'a',event_id:'e',text:'First passage'}},
  {requirement:{id:'q2',text:'Keep format'},candidate:{id:'a',event_id:'e',text:'First passage'}},
  {requirement:{id:'q3',text:'Accept cancellation'},candidate:{id:'b',event_id:'e',text:'Second passage'}}
 ]},{events:[{id:'e',actor:'agent',kind:'reasoning'}]});
 const groups=result.children.filter(n=>n.tag==='details');assert.equal(groups.length,1);
 const fragments=groups[0].children.filter(n=>n.className==='diagnostic-match');assert.equal(fragments.length,2);
 assert.match(text(fragments[0]),/First passage/);assert.match(text(fragments[0]),/Keep bytes/);assert.match(text(fragments[0]),/Keep format/);
 assert.doesNotMatch(text(fragments[0]),/Accept cancellation/);assert.match(text(fragments[1]),/Accept cancellation/);
 assert.doesNotMatch(text(fragments[1]),/Keep bytes/);assert.match(text(result),/1 source record · 3 requirement matches/);
});
test('diagnostic excerpts lead with selected text and link only overlapping units',()=>{
 const ids=[],result=renderDiagnostic({value:1,candidates:[{requirement:{id:'q',text:'Keep all bytes'},candidate:{id:'f',text:'serialized',event_id:'e'}}]},
  {excerpts:{f:[{text:'the actual gap',actor:'agent',kind:'reasoning',field:['text'],node_ids:['gap-unit']}]},
   events:[{id:'e',text:'Earlier prose. The actual gap. Later prose.'}],nodeButton:id=>{ids.push(id);return new Element('button');}});
 assert.deepEqual(ids,['gap-unit']);assert.match(text(result),/agent · reasoning · text/);
 assert.match(text(result),/Full source record · e/);
 assert.ok(text(result).indexOf('the actual gap')<text(result).indexOf('Earlier prose.'));
});
test('custom evidence preserves false/zero, feedback and exact excerpts as inert text',()=>{
 const links=[],result=render(sample(),{nodeButton:id=>{links.push(id);return new Element('button');}});
 for(const value of ['Flagged','Recorded check failed','Inspect this artifact','false','0','/raw/check/passed','<script>untrusted text</script>','agent · action · write_file'])assert.ok(text(result).includes(value),value);
 assert.deepEqual(links,['unit-2']);assert.equal(status(sample()),'Flagged');
 assert.equal(JSON.stringify(result).includes('"tag":"script"'),false);
});
test('unknown and non-applicable findings stay explicit without implying a trace witness',()=>{
 for(const [key,label]of [['unknown','Unknown'],['not_applicable','Not applicable']]){
  const s=sample();s.details.detector.status=key;s.source_excerpts=[];s.input_values=[];
  const rendered=render(s);assert.match(text(rendered),/No trace passages or map nodes were attached/);assert.equal(status(s),label);
 }
});
test('generic code feedback renders but ordinary measures use their existing explanations',()=>{
 assert.equal(render({basis:'recorded_metric'}),null);assert.equal(status({basis:'recorded_metric'}),null);
 const generic=render({basis:'custom_code',reason:'Worker failed',details:{traceback:'local error'},evidence_ids:[]});
 assert.match(text(generic),/Worker failed/);assert.match(text(generic),/local error/);
});
test('external evaluator reports expose matching counts, original verdict and zero score',()=>{
 const s=sample();s.source_excerpts=[];s.input_values=[];
 s.evaluation_inputs={reward:['r'],check:['a','b'],absent:[]};
 s.evaluation_reports=[{inputs:['check'],receipt:{id:'a',label:'Hidden check',producer:'worker/1',verdict:'failed',execution:'completed',score:0,summary:'Reported failure',evidence:[{label:'Output',text:'<script>inert</script>'}]}}];
 const result=render(s),content=text(result);
 for(const expected of ['check · 2 matching reports · multiple reports','absent · 0 matching reports · missing','Hidden check · failed','score: 0','Reported failure','separate from the agent-visible trace','<script>inert</script>'])assert.ok(content.includes(expected),expected);
 assert.ok(!content.includes('No trace passages or map nodes'));
 assert.equal(JSON.stringify(result).includes('"tag":"script"'),false);
});

test('code-flow findings show the concrete mechanism and literal function evidence',()=>{
 const result=renderDiagnostic({value:1,evidence_roles:{action:{text:'complete recorded command'}},code_flows:[{mechanism:'test_answer_copy',view:{entry:'predict',parts:[{role:'entry',start_line:2,end_line:4,text:'return labels  # <script>inert</script>'}]}}]});
 const content=text(result);
 for(const phrase of ['Test-answer copying · predict','Test input → answer/label field → copied sample outputs','lines 2–4','Execution success is not established','<script>inert</script>'])assert.ok(content.includes(phrase),phrase);
 assert.equal(JSON.stringify(result).includes('"tag":"script"'),false);
 const details=result.children.filter(n=>n.tag==='details');
 assert.equal(details[0].open,true,'Show the focused mechanism without another click');
 assert.equal(details[1].open,false,'Keep the large original action available without burying the explanation');
 assert.match(text(details[1]),/complete recorded command/);
});

test('artifact contract findings show why the success test substitutes the target',()=>{
 const ids=[],result=renderDiagnostic({value:1,evidence_roles:{action:{text:'original command'}},artifact_contracts:[{view:{
  opening_context:[{id:'prefix',event_id:'e',text:'serialized task'}],payload:{command:'<script>quoted code</script>'}
 }}]}, {excerpts:{prefix:[{actor:'agent',kind:'reasoning',field:['text'],text:'Exercise the real target',node_ids:['event:e']}]},nodeButton:id=>{ids.push(id);return new Element('button');}});
 assert.match(text(result),/Actual target required → substitute produces success → installed as deliverable/);
 assert.match(text(result),/Exercise the real target/);assert.deepEqual(ids,['event:e']);
 const details=result.children.filter(n=>n.tag==='details');assert.equal(details[0].open,true);assert.equal(details[1].open,false);
 assert.equal(JSON.stringify(result).includes('"tag":"script"'),false);
});

test('repeated artifact evidence groups identical code and preserves readable newlines',()=>{
 const finding={view:{payload:{command:['bash','-lc','first line\nsecond line']},opening_context:[]},selections:{contract:'target_required'}};
 const result=renderDiagnostic({value:1,artifact_contracts:[finding,finding],evidence_roles:{}});
 const details=result.children.filter(n=>n.tag==='details');assert.equal(details.length,2);assert.equal(details[0].open,true);
 assert.match(text(details[0]),/2 recorded occurrences/);assert.ok(text(details[0]).includes('first line\nsecond line'));
});
