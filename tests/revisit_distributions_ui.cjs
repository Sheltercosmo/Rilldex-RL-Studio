// Installed-app navigation with authored controls and saved public traces.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.REVIEW_TEST_URL,out=process.env.REVIEW_OUTPUT_DIR;
(async()=>{const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
try{
 const fixture=JSON.parse(fs.readFileSync(out+'/fixture.json','utf8'));
 const page=await browser.newPage({viewport:{width:1440,height:1050}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/?view=strategies&experiment=revisit-controls');
 await page.getByRole('button',{name:'Revisit patterns',exact:true}).click();
 await page.waitForURL(/lens=revisit/);
 await page.locator('.bd-stats').getByText('saved same-work pairs',{exact:true}).waitFor();
 const snapshot=await page.request.get(base+'/api/behavior-distributions?lens=revisit&experiment=revisit-controls').then(r=>r.json());
 assert.equal(snapshot.distribution.total,64);
 assert.deepEqual(snapshot.distribution.counts,fixture.controls.distribution.counts);
 await page.locator('.behavior-distributions').screenshot({path:out+'/distribution.png'});
 await page.setViewportSize({width:390,height:900});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile distribution width');
 await page.getByRole('button',{name:'Revisit patterns',exact:true}).scrollIntoViewIfNeeded();
 assert.ok(await page.getByRole('button',{name:'Revisit patterns',exact:true}).isVisible());
 await page.screenshot({path:out+'/mobile-distribution.png'});
 await page.setViewportSize({width:1440,height:1050});
 // A category opens a bounded window; the map restores the same chart selection.
 await page.goto(base+'/?view=strategies&experiment=revisit-controls&lens=revisit&category=exact_repeat&cases=1&case_window=all');
 const target=page.locator('.bd-evidence-case>a').first();await target.waitFor();
 const originalUrl=page.url(),href=await target.getAttribute('href');
 await target.click();await page.getByRole('button',{name:'Compare attempts',exact:true}).waitFor();
 const details=page.locator('#detail-body');
 await details.getByRole('heading',{name:'Recorded inputs: unchanged',exact:true}).waitFor();
 assert.ok(await details.getByRole('heading',{name:'Feedback: unchanged',exact:true}).isVisible());
 assert.ok(await page.locator('.proof-node').count()>2);
 assert.ok((await details.innerText()).includes('intervening operation'));
 const originalGraph=new URL(page.url()).searchParams.get('graph');
 await page.reload();await details.getByRole('heading',{name:'Feedback: unchanged',exact:true}).waitFor();
 assert.equal(new URL(page.url()).searchParams.get('graph'),originalGraph);
 await details.getByRole('link',{name:'← Behavior distributions',exact:true}).click();
 assert.equal(page.url(),originalUrl);
 await page.goto(base+href);
 await page.setViewportSize({width:390,height:900});
 await details.getByRole('heading',{name:'Later feedback',exact:true}).scrollIntoViewIfNeeded();
 assert.ok(await details.getByRole('heading',{name:'Later feedback',exact:true}).isVisible());
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile evidence width');
 await page.screenshot({path:out+'/mobile-evidence.png'});
 // Each category resolves to the saved output, without needing a monitor definition.
 for(const category of snapshot.categories){
  const c=snapshot.cases.find(c=>c.category===category.id);assert.ok(c);
  await page.goto(base+c.map_url);
  await page.getByRole('button',{name:'Compare attempts',exact:true}).waitFor();
  await details.getByRole('heading',{name:'Feedback: '+c.repeated_work.feedback.status,exact:true}).waitFor();
 }
 await page.setViewportSize({width:1440,height:1050});
 for(const p of fixture.public){
  const c=p.cases.find(c=>c.category==='changed_inputs')||p.cases[0];
  await page.goto(base+c.map_url);await details.getByRole('heading',{name:'Recorded inputs: changed',exact:true}).waitFor();
  assert.ok((await details.innerText()).includes('Earlier attempt'));
  assert.ok((await details.innerText()).includes('Later attempt'));
  await details.screenshot({path:out+'/'+p.observer+'-evidence.png'});
 }
 // Conflicting source/graph coordinates cannot silently select another pair.
 const bad=new URL(base+snapshot.cases[0].map_url);bad.searchParams.set('graph',fixture.public[0].graph_id);
 await page.goto(bad.href);
 await page.getByText('This attempt pair belongs to a different saved graph.',{exact:true}).waitFor();
 assert.deepEqual(errors,[]);
 const report={passed:true,control_rollouts:64,public_pairs:16,categories:5,errors};
 fs.writeFileSync(out+'/browser-report.json',JSON.stringify(report));console.log(JSON.stringify(report));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
