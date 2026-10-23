// Run after scripts/public_trainer_replay.py against its database.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.REVIEW_TEST_URL,output=process.env.REVIEW_OUTPUT_DIR;
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true});
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/?view=health&experiment=public-timechat-captioner-grpo&signals_smooth=10');
  const board=page.locator('#trainer-telemetry');
  await board.getByText('256 logs',{exact:true}).waitFor();
  const outcome=board.locator('[data-signal-group="reward"]');
  for(const [label,expected] of [['Outcome metric','Reward · train'],['Entropy metric','Mean completion entropy · train'],['Clipping & masking metric','Policy clipping region · train'],['Token usage metric','Completion length · train']]){
   assert.equal(await board.getByRole('combobox',{name:label,exact:true}).locator('option:checked').innerText(),expected);
  }
  assert.match(await outcome.innerText(),/256\/256 measured/);
  assert.match(await board.innerText(),/Not recorded in this clock: Policy mismatch, Throughput/);
  if(output)await outcome.screenshot({path:output+'/public-reward-desktop.png'});
  await outcome.getByRole('combobox',{name:'Outcome metric',exact:true}).selectOption({label:'Groups with no reward variation · train'});
  await outcome.getByText('Definition & sources',{exact:true}).click();
  assert.match(await outcome.innerText(),/not a filtering or failure rate/);
  await outcome.getByRole('combobox',{name:'Outcome metric',exact:true}).selectOption({label:'Reward · train'});
  await board.getByRole('spinbutton',{name:'From step'}).fill('100');
  await board.getByRole('spinbutton',{name:'To step'}).fill('120');
  await board.getByRole('button',{name:'Select interval',exact:true}).click();
  await board.getByText('21 / 256 logs in interval',{exact:true}).waitFor();
  await outcome.getByRole('button',{name:'Inspect updates',exact:true}).click();
  const updates=page.getByRole('dialog',{name:'Recorded updates in interval'});
  await updates.locator('.telemetry-log-list button').first().waitFor();
  assert.equal(await updates.locator('.telemetry-log-list button').count(),21);
  await updates.locator('.telemetry-log-list button').first().click();
  await page.getByText('No training-use references recorded. Add references in TrainerTelemetry.log() to enable rollout drill-down.',{exact:true}).waitFor();
  assert.equal(await page.getByRole('link',{name:/Open rollout/}).count(),0);
  await page.getByRole('dialog',{name:'Reward',exact:true}).getByRole('button',{name:'Close',exact:true}).click();
  await updates.getByRole('button',{name:'Close',exact:true}).click();
  await board.locator('.telemetry-options > summary').click();
  await board.getByRole('button',{name:'Export comparison',exact:true}).click();
  const exports=page.getByRole('dialog',{name:'Export training signals'}),download=page.waitForEvent('download');
  await exports.getByRole('link',{name:'Download original JSONL · public-timechat-captioner-grpo'}).click();
  const file=await download,records=fs.readFileSync(await file.path(),'utf8').trim().split('\n').map(JSON.parse);
  assert.equal(records.length,21);
  assert.deepEqual(records.map(p=>p.records[0].step),Array.from({length:21},(_,i)=>i+100));
  await exports.getByRole('button',{name:'Close',exact:true}).click();
  await page.reload();await board.getByText('21 / 256 logs in interval',{exact:true}).waitFor();
  await page.setViewportSize({width:390,height:900});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  if(output)await outcome.screenshot({path:output+'/public-reward-mobile.png'});
  assert.deepEqual(errors,[]);
  console.log('Passed public trainer UI: default signals, native definitions, 21-step selection, raw update inspection, absent rollout links, exact export, frozen reload and mobile layout.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
