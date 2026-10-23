const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{pathToFileURL}=require('node:url');
const base=process.env.REVIEW_TEST_URL,out=process.env.REVIEW_OUTPUT_DIR;
const fixture=JSON.parse(fs.readFileSync(process.env.REPORT_FIXTURE,'utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true});page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/investigate?saved='+fixture.investigation);
  const report=page.getByRole('link',{name:'Read report',exact:true});await report.waitFor();
  assert.ok((await report.getAttribute('href')).includes(fixture.investigation));await report.click();
  await page.getByRole('heading',{name:'Delivery regression · synthetic report example',exact:true,level:1}).waitFor();
  assert.ok(await page.locator('main').innerText().then(s=>s.includes('One of two deliveries failed')));
  assert.equal(await page.locator('.finding').count(),3);assert.equal(await page.locator('.finding.contradicts').count(),1);assert.equal(await page.locator('.finding.pending').count(),1);
  assert.equal(await page.locator('script').count(),0);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  if(out)await page.screenshot({path:out+'/findings-desktop.png'});
  await page.getByRole('link',{name:'Synthetic delivery verification',exact:true}).click();
  await page.getByText('Delivery check failed: parcel remained at the depot after the retry budget was exhausted.',{exact:true}).waitFor();
  if(out)await page.screenshot({path:out+'/findings-evidence.png'});
  const downloadPromise=page.waitForEvent('download');await page.getByRole('link',{name:'Download HTML',exact:true}).click();
  const download=await downloadPromise,file=path.resolve(out,'findings-offline.html');await download.saveAs(file);
  const context=await browser.newContext({viewport:{width:390,height:900},offline:true}),offline=await context.newPage();
  let network=0;offline.on('request',r=>{if(/^https?:/.test(r.url()))network++;});offline.on('pageerror',e=>errors.push(e.message));
  await offline.goto(pathToFileURL(file).href);await offline.getByRole('heading',{name:'Findings',exact:true}).waitFor();
  assert.equal(network,0);assert.equal(await offline.locator('.finding').count(),3);
  assert.ok(await offline.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await offline.getByRole('link',{name:'Synthetic delivery verification',exact:true}).click();
  assert.match(await offline.locator('.source pre').first().innerText(),/parcel remained at the depot/);
  if(out)await offline.screenshot({path:out+'/findings-mobile.png'});
  await context.close();await page.getByRole('link',{name:'Open investigation',exact:true}).click();await report.waitFor();
  assert.equal(new URL(page.url()).searchParams.get('saved'),fixture.investigation);
  assert.deepEqual(errors,[]);
  console.log('Passed: saved investigation entry, findings/counterevidence/pending checks, quoted source, download, offline no-network rendering, desktop/mobile layout and return navigation.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
