const {test}=require('node:test');
const assert=require('node:assert/strict');
const {script}=require('../tracker/web/custom-monitor-setup.js');
const fs=require('node:fs');
const vm=require('node:vm');

test('Python setup binds the selected workspace and observer and publishes feedback',()=>{
 const code=script({database:'C:\\runs\\study.sqlite',name:'Response review',observer:'review-v2',experiment:'training',version:'2',description:'Our analysis',group:'Behavior'});
 assert.ok(code.includes('Workspace("C:\\\\runs\\\\study.sqlite", observer="review-v2", experiment="training")'));
 assert.match(code,/version="2"/);assert.match(code,/"Response review"/);
 for(const part of ['"value"','"evidence_ids"','"feedback"','"next_check"','monitor.run(','monitor.follow('])assert.ok(code.includes(part),part);
 assert.match(code,/if __name__ == "__main__"/);
});

test('setup escapes user text as Python string content',()=>{
 const code=script({name:'Quote " and newline\n__import__("os")'});
 assert.ok(code.includes('"Quote \\" and newline\\n__import__(\\"os\\")"'));
 assert.ok(!code.includes('\n__import__'));
 assert.ok(!code.includes('experiment='));
});

test('reward setup binds the reward contract and versioned check, without assuming a positive scale',()=>{
 const code=script({template:'reward',database:'study.sqlite',name:'Penalty integrity',rewardDefinition:'cost-v2',rewardPath:'/raw/score',checkPath:'/raw/check',subjectPath:'/raw/subject',threshold:-2,direction:'le'});
 for(const part of ['ws.reward_detector(', 'reward_definition="cost-v2"','"reward": "/raw/score"','"threshold": -2','"direction": "le"','check.get("subject_id") != subject','check.get("reward_definition") != ctx.reward_definition','"input_evidence"','"not_applicable"','monitor.follow(detect'])assert.ok(code.includes(part),part);
 assert.throws(()=>script({template:'reward',threshold:'not a number'}),/finite/);
 assert.throws(()=>script({template:'reward',threshold:''}),/finite/);
 assert.ok(script({template:'reward',definitionPath:'/raw/reward_version'}).includes('definition_path="/raw/reward_version"'));
 assert.ok(script({template:'reward',rewardDefinition:'x"\nimport os'}).includes('reward_definition="x\\"\\nimport os"'));
});

function editorHarness(){
 const source=fs.readFileSync(require.resolve('../tracker/web/monitoring.js'),'utf8');
 const nodes=new Map();const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,disabled:false,textContent:'',attributes:{},setAttribute(key,value){this.attributes[key]=value;},classList:{toggle(){}}});return nodes.get(id);};
 const ctx=vm.createContext({$,options:{question_setup:{},custom_setup:{database:'/workspace/live.sqlite'}},editing:null,CustomMonitorSetup:{script},showQuestionCheck(){}});
 vm.runInContext(source.slice(source.indexOf("let previousBuiltInKind="),source.indexOf('async function copyCustomMonitor()')),ctx);
 ctx.configureKind=observer=>{$('#monitor-observer').value=observer;ctx.configureCustomMode();};
 return {$,ctx};
}

test('code mode exposes setup and blocks an empty built-in monitor submission',()=>{
 const {$,ctx}=editorHarness();
 $('#monitor-kind').value='custom';ctx.configureCustomMode();
 assert.equal($('#monitor-mode-code').attributes['aria-pressed'],'true');
 assert.equal($('#monitor-mode-builtin').attributes['aria-pressed'],'false');
 assert.equal($('#monitor-kind-field').hidden,true);
 assert.equal($('#editor-custom-guide').hidden,false);
 assert.equal($('#monitor-discovery').hidden,true);
 assert.equal($('#save-monitor').disabled,true);
 assert.equal($('#monitor-population').hidden,true);
 assert.match($('#custom-monitor-script').textContent,/\/workspace\/live.sqlite/);
 $('#monitor-kind').value='metric';ctx.configureCustomMode();
 assert.equal($('#editor-custom-guide').hidden,true);
 assert.equal($('#save-monitor').disabled,false);
 assert.equal($('#monitor-discovery').hidden,false);
 assert.equal($('#monitor-mode-builtin').attributes['aria-pressed'],'true');
 assert.equal($('#monitor-kind-field').hidden,false);
});

