const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.REVIEW_TEST_URL,run=process.env.REVIEW_RUN_ID,out=process.env.REVIEW_OUTPUT_DIR;
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/connections?model_run='+run+'#model-section');
  const panel=page.locator('#model-setup');
  await page.waitForFunction(id=>document.querySelector('[aria-label="Pilot rollout"]')?.value===id,run);
  await panel.getByLabel('Decision calls',{exact:true}).fill('7');
  await panel.getByRole('button',{name:'Start / resume pilot',exact:true}).click();
  await panel.getByText('Pilot · budget reached',{exact:true}).waitFor({timeout:30000});
  assert.ok((await panel.innerText()).includes('1 / 3 action pairs inspected · 2 pending'));
  const local=await panel.getByRole('link',{name:'Open activities · work links pending →'}).getAttribute('href');
  if(out)await panel.screenshot({path:out+'/pilot-partial.png'});
  await page.reload();
  await panel.getByText('Pilot · budget reached',{exact:true}).waitFor();
  assert.equal(await panel.getByLabel('Decision calls',{exact:true}).inputValue(),'7');
  await panel.getByLabel('Decision calls',{exact:true}).fill('11');
  await panel.getByRole('button',{name:'Start / resume pilot',exact:true}).click();
  await panel.getByText('Pilot complete · activities and work links',{exact:true}).waitFor({timeout:30000});
  assert.ok((await panel.innerText()).includes('3 / 3 action pairs inspected · 0 pending'));
  assert.ok((await panel.innerText()).includes('7 saved decisions reused in the last pass.'));
  const state=await page.request.get(base+'/api/models').then(r=>r.json());
  assert.equal(state.pilot.usage.providers.jev.attempts,11);
  assert.equal(state.pilot.usage.providers.candidate.attempts,6);
  const complete=await panel.getByRole('link',{name:'Open the semantic map →'}).getAttribute('href');
  assert.notEqual(local,complete);
  await page.setViewportSize({width:390,height:900});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Pilot mobile overflow');
  if(out)await panel.screenshot({path:out+'/pilot-complete-mobile.png'});
  await page.setViewportSize({width:1440,height:1000});
  await panel.getByRole('link',{name:'Open the semantic map →'}).click();
  await page.waitForURL('**/semantic-map?**');
  const graph=await page.request.get(base+'/api/semantic-map/'+run+'?'+new URL(page.url()).searchParams).then(r=>r.json());
  assert.equal(graph.available,true);
  assert.ok(graph.document.relations.some(r=>r.type==='same_action_target'));
  await page.goto(base+local);
  assert.equal((await page.request.get(base+'/api/semantic-map/'+run+'?'+new URL(page.url()).searchParams).then(r=>r.json())).available,true);
  assert.deepEqual(errors,[]);
  const report={passed:true,installed:true,candidate_http_calls:6,authored_decision_calls:11,
   checks:['partial coverage','lifetime resume','reload','local observer stable','work map navigation','mobile overflow'],errors};
  if(out)fs.writeFileSync(out+'/browser-report.json',JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
