"""Head hints change the question, never source spans or selected probabilities."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tracker import work_content_targets as targets
from tracker.schema import InputError
from test_work_qualified_contents import choose

FIXTURE=Path(__file__).parent/'fixtures/feature-membership/argument-targets.json'


class ArgumentHeadEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.case=next(c for c in json.loads(FIXTURE.read_text(encoding='utf-8'))['cases']
                       if c['case']=='retail-embedded-listing')
        self.p,self.b,self.s=self.case['packet'],self.case['bound'],self.case['syntax']
        self.t=self.case['arms']['arguments-head']['targets'];self.f=self.case['feature_id']

    def request(self):
        return targets.request(self.p,self.b,self.f,self.t,version=targets.ARGUMENT_SYNTAX_VERSION,syntax_record=self.s)

    def test_heads_are_exact_source_tokens_and_choice_inventory_is_preserved(self):
        before=deepcopy((self.p,self.b,self.s,self.t)); req=self.request()
        old=targets.request(self.p,self.b,self.f,self.t,version=targets.ARGUMENT_HEAD_VERSION)
        self.assertEqual(set(req['questions']['target']['criteria']),set(old['questions']['target']['criteria']))
        self.assertEqual(req['state']['details'],old['state']['details'])
        self.assertEqual(req['state']['source_with_argument_occurrence'],old['state']['source_with_argument_occurrence'])
        hints=req['state']['predicate_head_evidence']
        self.assertEqual(hints['syntax_id'],self.s['id'])
        self.assertEqual([v['tokens'][0]['text'] for v in hints['candidates'].values()],['confirm','want','list'])
        source=self.s['parsed']['source']
        for item in hints['candidates'].values():
            for token in item['tokens']:
                self.assertEqual(source['text'][token['start']-source['start']:token['end']-source['start']],token['text'])
        self.assertEqual((self.p,self.b,self.s,self.t),before)

    def test_raw_argmax_still_controls_selection_and_roundtrip_retains_syntax(self):
        req=self.request(); selected='outside_content'
        raw=choose(req,{'target':selected,'form':'unresolved_reference'})
        keys=req['questions']['target']['criteria']; total=len(keys)+.001
        raw['answers']['target'].update(choice='actor::whole_content',confidence=1,
            probabilities={k:(1.001 if k==selected else 1)/total for k in keys})
        d=targets.resolve(self.p,self.b,self.f,self.t,raw,version=targets.ARGUMENT_SYNTAX_VERSION,syntax_record=self.s)
        self.assertEqual(d['target_choice'],selected)
        self.assertEqual(d['syntax'],self.s)
        v=targets.project(self.p,self.b,self.f,self.t,json.loads(json.dumps(d)))
        self.assertIsNone(v['qualification'])
        self.assertEqual(v['new_base_units'],[])

    def test_source_mismatch_or_missing_syntax_is_rejected_before_transport(self):
        with self.assertRaises(InputError):
            targets.request(self.p,self.b,self.f,self.t,version=targets.ARGUMENT_SYNTAX_VERSION)
        altered=deepcopy(self.s);altered['parsed']['tokens'][0]['text']='wrong'
        with self.assertRaises(InputError):
            targets.request(self.p,self.b,self.f,self.t,version=targets.ARGUMENT_SYNTAX_VERSION,syntax_record=altered)
        with self.assertRaises(InputError):
            targets.request(self.p,self.b,self.f,self.t,version=targets.ARGUMENT_HEAD_VERSION,syntax_record=self.s)


if __name__=='__main__':unittest.main()