test('top-level Advanced code choice preserves built-in settings when switching back',()=>{
 const {$,ctx}=editorHarness();
 $('#monitor-kind').value='graph';$('#monitor-observer').value='reviewed-v2';
 $('#monitor-name').value='Follow-through review';
 ctx.selectMonitorMode('custom');
 assert.equal($('#monitor-kind').value,'custom');
 assert.match($('#custom-monitor-script').textContent,/observer="reviewed-v2"/);
 assert.match($('#custom-monitor-script').textContent,/Follow-through review/);
 ctx.selectMonitorMode('custom'); // Clicking the already selected mode must be harmless.
 ctx.selectMonitorMode('builtin');
 assert.equal($('#monitor-kind').value,'graph');
 assert.equal($('#monitor-observer').value,'reviewed-v2');
 assert.equal($('#monitor-name').value,'Follow-through review');
 assert.equal($('#save-monitor').disabled,false);
});

test('reward template shows the matching callback instructions and blocks invalid downloads',()=>{
 const {$,ctx}=editorHarness();
 $('#monitor-kind').value='custom';$('#custom-monitor-template').value='reward';$('#custom-reward-threshold').value='-2';
 ctx.updateCustomScript();
 assert.equal($('#custom-reward-fields').hidden,false);
 assert.match($('#custom-callback-help').textContent,/flagged, clear, unknown/);
 assert.equal($('#monitor-group').value,'Reward integrity');
 assert.equal($('#download-custom-monitor').disabled,false);
 $('#custom-reward-threshold').value='';ctx.updateCustomScript();
 assert.equal($('#download-custom-monitor').disabled,true);
 assert.equal($('#custom-monitor-script').textContent,'');
});
test('evaluator template uses pinned reports without a scalar reward threshold',()=>{
 const code=script({template:'evaluations',rewardDefinition:'reward/v3',rewardProducer:'score-worker/1',checkProducer:'check "quoted"'});
 for(const part of ['evaluations={','"producer": "score-worker/1"','ctx.compare_evaluations("reward", "check")','"ambiguous_reports"','"evaluation_ids"','monitor.follow(detect'])assert.ok(code.includes(part),part);
 assert.ok(code.includes('"producer": "check \\"quoted\\""'));
 assert.ok(!code.includes('"threshold"'));
 const {$,ctx}=editorHarness();$('#custom-monitor-template').value='evaluations';ctx.updateCustomScript();
 assert.equal($('#custom-reward-fields').hidden,false);
 assert.equal($('#custom-recorded-check-fields').hidden,true);
 assert.equal($('#custom-evaluation-fields').hidden,false);
 assert.equal($('#download-custom-monitor').disabled,false);
 assert.match($('#custom-callback-help').textContent,/ctx.evaluations/);
});

test('artifact template is discoverable, configurable and needs no reward threshold',()=>{
 const code=script({template:'artifacts',artifactPath:'/raw/files',artifactNames:'grader.py\r\nanswer.json\ngrader.py',rewardDefinition:'eval/v2'});
 for(const part of ['from rilldex.reward_checks import check_artifacts, snapshot_artifact','"artifacts": "/raw/files"','"grader.py": {"nonempty": True}','"answer.json": {"nonempty": True}','monitor.follow(check_artifacts'])assert.ok(code.includes(part),part);
 assert.equal(code.match(/"grader.py":/g).length,1);
 assert.throws(()=>script({template:'artifacts',artifactNames:'  '}),/artifact names/);
 const {$,ctx}=editorHarness();$('#custom-monitor-template').value='artifacts';$('#custom-artifact-names').value='answer.json';ctx.updateCustomScript();
 assert.equal($('#custom-artifact-fields').hidden,false);
 assert.equal($('#custom-recorded-check-fields').hidden,true);
 assert.equal($('#custom-evaluation-fields').hidden,true);
 assert.equal($('#download-custom-monitor').disabled,false);
 assert.match($('#custom-callback-help').textContent,/trusted sha256/);
 $('#custom-artifact-names').value='';ctx.updateCustomScript();assert.equal($('#download-custom-monitor').disabled,true);
 $('#custom-monitor-template').value='metric';ctx.updateCustomScript();assert.equal($('#custom-artifact-fields').hidden,true);
});
