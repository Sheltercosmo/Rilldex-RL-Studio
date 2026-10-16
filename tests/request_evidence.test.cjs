const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
class Node{constructor(tag){this.tag=tag;this.children=[];this.attributes={};}append(...c){this.children.push(...c);}replaceChildren(...c){this.children=c;}setAttribute(k,v){this.attributes[k]=v;}}
const walk=n=>[n,...n.children.flatMap(walk)],text=n=>walk(n).map(x=>x.textContent||'').join(' ');
function render(rows){const c=vm.createContext({window:{},document:{createElement:t=>new Node(t)}});vm.runInContext(fs.readFileSync(require.resolve('../tracker/web/request-evidence.js'),'utf8'),c);const host=new Node('div'),opened=[];c.window.RequestEvidence.render(host,{rows,counts:{unrepresented_actions:0},excluded:[]},id=>opened.push(id));return {host,opened};}
const row=(extra={})=>({clause:{kind:'requested_check',text:'Verify the requested balance.'},state:'requested',origin:{event_id:'e1',node_id:'unit-request'},coverage:'unreviewed',counts:{dispatch_opportunities:2,dispatch_reviewed:0,response_opportunities:2,response_reviewed:0,dispatch_choices:{},response_choices:{}},dispatches:[],responses:[],...extra});
test('unreviewed coverage appears in the summary without opening details',()=>{
 const {host}=render([row()]);const summary=walk(host).find(n=>n.tag==='summary');assert.match(text(summary),/Not reviewed/);assert.match(text(summary),/0\/2 dispatches reviewed/);assert.doesNotMatch(text(host),/0 failed|passed|satisfied/);
});
test('historical requested checks are visible by default and can be hidden',()=>{
 const {host}=render([row({state:'superseded'})]);assert.match(text(host),/Verify the requested balance/);const input=walk(host).find(n=>n.tag==='input');assert.equal(input.checked,true);input.checked=false;input.onchange();assert.doesNotMatch(text(host),/Verify the requested balance/);assert.match(text(host),/No current clauses/);
});
test('response evidence opens its own source and never renders a success badge',()=>{
 const {host,opened}=render([row({coverage:'complete_saved_review',latest_response_choice:'no_answer',responses:[{action_unit_id:'a',action:{index:2,text:'read balance',node_id:'a',event_id:'e2'},choice:'no_answer',response:{text:'Different card',event_id:'e3',node_id:'event:e3'}}]})]);
 const button=walk(host).find(n=>n.tag==='button'&&n.textContent==='Open response · e3');button.onclick();assert.deepEqual(opened,['event:e3']);assert.match(text(host),/No answer in this response/);assert.doesNotMatch(text(host),/Check passed|Task completed/);
});
test('missing source-bound clauses remain unknown',()=>{const {host}=render([]);assert.match(text(host),/Check coverage is unknown/);assert.equal(walk(host).filter(n=>n.tag==='summary').length,0);});
test('negative answers and preparation are visible without expanding a check',()=>{const {host}=render([row({counts:{dispatch_opportunities:3,dispatch_reviewed:3,response_opportunities:3,response_reviewed:3,dispatch_choices:{prepares:1,none:2},response_choices:{no_answer:3}},coverage:'complete_saved_review'})]);const summary=walk(host).find(n=>n.tag==='summary');assert.match(text(summary),/1 preparatory action/);assert.match(text(summary),/3 responses without an answer/);assert.doesNotMatch(text(summary),/0 observed attempts/);});
