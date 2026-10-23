const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.REVIEW_TEST_URL,out=process.env.REVIEW_OUTPUT_DIR;
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 const fixture=JSON.parse(fs.readFileSync(out+'/fixture.json','utf8'));
 let page;
 try{
  page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  const f=fixture.authored,query=new URLSearchParams({run:f.run_id,observer:f.observer,level:'plans'});
  const response=await page.request.get(base+'/api/semantic-map/'+f.run_id+'?'+new URLSearchParams({observer:f.observer,plans:'1'}));
  assert.ok(response.ok());const map=await response.json();
  const stage=map.document.plan_execution.plans[0].stages[0];
  assert.equal(stage.role_counts.attempts,2);assert.equal(stage.action_unit_ids.length,3);
  assert.deepEqual(stage.response_evidence[0].action_unit_ids,['a0','a0-tail']);
  assert.deepEqual(stage.response_evidence[0].response_unit_ids,['f0','f0-tail']);
  assert.equal(map.document.plan_execution.plans[0].counts.stage_changes,0);
  await page.goto(base+'/semantic-map?'+query);
  await page.locator('#plan-hierarchy').waitFor({state:'visible'});
  await page.getByRole('button',{name:/STEP 1.*Write report content/s}).click();
  assert.ok((await page.locator('#plan-hierarchy').innerText()).includes('2 attempts'));
  assert.deepEqual(await page.locator('.pap-role.attempts_plan_step').allTextContents(),['Attempt 1','Attempt 2']);
  assert.equal(await page.locator('.pap-row').count(),2);
  assert.equal(await page.locator('.pap-row').first().locator('.pap-action-title').count(),2);
  assert.equal(await page.locator('.pap-row').first().locator('.pap-response').count(),2);
  await page.getByRole('button',{name:'Compare attempts',exact:true}).click();
  assert.equal(await page.locator('.pap-row:visible').count(),2);
  await page.locator('#plan-hierarchy').screenshot({path:out+'/plans.png'});
  await page.setViewportSize({width:390,height:900});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:out+'/mobile.png'});
  await page.setViewportSize({width:1440,height:1000});
  // Every original fragment remains addressable after aggregation.
  for(const id of ['a0','a0-tail','f0','f0-tail']){
   await page.goto(base+'/semantic-map?'+new URLSearchParams({run:f.run_id,observer:f.observer,level:'units',focus_unit:id}));
   await page.locator('#map-inspector').waitFor({state:'visible'});
   const details=await page.locator('#detail-body').innerText();
   const clean=s=>s.replace(/\s+/g,' ').trim();
   assert.ok(details.includes(id)||clean(details).includes(clean(map.document.units.find(u=>u.id===id).source.text)));
  }
  // Public material reads remain accessible under the same installed package.
  const p=fixture.public;
  await page.goto(base+'/semantic-map?'+new URLSearchParams({run:p.run_id,observer:p.observer,level:'plans'}));
  await page.locator('#plan-hierarchy .pap-action-title:visible').first().waitFor({state:'visible'});
  assert.ok((await page.locator('#plan-hierarchy').innerText()).includes('report'));
  await page.locator('#plan-hierarchy .pap-compare-button:visible').first().click();
  await page.getByRole('heading',{name:'Work recorded between these endpoints',exact:true}).waitFor();
  assert.deepEqual(errors,[]);
  const report={passed:true,installed:true,desktop:true,mobile:true,unit_witnesses:4,stage_attempts:2,errors};
  fs.writeFileSync(out+'/browser-report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }catch(e){
  if(page){await page.screenshot({path:out+'/failure.png'});fs.writeFileSync(out+'/failure.txt',await page.locator('body').innerText());}throw e;
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
