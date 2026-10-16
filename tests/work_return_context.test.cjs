const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context={window:{}};
vm.runInNewContext(fs.readFileSync(require.resolve('../tracker/web/work-navigation.js'),'utf8'),context);
const project=context.window.WorkNavigationView.returnContext;
const plain=v=>JSON.parse(JSON.stringify(v));
function fixture(){
 const visits=['a','b','c','d','later','other'].map(id=>({id,target:id,group_id:['a','c','d','later'].includes(id)?'work-x':'work-'+id}));
 const link={type:'same_work_return',source:'d',target:'c',episode_id:'e',category:'returned'};
 const rel=(id,target)=>({id,type:'work_relation',family:'revision',source:'d',target,relation_type:'revises',label:'Revision',node_ids:[id+'-unit'],edge_ids:[id+'-edge']});
 return {visits,paths:[{visit_ids:['a','c','b','d','later']},{visit_ids:['other']}],episodes:[{id:'e'}],links:[link,rel('middle','b'),rel('prior','c'),rel('older','a'),rel('future','later'),rel('cross-route','other'),rel('internal','d')]};
}
test('return context uses the saved previous visit, not the first similarly named target',()=>{
 const data=fixture(),before=JSON.stringify(data),r=project(data,data.links[0]);
 assert.equal(r.previous.id,'c');assert.equal(r.current.id,'d');assert.deepEqual(plain(r.between).map(v=>v.id),['b']);
 assert.deepEqual(plain(r.interveningReferences).map(v=>v.id),['middle']);
 assert.deepEqual(plain(r.earlierWorkReferences).map(v=>v.id),['prior','older']);
 assert.equal(JSON.stringify(data),before);
});
test('future, internal and other-context links are not presented as references to prior work',()=>{
 const data=fixture(),r=project(data,data.links[0]);const ids=[...r.interveningReferences,...r.earlierWorkReferences].map(v=>v.id);
 for(const id of ['future','cross-route','internal'])assert.equal(ids.includes(id),false);
});
test('unresolved intervening work remains in the displayed window',()=>{
 const data=fixture();data.visits.find(v=>v.id==='b').group_id=null;data.visits.find(v=>v.id==='b').order_known=false;
 const r=project(data,data.links[0]);assert.equal(r.between.length,1);assert.equal(r.between[0].group_id,null);assert.equal(r.between[0].order_known,false);
});
test('parallel siblings remain separate cards with their original ordering evidence',()=>{
 const data=fixture();data.paths[0].visit_ids.splice(3,0,'sibling');data.visits.push({id:'sibling',group_id:'another',order_known:false});data.visits.find(v=>v.id==='b').order_known=false;
 const r=project(data,data.links[0]);assert.deepEqual(plain(r.between).map(v=>v.id),['b','sibling']);assert.equal(r.between.every(v=>v.order_known===false),true);
});
test('missing and ambiguous route membership cannot construct a recurrence story',()=>{
 for(const edit of [d=>d.links.splice(0,1),d=>d.paths[0].visit_ids.reverse(),d=>d.paths.push(d.paths[0]),d=>d.visits.splice(d.visits.findIndex(v=>v.id==='b'),1)]){
  const data=fixture(),link=data.links[0];edit(data);assert.equal(project(data,link).available,false);
 }
});
test('bundled references retain each exact witness and do not duplicate the work visits',()=>{
 const data=fixture(),r=data.links[1];data.links.push({...r,id:'second',node_ids:['second-unit'],edge_ids:['second-edge']});
 const out=project(data,data.links[0]);assert.equal(out.between.length,1);assert.equal(out.interveningReferences.length,1);
 assert.deepEqual(plain(out.interveningReferences[0].edge_ids),['middle-edge','second-edge']);assert.equal(out.interveningReferences[0].bundle.length,2);
});
test('same text never creates a same-work reference without recorded group identity',()=>{
 const data=fixture();data.visits.find(v=>v.id==='b').target='a';
 assert.deepEqual(plain(project(data,data.links[0]).earlierWorkReferences).map(r=>r.id),['prior','older']);
});
test('target comparisons are preserved separately and never become expressed references',()=>{
 const data=fixture();data.links=data.links.map(l=>l.type==='work_relation'?{...l,family:'target',relation_type:'different_work_same_subject'}:l);
 const r=project(data,data.links[0]);assert.equal(r.interveningReferences.length,0);assert.equal(r.earlierWorkReferences.length,0);
 assert.deepEqual(Array.from(r.workComparisons,v=>v.id),['middle','prior','older']);
});
test('an unknown relation family does not acquire expressed-reference meaning',()=>{
 const data=fixture();data.links[1].family='custom_comparison';
 assert.equal(project(data,data.links[0]).interveningReferences.length,0);
});
