from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker.adapters import normalize
from tracker import reward_records as reward
from tracker.rollout_metrics import source_record, report, training_series, save
from tracker.schema import digest
from tracker.store import Store


def envelope():
    return {'schema': reward.CONTRACT, 'criteria': [
        {'id': 'a', 'description': 'Required content A', 'weight': 4, 'category': 'Content'},
        {'id': 'b', 'description': 'Required content B', 'weight': 6, 'category': 'Content'},
        {'id': 'c', 'description': 'Undesired content', 'weight': -5, 'category': 'Penalty'}],
        'verdicts': [{'criterion_id': 'c', 'met': True}, {'criterion_id': 'a', 'met': True}, {'criterion_id': 'b', 'met': False}],
        'reported_counts': {'criteria': 3, 'verdicts': 3, 'met': 2}, 'score': .25, 'timeout': False, 'error': ''}


def native_run(value=None):
    return normalize({'input': 'Task', 'output': 'Answer', 'score': .25, 'step': 0,
                      'reward_evaluation': envelope() if value is None else value}, 'verl-generation', {'experiment': 'trial'})[0]


def legacy_run():
    return normalize({'input': 'Task', 'output': 'Answer', 'score': .25, 'step': 0,
        'healthbench_rubric_items': json.dumps([{'criterion': r['description'], 'points': r['weight'], 'tags': {'axis': r['category']}} for r in envelope()['criteria']]),
        'healthbench_verdict_vector': '[1,0,1]', 'healthbench_rubric_count': 3,
        'healthbench_verdict_count': 3, 'healthbench_met_count': 2, 'error': '', 'timeout': False},
        'verl-generation', {'experiment': 'trial'})[0]


