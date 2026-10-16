const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const code=fs.readFileSync(require.resolve('../tracker/web/population-evidence.js'),'utf8');
class Node{constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.dataset={};}append(...children){this.children.push(...children);}replaceChildren(...children){this.children=children;}setAttribute(k,v){this.attributes[k]=v;}scrollIntoView(){}}
function harness(){const c=vm.createContext({window:{},location:{pathname:'/',search:'?view=health'},URLSearchParams,document:{createElement:tag=>new Node(tag),createElementNS:(ns,tag)=>new Node(tag)}});vm.runInContext(code,c);return c.window.PopulationEvidence;}
function text(node){return [node.textContent||'',...node.children.map(text)].join(' ');}

test('coverage transforms preserve source and receipt identities without rewriting metric values',()=>{
 const api=harness(),s={cohort:{environment:'terminal'},points:[{run_id:'a',value:0,value_id:'v1'},{run_id:'b',value:null,value_id:null}],bins:[{step:1,value:0,readiness:{measurement_coverage:.5}}]};
 const result=api.coverageSeries(s);assert.deepEqual(Array.from(result.points,p=>p.value),[1,0]);
 assert.equal(result.bins[0].value,.5);assert.equal(result.points[0].value_id,'v1');
 assert.equal(s.points[0].value,0);assert.equal(s.points[1].value,null);assert.equal(s.bins[0].value,0);
});
test('missing lifecycle instrumentation remains explicit rather than displaying zero running jobs',()=>{
 const node=harness().executionContext({available:true,observed_attempts:0,groups:[],experiment:'x'});
 assert.match(text(node),/no lifecycle reports/);assert.match(text(node),/cannot reveal unreported or queued work/);
 assert.doesNotMatch(text(node),/0 unfinished/);
 assert.match(node.children.at(-1).href,/analysis_table=executions/);
});
test('comparison keeps execution scope and source measurement state distinct',()=>{
 const api=harness();assert.match(api.readinessText({measured:2,observed:8,unfinished:3,completed_unmeasured:2,imported_unmeasured:1,failed_capture:0}),/2\/8.*3 unfinished.*3 arrived/);
 const node=api.review({scope:{experiment:'x',environment:'terminal'},review:[{title:'Unfinished',evidence:'3 captures',next_check:'Inspect tasks'}]});
 assert.match(text(node),/Undeclared workload remains unknown/);assert.match(text(node),/Inspect tasks/);
 assert.ok(node.children.at(-1).children.every(a=>a.href.includes('experiment=x')&&a.href.includes('environment=terminal')));
});

const cohort=(id,index,extra={})=>({id,producer:'scheduler',label:'Batch '+index,coordinate:{clock:'generation',basis:'batch',index},context:{environment:'terminal'},declared:4,complete_captures:2,sealed:true,generation_states:{admitted:2},outcome_support:{observed_rate:.5,known:2,declared:4,unknown:2,lower:.25,upper:.75,complete:false,coverage:.5},outcome_selection:[{field:'task_id',groups:[{value:'short',known:2,declared:2,declared_share:.5,observed_share:1,success_rate:.5},{value:'long',known:0,declared:2,declared_share:.5,observed_share:0,success_rate:null}]}],...extra});
function find(node,tag){return [node,...node.children.flatMap(n=>find(n,tag))].filter(n=>n.tag===tag);}
test('readiness makes incomplete task mix and logical bounds visible without claiming confidence',()=>{
 const node=harness().outcomeReadiness({experiment:'x',cohorts:[cohort('a',4)]});
 assert.match(text(node),/2 \/ 4 outcomes known/);assert.match(text(node),/25.0%–75.0%/);assert.match(text(node),/not a confidence interval/);
 assert.match(text(node),/short/);assert.match(text(node),/long/);assert.match(text(node),/provisional/);
 const point=find(node,'circle')[0];assert.equal(point.attributes.fill,'white');assert.equal(point.attributes.role,'button');
});
test('unknown scheduled membership is not shown as zero pending work',()=>{
 const node=harness().outcomeReadiness({cohorts:[]});assert.match(text(node),/cannot reveal work still pending/);assert.equal(find(node,'svg').length,0);
});
test('readiness selection survives live refresh and stays scoped to its generation stream',()=>{
 const api=harness(),a=cohort('a',1),b=cohort('b',2),node=api.outcomeReadiness({experiment:'x',cohorts:[a,b]});
 const selector=find(node,'select')[1];selector.value='a';selector.onchange();
 const refreshed=api.outcomeReadiness({experiment:'x',cohorts:[a,b,cohort('c',3)]});
 assert.equal(find(refreshed,'select')[1].value,'a');
 const other=api.outcomeReadiness({experiment:'y',cohorts:[a,b]});assert.equal(find(other,'select')[1].value,'b');
});
test('different generation clocks are not connected in one curve',()=>{
 const api=harness(),node=api.outcomeReadiness({experiment:'x',cohorts:[cohort('a',1),cohort('b',2,{coordinate:{clock:'other',basis:'batch',index:2}})]});
 assert.equal(find(node,'select')[0].children.length,2);assert.equal(find(node,'circle').length,1);
});

test('cohort inspection exposes paired outcomes immediately while retaining source links',()=>{
 const r={...cohort('a',1),windows:[],generation_states:{admitted:0,completed:1},delivered:1,declared:1,complete_captures:1,task_mix:[],success_available:1,reward_available:1,verified_success_rate:0,recorded_reward_mean:1,members:[{producer:'p',rollout_id:'r',run_id:'run-a',context:{task_id:'task'},attempts:[],generation_state:'completed',source_status:'delivered',coordinate_alignment:'matching',outcome:{verified_success:false,recorded_reward:1},measurement_status:'not_requested'}]};
 const node=harness().declaredCohorts({experiment:'x',available:true,distinct_declared_rollouts:1,distinct_delivered_rollouts:1,cohorts:[r]},{inspectMembers:true});
 assert.match(text(node),/Verified failure · reward 1/);
 assert.ok(find(node,'a').some(a=>a.href.includes('run=run-a')));
});
