const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../tracker/web/monitoring.js'),'utf8');

function harness(api){
 const controls=new Map();
 const context=vm.createContext({Set,api,
  $:id=>{if(!controls.has(id))controls.set(id,{showModal(){}});return controls.get(id);},
  caseRequestSequence:0,caseRows:[],options:null,query:()=>'',metricValue:String,
  cohortLabel:s=>s.cohort.environment,renderCases(){},
 });
 // Execute the actual async dialog handler and filtering used by export/review.
 vm.runInContext(source.slice(source.indexOf('async function openCases('),source.indexOf('function addToolEvidence(')),context);
 return {context,controls};
}
const row=(id,value,step=0)=>({run:{id,metadata:{training_step:step}},measurement:{value}});
const rows=[row('terminal-pass',1),row('terminal-unknown',null),row('terminal-later',0,1),row('business-pass',1)];
const series={cohort:{environment:'terminal'},points:rows.slice(0,3).map(r=>({run_id:r.run.id}))};
const monitor={id:'m',name:'Retry success',kind:'metric',coverage:{available:3},series:[series]};

test('dashboard scope retains global monitors and excludes other saved populations on every rerender',()=>{
 const scope={experiment:'A',environment:'terminal'},c=vm.createContext({$:id=>({value:scope[id.slice(1)]})});
 vm.runInContext(source.slice(source.indexOf('function inDashboardScope('),source.indexOf("for(const id of ['monitor-search'")),c);
 assert.equal(c.inDashboardScope({}),true);
 assert.equal(c.inDashboardScope({population:{experiment:'A'}}),true);
 assert.equal(c.inDashboardScope({population:{experiment:'B'}}),false);
 assert.equal(c.inDashboardScope({population:{environment:'browser'}}),false);
 scope.experiment='';assert.equal(c.inDashboardScope({population:{experiment:'B'}}),true);
});

test('long-run headlines expose current missingness and measured population',()=>{
 const c=vm.createContext({});
 vm.runInContext(source.slice(source.indexOf('function headlineDetails('),source.indexOf('function cohortLabel(')),c);
 assert.equal(c.headlineDetails({step:63,n:0,unknown:8,value:null},true),
  'Step 63 · No measurement at this position · 0 / 8 rollouts measured');
 assert.equal(c.headlineDetails({step:20,n:6,unknown:2,value:.5,numerator:3,denominator:6},true),
  'Step 20 · 3 / 6 opportunities · 6 / 8 rollouts measured');
 assert.equal(c.headlineDetails({order:10,value:null},false),'Rollout 10 · No measurement at this position');
});

test('fraction plots keep a common scale, preserve gaps and resize without stretching text',()=>{
 class Node{
  constructor(tag,text){this.tag=tag;this.textContent=text;this.children=[];this.attrs={};this.namespaceURI='svg';}
  setAttribute(k,v){this.attrs[k]=v;} append(...nodes){this.children.push(...nodes);} replaceChildren(){this.children=[];}
 }
 let resizeCallback,disconnected=false,selectedStep;
 const c=vm.createContext({Set,Math,document:{createElementNS:(ns,tag)=>new Node(tag)},
  make:(tag,text)=>new Node(tag,text),$:()=>({value:'step'}),metricValue:String,
  openCases:(m,step)=>selectedStep=step,
  ResizeObserver:class{constructor(fn){resizeCallback=fn;}observe(){}disconnect(){disconnected=true;}},
 });
 vm.runInContext(source.slice(source.indexOf('function plot('),source.indexOf('function table(')),c);
 const host=c.plot({name:'Retry',unit:'fraction',aggregation:'opportunity_ratio'},
  {bins:[{step:0,value:.5,n:4},{step:1,value:null,n:0,unknown:4},{step:2,value:.25,n:4}]});
 const svg=host.children.find(n=>n.tag==='svg');
 assert.match(svg.attrs['aria-label'],/training step; Enter opens contributing rollouts/);
 assert.ok(svg.children.some(n=>n.tag==='text'&&n.textContent==='100%'));
 const line=svg.children.find(n=>n.tag==='path');
 assert.equal((line.attrs.d.match(/M/g)||[]).length,2,'unknown step must break the line');
 resizeCallback([{contentRect:{width:1000,height:200}}]);
 assert.equal(svg.attrs.viewBox,'0 0 1000 200');
 assert.ok(svg.children.filter(n=>n.tag==='text').every(n=>!n.attrs.transform));
 assert.ok(svg.children.filter(n=>n.tag==='circle').every(n=>n.attrs.r===3));
 const press=key=>svg.onkeydown({key,preventDefault(){}});
 press('Home');press('Enter');assert.equal(selectedStep,0);
 press('End');press('Enter');assert.equal(selectedStep,2);
 host.dispose();assert.equal(disconnected,true);
});

test('step drilldown keeps the chart cohort for values, missing cases and review/export',async()=>{
 const {context:c,controls}=harness(async()=>({rows}));
 await c.openCases(monitor,0,null,null,series);
 assert.deepEqual(Array.from(c.filteredCases(),r=>r.run.id),['terminal-pass']);
 controls.get('#cases-filter').value='unknown';
 assert.deepEqual(Array.from(c.filteredCases(),r=>r.run.id),['terminal-unknown']);
 controls.get('#cases-filter').value='all';
 assert.deepEqual(Array.from(c.filteredCases(),r=>r.run.id),['terminal-pass','terminal-unknown']);
 assert.equal(c.caseCohort.environment,'terminal');
 assert.match(controls.get('#cases-note').textContent,/training step 0 · terminal/);
 await c.openCases(monitor);
 assert.equal(c.caseCohort,null);
 assert.equal(c.filteredCases().length,3,'population-wide inspect remains population-wide');
});

test('a slower previous cohort request cannot replace a newer selection',async()=>{
 const pending=[];
 const {context:c}=harness(()=>new Promise(resolve=>pending.push(resolve)));
 const previous=c.openCases(monitor,0,null,null,series);
 const current=c.openCases(monitor,0,null,null,{cohort:{environment:'business'},points:[{run_id:'business-pass'}]});
 pending[1]({rows});await current;
 pending[0]({rows});await previous;
 assert.deepEqual(Array.from(c.filteredCases(),r=>r.run.id),['business-pass']);
});
