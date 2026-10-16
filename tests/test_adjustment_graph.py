from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from shutil import copytree
from unittest import TestCase
from tracker import adjustment_graph as ag
from tracker.semantic_extraction import read
from tracker.schema import digest,InputError

ROOT=Path(__file__).resolve().parents[1]/'research'


class AdjustmentGraphTests(TestCase):
    def test_registered_snapshot_binds_review_without_global_catalog_edit(self):
        from tracker import semantic_catalog
        from tracker.store import Store
        from tracker.semantic_extraction import write
        with TemporaryDirectory() as folder:
            folder=Path(folder);destination=folder/'adjustments'
            copytree(ROOT/'adjustment-facets-2026-10-08/software',destination)
            result=read(destination/'local-adjustments.json')
            review={'observation_hash':digest(result),'notes':[]};write(destination/'source-review.json',review)
            store=Store(folder/'tracker.sqlite');store.add([self.inputs[0]])
            before=set(semantic_catalog.PROFILES)
            saved=ag.register(store,ROOT/'work-items-complete-2026-10-08/software',destination,'Pinned local content')
            self.assertEqual(set(semantic_catalog.PROFILES),before)
            view=semantic_catalog.load(self.inputs[0],saved['observer'],store)
            self.assertEqual(len(view['document']['adjustment_graph']['episodes']),8)
            observed=view['document'];unique={digest(r) for r in observed['relations']}
            for r in [*self.inputs[4]['relations'],*self.inputs[5]['relations']]:self.assertIn(digest(r),unique)
            self.assertEqual(len(observed['relations']),len(unique))
            final_links=[r for r in observed['relations'] if r.get('from')=='sdb67cc9aa54444a9ae89' and r['type']=='declares_same_work_as']
            self.assertEqual(len(final_links),4)
            self.assertTrue(any(p['observer']==saved['observer'] for p in semantic_catalog.catalog(store)['maps']))
            review['notes'].append({'text':'A new review changes this snapshot.','unit_ids':[]});write(destination/'source-review.json',review)
            with self.assertRaisesRegex(InputError,'observation or review changed'):
                semantic_catalog.load(self.inputs[0],saved['observer'],store)

    @classmethod
    def setUpClass(cls):
        b=read(ROOT/'local-adjustments-2026-10-08/software/baseline.json')
        previous=read(ROOT/'attempt-revisions-v4-2026-10-08/software/baseline.json')
        work=ROOT/'work-items-complete-2026-10-08/software'
        cls.inputs=(b['run'],previous['bundle']['document'],b['document'],b['local'],
            read(work/'history.json'),read(work/'action-correspondence.json'),
            read(ROOT/'local-adjustments-2026-10-08/software/local-adjustments.json'))

    def test_real_failed_edit_then_repair_and_retry_is_retained(self):
        r=ag.build(*self.inputs);case=next(e for e in r['episodes'] if e['failed_event_id']=='e30')
        self.assertEqual((case['retry_event_id'],case['retry_outcome']),('e33','completed'))
        self.assertEqual(case['changes'][0]['scope'],'retry_dispatch')
        self.assertEqual(r['metrics']['linked_adjustment_completion_fraction']['numerator'],2)
        self.assertEqual(r['metrics']['linked_adjustment_completion_fraction']['denominator'],6)
        self.assertEqual(r['metrics']['linked_adjustment_unknown_fraction']['numerator'],2)

    def test_preparation_path_does_not_depend_on_reclassifying_the_statement(self):
        r=ag.build(*self.inputs);case=next(e for e in r['episodes'] if e['failed_event_id']=='e36')
        u={u['id']:u['source']['event_id'] for u in self.inputs[1]['units']}
        expressions={u[c['declaration_unit_id']] for c in case['changes']}
        self.assertTrue({'e38','e41','e44','e47','e50'}<=expressions)
        for c in case['changes']:
            self.assertEqual(c['scope'],'preparation_for_shared_work')
            self.assertTrue(c['preparation_relations']);self.assertTrue(c['shared_work_ids'])

    def test_chronology_alone_cannot_replace_missing_preparation_edges(self):
        args=deepcopy(self.inputs);args[5]['relations']=[r for r in args[5]['relations'] if r['type']!='prepares_declared_work']
        r=ag.build(*args)
        self.assertNotIn('e36',[e['failed_event_id'] for e in r['episodes']])
        self.assertIn('e48',[e['failed_event_id'] for e in r['episodes']])
        self.assertTrue(any(e['reason'].startswith('No selected') for e in r['excluded_failed_pairs']))

    def test_disputed_same_work_is_never_promoted_by_an_adjustment(self):
        args=deepcopy(self.inputs)
        for pair in args[1]['method_comparison']['observations']:pair['upstream_identity_disputed']=True
        self.assertEqual(ag.build(*args)['episodes'],[])

    def test_changed_base_or_dependency_is_rejected(self):
        args=deepcopy(self.inputs);args[6]['work_items_hash']='altered'
        with self.assertRaises(InputError):ag.build(*args)

    def test_facet_cannot_forge_an_upstream_declaration(self):
        from tracker import local_adjustments as la
        args=deepcopy(self.inputs);items={(o['unit_id'],i['id']):i for o in args[3]['observations'] for i in o['items']}
        args[6]['schema']=la.FACET_VERSION
        for o in args[6]['observations']:
            for i in o['items']:
                i['declaration']=items[o['unit_id'],i['item_id']]['declaration']
                i['selection']='adjustment_content' if i['selection']=='prospective_adjustment' else 'other_content'
        self.assertEqual(len(ag.build(*args)['episodes']),8)
        item=next(i for o in args[6]['observations'] for i in o['items'])
        item['declaration']='reports_finished' if item['declaration']!='reports_finished' else 'commits'
        with self.assertRaisesRegex(InputError,'changed the selected declaration'):ag.build(*args)
        args=deepcopy(self.inputs);args[1]['units'][0]['activity']='invented'
        with self.assertRaises(InputError):ag.build(*args)

    def test_projection_preserves_unit_boundaries_and_existing_characteristics(self):
        r=ag.build(*self.inputs);bundle={'document':self.inputs[1]};before=deepcopy(bundle)
        view=ag.project(self.inputs[0],bundle,r)
        stripped=[{k:v for k,v in u.items() if k!='work_adjustments'} for u in view['document']['units']]
        self.assertEqual(stripped,self.inputs[1]['units']);self.assertEqual(bundle,before)
        self.assertTrue(any(e['type']=='attempts_local_adjustment' for e in view['document']['relations']))
