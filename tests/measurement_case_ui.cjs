const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn}=require('child_process'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=process.env.RILLDEX_UI_OUTPUT;fs.mkdirSync(root,{recursive:true});
const server=spawn(process.env.RILLDEX_TEST_PYTHON,['-I','-u',path.join(__dirname,'measurement_case_fixture.py'),root],{cwd:require('os').tmpdir(),windowsHide:true,stdio:['pipe','pipe','pipe']});
let output='';server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
(async()=>{let browser,page;const errors=[];try{
 const deadline=Date.now()+60000;while(!/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/.test(output)){if(server.exitCode!==null||Date.now()>deadline)throw Error(output);await new Promise(r=>setTimeout(r,100));}
 const base=output.match(/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/)[1],fixture=JSON.parse(fs.readFileSync(path.join(root,'fixture.json'),'utf8'));
 browser=await chromium.launch({headless:true,channel:'msedge'});page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));
 const saved=base+'/investigate?saved='+fixture.saved;await page.goto(saved);
 const panel=page.locator(`[data-monitor-id="${fixture.monitors.recovery}"]`);await panel.getByRole('button',{name:'Inspect reference Recovery windows',exact:true}).click();
 let dialog=page.locator('.ii-dialog'),row=dialog.locator(`[data-value-id="${fixture.values.recovery.value}"]`);await row.locator(':scope > summary').click();await row.getByRole('button',{name:'Inspect saved evidence',exact:true}).click();
 await row.getByRole('button',{name:'Next cases',exact:true}).click();const target=fixture.values.recovery.cases[23],key='analysis:'+target.id;
 let selected=row.locator(`[data-case-key='${key}']`);await selected.locator(':scope > summary').click();
 const href=await selected.getByRole('link',{name:'Open this case on the map',exact:true}).getAttribute('href');assert.ok(href.includes('measure_case='));
 await selected.getByRole('link',{name:'Open this case on the map',exact:true}).click();await page.waitForURL(u=>u.pathname==='/semantic-map');await page.waitForFunction(label=>document.querySelector('#detail-title')?.textContent===label,target.label);
 assert.equal(await page.locator('#map-error').isVisible(),false);assert.equal(new URL(page.url()).searchParams.get('measure_case'),key);assert.ok(await page.locator('#map-svg .proof-node').count()>0);
 await page.locator('#map-inspector').screenshot({path:path.join(root,'recovery-case-desktop.png')});
 await page.reload();await page.waitForFunction(label=>document.querySelector('#detail-title')?.textContent===label,target.label);
 await page.getByRole('link',{name:'Back to Investigation',exact:true}).click();await page.waitForURL(u=>u.pathname==='/investigate');
 dialog=page.locator('.ii-dialog');row=dialog.locator(`[data-value-id="${fixture.values.recovery.value}"]`);selected=row.locator(`[data-case-key='${key}']`);await selected.getByRole('link',{name:'Open this case on the map',exact:true}).waitFor();assert.equal(await selected.evaluate(n=>n.open),true);
 await row.getByRole('combobox',{name:'Measured case status',exact:true}).selectOption('unknown');assert.equal(await row.locator('.ii-measured-case').count(),4);
 await row.getByRole('searchbox',{name:'Find a measured case',exact:true}).fill('parser-case-27');assert.equal(await row.locator('.ii-measured-case').count(),1);
 await dialog.screenshot({path:path.join(root,'filtered-evidence-desktop.png')});await dialog.getByRole('button',{name:'Close',exact:true}).click();await page.waitForURL(u=>!u.searchParams.has('evidence_value'));
 // The same deep link works in source-clock interval investigations.
 const intervalUrl=base+'/investigate?'+new URLSearchParams({saved:fixture.interval,evidence_monitor:fixture.monitors.recovery,evidence_side:'baseline',evidence_value:fixture.values.recovery.value,evidence_case:key});
 await page.goto(intervalUrl);dialog=page.locator('.ii-dialog');await dialog.locator(`[data-case-key='${key}']`).getByRole('link',{name:'Open this case on the map',exact:true}).waitFor();await dialog.getByRole('button',{name:'Close',exact:true}).click();
 // A task-specific drilldown must not widen to all tasks when returning.
 await page.goto(saved);const taskPanel=page.locator(`[data-monitor-id="${fixture.monitors.recovery}"]`);await taskPanel.locator('details > summary').first().click();await taskPanel.getByRole('button',{name:'Inspect reference Recovery windows for parser-checks',exact:true}).click();
 dialog=page.locator('.ii-dialog');assert.equal(await dialog.locator('.ii-receipt').count(),1);await dialog.locator('.ii-receipt > summary').click();await dialog.getByRole('button',{name:'Inspect saved evidence',exact:true}).click();await dialog.getByRole('link',{name:'Open this case on the map',exact:true}).click();await page.waitForURL(u=>u.pathname==='/semantic-map');await page.locator('#detail-title').getByText('parser-case-00',{exact:false}).waitFor();
 await page.getByRole('link',{name:'Back to Investigation',exact:true}).click();dialog=page.locator('.ii-dialog');await dialog.getByRole('link',{name:'Open this case on the map',exact:true}).waitFor();assert.equal(await dialog.locator('.ii-receipt').count(),1);assert.equal(new URL(page.url()).searchParams.get('evidence_scope'),'task');
 // Work recurrences keep their own native input and feedback comparison.
 await page.goto(saved);await page.locator(`[data-monitor-id="${fixture.monitors.revisit}"]`).getByRole('button',{name:'Inspect reference Changed repeated attempts',exact:true}).click();
 dialog=page.locator('.ii-dialog');row=dialog.locator(`[data-value-id="${fixture.values.revisit.value}"]`);await row.locator(':scope > summary').click();await row.getByRole('button',{name:'Inspect saved evidence',exact:true}).click();await row.getByRole('link',{name:'Open this case on the map',exact:true}).click();
 await page.getByRole('heading',{name:'Recorded inputs: unchanged',exact:true}).waitFor();assert.equal(await page.locator('#map-error').isVisible(),false);
 await page.setViewportSize({width:390,height:844});await page.locator('#map-inspector').screenshot({path:path.join(root,'revisit-case-mobile.png')});
 await page.getByRole('link',{name:'Back to Investigation',exact:true}).click();dialog=page.locator('.ii-dialog');await dialog.getByRole('link',{name:'Open this case on the map',exact:true}).waitFor();assert.equal(await dialog.evaluate(n=>n.scrollWidth>n.clientWidth+2),false);await dialog.screenshot({path:path.join(root,'evidence-mobile.png')});
 // A stale/nonexistent case never opens another case as a substitute.
 const wrong=new URL(href,base);wrong.searchParams.set('measure_case','analysis:missing');await page.goto(wrong.href);await page.getByText('The requested case is not present in this saved measurement.',{exact:true}).waitFor();
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(root,'browser-report.json'),JSON.stringify({passed:true,fixture:'Two 105-dispatch authored check sequences plus two annotated repeated-work sequences; no inference',checks:['35-case pagination','exact recovery case map','highlighted evidence','reload retains case','back restores receipt and page','status and text filters','source-clock interval return','repeated input/feedback inspection','390px layout','missing case stays explicit'],errors},null,2));console.log('Measured-case navigation browser checks passed');
 }catch(e){if(page){await page.screenshot({path:path.join(root,'failure.png')});fs.writeFileSync(path.join(root,'failure.html'),await page.content());}throw e;}
 finally{if(browser)await browser.close();server.stdin.end();await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
