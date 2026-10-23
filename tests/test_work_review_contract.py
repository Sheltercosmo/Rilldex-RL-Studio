"""Native source -> Python comparisons -> actual work-review projection."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from tracker import repeated_work, work_navigation
from tracker.schema import digest
from test_revisit_distributions import sample
from test_repeated_work import freeze
from test_work_episodes import edge


def controls():
    cases=[]
    for index,kind in enumerate(('native_changed','formatted_same','feedback_order','native_only','feedback_fragments')):
        run,g=sample(index,'changed_inputs' if kind=='formatted_same' else 'exact_repeat')
        actions=[e for e in run['events'] if e['kind']=='action']
        if kind in {'native_changed','formatted_same'}:
            for i,e in enumerate((actions[0],actions[-1])):
                e.update(tool='search',arguments={'query':'beta' if kind=='native_changed' and i else 'alpha'})
        if kind=='feedback_order':
            # Two recorded response chunks in opposite order at the revisit.
            for e in run['events']:e['index']*=10
            for n in g['nodes']:n['event_index']*=10
            feedback=[e for e in run['events'] if e['kind']=='feedback']
            for i,e in enumerate((feedback[0],feedback[-1])):
                e['text']='first' if i==0 else 'second'
                unit=next(n for n in g['nodes'] if n['kind']=='unit' and n['properties']['source']['event_id']==e['id'])
                unit['properties']['source'].update(text=e['text'],end=len(e['text']))
                extra={**e,'id':e['id']+'-chunk','index':e['index']+1,'text':'second' if i==0 else 'first',
                       'source_pointer':e['source_pointer']+'/chunk/1'}
                run['events'].append(extra)
                g['nodes'].append(dict(id='event:'+extra['id'],kind='event',activity=None,trajectory_id='main',event_index=extra['index'],properties=extra))
                edge(g,'event:'+extra['id'],'event:'+actions[0 if i==0 else -1]['id'],'response_to')
            run['events'].sort(key=lambda e:e['index'])
        if kind=='native_only':
            removed={n['id'] for n in g['nodes'] if n['kind']=='unit' and n['properties']['kind']=='feedback'}
            g['nodes']=[n for n in g['nodes'] if n['id'] not in removed]
            g['edges']=[e for e in g['edges'] if not removed.intersection((e['source'],e['target']))]
        if kind=='feedback_fragments':
            original=next(n for n in g['nodes'] if n['kind']=='unit' and n['properties']['kind']=='feedback')
            extra=deepcopy(original);extra['id']='fragment';extra['properties']['id']='fragment'
            # Two nonoverlapping fragments of one returned source record.
            text=original['properties']['source']['text']
            original['properties']['source'].update(end=1,text=text[:1])
            extra['properties']['source'].update(start=1,text=text[1:]);g['nodes'].append(extra)
            action_unit=next(n for n in g['nodes'] if n['kind']=='unit' and n['properties']['source']['event_id']==actions[0]['id'])
            edge(g,extra,action_unit,'feedback_for')
            thinking=next(n for n in g['nodes'] if n['kind']=='unit' and n['properties']['kind']=='reasoning' and n['event_index']>original['event_index'])
            thinking['properties']['kind']='semantic';edge(g,thinking,extra,'assesses')
        for e in run['events']:e['content_hash']=digest(e['text'])
        events={e['id']:e for e in run['events']}
        for n in g['nodes']:
            if n['kind']=='event':n['properties']=deepcopy(events[n['properties']['id']])
        g['source_hash']=digest(run);g=freeze(g)
        cases.append(dict(kind=kind,run=run,graph=g,navigation=work_navigation.project(g),comparisons=repeated_work.project(g)))
    return cases


class WorkReviewContractTests(unittest.TestCase):
    def test_source_comparisons_and_map_counts_agree_across_capture_shapes(self):
        cases=controls();expected={
            'native_changed':('changed','unchanged'), 'formatted_same':('unchanged','unchanged'),
            'feedback_order':('unchanged','changed'), 'native_only':('unchanged','unchanged'),
            'feedback_fragments':('unchanged','unchanged')}
        for c in cases:
            from tracker.annotation_changes import _inventory
            _inventory(c['graph'])
            row=c['comparisons']['rows'][0]
            self.assertEqual((row['dispatch']['status'],row['feedback']['status']),expected[c['kind']])
        script=r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),R=require('./tracker/web/work-review.js');
const rows=JSON.parse(fs.readFileSync(0,'utf8'));
for(const c of rows){
 const before=JSON.stringify(c),m=R.project(c.navigation,c.graph,null,null,c.comparisons),target=m.targets[0],p=target.pairs[0],r=c.comparisons.rows[0];
 assert.equal(p.dispatch,r.dispatch.status,c.kind);assert.equal(p.feedback,r.feedback.status,c.kind);
 assert.equal(target.count.exact_repeats,r.inputs_and_feedback_match?1:0,c.kind);
 assert.equal(target.count.feedback,2,c.kind);assert.equal(p.input_comparison.id,r.id);
 if(c.kind==='feedback_order'){
  assert.deepEqual(target.steps.map(s=>s.responses.map(r=>r.raw)),[['first','second'],['second','first']]);
 }
 if(c.kind==='feedback_fragments'){
  assert.equal(target.steps[0].responses.length,1);assert.equal(target.steps[0].responses[0].raw,'1 failed');
  assert.equal(target.steps[0].responses[0].references.length,1);
 }
 assert.equal(JSON.stringify(c),before);
}
console.log(JSON.stringify({cases:rows.length,passed:true}));
'''
        node=shutil.which('node')
        self.assertIsNotNone(node,'Node is needed for the frontend/backend contract check')
        result=subprocess.run([node,'-e',script],input=json.dumps(cases),capture_output=True,text=True,
            cwd=Path(__file__).resolve().parents[1],timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),{'cases':5,'passed':True})


if __name__=='__main__':unittest.main()
