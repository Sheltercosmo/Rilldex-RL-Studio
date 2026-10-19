"""Real saved selector outputs survive projection without repairing their labels."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tracker import work_scope_interpretations as scopes, work_qualified_contents as qualified
from tracker.schema import InputError, digest


def cases():
    path=Path(__file__).parent/'fixtures/feature-membership/scope-consequences.json'
    return json.loads(path.read_text(encoding='utf-8'))['cases']


class ScopeConsequenceReceiptTests(unittest.TestCase):
    def test_recorded_requests_and_argmax_choices_match_the_default_selector(self):
        for case in cases():
            with self.subTest(case=case['case']):
                p,b,f=case['packet'],case['bound'],case['feature_id']
                request=scopes.request(p,b,f)
                self.assertEqual(request,case['request'])
                self.assertEqual(digest(request),case['receipt']['request_hash'])
                self.assertEqual(digest(case['response']),case['receipt']['response_hash'])
                self.assertEqual(case['receipt']['status'],'response_received')
                decision=scopes.resolve(p,b,f,case['response'])
                self.assertEqual(decision,case['decision'])
                self.assertEqual(decision['selection_policy'],'argmax/1')
                for key in ('application','content_ids'):
                    self.assertEqual(decision['selected'][key],case['reference'][key])
                self.assertEqual(digest(scopes.project(p,b,f,decision)),case['projection_hash'])

    def test_shared_and_collective_qualifications_reach_the_relationship_input_intact(self):
        for case in cases():
            with self.subTest(case=case['case']):
                p,b,f=case['packet'],case['bound'],case['feature_id'];frozen=deepcopy((p,b))
                decision=case['decision'];projection=scopes.project(p,b,f,decision)
                view=qualified.project(p,b,scope_reviews=[dict(decision=decision)])
                row=next(q for q in view['qualifications'] if q['feature']['id']==f)
                chosen=decision['selected'];self.assertEqual(row['application'],chosen['application'])
                if row['application']=='joint':
                    self.assertEqual(projection['individual_applications'],[])
                    self.assertEqual(len(row['targets']),1)
                    self.assertEqual(row['targets'][0]['content_ids'],chosen['content_ids'])
                    self.assertEqual(row['targets'][0]['distribution'],'not_distributed')
                else:
                    self.assertEqual(projection['joint_applications'],[])
                    self.assertEqual([r['content']['id'] for r in projection['individual_applications']],chosen['content_ids'])
                    self.assertEqual([t['content_id'] for t in row['targets']],chosen['content_ids'])
                    self.assertTrue(all(t['status']=='not_reviewed' for t in row['targets']))
                self.assertFalse(view['ready_for_relationships'])  # Inventory/details were not reviewed in this experiment.
                self.assertEqual((p,b),frozen)

    def test_new_wording_has_a_distinct_request_and_cannot_relabel_a_saved_receipt(self):
        case=cases()[0];p,b,f=case['packet'],case['bound'],case['feature_id']
        self.assertNotEqual(scopes.request(p,b,f),scopes.request(p,b,f,version=scopes.LEGACY_VERSION))
        bad=deepcopy(case['decision']);bad['schema']=scopes.LEGACY_VERSION
        with self.assertRaisesRegex(InputError,'receipt changed'):scopes.project(p,b,f,bad)
        with self.assertRaises(InputError):scopes.request(p,b,f,version='unspecified')


if __name__=='__main__':unittest.main()
