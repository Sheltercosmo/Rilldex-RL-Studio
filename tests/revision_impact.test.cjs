const assert=require('node:assert/strict');
const {summary,matches,badge}=require('../tracker/web/revision-impact.js');
const episodes=[
 {impact:{operation:{status:'gain'},checks:[{status:'gain'},{status:'harm'}],check_status:'mixed'}},
 {impact:{operation:{status:'still_failed'},checks:[{status:'unknown'}],check_status:'unknown'}},
 {impact:{operation:{status:'unknown'},checks:[],check_status:'unknown'}}
];
assert.deepEqual(summary(episodes),{gain:1,harm:0,retained:0,still_failed:1,unknown:1,total:3,unmeasured:0});
assert.deepEqual(summary(episodes,'checks'),{gain:1,harm:1,retained:0,still_failed:0,unknown:1,total:3,unmeasured:1});
assert(matches(episodes[0],'checks:gain'));
assert(matches(episodes[0],'checks:harm'),'Mixed benefit/harm remains visible in both filters');
assert(!matches(episodes[0],'operations:harm'),'Check failure cannot become an executor failure');
assert(matches(episodes[2],'operations:unknown'));
assert(!matches(episodes[2],'checks:harm'),'Missing check capture is not a negative finding');
assert.equal(badge(episodes[0]),'mixed');
assert.equal(badge(episodes[2]),'unknown');
const shared={impact:{checks:[{pair_id:'same-captured-pair',status:'gain'}]}};
assert.equal(summary([shared,shared],'checks').total,1,'Shared evidence does not become two independent check opportunities');
console.log('Revision impact: mixed results, separate populations, missing capture and filters verified');
