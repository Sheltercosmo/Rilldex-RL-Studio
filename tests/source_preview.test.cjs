const {test}=require('node:test');
const assert=require('node:assert/strict');
const {renderPreview,renderReceipts,receiptDestinations,recordLabel}=require('../tracker/web/source-preview.js');

function dom(){
 class Node {
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.attributes={};this.textContent='';}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(name,value){this.attributes[name]=value;}
  focus(){this.focused=true;}
  scrollIntoView(){this.scrolled=true;}
 }
 global.document={createElement:tag=>new Node(tag)};
 return new Node('host');
}
function all(node){return [node,...node.children.flatMap(all)];}
const event=(id,index,kind,text,extra={})=>({id,index,kind,text,actor:'agent',trajectory_id:'main',source_pointer:'/messages/'+index,media_count:0,omitted_characters:0,...extra});
const run={source_preview:{identity:{task_id:'Repair parser'},events:[event('e1',0,'action','<script>do not execute</script>',{tool:'read'}),event('e2',1,'feedback','Returned content'),event('e3',2,'message','',{media_count:1})],relations:[{action_id:'e1',feedback_id:'e2',basis:'call ID'}],total_events:40,omitted_events:37,omitted_relations:9,copied_context_events:3,note:'Source order only.'}};

test('preview renders source as text, explains empty media records, and follows explicit endpoints',()=>{
 const host=dom();renderPreview(host,[run]);const nodes=all(host);
 const text=nodes.find(n=>n.tag==='pre');assert.equal(text.textContent,'<script>do not execute</script>');
 assert.equal(nodes.filter(n=>n.tag==='script').length,0);
 assert.ok(nodes.some(n=>n.textContent==='No text recorded.'));
 assert.ok(nodes.some(n=>n.textContent.includes('1 media references')));
 assert.ok(nodes.some(n=>n.textContent.includes('37 later events')&&n.textContent.includes('9 links')));
 const button=nodes.find(n=>n.tag==='button');assert.equal(button.type,'button');assert.equal(button.title,'call ID');button.onclick();
 const target=nodes.find(n=>n.dataset.kind==='action');assert.equal(target.focused,true);assert.equal(target.scrolled,true);
});

test('sample selector opens first source immediately and switches without mixing records',()=>{
 const host=dom();const second={source_preview:{...run.source_preview,events:[event('x',0,'message','Second rollout')],relations:[],identity:{task_id:'Another task'}}};
 renderPreview(host,[run,second]);assert.ok(all(host).some(n=>n.textContent==='Returned content'));
 const select=all(host).find(n=>n.tag==='select');select.value='1';select.onchange();
 assert.ok(all(host).some(n=>n.textContent==='Second rollout'));assert.ok(!all(host).some(n=>n.textContent==='Returned content'));
 assert.equal(all(host).filter(n=>n.tag==='button').length,0);
});

test('receipt handoffs pin sources and retain independent experiment scopes and return destination',()=>{
 const receipts=[{run_id:'hash-a',revision:2,state:'complete',experiment:'a & b',task_id:'Task A'},
  {run_id:'hash-b',revision:0,state:'in_progress',experiment:'second',export_path:'nested/worker.jsonl',source_line:12}];
 const back='/connections?connection=id#directory-section';const links=receiptDestinations(receipts,back);
 const map=new URL(links[0].map,'http://local');assert.equal(map.searchParams.get('run'),'hash-a');assert.equal(map.searchParams.get('return_to'),back);
 assert.equal(new URL(links[0].overview,'http://local').searchParams.get('experiment'),'a & b');
 assert.equal(new URL(links[1].overview,'http://local').searchParams.get('experiment'),'second');
 assert.equal(links[1].label,'nested/worker.jsonl · line 12');
 const host=dom();renderReceipts(host,receipts,back);assert.equal(all(host).filter(n=>n.tag==='a').length,4);
 assert.equal(receiptDestinations([{...receipts[0],experiment:null}],back)[0].overview,null);
});

test('general options omit opaque content IDs and prefer meaningful source names',()=>{
 assert.equal(recordLabel({source_id:'a'.repeat(24),source_preview:{identity:{sample_id:'b'.repeat(24)}}},2),'Rollout 3');
 assert.equal(recordLabel({source_preview:{identity:{task_id:'Repair formatter',sample_id:'b'.repeat(24)}}},0),'Repair formatter');
});
