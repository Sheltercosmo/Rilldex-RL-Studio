const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const context={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../tracker/web/unit-review.js'),'utf8'),context);
const summary=context.window.UnitReview.changeSummary;
test('review summary explains activity and sequence changes without calling them behavior rates',()=>{
 const lines=Array.from(summary({status:'available',activities:[{activity:'orient',baseline:0,current:1}],boundary_changes:{split:1},transitions:[{from_activity:'inspect',to_activity:'orient',baseline:0,current:1}],relationship_groups_changed:2,note:'Annotation changes only.'}));
 assert.ok(lines.some(x=>x.includes('orient 0 → 1')));
 assert.ok(lines.some(x=>x.includes('inspect → orient: 0 → 1')));
 assert.ok(lines.some(x=>x.includes('do not mean the behavior did not occur')));
 assert.ok(lines.includes('Annotation changes only.'));
});
test('unchanged counts and unavailable legacy baseline are explicit',()=>{
 assert.equal(summary(undefined).length,0);
 assert.equal(summary({status:'unavailable',reason:'Cannot align baseline.'})[0],'Cannot align baseline.');
 assert.match(summary({status:'available',activities:[],boundary_changes:{},transitions:[],relationship_groups_changed:0,note:'Named review.'})[0],/meanings and connections may still change/);
});
