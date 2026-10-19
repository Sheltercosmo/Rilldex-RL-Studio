const {test}=require('node:test'),assert=require('node:assert/strict');
const alerts=require('../tracker/web/workspace-alerts.js');
const {commands}=require('../tracker/web/reward-checks.js');
test('dismissed receipts stay deduplicated; changed receipts alert again',()=>{
 const rows=[{id:'one'},{id:'two'}],seen=alerts.remember([],rows);
 assert.deepEqual(alerts.fresh(rows,seen),[]);
 assert.deepEqual(alerts.fresh([{id:'one'},{id:'revised'}],seen),[{id:'revised'}]);
 assert.equal(alerts.remember(seen,rows).length,2);
});
test('findings honor experiment and environment, including unassigned',()=>{
 const rows=[{id:'a',experiment:'exp',environment:'terminal'},{id:'b',experiment:null,environment:'browser'}];
 assert.deepEqual(alerts.scoped(rows,{experiment:'exp',environment:'terminal'}),[rows[0]]);
 assert.deepEqual(alerts.scoped(rows,{experiment:'__unassigned__'}),[rows[1]]);
});
test('budget and streaming commands preserve cache workspace and quote shell metacharacters',()=>{
 const c=commands({database:"C:/a 'quoted'/$x.sqlite",directory:'scan folder',experiment:"task's `name`",budget:0,shell:'powershell',mode:'watch'});
 assert.match(c.run,/watch 'scan folder'/);assert.match(c.run,/--max-new-calls 0$/);assert.doesNotMatch(c.run,/all-latest/);
 assert.match(c.run,/'C:\/a ''quoted''\/\$x.sqlite'/);assert.match(c.preview,/plan .*--all-latest$/);
 const bash=commands({experiment:"task's $(command)",shell:'bash'});
 assert.ok(bash.run.includes("'task'\"'\"'s $(command)'"));
 assert.match(bash.run,/run 'reward-scan'.*--all-latest --max-new-calls 20/);
 for(const budget of [-1,1.5,'x',100001])assert.throws(()=>commands({budget}));
 assert.throws(()=>commands({directory:'one\ntwo'}));
});
test('resume preserves saved adapters and explicit targets, with optional failed retries',()=>{
 const selected=commands({directory:'retained',selection:{kind:'latest',experiment:'trial',adapters:['harbor','swe-agent']},retryFailed:true});
 assert.match(selected.run,/--experiment 'trial' --adapter 'harbor' --adapter 'swe-agent'/);
 assert.match(selected.run,/--retry-failed$/);
 const ids={kind:'explicit_latest',run_ids:['abc123','def456']};
 assert.match(commands({selection:ids}).run,/--run-id 'abc123' --run-id 'def456'/);
 assert.doesNotMatch(commands({selection:ids}).run,/--all-latest/);
 assert.throws(()=>commands({selection:ids,mode:'watch'}));
});
test('scan coverage never renders an absent count as a negative detection',()=>{
 const {coverage}=require('../tracker/web/reward-scan-progress.js');
 assert.equal(coverage({status:'not_scanned'}),'No page coverage recorded');
 assert.equal(coverage({pages_scanned:1,pages_total:8,status:'partial'}),'1 / 8 pages');
 assert.equal(coverage({requests_completed:4}),'4 requests checked');
 assert.equal(coverage({requests_completed:2,stage:'requirement_extraction'}),'Reading requirements · 2 requests checked');
 assert.equal(coverage({requests_completed:4,stage:'requirement_scan'}),'Comparing behavior · 4 requests checked');
});
test('scan drilldown opens the source without confusing a diagnostic receipt with a monitor value',()=>{
 const {rolloutUrl}=require('../tracker/web/reward-scan-progress.js');
 const url=new URL(rolloutUrl({run_id:'abc',measurement_id:'diagnostic-receipt'}),'http://localhost');
 assert.equal(url.searchParams.get('run'),'abc');assert.equal(url.searchParams.get('observer'),'source');
 assert.equal(url.searchParams.has('value'),false);
});
