"""Source-preserving diagnostics from actual candidate-attention experiments."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tracker.jev import validate_answers
from tracker.schema import digest


class GeneratedPairAttentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=json.loads((Path(__file__).parent/'fixtures/generated-generalization-attention.json').read_text(encoding='utf8'))

    def test_raw_live_outputs_reproduce_every_score(self):
        requests=self.fixture['requests']
        for key,request in requests.items():
            self.assertEqual(digest(request),key)
        for experiment in self.fixture['sets'].values():
            for row in experiment['rows']:
                request=requests[row['request_hash']]
                answer=validate_answers(row['response'],request)[row['question_id']]
                prediction=answer['value'] if answer['status']=='decided' else answer['status']
                self.assertEqual(prediction,row['prediction'])
                self.assertEqual(row['correct'],prediction==row['reference'])

    def test_candidate_packet_effect_and_unresolved_target_miss_remain_visible(self):
        groups=self.fixture['sets']['focused']['groups']
        self.assertEqual(groups['plan/original']['correct'],3)
        self.assertEqual(groups['plan/single_question']['correct'],3)
        self.assertEqual(groups['plan/single_candidate']['correct'],4)
        self.assertEqual(groups['plan/source_only']['correct'],4)
        for arm in ('original','single_question','single_candidate','source_only'):
            self.assertEqual(groups['target/'+arm]['correct'],2)
            self.assertEqual(groups['target/'+arm]['pairs'],3)
            self.assertEqual(groups['target/'+arm]['failures'],['refined/simulation/e8/a0'])
        broad=self.fixture['sets']['broad_plan']['groups']
        self.assertEqual(broad['plan/original']['pairs'],36)
        self.assertEqual(broad['plan/original']['correct'],35)
        self.assertEqual(broad['plan/single_candidate']['pairs'],36)
        self.assertEqual(broad['plan/single_candidate']['correct'],36)

    def test_ablations_do_not_shorten_source_or_alter_native_dispatch(self):
        requests=self.fixture['requests']
        for experiment in self.fixture['sets'].values():
            def identity(row):
                return tuple(row[k] for k in ('kind','version','case_id','event_id','question_id'))
            originals={identity(r):requests[r['request_hash']] for r in experiment['rows'] if r['arm']=='original'}
            for row in experiment['rows']:
                original=originals[identity(row)]
                actual=requests[row['request_hash']]
                self.assertEqual(actual['state']['prefix'],original['state']['prefix'])
                expected=deepcopy(original)
                question=row['question_id']
                if row['arm']!='original':
                    expected['questions']={question:expected['questions'][question]}
                if row['arm'] in {'single_candidate','source_only'}:
                    field='plan_stage_candidates' if row['kind']=='plan' else 'prior_actions'
                    expected['state'][field]=[c for c in expected['state'][field] if c['id']==question]
                if row['arm']=='source_only':
                    if row['kind']=='plan':
                        expected['state'].pop('action_content',None)
                        expected['state'].pop('action_activity',None)
                        for candidate in expected['state']['plan_stage_candidates']:
                            candidate.pop('plan_content',None)
                            candidate['step'].pop('text',None)
                            candidate['step'].pop('target',None)
                        # Only this question's neutral identification changes:
                        # exact source evidence replaces the generated summary.
                        expected['questions'][question]['instructions']=actual['questions'][question]['instructions']
                        self.assertIn('exact source evidence',actual['questions'][question]['instructions'])
                    else:
                        expected['state'].pop('current_meaning',None)
                        for candidate in [expected['state']['current_action'],*expected['state']['prior_actions']]:
                            candidate.pop('content',None)
                            candidate.pop('activity',None)
                self.assertEqual(actual,expected)
