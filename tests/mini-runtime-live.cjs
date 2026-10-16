const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base=process.env.REVIEW_TEST_URL,out=process.env.MINI_AUDIT_OUTPUT;
(async()=>{const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];try{
 const get=async p=>(await(await fetch(base+p)).json()),snapshot=await get('/api/monitoring');
 assert.equal(snapshot.population,7);assert.equal(snapshot.training_rollouts,0);
 assert.ok(snapshot.runs.every(r=>r.state==='complete'));
 const page=await browser.newPage({viewport:{width:1450,height:1040}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/');const recovery=page.locator('.metric-card').filter({hasText:'Recovery of original criterion'});
 await recovery.locator('.metric-headline strong').waitFor();assert.equal(await recovery.locator('.metric-headline strong').innerText(),'6');
 assert.match(await recovery.innerText(),/1 unknown \/ 7 recorded opportunities/);
 const verification=page.locator('.metric-card').filter({hasText:'Verification applicable at delivery'});
 assert.equal(await verification.getByRole('link',{name:'0.0%',exact:true}).count(),1);
 assert.equal(await verification.getByRole('link',{name:'100.0%',exact:true}).count(),5);
 await page.screenshot({path:path.join(out,'monitor-desktop.png')});
 await verification.getByRole('link',{name:'0.0%',exact:true}).click();
 await page.getByRole('button',{name:'Explain value',exact:true}).click();
 assert.match(await page.locator('#detail-body').innerText(),/changed_inputs|changed inputs/i);
 await page.locator('.unit-card').filter({hasText:'Recorded check · passed'}).first().click();
 assert.match(await page.locator('.work-state-evidence').innerText(),/Required objects: app.py, rules.py/);
 await page.screenshot({path:path.join(out,'state-desktop.png')});
 const sources=await Promise.all(snapshot.runs.map(r=>get('/api/monitoring/rollout/'+r.id+'?observer=source')));
 const stopped=sources.map(s=>s.run).find(r=>r.metadata.sample_id==='text-limit');assert.ok(stopped);
 await page.goto(base+'/semantic-map?run='+stopped.id+'&observer=source');await page.locator('.unit-card').first().waitFor();
 const exit=page.locator('.unit-card').filter({hasText:'LimitsExceeded'});assert.equal(await exit.count(),1);
 assert.equal(await exit.getAttribute('data-activity'),'context');await exit.click();
 await page.setViewportSize({width:430,height:950});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 assert.deepEqual(errors,[]);
 const report={checks:['Seven current rollouts replace 39 historical snapshots','Limits stay in the completed-source population',
 'Recovery retains unknown evidence and delivery verification catches stale inputs','Chart value opens recorded state evidence',
 'Limit termination appears as environment context','430px inspector fits without script errors'],errors};
 fs.writeFileSync(path.join(out,'browser-audit.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
