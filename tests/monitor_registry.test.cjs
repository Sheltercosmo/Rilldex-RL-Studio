const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const source=fs.readFileSync(require.resolve('../tracker/web/monitoring.js'),'utf8');
const coverageSource=source.slice(source.indexOf('function coverageView('),source.indexOf('function download('));
const registrySource=source.slice(source.indexOf('function customDefinition('),source.indexOf('function renderRuns('));
const filterSource=source.slice(source.indexOf('function filterMonitors('),source.indexOf('function inDashboardScope('));
const presetSource=source.slice(source.indexOf('let presetOptionsSequence='),source.indexOf('function procedureCoverageText('));

test('presets load saved graph sources without first opening the monitor editor',async()=>{
 const nodes={'#monitor-presets':{open:true},'#monitor-questions':{},'#experiment':{value:'training'},'#environment':{value:'terminal'}};
 const calls=[],rendered=[],saved={graph_observers:[{id:'saved-graph',label:'Reviewed map'}],observers:[{id:'metric-only',label:'No graph'}]};
 const c=vm.createContext({$:id=>nodes[id],state:{monitors:[{id:'existing'}]},options:null,
  api:async path=>{calls.push(path);return saved;},load:async()=>{},
  IntervalInvestigation:{bundles:async(host,context)=>rendered.push({host,context})}});
 vm.runInContext(presetSource,c);await c.renderMonitorPresets();
 assert.deepEqual(calls,['/api/monitoring/options']);
 assert.equal(rendered[0].host,nodes['#monitor-questions']);
 assert.equal(rendered[0].context.observers,saved.graph_observers);
 assert.equal(rendered[0].context.experiment,'training');assert.equal(rendered[0].context.environment,'terminal');
});

test('stale preset option requests cannot overwrite a newer selection or reopen a closed library',async()=>{
 const nodes={'#monitor-presets':{open:true},'#monitor-questions':{},'#experiment':{value:'training'},'#environment':{value:''}},pending=[],rendered=[];
 const c=vm.createContext({$:id=>nodes[id],state:{monitors:[]},options:null,
  api:()=>new Promise(resolve=>pending.push(resolve)),load:async()=>{},
  IntervalInvestigation:{bundles:async(host,context)=>rendered.push(context.observers)}});
 vm.runInContext(presetSource,c);
 const old=c.renderMonitorPresets(),recent=c.renderMonitorPresets();
 const fresh=[{id:'fresh'}];pending[1]({graph_observers:fresh});await recent;
 pending[0]({graph_observers:[{id:'stale'}]});await old;
 assert.equal(rendered.length,1);assert.equal(rendered[0],fresh);
 const closed=c.renderMonitorPresets();nodes['#monitor-presets'].open=false;pending[2]({graph_observers:[]});await closed;
 assert.equal(rendered.length,1);
});

class Element{
 constructor(tag,text,cls){this.tag=tag;this.textContent=text??'';this.className=cls||'';this.children=[];this.options=[];this.style={};this.disabled=false;this.value='';}
 append(...items){this.children.push(...items);if(this.tag==='select')this.options.push(...items);}
 prepend(...items){this.children.unshift(...items);if(this.tag==='select')this.options.unshift(...items);}
 replaceChildren(...items){this.children=[...items];if(this.tag==='select')this.options=[...items];}
 setAttribute(){}
}

function harness(){
 const nodes=new Map();
 const context=vm.createContext({
  make:(tag,text,cls)=>new Element(tag,text,cls),opt:(value,label)=>{const option=new Element('option',label);option.value=value;return option;},
  $:id=>{if(!nodes.has(id))nodes.set(id,new Element('div'));return nodes.get(id);},
  state:{monitors:[]},options:{metrics:{},analysis_measures:{},observers:[],graph_observers:[]},view:'monitors',
  human:value=>String(value||'').replaceAll('_',' '),short:value=>String(value),failed:error=>{throw error;},
  configureKind:()=>{},applyPattern:()=>{},number:value=>String(value),
  URLSearchParams,location:{search:'',hash:'',href:''},history:{replaceState(){}},api:async()=>({added:[],existing:[]}),load:async()=>{},
 });
 vm.runInContext('let customGuideHashHandled=false;',context);vm.runInContext(coverageSource,context);vm.runInContext(registrySource,context);vm.runInContext(filterSource,context);
 context.$('#registry-search').value='';context.$('#monitor-group-filter').value='';context.$('#monitor-availability').value='all';context.$('#measure-count');
 return {context,nodes};
}

