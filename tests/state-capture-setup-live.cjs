// Read-only check on the existing application; no inference or source mutation.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base=process.env.REVIEW_TEST_URL||'http://127.0.0.1:8765',out=process.env.STATE_AUDIT_OUTPUT;
(async()=>{const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];try{
 const get=async p=>(await(await fetch(base+p)).json()),before=await get('/api/runs');
 const config=await get('/api/config');assert.equal(config.jev_configured,true);
 const page=await browser.newPage({viewport:{width:1450,height:1000}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/connections');await page.getByRole('link',{name:'Capture work state and check results →',exact:true}).click();
 assert.ok(page.url().endsWith('/integration-guide#work-state'));const recipe=page.locator('#work-state');
 const text=await recipe.innerText();for(const fragment of ['WorkStateRecorder','state_stable','file_versions','state.attach'])assert.ok(text.includes(fragment),fragment);
 await page.screenshot({path:path.join(out,'setup-desktop.png')});
 await page.setViewportSize({width:430,height:950});await recipe.evaluate(el=>el.scrollIntoView({block:'start'}));
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:path.join(out,'setup-mobile.png')});
 await page.setViewportSize({width:1450,height:1000});
 await page.goto(base+'/connections');await page.getByRole('link',{name:'Connect a running mini-SWE-agent →',exact:true}).click();
 const native=await page.locator('#mini-agent').innerText();for(const fragment of ['CaptureMixin','MiniCapture','state.attach','complete trace, not task success'])assert.ok(native.includes(fragment),fragment);
 const catalog=await get('/api/integrations');assert.ok(catalog.routes.some(r=>r.name==='mini-SWE-agent v2'));
 await page.goto(base+'/semantic-map?run=23a6f4b7c76c919e74ae6d50&observer=source');
 await page.locator('.unit-card').first().waitFor();assert.ok(await page.locator('.unit-card').count()>5);
 await page.locator('.unit-card').first().click();assert.ok(await page.locator('#detail-body').innerText());
 const after=await get('/api/runs');assert.deepEqual(after.runs.map(r=>r.id).sort(),before.runs.map(r=>r.id).sort());assert.deepEqual(errors,[]);
 const report={checks:['Connections opens the producer recipe','430px recipe fits','Native mini recipe explains capture and stop semantics','Catalog exposes the tested native boundary','Existing source map and inspector load','Source identities and configured key preserved'],sources:after.runs.length,errors};
 fs.writeFileSync(path.join(out,'existing-app-audit.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
