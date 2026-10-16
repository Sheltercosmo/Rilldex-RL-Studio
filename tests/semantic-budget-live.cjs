// Read-only setup/navigation check; no model calls or source writes.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.REVIEW_TEST_URL||'http://127.0.0.1:8765';
(async()=>{const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
try{
 const before=await(await fetch(base+'/api/runs')).json();
 const page=await browser.newPage({viewport:{width:1450,height:1000}});
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/connections');
 await page.getByRole('link',{name:'Configure semantic inspection limits →',exact:true}).click();
 assert.ok(page.url().endsWith('/integration-guide#inspection-budgets'));
 const recipe=page.locator('#inspection-budgets');await recipe.evaluate(el=>el.scrollIntoView({block:'start'}));
 const text=await recipe.innerText();
 for(const fragment of ['semantic prepare','semantic status','--max-new-calls 20',
 '--max-candidate-calls 0','--max-input-bytes 500000','semantic audit',
 'Resume starts a new allowance','not billed tokens or money','generator is not bundled'])assert.ok(text.includes(fragment),fragment);
 await page.screenshot({path:'research/semantic-budget-2026-10-11/verified/setup-desktop.png'});
 await page.setViewportSize({width:430,height:950});await recipe.evaluate(el=>el.scrollIntoView({block:'start'}));
 assert.ok((await recipe.locator('h2').boundingBox()).y>=0);
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:'research/semantic-budget-2026-10-11/verified/setup-mobile.png'});
 const after=await(await fetch(base+'/api/runs')).json();assert.equal(after.runs.length,before.runs.length);
 assert.deepEqual(errors,[]);
 const report={checks:['Connections links to the actual inspection recipe','Commands expose separate candidate/Jev/payload limits',
 'Allowance, billing and generator boundaries are explicit','430px page fits; no data changed'],
 sources_before:before.runs.length,sources_after:after.runs.length,errors};
 fs.writeFileSync('research/semantic-budget-2026-10-11/verified/browser-audit.json',JSON.stringify(report,null,2));
 console.log(JSON.stringify(report));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
