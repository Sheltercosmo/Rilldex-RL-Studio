"""Replay actual responses; retained development disagreements remain visible."""
import json
from pathlib import Path
import unittest

from tracker import work_content_bindings as scoped


class ScopeMembershipReplayTests(unittest.TestCase):
    def test_frozen_requests_selections_and_source_qualifications(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/scope_membership.json').read_text(encoding='utf-8'))
        clarified=[];known_failure=False
        for case in fixture['cases']:
            with self.subTest(case=case['case']):
                p,b,f=case['packet'],case['bound'],case['feature_id'];rule=case['intent_rule']
                self.assertEqual(scoped.membership_scope_request(p,b,f,intent_rule=rule),case['request'])
                result=scoped.membership_scope_result(p,b,f,case['response'],intent_rule=rule)
                self.assertEqual(result,case['result'])
                view=scoped.project_membership_scope(p,b,result)
                self.assertEqual(view['unit']['source'],case['request']['state']['unit']['source'])
                self.assertEqual({c['id'] for c in view['contents'] if c['scope_status']=='applies'},set(result['supported_content_ids']))
                agrees=result['content_ids']==sorted(case['reference']['expected_content_ids'])
                if rule=='expressed_work':clarified.append(agrees)
                if 'shared-intent/attachment' in case['case']:
                    known_failure=True;self.assertFalse(agrees)
        self.assertTrue(known_failure)
        self.assertEqual(clarified,[True]*4)


if __name__=='__main__':unittest.main()
