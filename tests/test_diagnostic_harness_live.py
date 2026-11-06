"""Actual paired Jev observations, including failures; no new predictions."""
from collections import Counter
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.evaluate_diagnostic_harness import prepared
from tracker import diagnostic_direct as direct, diagnostic_search as search
from tracker.jev import validate_answers
from tracker.schema import digest

FIXTURE=Path(__file__).parent/'fixtures/diagnostic-harness-live.json'


class DiagnosticHarnessLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=json.loads(FIXTURE.read_text(encoding='utf-8'))
        cls.controls,rows=prepared(FIXTURE.with_name(cls.fixture['source_fixture']),
                                  versions=[search.CONTRACT_VERSION,search.HARNESS_VERSION])
        cls.generated={(row['case_id'],row['version']):row for row in rows}

    def test_exact_source_protocol_and_requests_regenerate_from_pre_live_controls(self):
        self.assertEqual(digest(self.controls),self.fixture['source_fixture_hash'])
        references={case['id']:case['reference'] for case in self.controls['cases']}
        self.assertEqual(digest(references),self.fixture['pre_live_reference_hash'])
        self.assertEqual(len(self.generated),20)
        for version,protocol in self.fixture['protocols'].items():
            self.assertEqual(search.protocol(version),protocol)
        for frozen in self.fixture['rows']:
            actual=self.generated[frozen['case_id'],frozen['version']]
            for key in ('source_hash','normalized_source_hash','request_hashes'):
                self.assertEqual(actual[key],frozen[key],(frozen['case_id'],key))
            for request in actual['requests']:
                self.assertEqual(request['model'],self.fixture['model'])

    def test_all_twenty_actual_responses_keep_exact_probabilities_and_raw_argmax(self):
        count=0
        for frozen in self.fixture['rows']:
            actual=self.generated[frozen['case_id'],frozen['version']]
            requests={digest(req):req for req in actual['requests']}
            for observation in frozen['observations']:
                request=requests[observation['request_hash']]
                response=observation['response']
                self.assertEqual(digest(response),observation['response_hash'])
                self.assertEqual(response['model'],request['model'])
                answers=validate_answers(response,request)
                for key,question in request['questions'].items():
                    expected=max(question['criteria'],key=response['answers'][key]['probabilities'].get)
                    self.assertEqual(answers[key]['value'],expected)
                count+=1
        self.assertEqual(count,20)

    def test_current_builder_replays_every_metric_finding_and_known_miss(self):
        totals=Counter();misses=set()
        with patch('urllib.request.urlopen',side_effect=AssertionError('Replay cannot call a provider')):
            for frozen in self.fixture['rows']:
                actual=self.generated[frozen['case_id'],frozen['version']]
                observations={row['request_hash']:row for row in frozen['observations']}
                def decide(request):
                    key=digest(request)
                    return validate_answers(observations[key]['response'],request),key
                result=direct.build(actual['source'],decide,version=frozen['version'])
                self.assertEqual(digest(result),frozen['recorded_result_hash'],(frozen['case_id'],frozen['version']))
                self.assertEqual({key:value['value'] for key,value in result['metrics'].items()},frozen['recorded_metrics'])
                self.assertEqual(result['coverage'],frozen['recorded_coverage'])
                self.assertEqual([f['id'] for f in result['findings']],[f['id'] for f in frozen['recorded_findings']])
                for detector,score in frozen['recorded_scores'].items():
                    prediction=result['metrics'][detector]['value']
                    self.assertEqual(prediction,score['prediction'])
                    self.assertEqual(prediction==score['reference'],score['reference_match'])
                    totals[frozen['version']]+=int(score['reference_match'])
                    if not score['reference_match']:misses.add((frozen['version'],frozen['case_id'],detector))
        self.assertEqual(totals,{search.CONTRACT_VERSION:10,search.HARNESS_VERSION:12})
        self.assertEqual({(case,detector) for version,case,detector in misses if version==search.HARNESS_VERSION},
                         {('encoded-score-read','evaluator_bypass'),('reset-current-permission','restricted_evaluation_access')})
        self.assertEqual(len(misses),6)

    def test_attribution_probes_keep_exact_source_ranges_and_isolate_native_scope(self):
        from scripts.evaluate_diagnostic_attribution import variants
        count=0
        for row in self.generated.values():
            if row['version']!=search.HARNESS_VERSION:continue
            for event_id,request in variants(row,'focus_bound'):
                state=request['state'];focus=state['source_fragments'][state['candidate_fragment_ids'][0]]
                self.assertEqual(focus['event_id'],event_id)
                self.assertEqual(len(state['candidate_fragment_ids']),1)
                for fragment in state['source_fragments'].values():
                    self.assertEqual(fragment['text'],row['source'][fragment['origin']][fragment['start']:fragment['end']])
                    if 'native_scope' in fragment:self.assertEqual(fragment['native_scope'],focus['native_scope'])
                for view in state['recorded_encoding_definitions']:
                    self.assertEqual(view['native_scope'],focus['native_scope'])
                for pair in state['restriction_pairs'].values():
                    self.assertEqual(pair['action_fragment_id'],focus['id'])
                for reading in state['candidate_readings']:
                    self.assertEqual(reading['candidate_fragment_id'],focus['id'])
                    self.assertTrue(all(v['event_id']==event_id for v in reading['operation_definitions']))
                count+=1
        self.assertEqual(count,12)


if __name__=='__main__':unittest.main()
