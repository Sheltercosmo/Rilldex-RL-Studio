const {test}=require('node:test');
const assert=require('node:assert/strict');
const R=require('../tracker/web/unit-reading.js');
const node=(id,lane,ordinal,extra={})=>({id,lane,ordinal,trajectory_id:'main',kind:'unit',summary:'Summary '+id,target:'Target '+id,properties:{kind:lane===1?'action':lane===2?'feedback':'semantic',source:{text:'Source '+id}},...extra});
const edge=(id,source,target,type,family)=>({id,source,target,type,family,properties:{}});
const layout=(nodes,edges)=>({nodes,edges,byId:new Map(nodes.map(n=>[n.id,n]))});
const a=node('a',1,1),r=node('r',2,2),t=node('t',0,3),later=node('later',1,4);
const response=edge('result','r','a','feedback_for','feedback'),assessment=edge('review','t','r','assesses','review');

test('action → returned evidence → assessment stays an explicit two-edge path',()=>{
 const l=layout([a,r,t,later],[response,assessment,edge('order','r','later','source_order','sequence')]);
 const groups=R.sections(l,'a');
 assert.deepEqual(groups.map(g=>g.key),['result','use']);
 const row=groups[1].rows[0];assert.equal(row.node.id,'t');assert.equal(row.edge.id,'review');assert.equal(row.via.node.id,'r');assert.equal(row.via.edge.id,'result');
 assert.equal(R.sentence(l,assessment),'#3 assesses feedback #2');
 assert.ok(!groups.flatMap(g=>g.rows).some(row=>row.node.id==='later'));
});
test('adjacency and error wording cannot create a feedback-use or recovery relation',()=>{
 const error={...r,properties:{source:{text:'ERROR: failed'}}};
 const l=layout([a,error,t],[response,edge('seq','r','t','source_order','sequence')]);
 const group=R.sections(l,'a').find(g=>g.key==='use');assert.equal(group.rows.length,0);assert.match(group.empty,/does not establish/);
 assert.equal(R.sections(l,'r').find(g=>g.key==='use').rows.length,0);
});
test('missing result is distinguished from failed action or ignored response',()=>{
 const result=R.sections(layout([a,t],[]),'a');assert.equal(result.length,1);assert.equal(result[0].rows.length,0);assert.match(result[0].empty,/No response is bound/);
 assert.deepEqual(R.sections(layout([t],[]),'t'),[]);
});
test('two-hop reading never bridges separate trajectories',()=>{
 const other={...t,trajectory_id:'parallel'};
 const l=layout([a,r,other],[response,assessment]);assert.equal(R.sections(l,'a').find(g=>g.key==='use').rows.length,0);
 const crossResult={...r,trajectory_id:'parallel'};
 const l2=layout([a,crossResult,other],[response,assessment]);assert.equal(R.sections(l2,'a').find(g=>g.key==='use').rows.length,0);
});
test('parallel responses keep the specific witness rather than a single next-result guess',()=>{
 const r2=node('r2',2,5),t2=node('t2',0,6),e2=edge('result2','r2','a','response_to','feedback'),u2=edge('use2','t2','r2','uses_evidence','review');
 const groups=R.sections(layout([a,r,r2,t,t2],[response,e2,assessment,u2]),'a');
 assert.equal(groups[0].rows.length,2);assert.deepEqual(groups[1].rows.map(row=>[row.node.id,row.via.node.id]),[['t','r'],['t2','r2']]);
});
test('plan display endpoint is the actual stage and reverse relations keep their direction',()=>{
 const stage=node('step',0,null,{kind:'plan_step',properties:{id:'validate'}}),plan={...edge('plan','a','declaration','checks_plan_step','plan'),display_target:'step'};
 const l=layout([a,stage],[plan]);assert.equal(R.sections(l,'a')[1].rows[0].node.id,'step');assert.equal(R.sentence(l,plan),'#1 checks step “validate”');
 assert.equal(R.sentence(l,R.sections(l,'step')[0].rows[0].edge),'#1 checks step “validate”');
 assert.equal(R.foot(l,stage),'Checked by #1');assert.equal(R.foot(l,a),'Checks step “validate”');
});
test('short dispatches distinguish repeated targets without changing stored text',()=>{
 const command=raw=>({...a,target:'Install packages',properties:{source:{text:raw}}});
 const first=command('Running command: pip install --user pandas'),second=command('Running command: /usr/bin/python3 -m pip install --user pandas');
 assert.equal(R.content(first),'pip install --user pandas');assert.notEqual(R.content(first),R.content(second));assert.ok(first.properties.source.text.startsWith('Running command:'));
});
test('long script uses saved operation; missing operation preserves original summary',()=>{
 const script={...a,properties:{source:{text:'print(1)\n'.repeat(300)},content:{change:{text:'Creates the test dataset.'}}}};
 assert.equal(R.content(script),'Creates the test dataset.');delete script.properties.content.change;assert.equal(R.content(script),a.summary);
});
test('source-only action and structured retrieval feedback remain readable',()=>{
 const action={...a,kind:'event',properties:{text:'{"query":"Paris"}'}};
 assert.equal(R.content(action),'{"query":"Paris"}');
 const result={...r,properties:{text:'{"result":[{"document":{"contents":"Paris is the capital."}}]}'}};
 assert.equal(R.content(result),'Paris is the capital.');
});
test('footers identify linked units without turning assessment into correctness or success',()=>{
 const l=layout([a,r,t],[response,assessment]);assert.equal(R.foot(l,a),'Response #2');assert.equal(R.foot(l,r),'Assessed by #3');assert.equal(R.foot(l,t),'Assesses feedback #2');
 assert.equal(R.foot(layout([r],[]),r),'Output excerpt · no saved use link');
});
test('projection is deterministic and does not alter stored nodes, edges, or absence',()=>{
 const l=layout([a,r,t],[response,assessment]);const before=JSON.stringify([l.nodes,l.edges]);assert.deepEqual(R.sections(l,'a'),R.sections(l,'a'));R.content(a);R.foot(l,r);assert.equal(JSON.stringify([l.nodes,l.edges]),before);assert.deepEqual(R.sections(l,'missing'),[]);
});
test('one-link reading prefers the actual result over work identity and respects visibility',()=>{
 const repeat=edge('repeat','later','a','same_action_target','return'),l=layout([a,r,t,later],[repeat,response,assessment]);
 assert.equal(R.primaryLink(l,'a').id,'result');
 assert.equal(R.primaryLink(l,'a',new Set(['return'])).id,'repeat');
 assert.equal(R.primaryLink(l,'a',new Set()),null);
 assert.equal(R.primaryLink(l,'r').id,'result');
 assert.equal(R.primaryLink(l,'t').id,'review');
});

