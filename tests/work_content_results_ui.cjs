const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.REVIEW_TEST_URL,run=process.env.REVIEW_RUN_ID,graph=process.env.REVIEW_GRAPH_ID;
const output=process.env.REVIEW_OUTPUT_DIR;
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let page;
 try{
  page=await browser.newPage({viewport:{width:1600,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  const url=base+'/semantic-map?'+new URLSearchParams({run,graph,observer:'content-control',level:'units',focus_unit:'unit-0'});
  await page.goto(url);
  const panel=page.locator('#detail-body .work-contents');
  await panel.getByText('Budget limit reached',{exact:true}).waitFor();
  assert.equal(await panel.locator('.wc-card').count(),2);
  assert.equal(await panel.locator('.wc-attachment').count(),2);
  assert.ok((await panel.innerText()).includes('2 attributes still await attachment decisions.'));
  const quote=panel.locator('details[data-key="c1:source"]');
  await quote.locator('summary').click();
  assert.equal(await quote.getAttribute('open'),'');
  fs.writeFileSync(output+'/advance','resume');
  if(process.env.REVIEW_RELATIONS){
   await panel.getByText('0 selected · 0 unresolved · 0/8 checks inspected',{exact:true}).waitFor({timeout:20000});
   assert.equal(await panel.locator('.wc-card').count(),2);
   fs.writeFileSync(output+'/advance-relations','resume');
  }
  await panel.getByText('Complete',{exact:true}).waitFor({timeout:20000});
  assert.equal(await quote.getAttribute('open'),'','Polling must preserve open source details');
  assert.equal(await panel.locator('.wc-attachment').count(),5);
  assert.equal(await panel.locator('.wc-uncertain').count(),2);
  assert.equal(await panel.locator('.wc-card').count(),2);
  assert.equal(await panel.getByText('2 attributes still await attachment decisions.',{exact:true}).count(),0);
  if(process.env.REVIEW_RELATIONS){
   await panel.getByText('1 selected · 0 unresolved · 8/8 checks inspected',{exact:true}).waitFor();
   await panel.getByText('A → B · serves the aim',{exact:true}).click();
   await panel.getByRole('button',{name:'To B · test implementation 0',exact:true}).click();
   assert.equal(await panel.locator('.wc-card.wc-focused').count(),1);
   assert.ok((await panel.locator('.wc-card.wc-focused').innerText()).includes('test implementation 0'));
  }
  await panel.getByRole('button',{name:'Refresh',exact:true}).click();
  await panel.getByText('Complete',{exact:true}).waitFor();
  await panel.locator('.wc-heading').scrollIntoViewIfNeeded();
  await page.screenshot({path:output+'/desktop.png'});
  await page.locator('#map-inspector').screenshot({path:output+'/panel.png'});
  await page.setViewportSize({width:390,height:844});
  await panel.locator('.wc-heading').scrollIntoViewIfNeeded();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Mobile page overflow');
  assert.ok(await panel.evaluate(n=>n.scrollWidth<=n.clientWidth+1),'Mobile panel overflow');
  await page.screenshot({path:output+'/mobile.png'});
  await page.reload();await panel.getByText('Complete',{exact:true}).waitFor();
  assert.equal(await panel.locator('.wc-uncertain').count(),2);
  // The empty state offers code setup on an eligible unannotated unit.
  await page.goto(url.replace('unit-0','unit-1'));
  await panel.getByText('Work contents have not been annotated for this unit.',{exact:true}).waitFor();
  await panel.getByText('Extract with Python',{exact:true}).click();
  assert.ok((await panel.locator('pre').innerText()).includes('"unit-1"'));
  assert.equal(await panel.getByRole('link',{name:'Model setup →'}).getAttribute('href'),'/connections#model-section');
  assert.ok(await panel.evaluate(n=>n.scrollWidth<=n.clientWidth+1),'Code example overflow');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({desktop:true,mobile:true,liveProgress:true,reload:true,openDetailsPreserved:true,emptyCodeSetup:true,errors}));
 }catch(e){
  if(page){await page.screenshot({path:output+'/failure.png'});fs.writeFileSync(output+'/failure.txt',await page.locator('body').innerText());}
  throw e;
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
