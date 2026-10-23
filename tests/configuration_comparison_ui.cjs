const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn}=require('child_process'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=process.env.RILLDEX_UI_OUTPUT,py=process.env.RILLDEX_TEST_PYTHON;fs.mkdirSync(root,{recursive:true});
const server=spawn(py,['-I','-u',path.join(__dirname,'experiment_management_fixture.py'),root],{cwd:require('os').tmpdir(),windowsHide:true,stdio:['pipe','pipe','pipe']});
let output='';server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
(async()=>{let browser,page;const errors=[];try{
 const deadline=Date.now()+30000;while(!/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/.test(output)){if(server.exitCode!==null||Date.now()>deadline)throw Error(output);await new Promise(r=>setTimeout(r,100));}
 const base=output.match(/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/)[1];browser=await chromium.launch({headless:true,channel:'msedge'});
 page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base);const list=page.locator('#experiment-browser'),search=list.getByRole('searchbox',{name:'Search experiments'});
 await list.getByRole('combobox',{name:'Search in',exact:true}).selectOption('settings');await search.fill('adamw');
 await page.waitForFunction(()=>document.querySelectorAll('#experiment-browser tbody tr').length===30&&document.querySelector('.experiment-footer').textContent.includes('of 40'));
 await search.fill('not-captured');await page.waitForFunction(()=>document.querySelectorAll('#experiment-browser tbody tr').length===0);
 await list.getByRole('combobox',{name:'Search in',exact:true}).selectOption('labels');
 for(const id of ['01','02']){await search.fill('Seed '+id);await list.getByRole('checkbox',{name:'Select sweep/seed-'+id,exact:true}).check();}
 await list.getByRole('button',{name:'Compare settings',exact:true}).click();let d=page.getByRole('dialog',{name:'Compare settings',exact:true});
 await d.getByText('/sampling/temperature',{exact:true}).waitFor();assert.equal(await d.locator('tbody tr').count(),3);
 await d.screenshot({path:path.join(root,'settings-desktop.png')});
 const download=page.waitForEvent('download');await d.getByRole('button',{name:'Download snapshots',exact:true}).click();await(await download).saveAs(path.join(root,'settings.json'));
 const captured=JSON.parse(fs.readFileSync(path.join(root,'settings.json'),'utf8'));assert.equal(captured.runs[0].selected.config.seed,1);assert.equal(captured.runs[1].selected.config.seed,2);
 const late=await page.request.post(base+'/api/run-records',{data:{schema:'run-records/1',producer:'worker',experiment:'sweep/seed-01',records:[{id:'restart',session:'restart',kind:'manifest',observed_at:new Date().toISOString(),payload:{name:'Seed 01',project:'Baseline',config:{seed:999,learning_rate:1e-5},runtime:{}}}]}});assert.ok(late.ok(),await late.text());
 await d.getByRole('checkbox',{name:'Differences only',exact:true}).uncheck();await d.getByText('/eval_datasets',{exact:true}).waitFor();assert.equal(await d.locator('tbody tr').count(),9);
 let seedRow=d.locator('tbody tr').filter({has:page.getByText('/seed',{exact:true})});assert.deepEqual(await seedRow.locator('pre').allTextContents(),['1','2']);
 await page.setViewportSize({width:390,height:844});await d.screenshot({path:path.join(root,'settings-mobile.png')});
 assert.equal(await d.evaluate(n=>n.scrollWidth>n.clientWidth+2),false);
 await d.getByRole('searchbox',{name:'Find a setting or value'}).fill('temperature');await d.getByRole('button',{name:'Search',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('.configuration-table tbody tr').length===1);
 await d.getByRole('button',{name:'Open training curves',exact:true}).click();await page.waitForURL(u=>u.searchParams.has('settings_sources'));
 await page.locator('#trainer-telemetry').getByRole('button',{name:'Compare settings',exact:true}).click();d=page.getByRole('dialog',{name:'Compare settings'});
 await d.getByText('/seed',{exact:true}).waitFor();seedRow=d.locator('tbody tr').filter({has:page.getByText('/seed',{exact:true})});assert.deepEqual(await seedRow.locator('pre').allTextContents(),['1','2']);
 await d.getByRole('button',{name:'Refresh sources',exact:true}).click();await page.waitForFunction(()=>[...document.querySelectorAll('.configuration-table pre')].some(p=>p.textContent==='999'));
 await d.getByRole('combobox',{name:'Snapshot for Seed 01',exact:true}).selectOption(captured.runs[0].selected.id);
 await page.waitForFunction(()=>![...document.querySelectorAll('.configuration-table pre')].some(p=>p.textContent==='999'));
 const bad=await page.request.post(base+'/api/experiments/settings',{data:{experiments:['sweep/seed-01','sweep/seed-02'],unexpected:true}});assert.equal(bad.status(),400);
 assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(root,'browser-report.json'),JSON.stringify({passed:true,checks:['configuration search','selection to settings','typed nested differences','JSON snapshot download','late arrival holds source','mobile scrolling','field search','settings to curves and back','explicit refresh','older session selection','HTTP validation'],errors},null,2));
 console.log('Configuration comparison browser checks passed');
 }catch(e){if(page){await page.screenshot({path:path.join(root,'failure.png')});fs.writeFileSync(path.join(root,'failure.html'),await page.content());}throw e;}
 finally{if(browser)await browser.close();server.stdin.end();await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