test('connection reader preserves reference direction instead of reversing it into trace order',()=>{
 const l=layout([a,r,t],[response,assessment]),before=JSON.stringify(l.edges);
 const returned=R.connection(l,response),used=R.connection(l,assessment);
 assert.equal(returned.question,'What did the action return?');
 assert.equal(returned.from.id,'r');assert.equal(returned.to.id,'a');assert.equal(returned.direction,'#2 → #1');
 assert.equal(used.question,'How did the agent interpret this feedback?');
 assert.equal(used.direction,'#3 → #2');assert.match(used.meaning,/does not establish correctness/);
 assert.equal(JSON.stringify(l.edges),before);
});

test('connection reader resolves plan display endpoints and does not create relationships for chronology',()=>{
 const step=node('step',0,null,{kind:'plan_step',properties:{id:'validate'}}),e={...edge('plan','a','declaration','checks_plan_step','plan'),display_target:'step'};
 const l=layout([a,step],[e]);assert.equal(R.connection(l,e).to.id,'step');
 assert.equal(R.connection(l,e).question,'Which planned step was checked?');
 assert.equal(R.connection(l,edge('seq','a','step','source_order','sequence')),null);
 assert.equal(R.connection(l,edge('missing','a','missing','assesses','review')),null);
});

test('unknown native relation keeps its name and explanation without a guessed diagnostic purpose',()=>{
 const e=edge('native','t','r','native:supports','context');e.properties.explanation='Native reference label.';
 const reading=R.connection(layout([r,t],[e]),e);
 assert.equal(reading.label,'native:supports');assert.equal(reading.meaning,'Native reference label.');
 assert.equal(reading.question,'What relationship is recorded?');
});

