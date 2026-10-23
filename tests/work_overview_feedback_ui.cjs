const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.REVIEW_TEST_URL,out=process.env.REVIEW_OUTPUT_DIR;
const fixtures=JSON.parse(fs.readFileSync(out+'/fixture.json','utf8'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[],results=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1100}});page.on('pageerror',e=>errors.push(e.message));
  for(const [index,f]of fixtures.entries()){
   const url=base+'/semantic-map?'+new URLSearchParams({run:f.run_id,graph:f.graph_id,observer:f.observer,level:'work'});
   await page.goto(url);await page.locator('.wr-target').first().waitFor();
   assert.ok(await page.locator('.wr-target .wr-followup-summary').count());
   await page.getByRole('combobox',{name:'Repeated work filter',exact:true}).selectOption('errors_again');
   const filtered=await page.locator('.wr-target').count();assert.equal(filtered>0,index===0);
   await page.reload();await page.getByRole('combobox',{name:'Repeated work filter',exact:true}).waitFor();
   assert.equal(await page.getByRole('combobox',{name:'Repeated work filter',exact:true}).inputValue(),'errors_again');
   assert.equal(await page.locator('.wr-target').count(),filtered);
   await page.locator('[data-work-view=timeline]').click();await page.locator('.wtl-mark').first().waitFor();
   const counts=await page.locator('.wtl-mark[data-report]').evaluateAll(marks=>{const result={};for(const m of marks)result[m.dataset.report]=(result[m.dataset.report]||0)+1;return result;});
   assert.deepEqual(counts,index===0?{reported_again:4,no_reported_error:3,followup_unknown:1,no_prior_error:2}:{no_reported_error:3,no_prior_error:3});
   const summary=await page.locator('.wtl-followups').textContent();assert.match(summary,index===0?/8 pairs after errors/:/3 pairs after errors/);
   await page.locator('[data-lens=procedure]').click();
   assert.equal(await page.locator('.wtl-mark[data-report]').count(),Object.values(counts).reduce((a,b)=>a+b,0));
   await page.locator('.wn-timeline').screenshot({path:out+'/overview-'+index+'-desktop.png'});
   // Badges sit inside the row, and retain distinct text independently of color.
   assert.ok(await page.locator('.wtl-mark .wtl-result').evaluateAll(badges=>badges.every(b=>{const box=b.getBoundingClientRect(),row=b.closest('.wtl-row').getBoundingClientRect();return box.top>=row.top&&box.bottom<=row.bottom+1&&b.textContent.trim();})));
   await page.setViewportSize({width:390,height:900});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await page.locator('.wtl-scroll').evaluate(s=>s.scrollLeft=s.scrollWidth);
   await page.locator('.wn-timeline').screenshot({path:out+'/overview-'+index+'-mobile.png'});
   const mark=page.locator('.wtl-mark.method-settings[data-report="'+(index===0?'reported_again':'no_reported_error')+'"]');
   await mark.click();
   const panel=page.locator('#detail-body .wr-executor-followup');await panel.waitFor();
   assert.match(await panel.textContent(),index===0?/Error reported again/:/Later response inspected: no error reported/);
   await panel.getByRole('button',{name:'Inspect later response',exact:true}).click();
   const selected=new URL(page.url()).searchParams.get('focus_unit');assert.ok(selected);
   await page.reload();await page.locator('#map-inspector').waitFor();assert.equal(new URL(page.url()).searchParams.get('focus_unit'),selected);
   if(index===0)assert.ok((await page.locator('#detail-body').textContent()).includes('User site-packages are not visible'));
   results.push({domain:index===0?'software':'airline',counts,filtered_targets:filtered,selected_response:selected});
   await page.setViewportSize({width:1440,height:1100});
  }
  assert.deepEqual(errors,[]);const report={passed:true,installed:true,provider_calls:0,results,errors};
  fs.writeFileSync(out+'/browser-report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
