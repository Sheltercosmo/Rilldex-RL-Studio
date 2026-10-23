const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn}=require('child_process'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=process.env.RILLDEX_UI_OUTPUT;fs.mkdirSync(root,{recursive:true});
const server=spawn(process.env.RILLDEX_TEST_PYTHON,['-I','-u',path.join(__dirname,'approach_distribution_fixture.py'),root],{cwd:require('os').tmpdir(),windowsHide:true,stdio:['pipe','pipe','pipe']});
let output='';server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
(async()=>{let browser,page;const errors=[];try{
 const deadline=Date.now()+60000;while(!/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/.test(output)){if(server.exitCode!==null||Date.now()>deadline)throw Error(output);await new Promise(r=>setTimeout(r,100));}
 const base=output.match(/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/)[1];browser=await chromium.launch({headless:true,channel:'msedge'});page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));
 const params={view:'strategies',lens:'procedure',observer:'test',experiment:'approach-followup-controls',a_start:0,a_end:2,b_start:3,b_end:5};
 await page.goto(base+'/?'+new URLSearchParams(params));const panel=page.getByRole('region',{name:'Approaches after an error',exact:true});await panel.waitFor();
 const captureStyle='header.workspace-bar, .workspace .skip-link { visibility: hidden !important; }';
 await panel.screenshot({path:root+'/after-error-desktop.png',style:captureStyle});
 const before=panel.locator('[data-category="same_procedure"][data-window="earlier"]');
 await before.locator('.bd-followup-bar button').click();assert.equal(new URL(page.url()).searchParams.get('case_report'),'reported_again');
 await before.getByRole('button',{name:'Same procedure · Earlier · Error reported again · 16 of 16 pairs',exact:true}).click();
 let evidence=page.locator('.bd-evidence');await evidence.getByText('1–12 of 16 cases',{exact:true}).waitFor();
 assert.equal(new URL(page.url()).searchParams.get('case_report'),'reported_again');
 await evidence.getByRole('button',{name:'Next cases',exact:true}).click();await evidence.getByText('13–16 of 16 cases',{exact:true}).waitFor();
 const download=page.waitForEvent('download');await evidence.getByRole('button',{name:'Export matching cases',exact:true}).click();await(await download).saveAs(root+'/selected-cases.json');
 const exported=JSON.parse(fs.readFileSync(root+'/selected-cases.json','utf8'));assert.equal(exported.cases.length,16);assert.equal(exported.filters.report,'reported_again');assert.ok(exported.cases.every(c=>c.error_followup.category==='reported_again'));
 const savedURL=page.url();await page.reload();await evidence.getByText('13–16 of 16 cases',{exact:true}).waitFor();
 await evidence.locator('.bd-evidence-case>a').first().click();await page.locator('#map-inspector .wr-executor-followup').getByText('Error reported again',{exact:true}).waitFor();assert.deepEqual(Object.fromEntries(new URL(new URL(page.url()).searchParams.get('return_to'),base).searchParams),Object.fromEntries(new URL(savedURL).searchParams));
 assert.equal(new URL(page.url()).searchParams.get('work_episode'),exported.cases[12].episode.id);
 await page.locator('#workspace-back').click();await evidence.getByText('13–16 of 16 cases',{exact:true}).waitFor();
 const missing=panel.locator('[data-category="unknown"][data-window="later"]');await missing.locator('.bd-followup-choice').filter({hasText:'Unresolved'}).click();await evidence.locator('.bd-evidence-case').first().waitFor();assert.equal(await evidence.locator('.bd-evidence-case').count(),1);
 await evidence.getByRole('combobox',{name:'Response after attempt',exact:true}).selectOption('');assert.equal(new URL(page.url()).searchParams.has('case_report'),false);
 await page.getByRole('combobox',{name:'Weighting',exact:true}).selectOption('opportunity');await page.waitForFunction(()=>document.querySelector('.bd-followup')?.textContent.includes('Within each approach, pairs with a reported earlier error.'));
 assert.equal((await panel.locator('[data-category="reconfigured_procedure"][data-window="later"] .no_reported_error strong').textContent()),'50.0%');
 await page.setViewportSize({width:390,height:844});assert.equal(await panel.evaluate(n=>n.scrollWidth>n.clientWidth+1),false);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);await panel.screenshot({path:root+'/after-error-mobile.png',style:captureStyle});
 const replays=JSON.parse(fs.readFileSync(root+'/public-replay.json','utf8'));
 await page.setViewportSize({width:1440,height:1000});
 for(const replay of replays){
  await page.goto(base+'/?'+new URLSearchParams({view:'strategies',lens:'procedure',observer:replay.observer,population_mode:'task_mix',experiment:'',case_window:'all'}));await panel.waitFor();
  const api=await page.request.get(base+'/api/behavior-distributions?'+new URLSearchParams({lens:'procedure',observer:replay.observer,population_mode:'task_mix'}));const d=await api.json();
  assert.equal(d.approach_followup.overall.total,replay.total);
  for(const row of d.approach_followup.overall.rows)for(const [status,count]of Object.entries(row.counts))if(count){
   await panel.locator(`[data-category="${row.id}"]`).getByRole('button',{name:`${row.label} · Whole cohort · ${status==='reported_again'?'Error reported again':status==='no_reported_error'?'No error reported in later response':'Later report unresolved'} · ${count} of ${row.total} pairs`,exact:true}).click();
   assert.equal(await evidence.locator('.bd-evidence-case').count(),Math.min(count,12));
   const selection=page.waitForEvent('download');await evidence.getByRole('button',{name:'Export matching cases',exact:true}).click();const file=root+'/public-'+replay.observer+'-'+row.id+'-'+status+'.json';await(await selection).saveAs(file);
   const saved=JSON.parse(fs.readFileSync(file,'utf8'));assert.equal(saved.cases.length,count);assert.ok(saved.cases.every(c=>c.category===row.id&&c.error_followup.category===status));
  }
  await panel.screenshot({path:root+'/public-'+(replay.counts.reported_again?'software':'airline')+'.png',style:captureStyle});
 }
 assert.deepEqual(errors,[]);fs.writeFileSync(root+'/browser-report.json',JSON.stringify({passed:true,provider_calls:0,public_replays:replays,checks:['conditional distribution','unresolved denominator','exact cell drilldown','pagination','export all pages','reload and map back navigation','weighting','390px layout','retained public source pairs'],errors},null,2));console.log('Approach distribution browser checks passed');
 }catch(e){if(page){await page.screenshot({path:root+'/failure.png'});fs.writeFileSync(root+'/failure.html',await page.content());}throw e;}
 finally{if(browser)await browser.close();server.stdin.end();await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
