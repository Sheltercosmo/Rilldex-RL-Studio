const {test}=require('node:test');
const assert=require('node:assert/strict');
const L=require('../tracker/web/map-layout.js');
const R=require('../tracker/web/unit-reading.js');
test('native call relationships remain visible and distinct from agent actions',()=>{
 const nodes=[['root','call','workflow'],['child','call','model'],['input','context','A prompt'],['output','message','An answer']].map(([id,kind,text],index)=>({id,kind:'event',trajectory_id:id,event_index:index,properties:{id,kind,text,actor:kind==='message'?'agent':'harness',display_label:kind==='call'?'Readable '+text:null}}));
 const edges=[['root','child','contains_call'],['child','input','call_input'],['child','output','call_output']].map(([source,target,type],i)=>({id:'edge'+i,source,target,type,properties:{basis:'native_source'}}));
 const layout=L.project({observer:'source',nodes,edges});
 assert.equal(layout.byId.get('root').summary,'Readable workflow');
 const sections=R.sections(layout,'child');
 assert.equal(sections[0].key,'trace');assert.equal(sections[0].title,'Call structure');assert.equal(sections[0].rows.length,3);
 assert.equal(L.relationMeaning(edges[0]).label,'Contains call');
 assert.match(L.relationMeaning(edges[0]).meaning||L.relationMeaning(edges[0]).description||JSON.stringify(L.relationMeaning(edges[0])),/Nesting/);
 assert.equal(layout.nodes.filter(n=>n.lane===1).length,0);
});
