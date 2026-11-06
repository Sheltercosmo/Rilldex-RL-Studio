const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const M=require('../tracker/web/semantic-map.js');
const cases=require('./fixtures/generated-generalization-method-recall.json').cases;

class Element{
 constructor(tag){this.tag=tag;this.textContent='';this.children=[];}
 append(...children){this.children.push(...children);}
}
function render(name,eventId){
 const record=structuredClone(cases[name]),doc=record.document;
 doc.method_comparison={...record.report.result,definitions:{reconfigured_procedure:'Changed explicit inputs.',different_work:'Different immediate work.'}};
 const context=vm.createContext({record,doc});
 vm.runInContext(fs.readFileSync(require.resolve('../tracker/web/semantic-map.js'),'utf8'),context);
 context.document={createElement:tag=>new Element(tag)};context.host=new Element('aside');
 context.selectedId=doc.units.find(u=>u.source.event_id===eventId).id;
 vm.runInContext('state.doc=doc;state.run=record.source;inspectWorkHistory(unit(selectedId),host)',context);
 const text=node=>[node.textContent,...node.children.map(text)].filter(Boolean).join('\n');
 return {host:context.host,text:text(context.host)};
}

test('a related same-work comparison is reachable inside the existing action inspector',()=>{
 const {host,text}=render('simulation','e8');
 assert.equal(host.children.length,1);assert.equal(host.children[0].tag,'details');
 assert.match(text,/Compare with earlier work/);
 assert.match(text,/Reconfigured procedure/);
 assert.match(text,/reported flood/);assert.match(text,/Agent’s stated basis · e6/);
 assert.match(text,/Open earlier operation/);
 assert.doesNotMatch(text,/grouping disputed/);
});

test('related negative decisions remain inspectable without disputing an identity group',()=>{
 const {text}=render('simulation','e12');
 assert.equal((text.match(/Earlier operation comparison/g)||[]).length,2);
 assert.match(text,/Different immediate work; no procedure comparison is assigned/);
 assert.doesNotMatch(text,/grouping disputed|disputes the shared work grouping/);
});

test('pair lookup keeps source endpoints exact and original recurrence labels intact',()=>{
 const doc=cases.simulation.document,rows=cases.simulation.report.result.observations;
 const view={...doc,method_comparison:{observations:rows}};
 const changed=rows.find(r=>r.work_instance==='same_work_instance');
 assert.equal(M.relatedMethodObservations(view,changed.current_unit_id).length,1);
 assert.equal(M.relatedMethodObservations(view,changed.previous_unit_id).length,0);
 assert.equal(M.methodObservation(view,{previous_group_unit_id:changed.previous_unit_id,unit_id:changed.current_unit_id,group_id:null}),changed);
 assert.equal(M.methodGroupSummary(view,'unrelated-group').pairs,0);
 assert.equal(M.methodPairLabel({status:'selected',comparison:'different_work',group_id:'existing-group'}),'Different work · grouping disputed');
 assert.equal(M.methodPairLabel({status:'pending',comparison:'different_work',group_id:null}),'Comparison not inspected');
});
