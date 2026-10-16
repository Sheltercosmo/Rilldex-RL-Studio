import tempfile
import unittest
from pathlib import Path

from tracker.schema import InputError
from tracker.store import Store
from tracker.training_lineage import receive, validate
from tracker.training_health import snapshot


def record(kind, sample='a', identifier=None, revision=0, **data):
    defaults = {
        'sample': {'split': 'train', 'group_id': 'g', 'group_size': 2, 'step': 0, 'step_basis': 'generation'},
        'score': {'component': 'accuracy', 'definition': 'verifier/1', 'status': 'scored', 'value': 0},
        'use': {'batch_id': 'batch', 'learner_step': 7, 'stage': 'backward_completed'},
        'selection': {'filter': 'mask', 'definition': 'mask/1', 'batch_id': 'batch', 'decision': 'admitted'},
    }
    return {'id': identifier or kind+'/'+sample, 'revision': revision, 'kind': kind,
        'sample': {'producer': 'worker', 'rollout_id': sample},
        'evidence': {'basis': 'authored diagnostic control'}, 'data': defaults[kind] | data}


class TrainingHealthTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name)/'health.sqlite')

    def add(self, *records, producer='worker', experiment='exp'):
        return receive(self.store, {'schema': 'training-records/1', 'producer': producer,
                                   'experiment': experiment, 'records': list(records)})

    def group(self, name, scores, size=None, **context):
        for i, value in enumerate(scores):
            sample = name+str(i)
            self.add(record('sample', sample, group_id=name, group_size=size or len(scores), **context),
                     record('score', sample, value=value))

    def reward(self):
        return snapshot(self.store)['cohorts'][0]['rewards'][0]

    def test_group_and_sample_weighting_are_distinct(self):
        self.group('constant', [0, 0]); self.group('contrast', [0, 0, 1, 1])
        r = self.reward()
        self.assertEqual(r['constant_groups'], {'value': .5, 'numerator': 1, 'denominator': 2})
        self.assertAlmostEqual(r['samples_in_constant_groups']['value'], 1/3)
        self.assertAlmostEqual(r['mean'], 1/3)
        self.assertEqual(r['states'], {'scored': 6})
        self.assertEqual(r['group_states'], {'complete': 2})

    def test_parallel_learner_policy_clocks_do_not_merge_numeric_steps(self):
        for name,clock,index,step in [('a','learner-A',1,7),('b','learner-B',1,7),('c',None,0,7),('d','learner-A',2,8)]:
            policy={'learner_policy':dict(schema='policy-clock/1',clock=clock,unit='optimizer_update',index=index)} if clock else {}
            self.add(record('sample',name),record('use',name,learner_step=step,**policy))
        streams=snapshot(self.store,experiment='exp')['cohorts'][0]['uses']
        self.assertEqual(len(streams),3)
        self.assertEqual(len({s['id'] for s in streams}),3)
        by_clock={s['learner_policy_clock']['clock'] if s['learner_policy_clock'] else None:s for s in streams}
        self.assertEqual([p['step'] for p in by_clock['learner-A']['points']],[7,8])
        self.assertEqual([p['step'] for p in by_clock['learner-B']['points']],[7])
        self.assertEqual(len(by_clock[None]['points'][0]['records']),1)
        self.assertTrue(all(len(p['records'])==1 for s in streams for p in s['points']))

    def test_partial_singleton_and_unknown_size_never_establish_constant_group(self):
        self.group('partial', [0], size=2); self.group('single', [1])
        r = record('sample', 'legacy', group_id='legacy'); r['data'].pop('group_size')
        self.add(r, record('score', 'legacy'))
        result = self.reward()
        self.assertIsNone(result['constant_groups']['value'])
        self.assertEqual(result['group_states'], {'incomplete': 1, 'singleton': 1, 'size_unrecorded': 1})

    def test_late_member_completes_group_and_missing_score_is_not_zero(self):
        self.group('g', [0], size=2)
        self.add(record('sample', 'g1'))
        self.assertEqual(self.reward()['group_states'], {'scores_incomplete': 1})
        self.add(record('score', 'g1', value=1))
        self.assertEqual(self.reward()['constant_groups']['value'], 0)

    def test_corrections_override_arrival_order_and_replay_is_idempotent(self):
        self.group('g', [0, 1])
        correction = record('score', 'g1', revision=2, value=0)
        self.add(correction); self.add(record('score', 'g1', revision=1, value=2))
        before = snapshot(self.store)
        self.add(correction)
        self.assertEqual(before, snapshot(self.store))
        self.assertEqual(self.reward()['constant_groups']['value'], 1)

    def test_score_errors_and_conflicting_records_remain_excluded(self):
        self.group('g', [0, 1])
        self.add(record('score', 'g0', revision=1, status='error', value=None))
        self.assertEqual(self.reward()['states'], {'error': 1, 'scored': 1})
        self.assertIsNone(self.reward()['constant_groups']['value'])
        self.add(record('score', 'g1', identifier='duplicate-logical-score', value=1))
        self.assertEqual(self.reward()['states'], {'error': 1, 'conflicting': 1})

    def test_group_context_conflict_and_overfull_are_excluded(self):
        self.group('over', [0, 0, 0], size=2)
        self.add(record('sample', 'a', policy_version='one'), record('score', 'a'))
        self.add(record('sample', 'b', policy_version='two'), record('score', 'b'))
        self.assertEqual(self.reward()['group_states'], {'conflicting_context': 1, 'overfull': 1})

    def test_component_and_producer_never_blend(self):
        self.group('g', [0, 0])
        for s, v in [('g0', 0), ('g1', 1)]:
            self.add(record('score', s, identifier='other/'+s, component='format', value=v))
            self.add(record('score', s, value=v), producer='second-scorer')
        rewards = snapshot(self.store)['cohorts'][0]['rewards']
        self.assertEqual(len(rewards), 3)
        self.assertEqual(sorted(r['constant_groups']['value'] for r in rewards), [0, 0, 1])

    def test_generation_and_learner_coordinates_remain_separate(self):
        self.group('g', [0, 1], step=2)
        self.add(record('use', 'g0', learner_step=8, loss_tokens=0, advantage=1),
                 record('use', 'g1', learner_step=8, loss_tokens=3, advantage=0))
        c = snapshot(self.store)['cohorts'][0]
        self.assertEqual(c['rewards'][0]['points'][0]['step'], 2)
        self.assertEqual(c['uses'][0]['points'][0]['step'], 8)
        self.assertEqual(c['uses'][0]['positive_mask']['value'], .5)
        self.assertEqual(c['uses'][0]['zero_advantage']['value'], 1)

    def test_zero_mask_unknown_advantages_and_token_weighting(self):
        self.group('g', [0, 1])
        self.add(record('use', 'g0', loss_tokens=0, model_tokens=10, advantage=0),
                 record('use', 'g1', loss_tokens=2, model_tokens=2, advantage=-1),
                 record('use', 'g1', identifier='unknown-mask', advantage=0),
                 record('use', 'g1', identifier='unknown-advantage', loss_tokens=2))
        u = snapshot(self.store)['cohorts'][0]['uses'][0]
        self.assertEqual(u['zero_advantage'], {'value': 0, 'numerator': 0, 'denominator': 1})
        self.assertEqual(u['negative_advantage']['value'], 1)
        self.assertEqual(u['positive_mask']['value'], 2/3)
        self.assertEqual(u['loss_token_fraction']['value'], 2/12)
        self.assertEqual(u['unknown_mask'], 1)
        self.assertEqual(u['unknown_advantage_with_positive_mask'], 1)
        self.assertEqual(u['unknown_token_pair'], 2)

    def test_use_stage_and_producer_are_independent_streams(self):
        self.group('g', [0, 1])
        self.add(record('use', 'g0'), record('use', 'g0', identifier='repeat'))
        self.add(record('use', 'g0', identifier='optimizer', stage='optimizer_step_completed'))
        self.add(record('use', 'g0'), producer='second-trainer')
        uses = snapshot(self.store)['cohorts'][0]['uses']
        self.assertEqual(len(uses), 3)
        self.assertEqual(sorted(u['receipts'] for u in uses), [1, 1, 2])
        self.assertTrue(all(u['unique_samples'] == 1 for u in uses))
        self.assertTrue(all(u['positive_mask']['value'] is None for u in uses))

    def test_splits_clocks_env_versions_stay_separate(self):
        self.group('train', [0, 1]); self.group('eval', [0, 0], split='evaluation')
        self.group('clock', [0, 0], step_basis='other clock')
        self.group('env', [0, 0], environment_version='2')
        self.assertEqual(len(snapshot(self.store)['cohorts']), 4)

    def test_filter_denominator_excludes_unknown_and_batch_variation(self):
        self.group('g', [0, 1, 0, 1, 0])
        self.add(record('selection', 'g0'), record('selection', 'g1', decision='rejected'),
                 record('selection', 'g2', decision='unknown'), record('selection', 'g3'),
                 record('selection', 'g3', identifier='later', decision='rejected', batch_id='later'))
        f = snapshot(self.store)['cohorts'][0]['filters'][0]
        self.assertEqual(f['admission']['value'], .5)
        self.assertEqual(f['admission']['denominator'], 2)
        self.assertEqual(f['states']['not_recorded'], 1)
        self.assertEqual(f['states']['varies_by_batch'], 1)

    def test_no_native_records_is_empty_not_zero_training(self):
        self.assertEqual(snapshot(self.store)['cohorts'], [])
        self.add(record('sample'))
        c = snapshot(self.store)['cohorts'][0]
        self.assertEqual(c['uses'], []); self.assertEqual(c['rewards'], [])

    def test_group_size_contract_rejects_ambiguous_or_invalid_size(self):
        for n in [0, -1, True, 2.5, '2']:
            with self.assertRaises(InputError): self.add(record('sample', group_size=n))
        r = record('sample'); r['data'].pop('group_id')
        with self.assertRaises(InputError): self.add(r)

    def test_behavior_conditions_use_native_sign_and_deduplicate_shared_sources(self):
        from tracker.portable import generation_document
        from tracker.monitoring import create, sync
        for name, text in [('short', 'abcd'), ('long', 'abcdefgh')]:
            self.store.ingest({'producer': 'worker', 'rollout_id': name, 'revision': 0, 'state': 'complete',
                'document': generation_document('task', text, metadata={'experiment': 'exp', 'split': 'train'})})
        records = []
        for name, source in [('s1', 'short'), ('s2', 'short'), ('s3', 'long')]:
            declaration = record('sample', name, source={'producer': 'worker', 'rollout_id': source, 'revision': 0})
            uses = [record('use', name, advantage=1, loss_tokens=2),
                    record('use', name, identifier='reuse/'+name, advantage=1, loss_tokens=2)]
            for r in [declaration, *uses]:
                r['sample'] = {'producer': 'worker', 'id': name}; records.append(r)
        negative = record('use', 's1', identifier='negative', advantage=-1, loss_tokens=2)
        negative['sample'] = {'producer': 'worker', 'id': 's1'}; records.append(negative)
        receive(self.store, {'schema': 'training-records/2', 'producer': 'worker', 'experiment': 'exp', 'records': records})
        monitor = create(self.store, {'name': 'Text length', 'kind': 'metric', 'observer': 'source', 'metric': 'agent_text_chars'})
        # No measurements yet: never treat a missing annotation as zero.
        u = snapshot(self.store, monitor=monitor['id'])['cohorts'][0]['uses'][0]
        self.assertIsNone(u['behavior_by_advantage']['positive']['mean_per_rollout'])
        sync(self.store)
        u = snapshot(self.store, monitor=monitor['id'])['cohorts'][0]['uses'][0]
        positive = u['behavior_by_advantage']['positive']
        self.assertEqual(positive['mean_per_rollout'], 6)
        self.assertEqual(positive['population'], 3)
        self.assertEqual(positive['source_measured'], 2)
        self.assertEqual(positive['receipts'], 6)
        self.assertEqual(u['behavior_by_advantage']['negative']['mean_per_rollout'], 4)
        self.assertEqual(u['positive_negative_shared_sources'], 1)
        self.assertIsNone(u['behavior_by_advantage']['zero']['mean_per_rollout'])


if __name__ == '__main__':
    unittest.main()
