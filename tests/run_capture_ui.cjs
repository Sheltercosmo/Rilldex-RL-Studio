const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn}=require('child_process');const fs=require('fs');const path=require('path');
const root=process.env.RILLDEX_UI_OUTPUT||fs.mkdtempSync(path.join(require('os').tmpdir(),'rilldex-ui-')),py=process.env.RILLDEX_TEST_PYTHON||'python';
const server=spawn(py,['-I','-u',path.join(__dirname,'run_capture_fixture.py'),root],{cwd:require('os').tmpdir(),windowsHide:true,stdio:['pipe','pipe','pipe']});
let output='';server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
(async()=>{
 let browser;
 try{
  const start=Date.now();while(!/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/.test(output)){if(server.exitCode!==null||Date.now()-start>30000)throw Error(output);await new Promise(r=>setTimeout(r,100));}
  const url=output.match(/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/)[1];browser=await chromium.launch({headless:true,channel:'msedge'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.locator('#experiment-browser').waitFor({state:'visible'});
  await page.getByRole('combobox',{name:'Project',exact:true}).selectOption('product-check');
  await page.getByRole('button',{name:'Run details',exact:true}).first().click();
  const dialog=page.getByRole('dialog',{name:'Run details',exact:true});await dialog.getByText('Configuration',{exact:true}).waitFor();
  await dialog.getByRole('button',{name:'Logs',exact:true}).click();await dialog.locator('.capture-console').first().waitFor();
  await dialog.getByRole('searchbox',{name:'Search captured records'}).fill('timeout');await dialog.getByRole('button',{name:'Search',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.capture-console pre')?.textContent.includes('timeout'));
  if(await dialog.locator('.capture-console').count()!==1)throw Error('Console search mismatch');
  const capturedExperiment=await dialog.locator('.run-detail-head>div').getAttribute('title');
  await dialog.getByRole('button',{name:'Follow',exact:true}).click();
  const live=await page.request.post(url+'/api/run-records',{data:{schema:'run-records/1',producer:'worker-live',experiment:capturedExperiment,records:[{id:'new-console',session:'live-session',kind:'console',observed_at:new Date().toISOString(),payload:{stream:'stderr',text:'new timeout live'}}]}});if(!live.ok())throw Error(await live.text());
  await dialog.getByText('new timeout live',{exact:true}).waitFor({timeout:10000});
  await dialog.getByRole('button',{name:'Hardware',exact:true}).click();await dialog.locator('svg').first().waitFor();
  await page.screenshot({path:path.join(root,'hardware-desktop.png')});
  await dialog.getByRole('button',{name:'Files',exact:true}).click();await dialog.getByRole('link',{name:'Download',exact:true}).waitFor();
  await dialog.getByRole('button',{name:'Preview text',exact:true}).click();await dialog.locator('pre:visible').waitFor();
  await dialog.locator('input[type=file]').setInputFiles({name:'notes.txt',mimeType:'text/plain',buffer:Buffer.from('A real browser upload')});
  await dialog.getByRole('heading',{name:'notes.txt',exact:true}).waitFor();
  const download=page.waitForEvent('download');await dialog.locator('.run-detail-record').filter({has:page.getByRole('heading',{name:'notes.txt',exact:true})}).getByRole('link',{name:'Download',exact:true}).click();await(await download).saveAs(path.join(root,'download.txt'));
  if(fs.readFileSync(path.join(root,'download.txt'),'utf8')!=='A real browser upload')throw Error('Download differs');
  await dialog.getByRole('button',{name:'Close',exact:true}).click();
  await page.getByRole('button',{name:'Organize',exact:true}).first().click();
  const edit=page.locator('dialog[open]');await page.screenshot({path:path.join(root,'organize-debug.png')});fs.writeFileSync(path.join(root,'organize-debug.html'),await edit.innerHTML());await edit.getByLabel('Run name',{exact:true}).fill('Readable trial');await edit.getByLabel('Project · leave empty to unassign',{exact:true}).fill('review');await edit.getByLabel('Pin run',{exact:true}).check();await edit.getByRole('button',{name:'Save',exact:true}).click();await edit.waitFor({state:'detached'});
  await page.getByRole('combobox',{name:'Project',exact:true}).selectOption('review');await page.getByRole('link',{name:'★ Readable trial',exact:true}).waitFor();
  await page.getByRole('combobox',{name:'Project',exact:true}).selectOption('');await page.locator('#experiment-browser tbody input[data-has-logs=true]').nth(0).check();await page.locator('#experiment-browser tbody input[data-has-logs=true]').nth(1).check();
  await page.getByRole('button',{name:'Save selection',exact:true}).click();await page.locator('dialog[open] input').fill('Review pair');await page.locator('dialog[open]').getByRole('button',{name:'Save',exact:true}).click();await page.locator('dialog[open]').waitFor({state:'detached'});
  await page.reload();await page.getByRole('combobox',{name:'Saved comparisons'}).waitFor();await page.waitForFunction(()=>[...document.querySelectorAll('select[aria-label="Saved comparisons"] option')].some(x=>x.textContent==='Review pair'));
  const arrival=await page.request.post(url+'/api/run-records',{data:{schema:'run-records/1',producer:'fresh-worker',experiment:'capture-only',records:[{id:'new-manifest',session:'first-session',kind:'manifest',observed_at:new Date().toISOString(),payload:{name:'New console-only run',project:'new-project',config:{},runtime:{}}}]}});if(!arrival.ok())throw Error(await arrival.text());
  await page.waitForFunction(()=>[...document.querySelectorAll('#experiment option')].some(o=>o.value==='capture-only'&&o.textContent==='New console-only run'),{},{timeout:20000});
  await page.locator('#experiment-browser').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'experiments-desktop.png')});
  await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Run details',exact:true}).first().click();await page.getByRole('button',{name:'Hardware',exact:true}).click();await page.locator('dialog[open] svg').first().waitFor();
  const over=await page.evaluate(()=>({body:document.documentElement.scrollWidth>innerWidth+2,dialog:[...document.querySelectorAll('dialog[open]')].some(d=>d.scrollWidth>d.clientWidth+2)}));if(over.body||over.dialog)throw Error('Mobile overflow '+JSON.stringify(over));
  await page.screenshot({path:path.join(root,'hardware-mobile.png')});await page.locator('dialog[open]').getByRole('button',{name:'Close',exact:true}).click();
  const legacy=page.locator('#experiment-browser tr').filter({has:page.getByRole('link',{name:'Legacy run',exact:true})});await legacy.getByRole('button',{name:'Run details',exact:true}).click();await page.getByRole('button',{name:'Settings · 1',exact:true}).waitFor();await page.locator('dialog[open]').getByText('learning_rate',{exact:true}).waitFor();
  if(errors.length)throw Error(errors.join('\n'));
  fs.writeFileSync(path.join(root,'browser-result.json'),JSON.stringify({passed:true,desktop:[1440,1000],mobile:[390,844],checks:['project filtering','console search','hardware plots','text preview','file upload/download','organization edits','pinned run','saved comparison reload','mobile overflow'],errors},null,2));
  console.log('Browser checks passed',url);
 }finally{if(browser)await browser.close();server.stdin.end();}
})().catch(e=>{console.error(e);process.exitCode=1;});
