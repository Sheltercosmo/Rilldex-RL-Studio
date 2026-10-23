// Start a server on scripts/detector_validation_fixture.py's authored workspace.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.REVIEW_TEST_URL,out=process.env.REVIEW_OUTPUT_DIR;
const fixture=JSON.parse(fs.readFileSync(process.env.VALIDATION_FIXTURE,'utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/monitors');await page.getByRole('link',{name:'Detector validation',exact:true}).click();
  await page.getByRole('heading',{name:'Compare detectors on reviewed cases'}).waitFor();
  await page.locator('#sets').selectOption(fixture.set);await page.locator('#split').selectOption('all');
  await page.waitForFunction(id=>[...document.querySelector('#results').options].some(o=>o.value===id),fixture.result);
  await page.locator('#results').selectOption(fixture.result);await page.locator('#baseline').selectOption(fixture.baseline);
  await page.getByText('1 regressed',{exact:true}).waitFor();await page.getByText('1 improved',{exact:true}).waitFor();
  assert.match(await page.locator('#coverage-note').innerText(),/1 false negatives/);
  assert.equal(await page.locator('.case-row').count(),10);
  assert.match(await page.locator('.case-row').first().innerText(),/False negative/);
  assert.doesNotMatch(await page.locator('#case-table').innerText(),/Present \/ taken|Absent \/ not taken/);
  await page.locator('#filter').selectOption('regressed');assert.equal(await page.locator('.case-row').count(),1);
  await page.getByRole('button',{name:'Inspect case',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Validation case'});await dialog.getByRole('heading',{name:'Frozen reference'}).waitFor();
  assert.match(await dialog.innerText(),/Synthetic reference authored/);
  const reviewLink=await dialog.getByRole('link',{name:'Open review',exact:true}).getAttribute('href');assert.ok(reviewLink.includes('&case='));
  const measurement=await dialog.getByRole('link',{name:'Open exact measurement →'}).getAttribute('href');assert.ok(measurement.includes('value='));
  await dialog.getByRole('button',{name:'Close',exact:true}).click();
  await page.locator('#filter').selectOption('all');if(out)await page.screenshot({path:out+'/validation-desktop.png',fullPage:true});
  const url=page.url();await page.reload();await page.getByText('1 regressed',{exact:true}).waitFor();
  await page.goto(base+reviewLink);await page.locator('#case-list button[aria-current=true]').waitFor();
  assert.equal(await page.locator('#case-list button[aria-current=true]').getAttribute('data-case'),new URL(base+reviewLink).searchParams.get('case'));
  await page.getByRole('link',{name:'Save validation set',exact:true}).click();await page.locator('#create-panel').waitFor();
  await page.locator('#set-name').fill('Synthetic UI saved references');await page.locator('#reviewer').fill('Authored control labels');
  await page.locator('#samples input').first().check();await page.getByText('Split settings',{exact:true}).click();await page.locator('#holdout').fill('0');
  await page.getByRole('button',{name:'Save validation set',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#create-panel').hidden);
  assert.equal(await page.locator('#sets option:checked').innerText(),'Synthetic UI saved references');
  await page.locator('#split').selectOption('development');
  await page.getByRole('button',{name:'Compare saved results',exact:true}).click();
  await page.locator('.score').first().waitFor();assert.ok(await page.locator('.case-row').count()>0);
  await page.getByText('Run custom Python',{exact:true}).click();assert.match(await page.locator('#code').innerText(),/validation.evaluate/);
  await page.goto(url);await page.getByText('1 regressed',{exact:true}).waitFor();
  await page.setViewportSize({width:390,height:900});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.locator('#filter').selectOption('unavailable');assert.equal(await page.locator('.case-row').count(),1);
  await page.getByRole('button',{name:'Inspect case',exact:true}).click();await dialog.getByRole('heading',{name:'Frozen reference'}).waitFor();
  assert.match(await dialog.innerText(),/Authored worker error/);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  if(out)await page.screenshot({path:out+'/validation-case-mobile.png'});
  assert.deepEqual(errors,[]);console.log('Passed: registry entry, version comparison, coverage, disagreement filters, frozen references, exact review deep link, new set, saved-result capture, Python guidance, reload and mobile layout.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
