"""Exact replay of prior code-flow/artifact pages and production21 regressions."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.evaluate_diagnostic_specialized import page_value
from tracker import diagnostic_direct as direct, diagnostic_search as search
from tracker.jev import validate_answers
from tracker.schema import digest


class DiagnosticSpecializedLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=json.loads((Path(__file__).parent/'fixtures/diagnostic-specialized-live.json').read_text(encoding='utf-8'))

    def test_exact_sources_regenerate_both_baseline_and_production_page_hashes(self):
        unchanged=0
        with patch('urllib.request.urlopen',side_effect=AssertionError('Source replay is offline')):
            for case in self.fixture['cases']:
                self.assertEqual(digest(case['source']),case['source_hash'])
                requests=[]
                for version,key in [(search.CONTRACT_VERSION,'baseline_request_hash'),(search.ATTRIBUTED_VERSION,'production_request_hash')]:
                    request=next(r for r in direct.requests(case['source'],version) if r['state']['page']==case['page'])
                    self.assertEqual(digest(request),case[key],(case['id'],version))
                    requests.append(request)
                    for fragment in request['state']['source_fragments'].values():
                        self.assertEqual(fragment['text'],case['source'][fragment['origin']][fragment['start']:fragment['end']])
                self.assertEqual(requests[0]==requests[1],case['packet_unchanged'])
                unchanged+=int(case['packet_unchanged'])
        self.assertEqual(unchanged,4)

    def test_all_actual_baseline_and_new_raw_selections_replay(self):
        receipts=self.fixture['receipts'];matched=0
        self.assertEqual(len(receipts),12)
        for case in self.fixture['cases']:
            for version,key,expected in [(search.CONTRACT_VERSION,'baseline_request_hash',case['baseline_prediction']),
                                        (search.ATTRIBUTED_VERSION,'production_request_hash',case['production_prediction'])]:
                request=next(r for r in direct.requests(case['source'],version) if r['state']['page']==case['page'])
                observation=receipts[case[key]];response=observation['response']
                self.assertEqual(digest(response),observation['response_hash'])
                self.assertEqual(response['model'],request['model'])
                answers=validate_answers(response,request)
                for name,question in request['questions'].items():
                    self.assertEqual(answers[name]['value'],max(question['criteria'],key=response['answers'][name]['probabilities'].get))
                self.assertEqual(page_value(request,response),expected)
            matched+=int(case['production_prediction']==case['expected_bypass'])
        self.assertEqual(matched,8)


if __name__=='__main__':unittest.main()
