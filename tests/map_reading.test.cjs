const {test}=require('node:test');
const assert=require('node:assert/strict');
const L=require('../tracker/web/map-layout.js');
const S=require('../tracker/web/rollout-story.js');
test('source actions and feedback retain type colors without becoming semantic contributions',()=>{
 const source={kind:'event',properties:{kind:'message'},lane:0};
 const action={kind:'event',properties:{kind:'action'},lane:1};
 const feedback={kind:'event',properties:{kind:'feedback'},lane:2};
 assert.equal(L.cardStyle(source).key,'source');
 assert.equal(L.cardStyle(action).key,'action');
 assert.equal(L.cardStyle(feedback).key,'feedback');
 assert.equal(new Set([source,action,feedback].map(n=>L.cardStyle(n).color)).size,3);
 assert.equal(L.cardStyle({...action,kind:'unit'}).color,L.cardStyle(action).color);
 assert.equal(L.cardStyle({...source,kind:'unit'}).key,'contribution');
});
const edges=[
 {id:'order',source:'a',target:'b',type:'source_order',family:'sequence'},
 {id:'response',source:'result',target:'a',type:'feedback_for',family:'feedback'},
 {id:'assessment',source:'thought',target:'result',type:'assesses',family:'review'},
 {id:'change',source:'later',target:'earlier',type:'revises',family:'review'},
 {id:'plan',source:'a',target:'p',display_target:'step',type:'attempts_plan_step',family:'plan'},
 {id:'repeat',source:'later',target:'a',type:'same_procedure',family:'return'}
];
test('default reading includes every relationship; explicit unit focus exposes incident links',()=>{
 const layout={nodes:['a','b','result','thought'],edges};
 assert.deepEqual(L.connectionView(layout).map(e=>e.id),['response','assessment','change','plan','repeat']);
 assert.deepEqual(L.connectionView(layout,'all','a','response').map(e=>e.id),['response','assessment','change','plan','repeat']);
 assert.deepEqual(L.connectionView(layout,'selected','a').map(e=>e.id),['response','plan','repeat']);
 assert.equal(layout.nodes.length,4);assert.equal(layout.edges.length,6);
 assert.deepEqual(L.connectionView(layout,'selected','step').map(e=>e.id),['plan']);
 assert.deepEqual(L.connectionView(layout,'selected_all','a').map(e=>e.id),['response','plan','repeat']);
});
test('feedback lens cannot turn revisions into feedback use; all view preserves repeat links',()=>{
 assert.deepEqual(L.connectionView({edges},'feedback').map(e=>e.id),['assessment']);
 assert.equal(L.connectionView({edges},'all').length,5);
 assert.ok(L.connectionView({edges},'all').some(e=>e.id==='repeat'));
});
test('measurement evidence and selected edge remain visible across reading lenses',()=>{
 assert.deepEqual(L.connectionView({edges},'response',null,'change',new Set(['plan'])).map(e=>e.id),['response','change','plan']);
});
test('pointer anchored zoom preserves the graph coordinate under the cursor',()=>{
 const p=L.zoomAnchor(.8,1.2,200,800,170,90);
 assert.equal((p.left+170)/1.2,(200+170)/.8);
 assert.ok(Math.abs((p.top+90)/1.2-(800+90)/.8)<1e-9);
});
test('text result excerpts keep error wording, full source and non-diagnostic type',()=>{
 const raw='File "/a.py", line 3\n\nSyntaxError: unterminated string\n[Python Interpreter: /env/bin/python]\nagent@host:/workspace $';
 const p=S.preview(raw);assert.equal(p.text,'SyntaxError: unterminated string');assert.equal(p.raw,raw);assert.equal(p.kind,'text');
 assert.equal(S.preview('[WARNING] Could not fetch image\n[Python Interpreter: /env]').text,'[WARNING] Could not fetch image');
});
test('metadata-only output is neither success nor an invented failure',()=>{
 const p=S.preview('[Python Interpreter: /env]\nagent@host:/workspace $');
 assert.equal(p.text,'No output text beyond environment metadata.');assert.equal(p.kind,'text');
 assert.equal(S.preview('The test previously failed').text,'The test previously failed');
});
test('a warning does not hide a later missing-dependency diagnostic',()=>{
 const raw='[WARNING] Could not fetch image\npdflatex not found. Please select a different engine.\n[Python Interpreter: /env]';
 const p=S.preview(raw);assert.ok(p.text.includes('Could not fetch'));assert.ok(p.text.includes('pdflatex not found'));assert.equal(p.kind,'text');assert.equal(p.raw,raw);
});
test('long output is bounded in the preview but source content stays complete',()=>{
 const raw='line\n'.repeat(10000);const p=S.preview(raw);
 assert.ok(p.text.length<=260);assert.equal(p.raw,raw.trim());
 const json=JSON.stringify({error:'sample'});assert.equal(S.preview(json).kind,'error-field');
});
test('embedded image data is represented as media presence without interpreting its pixels',()=>{
 const raw='<IPython.core.display.Image object>\n![image](data:image/png;base64,aGVsbG8=)';
 const p=S.preview(raw);assert.equal(p.raw,raw);assert.ok(p.text.includes('[Embedded image in source record]'));assert.ok(!p.text.includes('base64'));assert.equal(p.kind,'text');
});
