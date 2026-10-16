from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from tracker import graph_store
from tracker.store import Store
from tracker.schema import digest, InputError
from tracker.work_context import build
from research.work_purpose_trial import fixture, CASES


def example():
    run,local,_=fixture(CASES[0])
    def choose(req):
        pool=req['state']['candidate_frames']
        return {'choice':{'value':pool[-1]['id']}},digest(req)
    context=build(run,local,choose)
    doc={'source_hash':digest(run),'units':deepcopy(local['units']),'relations':[], 'work_context':context}
    return run,{'document':doc,'observer':{'id':'scope-test','label':'Scope test'}}


class WorkScopeGraphTests(unittest.TestCase):
    def test_scope_nodes_edges_and_unique_unit_coverage_survive_storage(self):
        run,bundle=example();before=deepcopy(bundle);g=graph_store.build(run,bundle)
        self.assertEqual(bundle,before)
        self.assertEqual(len([n for n in g['nodes'] if n['kind']=='unit']),len(bundle['document']['units']))
        scopes=[n for n in g['nodes'] if n['kind']=='work_scope'];self.assertEqual(len(scopes),2)
        memberships=[e for e in g['edges'] if e['type']=='in_work_scope'];self.assertEqual(len(memberships),3)
        self.assertTrue(all(e['properties']['request_ids'] and e['properties']['evidence'] for e in memberships))
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite');store.add([run])
            with store.connect() as c:graph_store.save(c,g)
            saved=graph_store.read(store,g['id'])
            self.assertEqual(saved['id'],g['id'])
            self.assertEqual(sorted(saved['nodes'],key=lambda n:n['id']),g['nodes'])
            self.assertEqual(saved['edges'],g['edges'])

    def test_partial_memberships_remain_observations_without_selected_edges(self):
        run,bundle=example();ctx=bundle['document']['work_context'];row=ctx['observations'][-1];row['status']='needs_review'
        g=graph_store.build(run,bundle)
        self.assertFalse(any(e['source']==row['unit_id'] and e['type']=='in_work_scope' for e in g['edges']))
        observed=g['semantic_context']['work_scopes']['observations'][-1]
        self.assertEqual(observed['scope_ids'],[]);self.assertTrue(observed['candidate_scope_ids'])

    def test_future_and_cross_trajectory_scope_rejected(self):
        run,bundle=example();ctx=bundle['document']['work_context']
        ctx['observations'][0]['frame_ids']=[ctx['frames'][-1]['id']]
        with self.assertRaises(InputError):graph_store.build(run,bundle)
        run,bundle=example();ctx=bundle['document']['work_context'];origin=ctx['frames'][0]['source']['event_id']
        next(e for e in run['events'] if e['id']==origin)['trajectory_id']='different'
        ctx['source_hash']=bundle['document']['source_hash']=digest(run)
        with self.assertRaisesRegex(InputError,'trajectory'):graph_store.build(run,bundle)

    def test_changed_source_cutoff_duplicates_and_empty_selection_rejected(self):
        for mutation in ['source','cutoff','duplicate','empty']:
            run,bundle=example();ctx=bundle['document']['work_context']
            if mutation=='source':ctx['source_hash']='other'
            elif mutation=='cutoff':ctx['observations'][0]['cutoff']['end']-=1
            elif mutation=='duplicate':ctx['observations'].append(deepcopy(ctx['observations'][0]))
            else:ctx['observations'][0]['frame_ids']=[]
            with self.assertRaises(InputError):graph_store.build(run,bundle)

    def test_shared_membership_does_not_duplicate_units(self):
        run,bundle=example();ctx=bundle['document']['work_context'];ctx['observations'][-1]['frame_ids']=[f['id'] for f in ctx['frames']]
        g=graph_store.build(run,bundle);uid=ctx['observations'][-1]['unit_id']
        self.assertEqual(sum(n['id']==uid for n in g['nodes']),1)
        self.assertEqual(sum(e['source']==uid and e['type']=='in_work_scope' for e in g['edges']),2)
        self.assertEqual(g['semantic_context']['work_scopes']['counts']['selected'],3)

    def test_legacy_graph_is_unchanged_and_no_scope_is_inferred_from_activity(self):
        run,bundle=example();del bundle['document']['work_context'];old=graph_store.build(run,bundle)
        self.assertFalse(any(n['kind']=='work_scope' for n in old['nodes']))
        self.assertNotIn('work_scopes',old['semantic_context'])
        _,new=example();g=graph_store.build(run,new);self.assertNotEqual(g['id'],old['id']);graph_store.validate(old)


if __name__=='__main__':unittest.main()
