const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn}=require('child_process'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=process.env.RILLDEX_UI_OUTPUT,py=process.env.RILLDEX_TEST_PYTHON;
const server=spawn(py,['-I','-u',path.join(__dirname,'workspace_picker_fixture.py'),root],{cwd:require('os').tmpdir(),windowsHide:true,stdio:['pipe','pipe','pipe']});
let output='';server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
(async()=>{let browser,page;const errors=[];try{
 const deadline=Date.now()+30000;while(!/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/.test(output)){if(server.exitCode!==null||Date.now()>deadline)throw Error(output);await new Promise(r=>setTimeout(r,100));}
 const base=output.match(/Rilldex: (http:\/\/127\.0\.0\.1:\d+)/)[1];browser=await chromium.launch({headless:true,channel:'msedge'});
 page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/connections#data-access-section');await page.getByRole('button',{name:'Switch workspace',exact:true}).click();
 let d=page.getByRole('dialog',{name:'Workspaces',exact:true});await d.getByRole('heading',{name:'Candidate study',exact:true}).waitFor();
 await d.screenshot({path:path.join(root,'picker-desktop.png')});
 await d.getByRole('searchbox',{name:'Find a workspace'}).fill('candidate');assert.equal(await d.locator('article').count(),1);
 await d.getByRole('button',{name:'Open Candidate study',exact:true}).click();await page.waitForURL(u=>u.origin!==base);
 const candidate=new URL(page.url()).origin;
 await page.getByRole('combobox',{name:'Project',exact:true}).waitFor();
 assert.match(await page.getByRole('combobox',{name:'Project',exact:true}).innerText(),/Candidate project/);
 assert.doesNotMatch(await page.getByRole('combobox',{name:'Project',exact:true}).innerText(),/Baseline project/);
 await page.waitForFunction(()=>[...document.querySelectorAll('select[aria-label="Saved comparisons"] option')].some(o=>o.textContent==='Candidate project comparison'));
 await page.getByRole('button',{name:'Switch workspace',exact:true}).click();d=page.getByRole('dialog',{name:'Workspaces'});
 await d.getByRole('button',{name:'Open Baseline study',exact:true}).click();await page.waitForURL(u=>u.origin===base&&u.hash==='#data-access-section');
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Switch workspace',exact:true}).click();d=page.getByRole('dialog',{name:'Workspaces'});
 await d.getByRole('heading',{name:'Candidate study',exact:true}).waitFor();assert.equal(await d.evaluate(n=>n.scrollWidth>n.clientWidth+2),false);
 await d.getByText('Open or create a workspace',{exact:true}).click();await d.getByLabel('Action',{exact:true}).selectOption('create');
 await d.getByLabel('Database path',{exact:true}).fill('new study.sqlite');await d.getByLabel('Workspace name',{exact:true}).fill('New study');
 await d.screenshot({path:path.join(root,'picker-mobile.png')});
 await d.locator('form button[type="submit"]').click();await page.waitForURL(u=>u.origin!==base&&u.origin!==candidate);
 assert.ok(fs.existsSync(path.join(root,'new study.sqlite')));
 await page.getByRole('button',{name:'Switch workspace',exact:true}).click();d=page.getByRole('dialog',{name:'Workspaces'});
 await d.getByRole('heading',{name:'New study',exact:true}).waitFor();
 await d.getByRole('button',{name:'Open Candidate study',exact:true}).click();await page.waitForURL(u=>u.origin===candidate);
 assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(root,'browser-report.json'),JSON.stringify({passed:true,desktop:[1440,1000],mobile:[390,844],checks:['sidebar picker','search by name','separate project lists','saved comparison isolation','restore previous view','mobile dialog and creation','return to running workspace'],errors},null,2));
 console.log('Workspace browser checks passed');
 }catch(e){if(page){await page.screenshot({path:path.join(root,'failure.png')});fs.writeFileSync(path.join(root,'failure.html'),await page.content());}throw e;}
 finally{if(browser)await browser.close();server.stdin.end();await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
