// Inspect the actual native-training artifact produced by validate_sb3_capture.py.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn}=require('child_process'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=process.env.RILLDEX_UI_OUTPUT,py=process.env.RILLDEX_TEST_PYTHON;
const report=JSON.parse(fs.readFileSync(path.join(root,'native-report.json'),'utf8'));
const server=spawn(py,['-I','-u',path.join(__dirname,'../scripts/validate_sb3_capture.py'),'--serve',path.join(root,'workspace.sqlite')],{cwd:require('os').tmpdir(),windowsHide:true,stdio:['pipe','pipe','pipe']});
let output='';server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
(async()=>{
 let browser;const errors=[];
 try{
  const deadline=Date.now()+30000;while(!/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/.test(output)){if(server.exitCode!==null||Date.now()>deadline)throw Error(output);await new Promise(r=>setTimeout(r,100));}
  const url=output.match(/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/)[1];browser=await chromium.launch({headless:true,channel:'msedge'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url+'/?view=health&experiment=native-control%2Fppo-cartpole');
  const board=page.locator('#trainer-telemetry');await board.locator('[data-signal-group="clipping"] svg').waitFor();
  assert.match(await board.innerText(),/8 logs/);assert.match(await board.innerText(),/environment_timesteps/);
  assert.doesNotMatch(await board.innerText(),/Not recorded in this clock:.*Policy mismatch/);
  const sessions=board.getByRole('combobox',{name:'Session',exact:true});await sessions.waitFor();
  assert.equal(await board.getByRole('spinbutton',{name:'From step'}).inputValue(),'2304');
  const firstSession=await sessions.locator('option').nth(1).getAttribute('value');
  assert.match(await sessions.locator('option').nth(1).innerText(),/Session 1 · native-cpu-worker · steps 256–2048/);
  await sessions.selectOption(firstSession);
  await page.waitForFunction(()=>document.querySelector('input[aria-label="From step"]')?.value==='256');
  assert.equal(await board.getByRole('spinbutton',{name:'To step'}).inputValue(),'2048');
  await page.reload();await sessions.waitFor();assert.equal(await sessions.inputValue(),firstSession);
  await sessions.selectOption('');await page.waitForFunction(()=>document.querySelector('input[aria-label="From step"]')?.value==='2304');
  const reward=board.locator('[data-signal-group="reward"]');assert.match(await reward.innerText(),/Episode return/);
  await reward.getByRole('button',{name:'Inspect updates',exact:true}).click();
  await page.getByRole('dialog',{name:'Recorded updates in interval'}).waitFor();
  await page.locator('.telemetry-log-list button').first().waitFor();
  await page.getByRole('dialog',{name:'Recorded updates in interval'}).getByRole('button',{name:'Close',exact:true}).click();
  await board.screenshot({path:path.join(root,'native-ppo-signals.png')});
  await page.goto(url+'/?view=health&experiment=native-control%2Fdqn-cartpole');
  await board.locator('[data-signal-group="loss"] svg').waitFor();
  assert.match(await board.innerText(),/DQN epsilon/);
  assert.equal(await board.locator('[data-signal-group="kl"]').count(),0);
  assert.doesNotMatch(await board.innerText(),/Not recorded in this clock/);
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);
  await board.screenshot({path:path.join(root,'native-dqn-mobile.png')});
  await page.setViewportSize({width:1440,height:1000});await page.goto(url);
  const row=page.locator('#experiment-browser tr').filter({has:page.getByRole('link',{name:'ppo-cartpole',exact:true})});
  await row.getByRole('button',{name:'Run details',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Run details',exact:true});await dialog.getByText('PPO',{exact:true}).first().waitFor();
  await dialog.getByRole('button',{name:'Logs',exact:true}).click();await dialog.getByText('Collected environment transitions: 4096',{exact:true}).waitFor();
  const workers=dialog.getByRole('combobox',{name:'Worker and session'});assert.equal(await workers.locator('option').count(),3);
  await dialog.getByRole('button',{name:'Files',exact:true}).click();await dialog.getByRole('heading',{name:'ppo-checkpoint.zip',exact:true}).waitFor();
  await dialog.getByRole('button',{name:'Hardware',exact:true}).click();await dialog.locator('svg').first().waitFor();
  await dialog.screenshot({path:path.join(root,'native-hardware.png')});
  await page.goto(url+'/semantic-map?'+new URLSearchParams({run:report.map_run,observer:'source',level:'units'}));
  await page.locator('#map-svg g').first().waitFor();assert.equal(await page.locator('#map-error').isVisible(),false);
  await page.locator('#map-viewport').screenshot({path:path.join(root,'native-source-map.png')});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(root,'browser-report.json'),JSON.stringify({passed:true,installed_package:true,errors,checks:['native PPO signals','native DQN defaults','no irrelevant mismatch prompt','shared session selection across charts','session selection survives reload','readable session labels','metric-to-update inspection','mobile width','shared run logs and sessions','checkpoint file','hardware','captured source map']},null,2));
  console.log('Native training UI passed',url);
 }catch(e){if(browser){const page=browser.contexts()[0]?.pages()[0];if(page){await page.screenshot({path:path.join(root,'ui-failure.png')});fs.writeFileSync(path.join(root,'ui-failure.html'),await page.content());}}throw e;}
 finally{if(browser)await browser.close();server.stdin.end();}
})().catch(e=>{console.error(e);process.exitCode=1;});
