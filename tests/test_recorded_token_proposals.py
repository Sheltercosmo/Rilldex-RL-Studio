"""Replay actual development receipts without paid calls or parser installs."""
import json
from pathlib import Path
import unittest
from tracker import work_content_stages as stages, work_content_bindings as scoped
from tracker.schema import digest

FIXTURE=Path(__file__).parent/'fixtures/feature-membership/token-proposals.json'


class RecordedTokenProposalTests(unittest.TestCase):
    def setUp(self):
        self.data=json.loads(FIXTURE.read_text(encoding='utf-8'))

    def replay(self, name):
        case=next(c for c in self.data['cases'] if c['case']==name)
        p,c,s=case['packet'],case['contents'],case['syntax']
        req=stages.scoped_feature_request(p,c,syntax=s)
        self.assertEqual(digest(req),case['request_hash'])
        b=stages.bind_scoped_features(p,c,req,case['proposal'],'gpt-6-luna token-addressed features',syntax=s)
        self.assertEqual(digest(b),case['bound_hash'])
        selected=scoped.select(p,b,case['response'])
        self.assertEqual(digest(selected),case['selected_hash'])
        self.assertEqual(b['contents'],c['contents'])
        return b,selected

    def test_all_recorded_proposals_bind_without_citation_repair(self):
        for name in ['installation','reasoning','retail']:
            with self.subTest(name=name):self.replay(name)

    def test_repeated_retail_pronouns_retain_their_actual_occurrences(self):
        b,_=self.replay('retail')
        occurrences=[f for f in b['features'] if f['type']=='subject' and f['expression']['text']=='I']
        self.assertEqual([f['expression']['start'] for f in occurrences],[21,76,127,241])
        self.assertEqual([f['scopes'] for f in occurrences],[[['c1']],[['c2']],[['c3']],[['c5']]])

    def test_shared_intention_is_available_and_selected_without_confidence_gate(self):
        for name,feature,expected in [('installation','f3',['c2','c3','c4']),('reasoning','f1',['c1','c2'])]:
            with self.subTest(name=name):
                b,selected=self.replay(name)
                self.assertIn(expected,next(f for f in b['features'] if f['id']==feature)['scopes'])
                self.assertEqual(next(f for f in selected['bindings'] if f['feature_id']==feature)['content_ids'],expected)

    def test_demonstrative_target_keeps_its_reference_form(self):
        b,_=self.replay('reasoning')
        feature=next(f for f in b['features'] if f['expression']['text']=='this expression')
        self.assertEqual(feature['form'],'unresolved_reference')


if __name__=='__main__':unittest.main()
