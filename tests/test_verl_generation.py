import copy
import json
from pathlib import Path
import tempfile
import unittest

from tracker.adapters import normalize
from tracker.rollout_metrics import source_record, report, training_series
from tracker.schema import InputError
from tracker.store import Store
from tracker.verl_generation import read_jsonl


class VerlGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.row = {'input': 'user\nQuestion?\nassistant\n', 'output': 'Answer.', 'step': 0,
                    'score': -0.25, 'gts': 'HIDDEN TARGET', 'genrm_response': 'EVALUATOR'}

    def test_evidence_and_score_do_not_become_success_or_agent_context(self):
        run = normalize(self.row, 'verl-generation', {'experiment': 'A'})[0]
        self.assertEqual(run['raw'], self.row)
        self.assertEqual([(e['actor'],e['source_pointer']) for e in run['events']], [('context','/input'),('agent','/output')])
        self.assertNotIn('HIDDEN TARGET', ''.join(e['text'] for e in run['events']))
        m = source_record(run)['metrics']
        self.assertEqual(m['recorded_reward']['value'], -0.25)
        self.assertEqual(m['recorded_reward']['evidence_ids'], ['/score'])
        self.assertIsNone(m['recorded_success']['value'])
        self.assertIsNone(m['actions']['value'])
        self.assertEqual(run['metadata']['training_step'], 0)
        self.assertNotIn('policy_version', run['metadata'])

    def test_repeated_completions_are_distinct_rollouts_and_reimport_is_stable(self):
        path = self.root/'not-a-step-999.jsonl'
        path.write_text(json.dumps(self.row)+'\n'+json.dumps(self.row)+'\n')
        runs = read_jsonl(path, {'experiment':'A'})
        self.assertEqual(len({r['id'] for r in runs}), 2)
        self.assertEqual([r['metadata']['source_line'] for r in runs], [1,2])
        self.assertEqual(runs, read_jsonl(path, {'experiment':'A'}))
        store = Store(self.root/'data.sqlite');store.add(runs);store.add(runs)
        result = training_series(report(store),'recorded_reward')
        self.assertEqual(len(result['cohorts'][0]['points']),2)
        self.assertEqual(result['cohorts'][0]['bins'][0]['start'],0)

    def test_record_step_and_score_validation(self):
        for value in (True, -1, '7', None):
            row = {**self.row, 'step':value}
            with self.assertRaises(InputError):normalize(row,'verl-generation')
        for value in (True, float('inf'), float('nan'), '1'):
            with self.assertRaises(InputError):normalize({**self.row,'score':value},'verl-generation')
        with self.assertRaisesRegex(InputError,'conflicts'):
            normalize(self.row,'verl-generation',{'training_step':9})
        run = normalize({**self.row,'score':None},'verl-generation')[0]
        self.assertIsNone(source_record(run)['metrics']['recorded_reward']['value'])

    def test_batch_requires_experiment_and_validates_every_line(self):
        path = self.root/'batch.jsonl';path.write_text(json.dumps(self.row)+'\n{}')
        with self.assertRaisesRegex(InputError,'experiment'):read_jsonl(path)
        with self.assertRaisesRegex(InputError,'line 2'):read_jsonl(path,{'experiment':'A'})
        with self.assertRaisesRegex(InputError,'size limit'):read_jsonl(path,{'experiment':'A'},max_bytes=2)

    def test_different_reward_definitions_and_step_bases_do_not_pool(self):
        store = Store(self.root/'data.sqlite')
        runs = [normalize(self.row,'verl-generation',{'experiment':'A','reward_definition':label})[0] for label in ('judge-A','judge-B')]
        store.add(runs)
        self.assertEqual(len(training_series(report(store),'recorded_reward')['cohorts']),2)
