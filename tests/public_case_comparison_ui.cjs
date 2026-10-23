const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const base=process.env.REVIEW_TEST_URL,output=process.env.REVIEW_OUTPUT_DIR;
const saved=process.env.REVIEW_INVESTIGATION;
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1500,height:1050}});
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/investigate?saved='+saved);
  await page.locator('.case-group').first().waitFor();
  assert.match(await page.locator('#investigation-app').innerText(),/8 reference \/ 8 selected rollouts/);
  await page.getByRole('combobox',{name:'Rollout outcome filter'}).selectOption('improved');
  await page.waitForFunction(()=>document.querySelectorAll('.case-group').length===2);
  await page.getByRole('button',{name:'Compare evidence',exact:true}).first().click();
  await page.locator('.case-unit').first().waitFor();await page.locator('.case-column').nth(1).locator('.case-unit').first().waitFor();
  const dialog=page.locator('.case-dialog');
  assert.match(await dialog.innerText(),/openai\/gpt-5-mini/);
  assert.match(await dialog.innerText(),/anthropic\/claude-sonnet-4-5/);
  assert.doesNotMatch(await dialog.innerText(),/Checkpoint not recorded/);assert.match(await dialog.innerText(),/Failed checks · not measured/);
  await dialog.locator('.case-column header details summary').first().click();
  assert.match(await dialog.locator('.case-column header details').first().innerText(),/Publisher-reported resolved/);
  if(output)await page.screenshot({path:output+'/public-comparison-desktop.png'});
  const graph=await dialog.locator('.case-column header a').first().getAttribute('href');
  await dialog.locator('.case-unit a').first().click();await page.locator('#detail-title').waitFor();
  await page.getByRole('link',{name:/Back to/}).click();await page.locator('.case-dialog .case-unit').first().waitFor();
  await page.reload();await page.locator('.case-dialog .case-unit').first().waitFor();
  assert.equal(await page.locator('.case-column header a').first().getAttribute('href'),graph);
  await dialog.getByRole('button',{name:'Close',exact:true}).click();
  await page.getByRole('button',{name:'New comparison',exact:true}).click();
  const setup=page.locator('.case-setup');await setup.getByRole('combobox',{name:'Reference outcome source',exact:true}).waitFor();
  for(const side of ['Reference','Selected']){
   const selector=setup.getByRole('combobox',{name:side+' outcome source',exact:true});
   assert.equal(JSON.parse(await selector.inputValue()).label,'SWE-bench published resolution');
   assert.match(await selector.innerText(),/8 rollouts/);
  }
  if(output)await page.screenshot({path:output+'/public-selection-desktop.png'});
  await page.setViewportSize({width:430,height:920});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  const box=await setup.boundingBox();assert.ok(box.width<=430);
  if(output)await page.screenshot({path:output+'/public-selection-mobile.png'});
  await setup.getByRole('button',{name:'Compare captured rollouts',exact:true}).click();
  await page.waitForURL(u=>u.searchParams.has('saved')&&u.searchParams.get('saved')!==saved);
  await page.locator('.case-group').first().waitFor();
  assert.match(await page.locator('#investigation-app').innerText(),/8 reference \/ 8 selected rollouts/);
  assert.deepEqual(errors,[]);
  console.log('Published case comparison: outcomes, context, evidence, map/back/reload, recapture, desktop/mobile passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
