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
