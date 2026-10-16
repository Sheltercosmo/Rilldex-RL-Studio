import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tracker.capture import Outbox
from tracker.portable import generation_document
from tracker.schema import InputError
from tracker.store import Store, ReviewConflict
from tracker.training_lineage import VERSION, receive, snapshot


def record(kind, sample='a', identifier=None, revision=0, **data):
    defaults = {
        'sample': {'split': 'train', 'group_id': 'g1', 'step': 0, 'step_basis': 'native generation'},
        'score': {'component': 'correctness', 'definition': 'verifier/1', 'status': 'scored', 'value': 0},
        'selection': {'filter': 'length', 'definition': 'length/1', 'decision': 'rejected', 'batch_id': 'b1'},
        'use': {'batch_id': 'update-0', 'learner_step': 0, 'stage': 'backward_completed'},
    }
    return {'id': identifier or kind+'/'+sample, 'revision': revision, 'kind': kind,
        'sample': {'producer': 'worker', 'rollout_id': sample},
        'evidence': {'basis': 'authored contract control', 'source_revision': 0}, 'data': defaults[kind] | data}


class TrainingLineageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name); self.store = Store(self.root/'server.sqlite')
        self.out = Outbox(self.root/'out.sqlite', producer='worker')

    def packet(self, records):
        return {'schema': VERSION, 'producer': 'worker', 'experiment': 'exp', 'records': records}

    def add(self, *records): return receive(self.store, self.packet(list(records)))

    def source(self, name, text='answer', revision=0):
        return self.store.ingest({'producer':'worker','rollout_id':name,'revision':revision,'state':'complete',
            'document':generation_document('question',text,metadata={'experiment':'exp','split':'train'})})

    def test_unequal_explicit_groups_and_reuse_do_not_duplicate_rollouts(self):
        for i in range(7):
            self.source(str(i))
            self.add(record('sample', str(i), group_id='g1' if i<4 else 'g2'), record('score',str(i)))
        self.add(record('use','0'), record('use','0',identifier='reuse',learner_step=1))
        got=snapshot(self.store); c=got['cohorts'][0]
        self.assertEqual(c['groups'],2);self.assertEqual(c['counts']['generated'],7)
        self.assertEqual(c['counts']['backward'],1);self.assertEqual(got['samples'][0]['use_count'],2)
        self.assertEqual(c['unknown_selection'],7);self.assertEqual(c['unknown_use'],6)
        self.assertEqual(c['counts']['optimizer'],0)

    def test_optimizer_confirmation_preserves_sample_grain_and_separate_stage_evidence(self):
        self.source('a'); self.add(record('sample'), record('use', loss_tokens=0))
        self.add(record('use', identifier='optimizer/0', stage='optimizer_step_completed', loss_tokens=0))
        self.add(record('use', identifier='optimizer/1', stage='optimizer_step_completed', learner_step=1, loss_tokens=0))
        got = snapshot(self.store); row = got['samples'][0]; cohort = got['cohorts'][0]
        self.assertEqual(cohort['counts']['optimizer'], 1)
        self.assertEqual(row['use_count'], 3)
        self.assertEqual(row['use_counts'], {'backward_completed': 1, 'optimizer_step_completed': 2})
        self.assertEqual(cohort['counts']['positive_mask_backward'], 0)

    def test_delayed_source_sample_and_score_revisions_join_without_rewriting_source(self):
        self.add(record('score',revision=2,value=1));self.add(record('score',revision=0,value=0))
        self.assertEqual(snapshot(self.store)['orphan_samples'],1)
        self.add(record('sample'));self.assertEqual(snapshot(self.store)['cohorts'][0]['missing_source'],1)
        original=self.source('a');self.source('a','changed source',revision=1)
        row=snapshot(self.store)['samples'][0]
        self.assertEqual(row['run_id'],original['id'])
        self.assertEqual([r['data']['value'] for r in row['records'] if r['kind']=='score'],[1])
        self.assertEqual(self.store.get(original['id'],raw=True)['run']['raw']['completion'],'answer')

    def test_conflict_rolls_back_complete_packet_and_duplicates_are_idempotent(self):
        r=record('score');self.assertEqual(self.add(r)['inserted'],1)
        self.assertEqual(self.add(r)['inserted'],0)
        with self.assertRaises(ReviewConflict):self.add(record('sample'),record('score',value=2))
        self.assertEqual(snapshot(self.store)['samples'],[])
        with self.assertRaises(ReviewConflict):self.add(record('score',revision=1,component='changed meaning'))

    def test_unknown_is_not_rejection_or_zero_and_revised_selection_uses_revision(self):
        self.add(record('sample'),record('selection',revision=2,decision='admitted'))
        self.add(record('selection',revision=1,decision='rejected'))
        c=snapshot(self.store)['cohorts'][0]
        self.assertEqual(c['counts']['admitted'],1);self.assertEqual(c['unknown_use'],1)
        self.assertIsNone(c['comparison']['generated']['mean_per_rollout'])
        self.assertEqual(c['comparison']['generated']['measured'],0)

    def test_existing_monitor_values_join_with_coverage_and_not_use_weighting(self):
        from tracker.monitoring import create,sync
        self.source('a','abcd');self.source('b','abcdefgh')
        self.add(record('sample','a'),record('sample','b'),record('use','b'),record('use','b',identifier='reuse'))
        m=create(self.store,{'name':'Text','kind':'metric','observer':'source','metric':'agent_text_chars'})
        sync(self.store)
        c=snapshot(self.store,monitor=m['id'])['cohorts'][0]['comparison']
        self.assertEqual(c['generated']['mean_per_rollout'],6)
        self.assertEqual(c['backward']['population'],1);self.assertEqual(c['backward']['mean_per_rollout'],8)

    def test_splits_clocks_and_environments_never_share_a_curve(self):
        self.add(record('sample','a'),record('sample','b',split='evaluation'),
            record('sample','c',step_basis='different clock'),record('sample','d',environment='browser'))
        self.assertEqual(len(snapshot(self.store)['cohorts']),4)

    def test_absent_training_stage_is_unavailable_but_recorded_zero_mask_is_available(self):
        self.add(record('sample','a'),record('sample','b'))
        c=snapshot(self.store)['cohorts'][0]
        self.assertFalse(c['availability']['backward']);self.assertFalse(c['bins'][0]['availability']['positive_mask_backward'])
        self.add(record('use','a',model_tokens=8,loss_tokens=0))
        c=snapshot(self.store)['cohorts'][0]
        self.assertTrue(c['availability']['positive_mask_backward']);self.assertEqual(c['counts']['positive_mask_backward'],0)
        self.assertFalse(c['availability']['optimizer'])

    def test_source_from_another_experiment_does_not_join(self):
        self.source('a')
        packet=self.packet([record('sample')]);packet['experiment']='different'
        receive(self.store,packet)
        self.assertEqual(snapshot(self.store)['cohorts'][0]['missing_source'],1)
        self.assertEqual(snapshot(self.store)['samples'][0]['join_status'],'experiment_conflict')

    def test_source_without_experiment_metadata_joins_by_explicit_native_identity(self):
        self.store.ingest({'producer':'worker','rollout_id':'a','revision':0,'state':'complete',
            'document':generation_document('question','answer')})
        self.add(record('sample'))
        self.assertIsNotNone(snapshot(self.store)['samples'][0]['run_id'])

    def test_two_sample_declarations_are_excluded_as_conflicting(self):
        self.add(record('sample'),record('sample',identifier='another-declaration'))
        got=snapshot(self.store)
        self.assertEqual(got['conflicting_samples'],1);self.assertEqual(got['samples'],[])

    def test_native_group_identity_can_span_workers_in_one_experiment(self):
        self.add(record('sample','a'))
        r=record('sample','b');r['sample']['producer']='worker-2'
        p=self.packet([r]);p['producer']='worker-2';receive(self.store,p)
        c=snapshot(self.store)['cohorts'][0]
        self.assertEqual(c['counts']['generated'],2);self.assertEqual(c['groups'],1)

    def test_transport_rejects_an_acknowledgment_for_another_packet(self):
        self.out.log_training('exp',[record('sample')])
        with patch('tracker.capture.urlopen',return_value=io.BytesIO(b'{"id":"wrong","revision":0}')):
            result=self.out.drain()
        self.assertEqual(result['pending'],1);self.assertEqual(result['sent_now'],0)
        self.assertIn('different training packet',result['errors'][0]['error'])

    def test_lineage_failure_policy_does_not_claim_existing_source_capture_is_absent(self):
        from tracker.trl_lineage import GRPOTrainingLineageMixin
        mixin=object.__new__(GRPOTrainingLineageMixin)
        mixin.training_capture=SimpleNamespace(on_error='warn',counts={'lineage_failures':0})
        with self.assertWarnsRegex(RuntimeWarning,'facts may be partial'):
            mixin._jev_error(BufferError('queue full'))
        self.assertEqual(mixin.training_capture.counts['lineage_failures'],1)
        mixin.training_capture.on_error='raise'
        with self.assertRaises(BufferError):mixin._jev_error(BufferError('queue full'))

    def test_malformed_facts_fail_before_queue_or_server_mutation(self):
        cases=[record('score',value=float('nan')),record('use',learner_step=True),
               record('score',status='unavailable',value=0),record('use',model_tokens=1,loss_tokens=2),
               record('sample',revision=1),record('sample',step_basis='')]
        for r in cases:
            with self.subTest(r=r), self.assertRaises(InputError): self.out.log_training('exp',[r])
        self.assertEqual(self.out.status()['pending'],0)

    def test_lost_ack_reopen_mixed_transport_and_late_records(self):
        self.out.log_training('exp',[record('sample'),record('score')])
        self.out.log('a',generation_document('question','answer',metadata={'experiment':'exp'}),state='complete')
        def send(req,**kwargs):
            p=json.loads(req.data)
            result=receive(self.store,p) if req.full_url.endswith('/training-records') else self.store.ingest(p)
            return io.BytesIO(json.dumps(result).encode())
        def lost(req,**kwargs):send(req);raise OSError('lost acknowledgment')
        with patch('tracker.capture.urlopen',side_effect=lost):self.out.drain()
        reopened=Outbox(self.root/'out.sqlite',producer='worker')
        with patch('tracker.capture.urlopen',side_effect=send):self.assertEqual(reopened.drain()['sent_now'],2)
        self.assertEqual(len(snapshot(self.store)['samples']),1)
        self.assertEqual(snapshot(self.store)['cohorts'][0]['missing_source'],0)
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM training_records').fetchone()[0],2)
        self.assertTrue(reopened.log_training('exp',[record('sample'),record('score')])['duplicate'])


if __name__=='__main__':unittest.main()
