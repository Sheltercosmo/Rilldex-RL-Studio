import copy
import tempfile
import unittest
from pathlib import Path

from tracker import procedure_reviews as review, work_episodes, adaptation_patterns, graph_store, failure_investigations
from tracker.schema import digest, InputError
from tracker.store import Store
import test_work_episodes as controls


def frozen(g):
    g['nodes'].sort(key=lambda n:n['id']);g['edges'].sort(key=lambda e:e['id'])
    g['id']='graph-'+digest({k:v for k,v in g.items() if k!='id'})
    return g


class ProcedureReviewTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.store=Store(Path(tmp.name)/'db.sqlite')
        self.run,self.graph,self.actions=controls.example(('A','B','A','A'))
        controls.edge(self.graph,self.actions[2],self.actions[0],'same_action_target')
        controls.edge(self.graph,self.actions[3],self.actions[2],'same_action_target')
        frozen(self.graph);self.store.add([self.run])
        with self.store.connect() as c:graph_store.save(c,self.graph)

    def document(self,g=None,value='same_procedure'):
        g=g or self.graph;a=self.actions
        d=review.template(g,a[0]['id'],a[2]['id'])['document']
        named={'author':'Authored contract test','note':'The exact dispatch pair supports this review choice.'}
        d['reviews']=[dict(previous_unit_id=a[0]['id'],current_unit_id=a[2]['id'],comparison=value,review=named)]
        d['revision']=named
        return d

    def test_review_supplies_exact_pair_to_existing_macro_projection(self):
        g=review.fork(self.graph,self.document())
        graph_store.validate(g);review.checked(g)
        p=work_episodes.project(g)
        self.assertEqual(p['counts']['method_compared'],1)
        self.assertEqual(p['episodes'][0]['method']['basis'],review.VERSION)
        self.assertIsNone(p['episodes'][1]['method'])
        a=adaptation_patterns.project(g)
        self.assertEqual([r['procedure'] for r in a['records']],['same_procedure','unresolved'])
        self.assertEqual(g['nodes'],self.graph['nodes']);self.assertEqual(g['edges'],self.graph['edges'])
        self.assertNotEqual(g['observer'],self.graph['observer'])

    def test_all_choices_remain_reviews_not_outcomes(self):
        for choice in review.CHOICES:
            with self.subTest(choice=choice):
                p=work_episodes.project(review.fork(self.graph,self.document(value=choice)))
                row=p['episodes'][0]
                self.assertEqual(row['method']['comparison'],choice)
                self.assertNotIn('success',row);self.assertNotIn('recovery',row)
                self.assertEqual(row['category'],'returned')

    def test_fork_rejects_modified_base_identity(self):
        document=self.document();g=copy.deepcopy(self.graph)
        g['observer_label']='Changed without a new graph identity'
        with self.assertRaisesRegex(InputError,'immutable identity'):review.fork(g,document)

    def test_unit_correction_invalidates_dependent_procedure_reviews(self):
        from tracker import unit_reviews
        import test_unit_reviews as correction
        base=copy.deepcopy(self.graph)
        events={e['id']:e for e in self.run['events']}
        for node in base['nodes']:
            if node['kind']=='unit':
                ref=node['properties']['source'];ref['source_pointer']=events[ref['event_id']]['source_pointer']
        frozen(base)
        g=review.fork(base,self.document(base))
        d=correction.document(self.run,g,self.actions[2]['id'],'construct','Execute the recurring operation.')
        revised=unit_reviews.fork(self.run,g,d)
        graph_store.validate(revised)
        self.assertNotIn('procedure_reviews',revised['semantic_context'])
        self.assertNotIn('work_observations',revised['semantic_context'])
        self.assertIn('procedure_reviews',g['semantic_context'])
        self.assertEqual(work_episodes.project(revised)['counts']['method_compared'],0)

    def test_original_method_is_restored_when_review_is_removed(self):
        g=copy.deepcopy(self.graph)
        controls.method(g,self.actions[2],self.actions[0],comparison='alternative_procedure',
                        work_instance='same_work_instance',status='selected')
        g['semantic_context']['work_observations']['method_schema']='work-method-comparison/3';frozen(g)
        r=review.fork(g,self.document(g))
        d=self.document(r);d['reviews']=[];d['revision']['note']='Remove the review and restore the original.'
        restored=review.fork(r,d)
        self.assertEqual(adaptation_patterns.project(restored)['records'][0]['procedure'],'alternative_procedure')
        self.assertEqual(g['semantic_context']['work_observations']['method_observations'],
                         restored['semantic_context']['work_observations']['method_observations'])

    def test_idempotent_save_stale_edits_and_parent_immutability(self):
        document=self.document();receipt=review.receive(self.store,document)
        self.assertEqual(review.receive(self.store,document),receipt)
        base=frozen(graph_store.read(self.store,self.graph['id']));self.assertEqual(base,self.graph)
        newer=self.document(value='unresolved')
        with self.assertRaisesRegex(InputError,'latest'):review.receive(self.store,newer)
        current=graph_store.read(self.store,receipt['graph_id'])
        d=self.document(current);self.assertEqual(review.fork(current,d)['id'],current['id'])

    def test_reject_nonrecurrence_reverse_duplicate_and_unattributed_review(self):
        for change in ('other','reverse','duplicate','author','choice'):
            d=self.document();r=d['reviews'][0]
            if change=='other':r['previous_unit_id']=self.actions[1]['id']
            elif change=='reverse':r['previous_unit_id'],r['current_unit_id']=r['current_unit_id'],r['previous_unit_id']
            elif change=='duplicate':d['reviews'].append(copy.deepcopy(r))
            elif change=='author':r['review']['author']=''
            else:r['comparison']='successful_recovery'
            with self.subTest(change=change),self.assertRaises(InputError):review.fork(self.graph,d)

    def test_context_reset_and_hidden_dispatch_cannot_be_reviewed_as_ordered_pair(self):
        for field,value in [('context_id','new-context'),('agent_visibility','not_established')]:
            g=copy.deepcopy(self.graph);eid=self.actions[2]['source']['event_id']
            next(n['properties'] for n in g['nodes'] if n['kind']=='event' and n['properties']['id']==eid)[field]=value
            frozen(g)
            with self.subTest(field=field),self.assertRaises(InputError):self.document(g)

    def test_forged_or_changed_review_observations_are_rejected(self):
        g=review.fork(self.graph,self.document())
        g['semantic_context']['work_observations']['method_observations'][0]['comparison']='alternative_procedure'
        with self.assertRaises(InputError):work_episodes.project(g)
        g=review.fork(self.graph,self.document());g['semantic_context'].pop('procedure_reviews')
        with self.assertRaises(InputError):work_episodes.project(g)

    def test_changed_source_ref_or_missing_identity_invalidates_review(self):
        g=review.fork(self.graph,self.document())
        g['edges']=[e for e in g['edges'] if not(e['type']=='same_action_target' and e['source']==self.actions[2]['id'])]
        with self.assertRaises(InputError):work_episodes.project(g)

    def test_review_profile_is_shared_across_sources_under_the_same_base_observer(self):
        _,g,a=controls.example(('Lookup account','Lookup balance','Lookup account'))
        controls.edge(g,a[2],a[0],'same_action_target');frozen(g)
        named={'author':'Business workflow review','note':'The same account lookup is dispatched after balance retrieval.'}
        d=review.template(g,a[0]['id'],a[2]['id'])['document']
        d.update(reviews=[dict(previous_unit_id=a[0]['id'],current_unit_id=a[2]['id'],comparison='same_procedure',review=named)],revision=named)
        reviewed=review.fork(g,d);other=review.fork(self.graph,self.document())
        self.assertEqual(reviewed['observer'],other['observer'])
        self.assertNotEqual(reviewed['id'],other['id'])

    def test_saved_review_is_immediately_discoverable_in_existing_investigations(self):
        r=review.receive(self.store,self.document())
        a=failure_investigations.snapshot(self.store,run=self.run['id'],observer=r['observer'])
        self.assertIn(r['observer'],[p['id'] for p in a['protocols']])
        b=failure_investigations.snapshot(self.store,**a['controls'])
        self.assertEqual(a['snapshot_id'],b['snapshot_id'])

    def test_derived_recovery_evidence_does_not_change_the_observer_inventory_during_save(self):
        from tracker import behavior_distributions
        failure_investigations.snapshot(self.store,run=self.run['id'],observer=self.graph['observer'])
        behavior_distributions.sync(self.store)
        r=review.receive(self.store,self.document())
        a=failure_investigations.snapshot(self.store,run=self.run['id'],observer=r['observer'])
        b=failure_investigations.snapshot(self.store,**a['controls'])
        self.assertEqual(a['snapshot_id'],b['snapshot_id'])
        self.assertNotIn('recovery-evidence/1',[p['id'] for p in a['protocols']])

    def test_existing_monitor_measures_reviewed_pairs_and_retains_unknowns_and_evidence(self):
        from tracker import monitoring, monitor_evidence
        r=review.receive(self.store,self.document(value='reconfigured_procedure'))
        monitor=monitoring.create(self.store,{'name':'Reviewed procedure changes','kind':'analysis','observer':r['observer'],
            'analysis':{'measure':'procedure_change_fraction'},'group':'Behavior'})
        monitoring.sync(self.store)
        value=monitoring.values(self.store,monitor['id'],{self.run['id']})[self.run['id']]
        self.assertEqual((value['numerator'],value['denominator'],value['unknown']),(1,1,1))
        evidence=monitor_evidence.read(self.store,value['id'])
        self.assertEqual(evidence['graph']['id'],r['graph_id'])
        self.assertEqual(monitoring.sync(self.store)['inserted'],0)


if __name__=='__main__':unittest.main()
