const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base=process.env.REVIEW_TEST_URL,output=process.env.STATE_AUDIT_OUTPUT;
(async()=>{const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];try{
 const get=async p=>(await(await fetch(base+p)).json());
 const snapshot=await get('/api/monitoring');assert.equal(snapshot.population,8);assert.equal(snapshot.training_rollouts,0);
 const recovery=snapshot.monitors.find(m=>m.analysis?.measure==='criterion_recovery');
 const verification=snapshot.monitors.find(m=>m.analysis?.measure==='delivery_verification');
 assert.equal(recovery.coverage.available,4);assert.equal(recovery.coverage.unknown_opportunities,4);
 assert.equal(verification.coverage.available,6);assert.equal(verification.coverage.unknown_opportunities,2);
 assert.equal(recovery.series.length,0);assert.equal(verification.series.length,0);
 const page=await browser.newPage({viewport:{width:1450,height:1080}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/');const card=page.locator('.metric-card').filter({hasText:'Recovery of original criterion'});
 await card.locator('.metric-headline strong').waitFor();assert.equal(await card.locator('.metric-headline strong').innerText(),'4');
 assert.match(await card.innerText(),/4 \/ 8/);
 assert.match(await card.innerText(),/4 unknown \/ 8 recorded opportunities/);
 const other=page.locator('.metric-card').filter({hasText:'Verification applicable at delivery'});
 assert.equal(await other.locator('.metric-headline strong').innerText(),'6');
 assert.equal(await other.getByRole('link',{name:'100.0%',exact:true}).count(),2);
 assert.equal(await other.getByRole('link',{name:'0.0%',exact:true}).count(),4);
 assert.match(await other.innerText(),/2 unknown \/ 8 recorded opportunities/);
 await page.screenshot({path:path.join(output,'monitor-desktop.png')});
 await card.getByRole('link',{name:'100.0%',exact:true}).first().click();
 await page.getByRole('button',{name:'Explain value',exact:true}).click();
 await page.locator('#detail-body').getByRole('button').filter({hasText:'Check '}).first().click();
 assert.match(await page.locator('#detail-body').innerText(),/recovered/);
 await page.screenshot({path:path.join(output,'evidence-desktop.png')});
 const counts=await page.evaluate(()=>({events:payload.run.events.length,empty:payload.run.events.filter(e=>e.actor==='agent'&&e.kind==='reasoning'&&!e.text).length,
  facts:payload.graph.nodes.filter(n=>['check','artifact_snapshot','object_version'].includes(n.kind)).length}));
 assert.ok(counts.facts>0);assert.equal(await page.locator('.unit-card').count(),counts.events-counts.empty);
 assert.equal(await page.locator('.unit-card').filter({hasText:'Empty reasoning record'}).count(),0);
 await page.locator('.unit-card').filter({hasText:'Recorded check · failed'}).first().click();
 assert.match(await page.locator('.work-state-evidence').innerText(),/Recorded result: failed/);
 assert.match(await page.locator('.work-state-evidence').innerText(),/Input stability: producer reports held fixed/);
 await page.screenshot({path:path.join(output,'state-inspector-desktop.png')});
 await page.setViewportSize({width:430,height:940});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 assert.deepEqual(errors,[]);
 const report={checks:['Eight controlled executions retain unknown opportunities','No invented training curve',
 'Recovery and delivery verification show distinct values','Metric value opens exact recovered-case evidence',
 'State facts stay attached to actual steps; empty reasoning wrappers fold','Action inspector exposes criterion, result and input stability','430px evidence page fits'],errors};
 fs.writeFileSync(path.join(output,'browser-audit.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
