// Replay the retained, previously annotated public DevAI graph, with its foundation audit.
const fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
const assets=process.env.REVIEW_ASSET_DIR||path.join(__dirname,'../tracker/web');
const P=require(path.join(assets,'inspection-paths.js')),L=require(path.join(assets,'map-layout.js'));
const file=process.env.REVIEW_GRAPH_PATH;
const bundle=JSON.parse(fs.readFileSync(file,'utf8')),{graph,foundation}=bundle,before=JSON.stringify(bundle);
assert.equal(graph.id,'graph-58c49c681047e56023b415b76fd878fced1e21e66c729e060b0b47b39892bc48');
const layout=L.project(graph,foundation.excluded_edge_ids,foundation.content_sources.excluded_unit_ids,foundation.source_order);
const groups=P.catalog(graph,layout,foundation.excluded_edge_ids),paths=groups.find(g=>g.id==='retry-paths').cases;
assert.equal(paths.length,8);assert.equal(groups.find(g=>g.id==='attempt-pairs').cases.length,10);
assert.equal(groups.find(g=>g.id==='failed-checks').cases.length,0);
const training=paths.find(c=>c.attempts[0].node.id==='s747e1ff1f925c75dbe6e');
assert.deepEqual(training.attempts.map(a=>a.node.ordinal),[27,36,54]);
const installation=paths.find(c=>c.attempts[0].node.id==='s3bcf5be1043c370df1b6');
assert.deepEqual(installation.attempts.map(a=>a.node.ordinal),[39,42,45,48,51]);
for(const path of paths){
 assert.equal(P.summary(path).checks,0);assert.equal(path.truncated,false);
 for(const a of path.attempts){
  assert.equal(a.responses.length,1);
  assert.ok(graph.edges.some(e=>['feedback_for','response_to'].includes(e.type)&&e.source===a.responses[0].id&&e.target===a.node.id));
 }
 for(const e of path.edges)assert.ok(graph.edges.some(original=>original.id===e.id&&original.source===e.source&&original.target===e.target));
}
assert.equal(JSON.stringify(bundle),before);
const report={graph:graph.id,source_hash:graph.source_hash,retry_starts:paths.length,paired_attempts:10,
 training_chain:training.attempts.map(a=>a.node.ordinal),installation_chain:installation.attempts.map(a=>a.node.ordinal),
 original_feedback_and_links_preserved:true,structured_check_outcomes:'unavailable',new_model_calls:0,
 limits:'One previously annotated public trace; validates projection and source identity, not independent semantic accuracy.'};
if(process.env.REVIEW_REPORT_PATH)fs.writeFileSync(process.env.REVIEW_REPORT_PATH,JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