test('relationship evidence retains expressed qualifications rather than replacing them with a target label',()=>{
 const thought={...t,target:'Install packages',properties:{source:{text:'It seems permissions are missing. Try the --user flag.'}}};
 assert.equal(R.evidenceText(thought),'It seems permissions are missing. Try the --user flag.');
 assert.equal(R.content(thought),'Install packages');
 assert.equal(R.evidenceText(a),R.content(a));assert.equal(R.evidenceText(r),R.content(r));
});

test('default card text preserves an interpretation instead of only its target',()=>{
 const thought={...t,target:'Install packages',summary:'Interprets the failure as a possible permission issue.'};
 assert.equal(R.cardText(thought),thought.summary);assert.equal(R.cardText(a),R.content(a));
 assert.equal(R.cardText(r),R.content(r));
});

test('guide counts distinct cards and opens only recorded witnesses',()=>{
 const t2=node('t2',0,5),retry=edge('retry','later','a','revisits_after_error_report','return'),extra=edge('review2','t2','r','uses_evidence','review');
 const step=node('step',0,null,{kind:'plan_step',properties:{id:'validate'}}),plan={...edge('plan','a','declaration','checks_plan_step','plan'),display_target:'step'};
 const l=layout([a,r,t,later,t2,step],[response,assessment,extra,retry,plan]);
 const before=JSON.stringify([l.nodes,l.edges]),[used,retries,plans]=R.inventory(l);
 assert.equal(used.value,'1 / 1');assert.equal(used.rows[0].links.length,2);
 assert.equal(retries.value,'1');assert.equal(retries.rows[0].node.id,'later');
 assert.equal(plans.value,'1 / 2');assert.equal(plans.rows[0].links[0].display_target,'step');
 assert.equal(JSON.stringify([l.nodes,l.edges]),before);
});

test('guide never invents use, retry or plan correspondence from adjacency and shared targets',()=>{
 const l=layout([a,r,t,later],[response,edge('order','r','t','source_order','sequence'),edge('same','later','a','same_action_target','return'),edge('context','a','t','recorded_with','execution')]);
 const [used,retries,plans]=R.inventory(l);assert.equal(used.value,'—');assert.equal(used.rows[0].links.length,0);
 assert.equal(retries.value,'—');assert.equal(plans.value,'—');
 assert.equal(retries.evidence_status,'no_saved_links');assert.equal(plans.status_label,'Not established');
 assert.match(used.note,/do not establish ignored/);assert.match(plans.note,/not evidence of deviation/);
});

test('guide excludes dangling and cross-trajectory relationships; source-only records remain eligible',()=>{
 const cross={...t,trajectory_id:'other'},sourceAction={...a,kind:'event'},sourceResult={...r,kind:'event'};
 const [used]=R.inventory(layout([sourceAction,sourceResult,cross],[response,assessment,edge('dangling','missing','r','uses_evidence','review')]));
 assert.equal(used.value,'—');assert.equal(used.rows[0].node.id,'r');
 assert.deepEqual(R.inventory(layout([],[])).map(g=>g.value),['—','—','—']);
});

test('unavailable annotations are not presented as an observed zero; recorded evidence still wins',()=>{
 const l=layout([a,r,t],[response]),coverage={semantic_relations:'unavailable'};
 assert.deepEqual(R.inventory(l,coverage).map(g=>g.value),['—','—','—']);
 assert.match(R.inventory(l,coverage)[0].note,/Semantic observations are unavailable/);
 assert.equal(R.inventory({...l,edges:[response,assessment]},coverage)[0].value,'1 / 1');
 assert.equal(R.inventory(l,{semantic_relations:'partial'})[0].value,'—');
});

test('a feedback-only graph cannot imply measured retry or work-correspondence zeros',()=>{
 const groups=R.inventory(layout([a,r,t,later],[response,assessment]),{semantic_relations:'partial'});
 assert.equal(groups[0].value,'1 / 1');assert.equal(groups[0].evidence_status,'saved_links');
 for(const group of groups.slice(1)){
  assert.equal(group.value,'—');assert.equal(group.status_label,'Not established');
  assert.match(group.note,/does not establish zero occurrences/);
 }
});
