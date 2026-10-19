const test=require('node:test'),assert=require('node:assert/strict');
const {anchor,plan,questions,why,scopeNote,requestedPlan,literalNote}=require('../tracker/web/source-evidence.js');

test('phrase coverage distinguishes exact excerpts from fallback and omitted passages',()=>{
 assert.equal(literalNote({}), '');
 assert.match(literalNote({questions:[{literal_phrases:['not installed'],literal_matched_events:0}]}),/No exact phrase matched/);
 assert.match(literalNote({questions:[{literal_phrases:['a phrase'],literal_matched_events:1}]}),/outside this page/);
 const q={literal_phrases:['a phrase'],literal_matched_events:1,retained_literal_event_ids:['e1']};
 assert.match(literalNote({questions:[q,q]}),/shown in 1 record\./);
});
test('source events leave Unicode length to the server; semantic units keep original offsets',()=>{
 assert.deepEqual(anchor({kind:'event',properties:{id:'e1',text:'A😀B'}}),{event_id:'e1'});
 assert.deepEqual(anchor({kind:'unit',properties:{source:{event_id:'e1',start:1,end:2,text:'😀'}}}),{event_id:'e1',start:1,end:2});
 assert.equal(anchor({kind:'work_mention',properties:{text:'unbound meaning'}}),null);
});
test('query uses immutable source identity and does not write a graph relation',()=>{
 const graph={run_id:'r',source_hash:'h',id:'g'},ref={event_id:'e5',start:0,end:20};
 const p=plan(graph,ref,'  dataset  ');assert.equal(p.nodes.length,1);assert.equal(p.nodes[0].op,'evidence_search');
 assert.deepEqual(p.nodes[0].params,{run_id:'r',source_hash:'h',query:{anchor:ref,limit:8,max_chars:16000,text:'dataset'}});
 assert.equal('text' in plan(graph,ref,'').nodes[0].params.query,false);
});
test('expanded source context is labeled separately from native correspondence',()=>{
 assert.equal(why({kind:'matching_record_context'}),'Surrounding matching source record');
 assert.equal(why({kind:'recorded_dispatch',of_event_id:'e40'}),'Recorded dispatch for e40');
 assert.equal(why({kind:'recorded_response',of_event_id:'e39'}),'Recorded response to e39');
 assert.equal(why({kind:'future-context-kind'}),'Additional source context');
 assert.equal(why({kind:'literal_match',rank:1}),'Exact phrase match #1');
 assert.equal(why({kind:'literal_match',question_id:'q'}),'Exact phrase passage');
 assert.equal(why({kind:'question_match',question_id:'term-opaque'}, {'term-opaque':'Check the balance'}),'Candidate for: Check the balance');
});

test('multiple questions preserve wording and the shared source budget',()=>{
 const p=plan({run_id:'r',source_hash:'h'},{event_id:'e7'},'context','  Which input?\r\n\nWhich returned result? ');
 const q=p.nodes[0].params.query;
 assert.deepEqual(q.questions,[{id:'question-1',text:'Which input?'},{id:'question-2',text:'Which returned result?'}]);
 assert.equal(q.max_chars,16000);assert.equal(q.limit,8);
 assert.deepEqual(questions(' \n '),[]);
 assert.equal(why({kind:'recorded_child_dispatch',of_event_id:'e1'}),'Dispatch in source message e1');
 assert.equal(why({kind:'recorded_dispatch_group',of_event_id:'e2',parent_event_id:'e1'}),'Command from the same source message as e2 · context, not a dependency');
 assert.equal(why({kind:'question_match',question_id:'question-2'}),'Candidate for question 2');
 assert.equal(plan({run_id:'r',source_hash:'h'},{event_id:'e7'},'x','','source_and_calls').nodes[0].params.query.strategy,'source_and_calls');
});

test('continuation binds the next page without changing query or budgets',()=>{
 const cursor={search_id:'evidence-search-'+ 'a'.repeat(64),offset:8};
 const p=plan({run_id:'r',source_hash:'h'},{event_id:'e40'},'checksum','Which result?','source_and_calls',cursor);
 assert.deepEqual(p.nodes[0].params.query.cursor,cursor);
 cursor.offset=100;assert.equal(p.nodes[0].params.query.cursor.offset,8);
 assert.equal(p.nodes[0].params.query.max_chars,16000);
 assert.equal(p.nodes[0].params.query.strategy,'source_and_calls');
});

test('scope text distinguishes recorded sessions, missing boundaries and unavailable order',()=>{
 assert.match(scopeNote({scope:{anchor_order_established:true,context_boundary:'recorded'}}),/same recorded session/);
 assert.match(scopeNote({scope:{anchor_order_established:true,context_boundary:'unspecified'}}),/session boundary not recorded/);
 const unknown=scopeNote({scope:{anchor_order_established:false},coverage:{excluded_source_records:[{event_id:'e1'}]}});
 assert.match(unknown,/only earlier text within this record/);assert.match(unknown,/1 records excluded/);
 assert.match(scopeNote({}),/not recorded in this search version/);
});

test('requested-term review pins its graph and exact selected term identities',()=>{
 const ids=['term-a','term-b'],g={id:'graph-current',run_id:'r',source_hash:'h'},ref={event_id:'e40'};
 const p=requestedPlan(g,ref,ids,'source_and_calls');ids.push('later');
 assert.equal(p.nodes[0].op,'requested_evidence');assert.equal(p.nodes[0].params.graph_id,'graph-current');
 assert.deepEqual(p.nodes[0].params.query.question_ids,['term-a','term-b']);
 assert.equal(p.nodes[0].params.query.strategy,'source_and_calls');
 assert.deepEqual(requestedPlan(g,ref).nodes[0].params.query.question_ids,[]);
});
