const {test}=require('node:test');
const assert=require('node:assert/strict');
const L=require('../tracker/web/map-layout.js');
function fixture(semantic=false){
 const node=(id,kind,index,properties)=>({id,kind,event_index:index,trajectory_id:'main',properties});
 const source=[node('event:lookup','event',0,{id:'lookup',kind:'action',text:'lookup()'}),node('event:return','event',1,{id:'return',kind:'feedback',text:'{}'}),node('event:use','event',2,{id:'use',kind:'action',text:'use()'})];
 const edges=[{id:'f',source:'event:return',target:'event:lookup',type:'response_to'}];
 if(semantic){source.push(node('unit','unit',2,{kind:'action',source:{event_id:'use'},content:{summary:'Use item'}}));edges.push({id:'g',source:'unit',target:'event:use',type:'grounded_in'});}
 const plain={nodes:source,edges},graph=structuredClone(plain);
 graph.nodes.push(node('query','history_evidence_query',null,{name:'Example'}),node('observation','history_evidence_observation',2,{value:null}),node('fact','source_json_fact',1,{event_id:'return',value:'x'}));
 for(const [target,type] of [['event:use','observes_dispatch'],['query','evaluated_by_query'],['fact','uses_recorded_fact'],['event:return','uses_recorded_return']])graph.edges.push({id:type,source:'observation',target,type});
 graph.edges.push({id:'source-fact',source:'fact',target:'event:return',type:'sourced_from_event'});
 return {plain,graph};
}
test('evidence objects add no activity cards, lanes or chronological steps',()=>{
 for(const semantic of [false,true]){const {plain,graph}=fixture(semantic),before=JSON.stringify(graph);assert.deepEqual(L.project(graph),L.project(plain));assert.equal(JSON.stringify(graph),before);}
});
test('action inspector resolves exact query and fact edges from either unit or native action',()=>{
 for(const semantic of [false,true]){const {graph}=fixture(semantic),rows=L.historyEvidence(graph,semantic?'unit':'event:use');assert.equal(rows.length,1);assert.equal(rows[0].observation.properties.value,null);assert.equal(rows[0].query.id,'query');assert.deepEqual(rows[0].facts.map(n=>n.id),['fact']);assert.equal(rows[0].dispatch.target,'event:use');assert.equal(rows[0].edges.find(e=>e.type==='uses_recorded_return').target,'event:return');assert.deepEqual(L.historyEvidence(graph,'event:lookup'),[]);}
});
