const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn}=require('child_process'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=process.env.RILLDEX_UI_OUTPUT,py=process.env.RILLDEX_TEST_PYTHON;fs.mkdirSync(root,{recursive:true});
const server=spawn(py,['-I','-u',path.join(__dirname,'trainer_case_fixture.py'),root],{cwd:require('os').tmpdir(),windowsHide:true,stdio:['pipe','pipe','pipe']});
let output='';server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
(async()=>{let browser,page;const errors=[];try{
 const deadline=Date.now()+40000;while(!/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/.test(output)){if(server.exitCode!==null||Date.now()>deadline)throw Error(output);await new Promise(r=>setTimeout(r,100));}
 const base=output.match(/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/)[1],fixture=JSON.parse(fs.readFileSync(path.join(root,'fixture.json'),'utf8'));
 browser=await chromium.launch({headless:true,channel:'msedge'});page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/?'+new URLSearchParams({view:'health',experiment:fixture.experiment,signals_from:128,signals_to:255}));
 const panel=page.locator('.telemetry-card[data-signal-group="loss"]');await panel.getByRole('button',{name:'Compare linked rollouts',exact:true}).click();
 let dialog=page.getByRole('dialog',{name:'Compare linked rollouts',exact:true});
 assert.equal(await dialog.getByRole('spinbutton',{name:'Selected first step',exact:true}).inputValue(),'128');
 assert.equal(await dialog.getByRole('spinbutton',{name:'Reference last step',exact:true}).inputValue(),'127');
 await dialog.screenshot({path:path.join(root,'setup-desktop.png')});
 await dialog.getByRole('button',{name:'Save linked comparison',exact:true}).click();await page.waitForURL(u=>u.pathname==='/investigate'&&u.searchParams.has('saved'));
 const savedUrl=page.url(),savedId=new URL(savedUrl).searchParams.get('saved');
 await page.getByText('Improved reported outcome',{exact:true}).last().waitFor();
 const doc=await(await page.request.get(base+'/api/investigations/'+savedId)).json();
 assert.deepEqual(doc.snapshot.population,{baseline:[fixture.sources.before],current:[fixture.sources.after]});
 assert.deepEqual(doc.snapshot.trainer_selection.shared_run_ids,[fixture.sources.shared]);
 assert.equal(doc.snapshot.trainer_selection.cohorts.current.records,128);
 assert.ok(doc.snapshot.trainer_selection.cohorts.current.references.not_joined_to_selection>0);
 await page.locator('#investigation-app').screenshot({path:path.join(root,'comparison-desktop.png')});
 await page.getByRole('button',{name:'Compare evidence',exact:true}).click();
 dialog=page.locator('.case-dialog');await dialog.getByRole('link',{name:'Open behavior map →',exact:true}).first().waitFor();
 await dialog.getByRole('link',{name:'Open behavior map →',exact:true}).first().click();await page.waitForURL(u=>u.pathname==='/semantic-map');
 const map=new URL(page.url());assert.equal(map.searchParams.get('run'),fixture.sources.before);assert.ok(map.searchParams.get('graph'));assert.ok(map.searchParams.get('return_to').includes(savedId));
 await page.goto(base+map.searchParams.get('return_to'));await page.locator('.case-dialog').getByRole('button',{name:'Close',exact:true}).click();
 await page.getByRole('link',{name:'Back to training chart',exact:true}).click();await page.waitForURL(u=>u.pathname==='/'&&u.searchParams.has('signals_cutoffs'));
 const chartUrl=new URL(page.url());assert.equal(chartUrl.searchParams.get('signals_from'),'128');assert.equal(chartUrl.searchParams.get('signals_to'),'255');
 await panel.getByRole('button',{name:'Compare linked rollouts',exact:true}).waitFor();
 // Save another capture on a narrow viewport; the form must remain operable.
 await page.setViewportSize({width:390,height:844});await panel.getByRole('button',{name:'Compare linked rollouts',exact:true}).click();
 dialog=page.getByRole('dialog',{name:'Compare linked rollouts'});assert.equal(await dialog.evaluate(n=>n.scrollWidth>n.clientWidth+2),false);
 await dialog.screenshot({path:path.join(root,'setup-mobile.png')});await dialog.getByRole('button',{name:'Save linked comparison',exact:true}).click();await page.waitForURL(u=>u.pathname==='/investigate');
 await page.getByRole('link',{name:'Open reference map',exact:true}).waitFor();
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);
 await page.screenshot({path:path.join(root,'comparison-mobile.png'),fullPage:true});
 const beforeRecheck=new URL(page.url()).searchParams.get('saved');await page.getByRole('button',{name:'Recheck linked evidence',exact:true}).click();await page.waitForURL(u=>u.searchParams.get('saved')!==beforeRecheck);
 await page.getByRole('link',{name:'Open selected map',exact:true}).waitFor();
 const unchanged=await(await page.request.get(base+'/api/investigations/'+savedId)).json();assert.deepEqual(unchanged,doc);
 await page.goto(base+'/?'+new URLSearchParams({view:'health',experiment:fixture.experiment,signals_compare:'reference-without-links',signals_from:128,signals_to:255}));
 await panel.getByRole('button',{name:'Compare linked rollouts',exact:true}).click();dialog=page.getByRole('dialog',{name:'Compare linked rollouts'});
 assert.ok((await dialog.getByRole('combobox',{name:'Reference metric stream'}).locator('option:checked').textContent()).includes('reference-without-links'));
 assert.equal(await dialog.getByRole('spinbutton',{name:'Reference first step'}).inputValue(),'128');
 await dialog.getByRole('button',{name:'Save linked comparison',exact:true}).click();await page.waitForURL(u=>u.pathname==='/investigate');
 await page.getByRole('link',{name:'Add training-use links',exact:true}).waitFor();await page.getByRole('combobox',{name:'Selected rollout',exact:true}).selectOption(fixture.sources.after);await page.getByRole('link',{name:'Open selected map',exact:true}).waitFor();
 assert.equal(await page.getByRole('link',{name:'Open reference map',exact:true}).count(),0);
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(root,'browser-report.json'),JSON.stringify({passed:true,checks:['256-update authored stream','exact selected interval','partial and missing references','reused rollout separation','task comparison','pinned map drilldown','chart return with cutoff','mobile layout and save','explicit recheck','saved receipt unchanged','cross-run stream selection','missing-reference guidance and single-sided maps'],errors},null,2));
 console.log('Trainer-linked comparison browser checks passed');
 }catch(e){if(page){await page.screenshot({path:path.join(root,'failure.png')});fs.writeFileSync(path.join(root,'failure.html'),await page.content());}throw e;}
 finally{if(browser)await browser.close();server.stdin.end();await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
