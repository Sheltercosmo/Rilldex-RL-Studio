const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn}=require('child_process'),path=require('path'),fs=require('fs'),assert=require('node:assert/strict');
const root=process.env.RILLDEX_UI_OUTPUT,py=process.env.RILLDEX_TEST_PYTHON;
const processServer=spawn(py,['-I','-u',path.join(__dirname,'../scripts/validate_sb3_capture.py'),'--serve',path.join(root,'workspace.sqlite')],{cwd:require('os').tmpdir(),windowsHide:true,stdio:['pipe','pipe','pipe']});
let output='';processServer.stdout.on('data',d=>output+=d);processServer.stderr.on('data',d=>output+=d);
(async()=>{
 let browser,page;const errors=[],queries=[];
 try{
  const deadline=Date.now()+30000;while(!/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/.test(output)){if(processServer.exitCode!==null||Date.now()>deadline)throw Error(output);await new Promise(r=>setTimeout(r,100));}
  const url=output.match(/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/)[1];browser=await chromium.launch({headless:true,channel:'msedge'});
  page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true});page.on('pageerror',e=>errors.push(e.message));
  page.on('response',async r=>{if(r.url().includes('/api/trainer-telemetry/query?')&&r.ok())queries.push(await r.json());});
  const board=page.locator('#trainer-telemetry'),session=board.getByRole('combobox',{name:'Session',exact:true});
  const settled=async()=>{await board.locator('svg').first().waitFor();await page.waitForFunction(()=>!document.querySelector('#trainer-telemetry')?.hasAttribute('aria-busy'));};
  await page.goto(url+'/?view=health&experiment=session-history');await settled();
  assert.match(await board.innerText(),/Session 120 · worker-2/);assert.match(await board.innerText(),/64 of 81 metric series/);
  for(const group of ['reward','loss','entropy','kl','clipping','tokens'])assert.equal(await board.locator(`[data-signal-group="${group}"] svg`).count(),1);
  await board.getByRole('button',{name:'Browse all 120 sessions',exact:true}).click();
  let picker=page.getByRole('dialog',{name:'Trainer sessions'});await picker.getByText('120 matching sessions · 20 shown',{exact:true}).waitFor();
  await picker.getByRole('button',{name:'Next',exact:true}).click();await picker.getByText('Session 100 · worker-0',{exact:true}).waitFor();
  await picker.getByRole('searchbox',{name:'Search sessions'}).fill('phase-001');await picker.getByRole('button',{name:'Search',exact:true}).click();
  await picker.getByText('3 matching sessions · 3 shown',{exact:true}).waitFor();
  await picker.locator('.telemetry-catalog-row').filter({hasText:'Session 5 · worker-1'}).getByRole('button',{name:'Use session',exact:true}).click();
  await settled();assert.equal(await session.inputValue(),JSON.stringify(['worker-1','phase-001']));assert.match(await board.innerText(),/Session 5 · worker-1/);
  await page.reload();await settled();assert.equal(await session.inputValue(),JSON.stringify(['worker-1','phase-001']));
  await board.getByRole('spinbutton',{name:'From step'}).fill('4');await board.getByRole('spinbutton',{name:'To step'}).fill('7');await board.getByRole('button',{name:'Select interval',exact:true}).click();await settled();
  assert.match(await board.innerText(),/4 \/ 16 logs in interval/);
  await board.locator('.telemetry-options > summary').click();
  await board.getByRole('button',{name:'Export comparison',exact:true}).click();
  let dialog=page.getByRole('dialog',{name:'Export training signals'});const download=page.waitForEvent('download');await dialog.getByRole('link',{name:'Download original JSONL · session-history'}).click();
  const file=await download,packets=fs.readFileSync(await file.path(),'utf8').trim().split('\n').map(JSON.parse);
  assert.equal(packets.length,4);assert.ok(packets.every(p=>p.producer==='worker-1'&&p.records[0].session==='phase-001'));assert.deepEqual(packets.map(p=>p.records[0].step),[4,5,6,7]);
  await dialog.getByRole('button',{name:'Close',exact:true}).click();
  const arrival=JSON.parse(fs.readFileSync(path.join(root,'arrival.json'),'utf8'));const posted=await page.request.post(url+'/api/trainer-telemetry',{data:arrival});assert.ok(posted.ok(),await posted.text());
  await board.getByRole('combobox',{name:'Trend',exact:true}).selectOption('10');await settled();assert.match(await board.innerText(),/4 \/ 16 logs in interval/);
  assert.equal(await board.getByRole('button',{name:'Browse all 120 sessions',exact:true}).count(),1);
  await session.selectOption('');await settled();assert.match(await board.innerText(),/Session 120 · worker-2/);
  await board.getByRole('button',{name:'Resume updates',exact:true}).click();await settled();assert.match(await board.innerText(),/Session 121 · worker-0/);
  await board.getByRole('combobox',{name:'Compare run',exact:true}).selectOption('session-baseline');await settled();
  const reference=board.getByRole('combobox',{name:'Session · session-baseline',exact:true});await reference.waitFor();
  const referenceFirst=await reference.locator('option').nth(1).getAttribute('value');await reference.selectOption(referenceFirst);await settled();
  assert.equal(await session.inputValue(),'');assert.match(await board.innerText(),/Session 121 · worker-0/);
  await page.reload();await settled();assert.equal(await reference.inputValue(),referenceFirst);
  assert.ok(queries.some(q=>q.experiment==='session-baseline'&&q.session_selection.selected?.session==='baseline-0'));
  await page.screenshot({path:path.join(root,'session-comparison-desktop.png')});
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);
  await board.getByRole('button',{name:'Browse all 121 sessions',exact:true}).click();picker=page.getByRole('dialog',{name:'Trainer sessions'});await picker.getByText('121 matching sessions · 20 shown',{exact:true}).waitFor();
  assert.equal(await picker.evaluate(d=>d.scrollWidth>d.clientWidth+2),false);await page.screenshot({path:path.join(root,'sessions-mobile.png')});await picker.getByRole('button',{name:'Close',exact:true}).click();
  await page.goto(url+'/?'+new URLSearchParams({view:'health',experiment:'session-history',signals_session:JSON.stringify(['missing-worker','missing-session'])}));
  await session.waitFor();await page.waitForFunction(()=>!document.querySelector('#trainer-telemetry')?.hasAttribute('aria-busy'));
  assert.equal(await board.locator('.telemetry-card').count(),0);assert.match(await board.innerText(),/selected worker\/session has no records/i);
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(root,'browser-report.json'),JSON.stringify({passed:true,checks:['newest session beyond chart limit','all core metric families present','session paging and search','old session reload','exact worker/session export','frozen late arrival','resume newest session','independent reference session','mobile overflow','absent selection stays empty'],errors},null,2));
  console.log('Session browser checks passed');
 }catch(e){if(page){await page.screenshot({path:path.join(root,'failure.png')});fs.writeFileSync(path.join(root,'failure.html'),await page.content());}throw e;}
 finally{if(browser)await browser.close();processServer.stdin.end();}
})().catch(e=>{console.error(e);process.exitCode=1;});
