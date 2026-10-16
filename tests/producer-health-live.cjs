// Read-only verification of existing application data after the server upgrade.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.REVIEW_TEST_URL||'http://127.0.0.1:8765';
(async()=>{const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];try{
 const read=async path=>(await(await fetch(base+path)).json());
 const before=await read('/api/runs'),connections=await read('/api/connections'),config=await read('/api/config');
 assert.equal(before.runs.length,3091);assert.ok(config.jev_configured);
 assert.ok(connections.producers.every(p=>p.status==='unreported'&&p.report===null));
 const page=await browser.newPage({viewport:{width:1450,height:1050}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/connections');await page.locator('#producer-health').waitFor();
 if(connections.producers.length)await page.locator('.producer-card').first().waitFor();
 else await page.getByText('No workers have reported or delivered snapshots yet.',{exact:true}).waitFor();
 assert.equal(await page.locator('.producer-card').count(),connections.producers.length);
 for(const row of await page.locator('.producer-card').all()){assert.equal(await row.locator('.health').innerText(),'Queue not reported');assert.equal(await row.locator('.producer-facts strong').first().innerText(),'—');}
 await page.getByRole('link',{name:'Enable reports →',exact:true}).click();assert.ok(page.url().endsWith('#worker-delivery'));
 assert.match(await page.locator('#worker-delivery').innerText(),/report_status=True/);
 await page.goto(base+'/connections');await page.setViewportSize({width:430,height:900});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 assert.equal((await read('/api/runs')).runs.length,before.runs.length);assert.deepEqual(errors,[]);
 const report={saved_sources:before.runs.length,unreported_producers:connections.producers.length,
  checks:['Existing sources and process configuration retained',connections.producers.length?'Legacy producer queues are unknown rather than zero':'Imported-only data does not invent connected workers','Worker setup link opens the actual reporting recipe','430px connections page fits'],errors};
 fs.writeFileSync('research/concurrent-training-2026-10-11/verified/application-check.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
