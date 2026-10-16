import unittest
import test_training_lineage as fixtures
from test_training_lineage import record
from tracker import training_lineage, training_selection, monitoring
from tracker.schema import InputError


class SelectionComparisonTests(unittest.TestCase):
    setUp = fixtures.TrainingLineageTests.setUp
    packet = fixtures.TrainingLineageTests.packet
    add = fixtures.TrainingLineageTests.add
    source = fixtures.TrainingLineageTests.source
    def selected(self, monitor=None):
        options = training_lineage.snapshot(self.store)['selection_options']
        return training_lineage.snapshot(self.store, monitor=monitor, selection=options[0]['id'])

    def test_saved_monitor_scope_excludes_samples_without_changing_native_stage_counts(self):
        from tracker.portable import generation_document
        self.source('a')
        self.store.ingest({'producer':'worker','rollout_id':'b','revision':0,'state':'complete',
            'document':generation_document('question','eval answer',metadata={'experiment':'exp','split':'evaluation'})})
        for name in ('a','b','c'):
            self.add(record('sample',name,split='evaluation' if name=='b' else 'train'),record('selection',name,decision='admitted'))
        monitor=monitoring.create(self.store,{'name':'Train length','kind':'metric','observer':'source','metric':'agent_text_chars',
            'population':{'experiment':'exp','split':'train'}})
        monitoring.sync(self.store);result=self.selected(monitor['id'])
        self.assertEqual({r['rollout_id']:r['monitor_population'] for r in result['samples']},
                         {'a':'included','b':'excluded','c':'unknown'})
        train=next(c for c in result['cohorts'] if c['cohort']['split']=='train')
        self.assertEqual(train['counts']['generated'],2)
        self.assertEqual(train['comparison']['generated']['population'],1)
        self.assertEqual(train['selection_comparison']['states']['admitted']['population'],1)
        evaluation=next(c for c in result['cohorts'] if c['cohort']['split']=='evaluation')
        self.assertEqual(evaluation['counts']['generated'],1)
        self.assertEqual(evaluation['comparison']['generated']['population'],0)
        self.assertEqual(evaluation['selection_comparison']['inputs'],[])

    def test_filter_identity_and_unknown_are_not_any_admission(self):
        for name in ('a','b','c','d'):self.add(record('sample',name))
        self.add(record('selection','a'),record('selection','b',decision='unknown'),
                 record('selection','c',decision='admitted'),
                 record('selection','a',identifier='other',filter='other',definition='other/1',decision='admitted'))
        got=self.selected();states=got['cohorts'][0]['selection_comparison']['states']
        self.assertEqual({k:v['population'] for k,v in states.items()},
            {'admitted':1,'rejected':1,'unknown':1,'conflicting':0,'varies_by_batch':0,'not_recorded':1})
        a=next(r for r in got['samples'] if r['rollout_id']=='a')
        self.assertTrue(a['populations']['admitted']);self.assertEqual(a['filter_decision']['state'],'rejected')
        with self.assertRaises(InputError):training_lineage.snapshot(self.store,selection='missing')

    def test_repeated_decisions_revisions_conflicts_and_batch_variation(self):
        for name in ('a','b','c','d','e'):self.add(record('sample',name))
        self.add(record('selection','a',decision='admitted',revision=2),record('selection','a',revision=0),
                 record('selection','a',identifier='repeat',decision='admitted',batch_id='b2'),
                 record('selection','b'),record('selection','b',identifier='opposite-batch',decision='admitted',batch_id='b2'),
                 record('selection','c'),record('selection','c',identifier='contradiction',decision='admitted'),
                 record('selection','d',decision='unknown'),record('selection','d',identifier='known',decision='admitted',batch_id='b2'),
                 record('selection','e',decision='admitted'))
        got=self.selected();states={r['rollout_id']:r['filter_decision']['state'] for r in got['samples']}
        self.assertEqual(states,{'a':'admitted','b':'varies_by_batch','c':'conflicting','d':'unknown','e':'admitted'})
        old=got['cohorts'][0]['selection_comparison']['id']
        self.add(record('selection','a',decision='admitted',revision=1))
        self.assertEqual(self.selected()['cohorts'][0]['selection_comparison']['id'],old)

    def test_within_group_contrast_differs_from_task_mix_and_reuse_does_not_weight(self):
        # Unadjusted admitted mean is higher, but both group differences are -1.
        for name,text,group,state in [('a','x'*9,'hard','admitted'),('b','x'*10,'hard','rejected'),
                                       ('c','x'*9,'hard','admitted'),('d','x','easy','admitted'),
                                       ('e','xx','easy','rejected'),('f','xx','easy','rejected')]:
            self.source(name,text);self.add(record('sample',name,group_id=group),record('selection',name,decision=state))
        self.add(record('use','a'),record('use','a',identifier='reuse'))
        m=monitoring.create(self.store,{'name':'Length','kind':'metric','observer':'source','metric':'agent_text_chars'})
        monitoring.sync(self.store);result=self.selected(m['id'])['cohorts'][0]['selection_comparison']
        self.assertGreater(result['states']['admitted']['mean_per_rollout'],result['states']['rejected']['mean_per_rollout'])
        self.assertEqual(result['within_group']['mean_group_difference'],-1)
        self.assertEqual(result['within_group']['compared_groups'],2)
        self.assertEqual(result['states']['admitted']['measured'],3)

    def test_whole_group_filter_has_no_within_group_contrast(self):
        for name,state in [('a','admitted'),('b','rejected')]:
            self.add(record('sample',name,group_id=name),record('selection',name,decision=state))
        group=self.selected()['cohorts'][0]['selection_comparison']['within_group']
        self.assertIsNone(group['mean_group_difference']);self.assertEqual(group['excluded_groups'],{'no_admitted_rejected_overlap':2})

    def test_conflicting_group_context_is_excluded_and_missing_group_is_counted(self):
        for name,policy in [('a','v1'),('b','v2')]:
            self.add(record('sample',name,policy_version=policy),record('selection',name,decision='admitted' if name=='a' else 'rejected'))
        sample=record('sample','c');del sample['data']['group_id'];self.add(sample)
        group=self.selected()['cohorts'][0]['selection_comparison']['within_group']
        self.assertEqual(group['missing_group_samples'],1);self.assertEqual(group['excluded_groups'],{'conflicting_recorded_context':1})

    def test_pending_observation_and_late_materialization_change_view_without_training_facts(self):
        self.source('a','abcd');self.add(record('sample'),record('selection',decision='admitted'))
        m=monitoring.create(self.store,{'name':'Length','kind':'metric','observer':'source','metric':'agent_text_chars'})
        before=self.selected(m['id']);monitoring.sync(self.store);after=self.selected(m['id'])
        self.assertEqual(before['revision'],after['revision']);self.assertNotEqual(before['view_revision'],after['view_revision'])
        self.assertEqual(before['cohorts'][0]['selection_comparison']['states']['admitted']['missing'],1)
        self.assertEqual(after['cohorts'][0]['selection_comparison']['states']['admitted']['mean_per_rollout'],4)

    def test_opportunity_pooling_retains_all_unknown_rollouts_and_is_not_rollout_mean(self):
        rows=[{'measurement':{'status':'available','value':1,'numerator':1,'denominator':1,'opportunities':1,'unknown':0}},
              {'measurement':{'status':'available','value':0,'numerator':0,'denominator':9,'opportunities':9,'unknown':0}},
              {'measurement':{'status':'unavailable','value':None,'numerator':0,'denominator':0,'opportunities':4,'unknown':4}},
              {'measurement':None}]
        stats=training_selection.summary(rows,True)
        self.assertEqual(stats['mean_per_rollout'],.5);self.assertEqual(stats['pooled_opportunities']['value'],.1)
        self.assertEqual(stats['pooled_opportunities']['unknown'],4);self.assertEqual(stats['pooled_opportunities']['rollouts_without_counts'],1)

    def test_producers_and_definition_versions_are_not_silently_combined(self):
        self.add(record('sample'),record('selection'))
        p=self.packet([record('selection',identifier='different-owner')]);p['producer']='other';training_lineage.receive(self.store,p)
        self.add(record('selection',identifier='v2',definition='length/2'))
        self.assertEqual(len(training_lineage.snapshot(self.store)['selection_options']),3)


if __name__=='__main__':unittest.main()
