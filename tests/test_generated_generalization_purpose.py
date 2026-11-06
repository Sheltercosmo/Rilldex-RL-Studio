"""Replay the controlled diagnosis on freshly generated whole-trace workspaces."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tracker.jev import validate_answers
from tracker.schema import digest


class GeneratedPurposeEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=json.loads((Path(__file__).parent/'fixtures/generated-generalization-purpose.json').read_text(encoding='utf8'))['rows']

    def test_live_receipts_remain_bound_to_actual_requests(self):
        self.assertEqual(len(self.rows),44)
        for row in self.rows:
            with self.subTest(case=row['case_id'],event=row['event_id'],arm=row['arm']):
                self.assertEqual(digest(row['request']),row['request_hash'])
                self.assertEqual(row['response']['model'],row['request']['model'])
                answer=validate_answers(row['response'],row['request'])['choice']
                self.assertEqual(answer['value'],row['prediction'])

    def test_context_highlight_did_not_fix_the_boundary_failure(self):
        correct=Counter(row['arm'] for row in self.rows if row['correct'])
        self.assertEqual(dict(correct),dict(original=9,recent_expression=9,purpose_boundary=11,both=11))
        for arm in ('original','recent_expression'):
            failures={(r['case_id'],r['event_id']) for r in self.rows if r['arm']==arm and not r['correct']}
            self.assertEqual(failures,{('simulation','e12'),('service','e12')})

    def test_ablations_keep_source_native_links_and_all_choices(self):
        originals={(r['case_id'],r['event_id']):r['request'] for r in self.rows if r['arm']=='original'}
        for row in self.rows:
            q=deepcopy(row['request']);baseline=originals[row['case_id'],row['event_id']]
            if row['arm'] in {'recent_expression','both'}:
                highlighted=q['state'].pop('recent_expression_context')
                if highlighted['source'] is not None:self.assertIn(highlighted['source'],baseline['state']['prefix'])
            if row['arm'] in {'purpose_boundary','both'}:
                self.assertTrue(q['questions']['choice']['instructions'].startswith(baseline['questions']['choice']['instructions']))
                q['questions']['choice']['instructions']=baseline['questions']['choice']['instructions']
            self.assertEqual(q,baseline)