class RewardRecordTests(unittest.TestCase):
    def test_signed_penalties_and_score_transform_are_not_semantic_correctness(self):
        run = native_run(); before = deepcopy(run); result = reward.inspect(run); m = result['metrics']
        self.assertEqual(m['reward_positive_attainment']['value'], .4)
        self.assertEqual(m['reward_penalty_fraction']['value'], .5)
        self.assertEqual(m['reward_penalty_observed']['value'], 1)
        self.assertAlmostEqual(m['reward_score_gap']['value'], .35)
        self.assertEqual(result['calculation']['rubric_score'], -.1)
        self.assertEqual(m['reward_record_invalid']['value'], 0)
        self.assertEqual(m['reward_zero_with_negative_rubric']['value'], 0)
        self.assertEqual(run, before)
        self.assertFalse(any('Undesired' in e['text'] for e in run['events']))
        zero = envelope(); zero['score'] = 0
        self.assertEqual(reward.inspect(native_run(zero))['metrics']['reward_zero_with_negative_rubric']['value'], 1)

    def test_positional_source_and_named_envelope_agree_with_source_provenance(self):
        a, b = reward.inspect(native_run()), reward.inspect(legacy_run())
        self.assertEqual({k:m['value'] for k,m in a['metrics'].items()}, {k:m['value'] for k,m in b['metrics'].items()})
        self.assertNotEqual(a['protocol'], b['protocol'])
        self.assertEqual(b['source_fields']['/healthbench_verdict_vector'], '[1,0,1]')
        self.assertIn('/healthbench_verdict_vector', b['metrics']['reward_penalty_observed']['evidence'])
        self.assertEqual(b['criteria'][2]['verdict_reference'], '/healthbench_verdict_vector#2')
        self.assertNotIn('source_fields', reward.inspect(legacy_run(),include_criteria=False))

    def test_partial_evidence_can_support_positive_but_not_unobserved_negative(self):
        data = envelope(); data.pop('reported_counts'); data['verdicts'] = [{'criterion_id': 'a', 'met': True}]
        r = reward.inspect(native_run(data)); m = r['metrics']
        self.assertEqual(r['status'], 'partial'); self.assertEqual(m['reward_verdict_coverage']['value'], 1/3)
        self.assertIsNone(m['reward_penalty_observed']['value']); self.assertIsNone(m['reward_positive_attainment']['value'])
        data['verdicts'].append({'criterion_id': 'c', 'met': True})
        self.assertEqual(reward.inspect(native_run(data))['metrics']['reward_penalty_observed']['value'], 1)
        data['verdicts'][-1]['met'] = False
        self.assertEqual(reward.inspect(native_run(data))['metrics']['reward_penalty_observed']['value'], 0)

    def test_invalid_records_never_yield_fabricated_zero_penalties(self):
        for fault in ('duplicate_id', 'duplicate_verdict', 'unknown_id', 'bad_weight', 'count', 'bad_verdict', 'overflow'):
            data = envelope()
            if fault == 'duplicate_id': data['criteria'][1]['id'] = 'a'
            if fault == 'duplicate_verdict': data['verdicts'].append(deepcopy(data['verdicts'][0]))
            if fault == 'unknown_id': data['verdicts'][0]['criterion_id'] = 'missing'
            if fault == 'bad_weight': data['criteria'][0]['weight'] = True
            if fault == 'count': data['reported_counts']['met'] = 3
            if fault == 'bad_verdict': data['verdicts'][0]['met'] = 'true'
            if fault == 'overflow':
                data['criteria'][0]['weight'] = 1e308; data['criteria'][1]['weight'] = 1e308
            with self.subTest(fault=fault):
                r = reward.inspect(native_run(data))
                self.assertEqual(r['metrics']['reward_record_invalid']['value'], 1)
                self.assertIsNone(r['metrics']['reward_penalty_observed']['value'])
                self.assertIsNone(r['metrics']['reward_score_gap']['value'])
                self.assertEqual(r['metrics']['reward_timeout_reported']['value'], 0)

    def test_short_positional_vector_and_malformed_json_are_invalid_not_guessed(self):
        for text in ('[1,0]', 'not json'):
            run = legacy_run(); run['raw']['healthbench_verdict_vector'] = text
            result = reward.inspect(run)
            self.assertEqual(result['status'], 'invalid')
            self.assertEqual(result['metrics']['reward_record_invalid']['value'], 1)
            self.assertIsNone(result['metrics']['reward_verdict_coverage']['value'])

    def test_no_positive_denominator_and_unavailable_feedback_remain_distinct(self):
        data = envelope(); data.pop('reported_counts'); data['criteria'] = data['criteria'][2:]; data['verdicts'] = data['verdicts'][:1]
        m = reward.inspect(native_run(data))['metrics']
        self.assertEqual(m['reward_penalty_observed']['value'], 1)
        self.assertIsNone(m['reward_penalty_fraction']['value']); self.assertIsNone(m['reward_score_gap']['value'])
        run = native_run(); del run['raw']['reward_evaluation']
        self.assertTrue(all(m['value'] is None for m in reward.inspect(run)['metrics'].values()))
        self.assertIsNone(source_record(run)['metrics']['reward_record_invalid']['value'])

    def test_framework_neutral_envelope_does_not_require_a_generation_export(self):
        run = normalize({'trajectory_format': 'devai/1', 'trajectory': [
            {'step': 0, 'agent': {'thought': 'Do task', 'action': 'echo done'}, 'environment': 'done'}],
            'reward_evaluation': envelope()})[0]
        self.assertEqual(reward.inspect(run)['metrics']['reward_penalty_observed']['value'], 1)
        self.assertEqual(len(run['events']), 3)

    def test_source_v8_upgrade_has_one_current_row_and_preserves_historical_records(self):
        with TemporaryDirectory() as root:
            store = Store(Path(root)/'data.sqlite'); run = native_run(); store.add([run])
            old = source_record(run); old['schema'] = 'rollout-behavior/8'
            for k in reward.DEFINITIONS: old['metrics'].pop(k)
            old.pop('reward_inspection_protocol')
            with store.connect() as c: old_key = save(c,old)
            result = report(store); self.assertEqual(len(result['rows']), 1)
            self.assertEqual(result['rows'][0]['metrics']['reward_penalty_observed']['value'], 1)
            series = training_series(result,'reward_penalty_observed')
            self.assertEqual(series['aggregation'],'incidence'); self.assertEqual(series['cohorts'][0]['bins'][0]['mean'],1)
            self.assertEqual(series['cohorts'][0]['bins'][0]['positive'],1)
            report(store)
            with store.connect() as c:
                self.assertIsNotNone(c.execute('SELECT id FROM rollout_measurements WHERE id=?',(old_key,)).fetchone())
                self.assertEqual(c.execute('SELECT count(*) FROM rollout_measurements').fetchone()[0],2)

    def test_different_evaluator_schemas_do_not_pool_and_binary_incidence_uses_rollouts(self):
        with TemporaryDirectory() as root:
            store = Store(Path(root)/'data.sqlite'); a = native_run(); b = legacy_run()
            store.add([a,b]); full=report(store)
            self.assertEqual(len(training_series(full,'reward_penalty_observed')['cohorts']),2)
            self.assertEqual(full['definitions']['reward_penalty_observed']['aggregation'],'incidence')
            self.assertEqual(full['definitions']['reward_positive_attainment']['aggregation'],'distribution')


if __name__ == '__main__': unittest.main()
