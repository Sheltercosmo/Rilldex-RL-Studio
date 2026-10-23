const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.REVIEW_TEST_URL,run=process.env.REVIEW_RUN_ID,out=process.env.REVIEW_OUTPUT_DIR;
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/connections?model_run='+run+'#model-section');
  const panel=page.locator('#model-setup');
  await page.waitForFunction(id=>document.querySelector('[aria-label="Pilot rollout"]')?.value===id,run);
  await panel.getByLabel('Decision calls',{exact:true}).fill('10');
  await panel.getByRole('button',{name:'Start / resume pilot',exact:true}).click();
  await panel.getByText('Pilot · budget reached',{exact:true}).waitFor({timeout:30000});
  assert.ok((await panel.innerText()).includes('2 / 6 action–step pairs inspected · 4 pending'));
  const local=await panel.getByRole('link',{name:'Open activities · work links pending →'}).getAttribute('href');
  if(out)await panel.screenshot({path:out+'/plan-pilot-partial.png'});
  await page.reload();
  await panel.getByText('Pilot · budget reached',{exact:true}).waitFor();
  assert.equal(await panel.getByLabel('Decision calls',{exact:true}).inputValue(),'10');
  await panel.getByLabel('Decision calls',{exact:true}).fill('12');
  await panel.getByRole('button',{name:'Start / resume pilot',exact:true}).click();
  await panel.getByText('Pilot · running',{exact:true}).waitFor();
  assert.equal(await panel.getByRole('link',{name:'Open activities · work links pending →'}).getAttribute('href'),local);
  await panel.getByRole('link',{name:'Open plans & attempts →'}).waitFor({timeout:30000});
  assert.ok((await panel.innerText()).includes('6 / 6 action–step pairs inspected · 0 pending'));
  const plans=await panel.getByRole('link',{name:'Open plans & attempts →'}).getAttribute('href');
  assert.ok(plans.includes('level=plans'));
  await panel.getByLabel('Decision calls',{exact:true}).fill('17');
  await panel.getByRole('button',{name:'Start / resume pilot',exact:true}).click();
  await panel.getByText('Pilot complete · plans and activities',{exact:true}).waitFor({timeout:30000});
  const state=await page.request.get(base+'/api/models').then(r=>r.json());
  assert.equal(state.pilot.usage.providers.jev.attempts,17);
  assert.equal(state.pilot.usage.providers.candidate.attempts,9);
  await page.setViewportSize({width:390,height:900});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Pilot mobile overflow');
  if(out)await panel.screenshot({path:out+'/plan-pilot-complete-mobile.png'});
  await page.setViewportSize({width:1440,height:1000});
  await panel.getByRole('link',{name:'Open plans & attempts →'}).click();
  await page.waitForURL('**/semantic-map?**');
  await page.locator('#plan-hierarchy').waitFor({state:'visible',timeout:30000});
  assert.equal(await page.locator('#show-plan-level').getAttribute('aria-pressed'),'true');
  assert.ok((await page.locator('#plan-hierarchy').innerText()).includes('Write the Markdown report.'));
  const graph=await page.request.get(base+'/api/semantic-map/'+run+'?'+new URL(page.url()).searchParams).then(r=>r.json());
  assert.equal(graph.available,true);
  assert.equal(graph.document.relations.filter(r=>r.plan_step_id).length,3);
  await page.getByRole('button',{name:/STEP 2.*Convert to PDF/s}).click();
  assert.ok((await page.locator('#plan-hierarchy').innerText()).includes('ERROR: converter unavailable'));
  if(out)await page.screenshot({path:out+'/plan-pilot-map.png',fullPage:false});
  for(const href of [local,plans]){
   const older=await page.request.get(base+'/api/semantic-map/'+run+'?'+new URL(base+href).searchParams).then(r=>r.json());
   assert.equal(older.available,true);
  }
  assert.deepEqual(errors,[]);
  const report={passed:true,installed:true,candidate_http_calls:9,authored_decision_calls:17,
   checks:['partial plan coverage','shared lifetime resume','map retained during resume','reload','old observers stable','plan map navigation','mobile overflow'],errors};
  if(out)fs.writeFileSync(out+'/browser-report.json',JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