test('monitor registry renders compact cards with readable observer labels and safe custom actions',()=>{
 const {context:c,nodes}=harness();
 c.options.observers=[{id:'observer-private-hash',label:'Reviewed behavior map'}];
 c.state.monitors=[
  {id:'builtin',name:'Recorded reward',kind:'metric',metric:'recorded_reward',group:'Training',observer:'source',enabled:true,coverage:{available:8,population:10}},
  {id:'custom',name:'Review confidence',kind:'custom',description:'Reviewer supplied confidence.',observer:'observer-private-hash',enabled:true,custom:{version:'1',description:'Reviewer supplied confidence.',unit:'fraction',aggregation:'mean'},coverage:{available:3,population:10},feedback_counts:{info:9,warning:2,critical:1}},
  {id:'paused-snapshot',name:'Old measure',kind:'metric',metric:'recorded_reward',group:'Training',observer:'source',enabled:false},
 ];
 c.renderRegistry();
 const host=nodes.get('#monitor-table');
 assert.equal(host.children.length,3);
 assert.ok(host.children.every(card=>card.tag==='article'&&card.className==='registry-monitor'));
 assert.equal(host.children[0].children[0].children[0].children[0].textContent,'Review confidence','feedback needing attention is first');
 assert.match(host.children[0].children[0].children[2].children.map(tag=>tag.textContent).join(' '),/Reviewed behavior map/);
 assert.doesNotMatch(JSON.stringify(host.children[0]),/observer-private-hash/);
 const actionLabels=host.children[0].children[2].children.map(action=>action.textContent);
 assert.deepEqual(actionLabels,['View values','Show chart','Code setup','Pause']);
 assert.equal(host.children[0].children[1].children[2].textContent,'Feedback · 2 warning · 1 critical');
 assert.equal(host.children[1].children[2].children.some(action=>action.textContent==='Edit'),true);
 const pausedCoverage=host.children[2].children[1];
 assert.equal(pausedCoverage.children[0].textContent,'Paused · saved values retained');
 assert.equal(pausedCoverage.children.length,1,'no coverage count or bar is fabricated for an old paused snapshot');
});

test('coverage filters safely include paused snapshots with no coverage without inventing measured values',()=>{
 const {context:c,nodes}=harness();
 const paused={id:'paused',name:'Saved measure',enabled:false};
 nodes.get('#monitor-availability').value='all';
 assert.equal(c.filterMonitors([paused]).length,1);
 nodes.get('#monitor-availability').value='measured';
 assert.equal(c.filterMonitors([paused]).length,0);
 nodes.get('#monitor-availability').value='missing';
 assert.equal(c.filterMonitors([paused]).length,1);
 assert.equal(c.coverageView(paused).label,'Paused · saved values retained');
});

test('custom dashboard setup actions open the publisher guide instead of the monitor editor',()=>{
 const {context:c}=harness();c.view='overview';
 const action=c.monitorSetupAction({id:'custom',name:'Action review',kind:'custom',custom:{version:'1'}},'card-menu');
 assert.equal(action.textContent,'Code setup');
 action.onclick();
 assert.equal(c.location.href,'/monitors#custom-code');
});

test('custom guide hash is consumed after its first registry render',()=>{
 const {context:c}=harness();let opens=0;c.location.hash='#custom-code';c.openCustomCodeGuide=()=>opens++;
 c.state.monitors=[{id:'m',name:'Saved measure',enabled:false,coverage:null}];
 c.renderRegistry();c.renderRegistry();
 assert.equal(opens,1);
});

