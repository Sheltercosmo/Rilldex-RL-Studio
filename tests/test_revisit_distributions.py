"""Distribution-to-evidence workflow; authored controls, no model inference."""
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from tracker import behavior_distributions as d, graph_store, investigation_plans
from tracker.adapters import normalize
from tracker.schema import digest
from tracker.store import Store
from test_work_episodes import edge
from test_repeated_work import freeze


def sample(step, mode='exact_repeat'):
    changed=mode in {'changed_inputs','changed_inputs_no_feedback'}
    raw={'instance_id':f'revisit-{step}', 'trajectory':[
        {'thought':'Check the regression', 'action':'pytest tests/test_parser.py', 'observation':'1 failed'},
        {'thought':'Install the missing prerequisite', 'action':'pip install parser-dependency', 'observation':'Installed'},
        {'thought':'Check the regression again', 'action':'pytest -q tests/test_parser.py' if changed else 'pytest tests/test_parser.py',
         'observation':'' if mode in {'feedback_unknown','changed_inputs_no_feedback'} else '1 passed' if mode=='changed_feedback' else '1 failed'}]}
    run=normalize(raw,'swe-agent',{'experiment':'revisit-controls','task_id':'parser','training_step':step})[0]
    units=[]; actions=[]
    for e in run['events']:
        if not e['text']:continue
        u=dict(id='u'+e['id'],actor=e['actor'],kind=e['kind'],trajectory_id=e['trajectory_id'],activity='execute' if e['kind']=='action' else 'orient',
               source=dict(event_id=e['id'],start=0,end=len(e['text']),text=e['text'],source_pointer=e['source_pointer']),
               content={'target':{'text':e['text']}})
        units.append(u)
        if e['kind']=='action':actions.append(u)
    g=graph_store.build(run,{'observer':{'id':'review','label':'Saved work links'},'document':{
        'schema':'semantic-unit-map/1','source_hash':digest(run),'units':units,'relations':[]}})
    if mode not in {'uninspected','no_pairs'}:edge(g,actions[-1],actions[0],'same_action_target')
    if mode=='no_pairs':g['semantic_context']['work_observations']={'identity_reviews':[{
        'action_unit_id':a['id'],'status':'no_prior_selected_action'} for a in actions]}
    if mode=='unknown':
        missing=actions[1]['id']
        g['nodes']=[n for n in g['nodes'] if n['id']!=missing]
        g['edges']=[e for e in g['edges'] if missing not in (e['source'],e['target'])]
    return run,freeze(g)


class RevisitDistributionTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.store=Store(Path(folder.name)/'review.sqlite')

    def add(self,step,mode='exact_repeat'):
        run,g=sample(step,mode);self.store.add([run])
        with self.store.connect() as c:graph_store.save(c,g)
        return run,g

    def test_exclusive_categories_keep_both_unknown_kinds_in_denominator(self):
        modes=['changed_inputs','changed_feedback','exact_repeat','feedback_unknown','unknown']
        for step,mode in enumerate(modes):self.add(step,mode)
        s=d.snapshot(self.store,lens='revisit')
        self.assertEqual(s['distribution']['counts'],dict.fromkeys(modes,1))
        self.assertEqual(s['distribution']['total'],5)
        self.assertTrue(all(v==.2 for v in s['distribution']['shares'].values()))
        self.assertEqual(sum(p['work_coverage']['input_comparisons'] for p in s['points']),4)
        self.assertEqual(sum(p['work_coverage']['feedback_comparisons'] for p in s['points']),3)
        self.assertEqual(s['inference_calls'],0)
        from tracker.annotation_changes import _inventory
        for case in s['cases']:_inventory(graph_store.read(self.store,case['graph_id']))

    def test_changed_inputs_do_not_require_feedback_but_do_not_assert_recovery(self):
        self.add(0,'changed_inputs_no_feedback');s=d.snapshot(self.store,lens='revisit')
        self.assertEqual(s['distribution']['counts']['changed_inputs'],1)
        self.assertEqual(s['cases'][0]['repeated_work']['feedback']['status'],'unavailable')
        self.assertNotIn('success',s['cases'][0])
        self.assertIn('do not establish a new strategy',s['definition']['limit'])

    def test_no_pairs_missing_reviews_and_missing_graph_are_separate(self):
        self.add(0,'no_pairs');self.add(1,'uninspected')
        run,_=sample(2);self.store.add([run])
        s=d.snapshot(self.store,lens='revisit',observer='review')
        self.assertEqual(s['distribution']['total'],0)
        self.assertEqual(s['observed_rollouts'],1)
        self.assertTrue(all(v is None for v in s['distribution']['shares'].values()))
        self.assertEqual([r['status'] for r in s['observation_members']],['no_opportunities','layer_unavailable','not_observed'])

    def test_gap_and_exact_windows_preserve_original_pair_after_late_annotation(self):
        run,g=self.add(0);unobserved,_=sample(1);self.store.add([unobserved]);self.add(2,'changed_inputs')
        before=d.snapshot(self.store,lens='revisit',a_start=0,a_end=1,b_start=2,b_end=2)
        self.assertIsNone(before['bins'][1]['shares']['exact_repeat'])
        self.assertEqual((before['baseline']['population'],before['baseline']['eligible_rollouts']),(2,1))
        self.assertEqual(next(x['pp'] for x in before['deltas'] if x['id']=='changed_inputs'),100)
        case=next(x for x in before['cases'] if x['run_id']==run['id']);q=parse_qs(urlparse(case['map_url']).query)
        self.assertEqual(q['graph'],[g['id']]);self.assertEqual(q['revisit_case'],[case['id']])
        saved=investigation_plans.read_output(self.store,q['revisit'][0])
        self.assertEqual(saved['rows'][0],case['repeated_work'])
        updated=deepcopy(g);updated['edges']=[e for e in updated['edges'] if e['type']!='same_action_target']
        with self.store.connect() as c:graph_store.save(c,freeze(updated))
        self.store=Store(self.store.path)
        after=d.snapshot(self.store,lens='revisit',observer='review')
        self.assertEqual(after['distribution']['counts']['exact_repeat'],0)
        self.assertEqual(investigation_plans.read_output(self.store,q['revisit'][0]),saved)
        self.assertEqual(graph_store.read(self.store,g['id'])['edges'],g['edges'])

    def test_repeat_snapshots_use_cache_and_keep_graph_edges(self):
        _,g=self.add(0);first=d.snapshot(self.store,lens='revisit')
        with self.store.connect() as c:n=c.execute('SELECT COUNT(*) FROM investigation_nodes').fetchone()[0]
        second=d.snapshot(self.store,lens='revisit')
        self.assertEqual(first['cases'],second['cases'])
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM investigation_nodes').fetchone()[0],n)
        self.assertEqual(freeze(graph_store.read(self.store,g['id'])),g)


if __name__=='__main__':unittest.main()
