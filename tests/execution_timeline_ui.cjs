// Run against scripts/execution_timeline_smoke.py's isolated synthetic workspace.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.REVIEW_TEST_URL,output=process.env.REVIEW_OUTPUT_DIR;
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[],checks=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/?view=execution&experiment=synthetic-execution-signals');
  await page.locator('.ex-block').first().waitFor();
  const originalSpans=await page.locator('.ex-block').count();assert.ok(originalSpans>=331);
  assert.ok(await page.locator('.ex-signal').count()>=5);
  await page.locator('.ex-kind-learner_update').nth(25).click();
  await page.getByRole('heading',{name:/linked samples/}).waitFor();
  assert.ok(await page.locator('#execution-detail a[href^="/semantic-map"]').count()>=3);
  assert.match(await page.locator('#execution-detail').innerText(),/Policy age 4/);
  checks.push('331 actual recorded spans; linked update selects sample sources and token-weighted policy age');
  await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));
  if(output)await page.screenshot({path:output+'/desktop.png',fullPage:true});
  await page.getByText('Exact interval & clock',{exact:true}).click();
  await page.getByLabel('From (seconds)').fill('200');
  await page.getByLabel('To (seconds)').fill('300');
  await page.getByRole('button',{name:'Apply interval',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.ex-block').length<100);
  assert.ok(await page.locator('.ex-signal').count()>=5);
  checks.push('One interval updates execution and signal panels');
  await page.locator('.ex-signal svg').first().scrollIntoViewIfNeeded();
  const curve=await page.locator('.ex-signal svg').first().boundingBox();
  await page.mouse.move(curve.x+curve.width*.35,curve.y+curve.height*.1);await page.mouse.down();
  await page.mouse.move(curve.x+curve.width*.7,curve.y+curve.height*.1);
  assert.ok(Number(await page.locator('.ex-selection').getAttribute('width'))>0);
  await page.mouse.up();
  await page.waitForFunction(()=>Number(new URLSearchParams(location.search).get('execution_start'))>200);
  checks.push('Brushing a signal curve selects the same interval for all panels');
  await page.getByRole('button',{name:'Save view',exact:true}).click();
  await page.waitForURL('**/*execution_saved=*');
  await page.getByRole('button',{name:'Return to live',exact:true}).waitFor();
  const frozenCount=await page.locator('.ex-block').count();
  const arrival=await page.request.post(base+'/api/execution-records',{data:{schema:'execution-records/2',producer:'browser-control',experiment:'synthetic-execution-signals',records:[{
   id:'live-'+Date.now(),revision:0,kind:'inference',rollout:{producer:'browser-control',id:'pending'},state:'running',context:{worker:'Late sampler'},
   evidence:'Synthetic live-arrival UI check',timing:{clock:'synthetic/shared-seconds',start:250,end:null}}]}});
  assert.equal(arrival.ok(),true);
  assert.equal(await page.getByLabel('Execution clock',{exact:true}).isDisabled(),true);
  await page.reload();await page.getByRole('button',{name:'Return to live',exact:true}).waitFor();
  assert.equal(await page.locator('.ex-block').count(),frozenCount);
  checks.push('Frozen evidence survives navigation/reload');
  for(const width of [1024,390]){
   await page.setViewportSize({width,height:900});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
   await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));
   if(output)await page.screenshot({path:output+`/width-${width}.png`});
  }
  if(await page.locator('.ex-inspector-dialog').isVisible())await page.locator('.ex-inspector-dialog').getByRole('button',{name:'Close',exact:true}).click();
  await page.getByRole('button',{name:'Return to live',exact:true}).click();
  await page.getByRole('button',{name:'Full range',exact:true}).click();
  await page.waitForFunction(n=>document.querySelectorAll('.ex-block').length===n,originalSpans+1);
  await page.route('**/api/training-execution?*',route=>route.abort());
  await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  await page.getByText(/Showing the last captured data/).waitFor();
  assert.equal(await page.locator('.ex-block').count(),originalSpans+1);
  await page.unroute('**/api/training-execution?*');
  await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  await page.getByText(/Showing the last captured data/).waitFor({state:'hidden'});
  checks.push('Late arrivals leave saved views unchanged; reconnect restores unchanged evidence after an outage');
  checks.push('Desktop/tablet/mobile have no page overflow; return to live restores full interval');
  await page.getByRole('button',{name:'Save view',exact:true}).click();
  await page.getByRole('button',{name:'Return to live',exact:true}).waitFor();
  await page.locator('#environment').selectOption('terminal');
  await page.getByRole('button',{name:'Save view',exact:true}).waitFor();
  assert.equal(new URL(page.url()).searchParams.has('execution_saved'),false);
  await page.getByText('Environment filters narrow rollout lanes. Shared learner updates retain their complete batch and native metrics.').waitFor();
  checks.push('Changing scope leaves the saved comparison and loads the selected live population');
  await page.goto(base+'/?view=health&experiment=synthetic-execution-signals');
  await page.getByRole('heading',{name:'Gradient norms',exact:true}).waitFor();
  await page.getByRole('heading',{name:'Trainer–sampler mismatch',exact:true}).waitFor();
  checks.push('Gradient and mismatch signals are visible in the existing trainer dashboard too');
  await page.goto(base+'/connections#execution-section');
  await page.locator('#execution-section').waitFor({state:'visible'});
  checks.push('Capture instructions open in the correct Data & workflows section');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({checks,errors},null,2));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
