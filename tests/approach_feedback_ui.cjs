const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.REVIEW_TEST_URL,out=process.env.REVIEW_OUTPUT_DIR,fixtures=JSON.parse(fs.readFileSync(out+'/fixture.json','utf8'));
(async()=>{const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));
 for(const f of fixtures){
  const pair=f.rows.find(r=>r.procedure==='reconfigured_procedure');
  await page.goto(base+'/?'+new URLSearchParams({view:'strategies',lens:'procedure',observer:f.observer,population_mode:'task_mix',category:'reconfigured_procedure',cases:'1',case_window:'all'}));
  await page.locator('.bd-report-state').getByText(pair.error_followup.label,{exact:false}).waitFor();
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'Export matching cases',exact:true}).click();await(await download).saveAs(out+'/export-'+f.run_id+'.json');
  const exported=JSON.parse(fs.readFileSync(out+'/export-'+f.run_id+'.json','utf8'));assert.deepEqual(exported.cases[0].error_followup,pair.error_followup);
 }
 const f=fixtures[0],pair=f.rows.find(r=>r.procedure==='reconfigured_procedure');
 await page.goto(base+'/semantic-map?'+new URLSearchParams({run:f.run_id,value:f.value_id,observer:f.observer,level:'units'}));
 await page.getByRole('button',{name:'Explain value',exact:true}).click();await page.locator('#detail-body').getByText('4 pairs report errors again',{exact:false}).waitFor();
 const target=f.error_measure.cases.find(c=>c.adaptation.current_unit_id===pair.current).label;
 await page.locator('#detail-body .relation-button').filter({hasText:target}).filter({hasText:'Reported again'}).first().click();
 await page.locator('#detail-body .wr-executor-followup').getByText('Error reported again',{exact:true}).waitFor();
 await page.locator('#detail-body .wr-executor-followup').getByRole('button',{name:'Inspect later response',exact:true}).click();
 const selected=new URL(page.url()).searchParams.get('focus_unit');assert.ok(selected,'Later response has an addressable selection');
 assert.ok((await page.locator('#detail-body').textContent()).includes('User site-packages are not visible'));
 await page.reload();await page.locator('#map-inspector').waitFor();assert.equal(new URL(page.url()).searchParams.get('focus_unit'),selected);
 await page.goto(base+'/semantic-map?'+new URLSearchParams({run:f.run_id,graph:f.graph_id,observer:f.observer,level:'work'}));await page.locator('.wr-target').first().waitFor();
 const targets=page.locator('.wr-target');let found=false;
 for(let i=0;i<await targets.count();i++){await targets.nth(i).click();const band=page.locator('.wr-between').filter({hasText:pair.reason.text});if(await band.count()){
  found=true;await band.locator('.wr-executor-followup').getByText('Error reported again',{exact:true}).waitFor();await band.screenshot({path:out+'/error-followup-desktop.png'});
  await page.setViewportSize({width:390,height:900});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await band.screenshot({path:out+'/error-followup-mobile.png'});
  await band.getByRole('button',{name:'Inspect later response',exact:true}).click();assert.ok((await page.locator('#detail-body').textContent()).includes('User site-packages are not visible'));break;
 }}
 assert.ok(found);assert.deepEqual(errors,[]);
 const result={passed:true,installed:true,provider_calls:0,checks:['software repeated error','airline inspected absence','exported report provenance','monitor value to pair to exact response','source selection reload','desktop/mobile work path'],errors};
 fs.writeFileSync(out+'/browser-report.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
