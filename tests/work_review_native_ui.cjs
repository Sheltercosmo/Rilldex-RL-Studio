const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.REVIEW_TEST_URL,out=process.env.REVIEW_OUTPUT_DIR;
(async()=>{const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
try{
 const cases=JSON.parse(fs.readFileSync(out+'/fixture.json','utf8'));
 const page=await browser.newPage({viewport:{width:1440,height:1050}});page.on('pageerror',e=>errors.push(e.message));
 const open=async c=>{
  await page.goto(base+'/semantic-map?'+new URLSearchParams({run:c.run.id,graph:c.graph.id,observer:c.graph.observer,level:'work',work_view:'review'}));
  await page.locator('.wr-target').first().waitFor();await page.locator('.wr-target').first().click();
  await page.locator('.wr-sequence').waitFor();
 };
 const changed=cases.find(c=>c.kind==='native_changed');await open(changed);
 const sequence=page.locator('.wr-sequence');
 assert.ok((await sequence.innerText()).includes('Recorded inputs changed'));
 assert.ok((await sequence.innerText()).includes('Compared native tool and arguments'));
 await sequence.locator('.wr-input-diff>summary').click();
 assert.ok((await sequence.locator('.wr-input-diff').innerText()).includes('/arguments/query'));
 assert.ok((await sequence.locator('.wr-input-diff').innerText()).includes('beta'));
 await sequence.screenshot({path:out+'/native-input-difference.png'});
 await sequence.getByRole('button',{name:'Compare pair',exact:true}).click();
 const detail=page.locator('#detail-body');
 await detail.getByRole('heading',{name:'Recorded inputs changed',exact:true}).waitFor();
 const mapUrl=page.url();await detail.getByRole('link',{name:'Inspect inputs and both feedback records →',exact:true}).click();
 await detail.getByRole('heading',{name:'Recorded inputs: changed',exact:true}).waitFor();
 await page.reload();await detail.getByRole('heading',{name:'Recorded inputs: changed',exact:true}).waitFor();
 await detail.getByRole('link',{name:'← Work path',exact:true}).click();
 assert.equal(page.url(),mapUrl);await page.locator('.wr-sequence').waitFor();
 // Native responses are visible even without a single semantic feedback unit.
 await open(cases.find(c=>c.kind==='native_only'));
 assert.equal(await sequence.locator('.wr-feedback').getByText('1 failed',{exact:true}).count(),2);
 await page.setViewportSize({width:390,height:900});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await sequence.locator('.wr-feedback').last().scrollIntoViewIfNeeded();
 assert.ok(await sequence.locator('.wr-feedback').last().isVisible());
 await page.screenshot({path:out+'/mobile-native-feedback.png'});
 await page.setViewportSize({width:1440,height:1050});
 await open(cases.find(c=>c.kind==='feedback_order'));
 const order=await sequence.locator('.wr-feedback').allInnerTexts();
 assert.ok(order[0].indexOf('first')<order[0].indexOf('second'));
 assert.ok(order[1].indexOf('second')<order[1].indexOf('first'));
 assert.ok((await sequence.innerText()).includes('Recorded feedback changed'));
 assert.ok(!(await sequence.innerText()).includes('Exact feedback text also repeats'));
 await open(cases.find(c=>c.kind==='feedback_fragments'));
 assert.equal(await sequence.locator('.wr-feedback').getByText('1 failed',{exact:true}).count(),2);
 assert.equal(await sequence.getByRole('button',{name:/Inspect reference/}).count(),1);
 for(const c of cases.slice(5)){
  await open(c);assert.ok(await sequence.locator('.wr-feedback button').count()>=2);
  await sequence.getByRole('button',{name:'Compare pair',exact:true}).first().click();
  await detail.getByRole('link',{name:'Inspect inputs and both feedback records →',exact:true}).waitFor();
  await page.locator('#work-route').screenshot({path:out+'/'+c.kind+'.png'});
 }
 assert.deepEqual(errors,[]);const report={passed:true,authored_cases:5,public_pairs:16,errors};
 fs.writeFileSync(out+'/browser-report.json',JSON.stringify(report));console.log(JSON.stringify(report));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