test('editor discovery searches registered measures and applies a semantic starter definition',()=>{
 const {context:c,nodes}=harness();
 c.options={
  metrics:{recorded_reward:{label:'Recorded reward',description:'Producer score.'},operation_failed_fraction:{label:'Failed operation share',description:'Fraction of failed outcomes.'},exploration_rate:{label:'Old exploration rate',description:'Legacy placeholder.'},plan_deviation_rate:{label:'Old plan deviation',description:'Legacy placeholder.'},recovery_rate:{label:'Old recovery rate',description:'Legacy placeholder.'},plan_completion_rate:{label:'Old plan completion',description:'Legacy placeholder.'}},
  analysis_measures:{returns:{label:'Work returns',description:'Observed returns.'}},
  observers:[],graph_observers:[{id:'reviewed-v2',label:'Reviewed observer'}],
  starter_catalog:[{id:'returns',name:'Returns after operations',question:'How often does work return?',kind:'analysis',measure:'returns',group:'Behavior',observer_requirement:'explicit_observer',definition:{name:'Returns after operations',kind:'analysis',group:'Behavior',observer:null,analysis:{measure:'returns'}}}],
 };
 c.$('#metric-catalog-search');c.$('#monitor-starters');c.$('#metric-catalog-results');c.$('#monitor-kind');c.$('#monitor-analysis');c.$('#monitor-name');c.$('#monitor-group');c.$('#monitor-observer');
 nodes.get('#metric-catalog-search').value='failed outcomes';
 c.renderMonitorDiscovery();
 assert.equal(nodes.get('#metric-catalog-results').children.length,1);
 assert.equal(nodes.get('#metric-catalog-results').children[0].children[0].textContent,'Failed operation share');
 const recipe=nodes.get('#monitor-starters').children[0];
 recipe.onclick();
 assert.equal(nodes.get('#monitor-kind').value,'analysis');
 assert.equal(nodes.get('#monitor-analysis').value,'returns');
 assert.equal(nodes.get('#monitor-name').value,'Returns after operations');
 assert.equal(nodes.get('#monitor-group').value,'Behavior');
 assert.deepEqual(Array.from(c.catalogEntries(),item=>item.id).filter(id=>['exploration_rate','plan_deviation_rate','recovery_rate','plan_completion_rate'].includes(id)),[]);
 assert.equal(c.metricChoices().some(([,label])=>label.includes('exploration_rate')),false);
 assert.equal(c.metricChoices({metric:'exploration_rate'}).some(([id])=>id==='exploration_rate'),true,'legacy metrics remain inspectable when editing an existing definition');
});

test('semantic starter on a source-only workspace explains that a saved observer is required',()=>{
 const {context:c,nodes}=harness();
 c.options={metrics:{},analysis_measures:{returns:{label:'Work returns',description:'Observed returns.'}},observers:[],graph_observers:[],starters:[]};
 for(const id of ['#editor-error','#monitor-kind','#monitor-group','#monitor-name','#monitor-analysis','#monitor-observer','#monitor-starters'])c.$(id);
 nodes.set('#monitor-observer',new Element('select'));
 c.applyStarterRecipe({id:'returns',name:'Returns after operations',kind:'analysis',measure:'returns',observer_requirement:'explicit_observer',definition:{name:'Returns after operations',kind:'analysis',group:'Behavior',observer:null,analysis:{measure:'returns'}}});
 assert.match(nodes.get('#editor-error').textContent,/needs a saved semantic observer/);
 assert.match(nodes.get('#editor-error').textContent,/recorded source cannot satisfy/);
 assert.equal(nodes.get('#monitor-observer').value,'');
 assert.equal(nodes.get('#monitor-observer').options[0].textContent,'No saved semantic observer available');
});

test('custom rollout cases show feedback severity and expandable result details',()=>{
 const {context:c,nodes}=harness();
 const run={id:'run-1',metadata:{task_id:'Task A',training_step:3}};
 c.casePage=0;c.caseMonitor={id:'custom-id',kind:'custom',observer:'source',unit:'value',custom:{version:'1',description:'Action count',unit:'value',aggregation:'mean'}};
 c.filteredCases=()=>[{run,measurement:{value:4,feedback:{severity:'warning',summary:'Review the action count.',next_check:'Inspect the rollout.'},details:{action_count:4}}}];
 c.metricValue=value=>String(value);c.mapLink=()=>'/source';c.addToolEvidence=()=>{};
 c.table=headers=>{const table=new Element('table');table.headers=headers;return table;};
 const start=source.indexOf('function renderCases()');
 const end=source.indexOf('\nfunction configureKind(',start);
 vm.runInContext(source.slice(start,end),c);
 c.renderCases();
 const row=nodes.get('#case-table').children[0].children[0];
 const evidence=row.children[3];
 assert.match(JSON.stringify(evidence),/Warning: Review the action count/);
 assert.match(JSON.stringify(evidence),/Inspect the rollout/);
 assert.match(JSON.stringify(evidence),/action_count/);
});

test('Add core monitors posts the idempotent source-default request and reloads the registry',async()=>{
 const {context:c,nodes}=harness();let request=null,reloaded=false;
 c.api=async(path,body)=>{request={path,body};return {added:['a','b'],existing:['c']};};
 c.load=async()=>{reloaded=true;};
 const start=source.indexOf('async function addCoreMonitors()');
 const end=source.indexOf("\n$('#add-core-monitors')",start);
 vm.runInContext(source.slice(start,end),c);
 await c.addCoreMonitors();
 assert.equal(request.path,'/api/monitoring/starters');
 assert.deepEqual(Object.keys(request.body),[]);
 assert.equal(reloaded,true);
 assert.equal(nodes.get('#registry-feedback').textContent,'2 added · 1 already present');
 assert.equal(nodes.get('#add-core-monitors').disabled,false);
});
