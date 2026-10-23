const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn}=require('child_process'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=process.env.RILLDEX_UI_OUTPUT;fs.mkdirSync(root,{recursive:true});
const server=spawn(process.env.RILLDEX_TEST_PYTHON,['-I','-u',path.join(__dirname,'case_behavior_fixture.py'),root],{cwd:require('os').tmpdir(),windowsHide:true,stdio:['pipe','pipe','pipe']});
let output='';server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
(async()=>{let browser,page;const errors=[];try{
 const deadline=Date.now()+60000;while(!/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/.test(output)){if(server.exitCode!==null||Date.now()>deadline)throw Error(output);await new Promise(r=>setTimeout(r,100));}
 const base=output.match(/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/)[1],fixture=JSON.parse(fs.readFileSync(path.join(root,'fixture.json'),'utf8'));
 browser=await chromium.launch({headless:true,channel:'msedge'});page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));
 const saved=base+'/investigate?saved='+fixture.saved;await page.goto(saved);
 const section=page.locator('#case-behavior'),success=section.locator(`[data-monitor-id="${fixture.success}"]`),recovery=section.locator(`[data-monitor-id="${fixture.recovery}"]`);
 await success.getByRole('button',{name:'Inspect reference Reported success',exact:true}).waitFor();
 assert.equal(await success.getByRole('button',{name:'Inspect reference Reported success',exact:true}).textContent(),'75.0%');
 assert.equal(await success.getByRole('button',{name:'Inspect selected Reported success',exact:true}).textContent(),'25.0%');
 assert.equal(await recovery.getByText('32 unresolved opportunities',{exact:true}).count(),2);
 await section.scrollIntoViewIfNeeded();await section.screenshot({path:path.join(root,'all-rollouts-desktop.png')});
 await section.getByRole('combobox',{name:'Behavior comparison population'}).selectOption('matched');
 assert.equal(await success.getByRole('button',{name:'Inspect reference Reported success',exact:true}).textContent(),'50.0%');
 assert.equal(await success.getByRole('button',{name:'Inspect selected Reported success',exact:true}).textContent(),'50.0%');
 await success.getByText('Task coverage & measurement versions',{exact:true}).click();
 await success.getByRole('button',{name:'Inspect reference Reported success for escaping',exact:true}).waitFor();
 assert.equal(await success.getByText('24 / 24 rollouts measured',{exact:true}).count(),2);
 await section.screenshot({path:path.join(root,'same-tasks-desktop.png')});
 await success.getByRole('button',{name:'Inspect reference Reported success for escaping',exact:true}).click();
 let dialog=page.locator('.ii-dialog');await dialog.locator('details').first().locator('summary').click();
 await dialog.getByRole('button',{name:'Inspect saved evidence',exact:true}).first().click();await dialog.getByText('Exact evidence and limits',{exact:true}).first().waitFor();
 const pinned=await dialog.getByRole('link',{name:'Open pinned rollout map',exact:true}).first().getAttribute('href'),map=new URL(pinned,base);
 assert.ok(map.searchParams.get('graph'));assert.ok(map.searchParams.get('value'));assert.ok(map.searchParams.get('return_to').includes('case_measure_view=matched'));
 await page.goto(map.href);await page.waitForFunction(()=>document.querySelector('#map-count')?.textContent.includes('source records'));
 assert.equal(await page.locator('#map-error').isVisible(),false);assert.equal(await page.locator('#map-title').textContent(),'escaping');
 assert.equal((await page.request.get(base+'/api/monitoring/values/'+map.searchParams.get('value'))).status(),200);
 await page.goto(base+map.searchParams.get('return_to'));await section.waitFor();assert.equal(await section.getByRole('combobox',{name:'Behavior comparison population'}).inputValue(),'matched');
 await page.locator('.ii-dialog').getByText('Exact evidence and limits',{exact:true}).first().waitFor();await page.locator('.ii-dialog').getByRole('button',{name:'Close',exact:true}).click();
 await recovery.getByRole('button',{name:'Inspect selected Recorded recovery',exact:true}).click();dialog=page.locator('.ii-dialog');await dialog.locator('details').first().locator('summary').click();await dialog.getByRole('button',{name:'Inspect saved evidence',exact:true}).first().click();await dialog.getByText('Exact evidence and limits',{exact:true}).first().waitFor();await dialog.getByRole('button',{name:'Close',exact:true}).click();
 const created=await page.request.post(base+'/api/monitoring/monitors',{data:{definition:{name:'Later source measure',kind:'metric',metric:'actions',observer:'source'}}});assert.equal(created.ok(),true,await created.text());
 await section.getByRole('button',{name:'Change measures',exact:true}).click();dialog=page.getByRole('dialog',{name:'Comparison measures',exact:true});await dialog.getByRole('checkbox',{name:'Later source measure',exact:true}).waitFor();await dialog.getByRole('checkbox',{name:'Response length',exact:true}).uncheck();
 await dialog.getByRole('button',{name:'Save with these measures',exact:true}).click();await page.waitForURL(u=>u.searchParams.get('saved')!==fixture.saved);
 await section.waitFor();assert.equal(await section.locator('.case-measure-row').count(),2);
 const next=await(await page.request.get(base+'/api/investigations/'+new URL(page.url()).searchParams.get('saved'))).json();assert.equal(next.parent_id,fixture.saved);assert.equal(next.snapshot.behavior.monitor_ids.length,2);
 const original=await(await page.request.get(base+'/api/investigations/'+fixture.saved)).json();assert.equal(original.snapshot.behavior.panels.length,3);
 await page.setViewportSize({width:390,height:844});await section.scrollIntoViewIfNeeded();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);await section.screenshot({path:path.join(root,'comparison-mobile.png')});
 await section.getByRole('button',{name:'Change measures',exact:true}).click();dialog=page.getByRole('dialog',{name:'Comparison measures',exact:true});await dialog.getByRole('checkbox',{name:'Later source measure',exact:true}).waitFor();assert.equal(await dialog.evaluate(n=>n.scrollWidth>n.clientWidth+2),false);await dialog.screenshot({path:path.join(root,'choose-mobile.png')});
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(root,'browser-report.json'),JSON.stringify({passed:true,fixture:{rollouts:64,events_per_rollout:33,authored:true,inference_calls:0},checks:['raw population shift','equal-task weighting','per-task trial counts','custom monitor unresolved opportunities','exact evidence loading','pinned map link and return','population mode persistence','measure selection creates a new saved comparison','original remains unchanged','390px mobile layout'],errors},null,2));console.log('Behavior comparison browser checks passed');
 }catch(e){if(page){await page.screenshot({path:path.join(root,'failure.png')});fs.writeFileSync(path.join(root,'failure.html'),await page.content());}throw e;}
 finally{if(browser)await browser.close();server.stdin.end();await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
