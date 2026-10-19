"""Several predicate roles survive one request without multiplying work units."""
from copy import deepcopy
import unittest
from tracker import work_argument_pairs as pairs
from tracker.schema import InputError
import test_argument_head_evidence as head_fixture
from test_work_qualified_contents import choose


class ArgumentPairTests(unittest.TestCase):
    def setUp(self):
        case=head_fixture.ArgumentHeadEvidenceTests();case.setUp()
        self.p,self.b,self.s,self.t,self.f=case.p,case.b,case.s,case.t,case.f

    def test_pair_choices_are_independent_and_project_multiple_roles(self):
        before=deepcopy((self.p,self.b,self.s,self.t))
        req=pairs.request(self.p,self.b,self.f,self.t,self.s)
        parts=req['state']['argument_pairs'];choices={'coverage':'covered','form':'unresolved_reference'}
        for p in parts:choices[p['question']]='not_argument'
        choices[parts[1]['question']]='recipient'
        choices[parts[2]['question']]='actor'
        raw=choose(req,choices) # Plumbing only; not a semantic reference for this public passage.
        d=pairs.resolve(self.p,self.b,self.f,self.t,self.s,raw)
        view=pairs.project(self.p,self.b,self.f,self.t,d)
        self.assertEqual([x['role'] for x in view['qualifications']],['recipient','actor'])
        self.assertEqual(len(view['relations']),3)
        self.assertEqual(view['new_work_items'],[])
        self.assertTrue(all(x['execution_status']=='not_established_by_prose' for x in view['qualifications']))
        self.assertEqual((self.p,self.b,self.s,self.t),before)

    def test_missing_coverage_keeps_positive_evidence_and_reports_partial_result(self):
        req=pairs.request(self.p,self.b,self.f,self.t,self.s)
        choices={p['question']:'not_argument' for p in req['state']['argument_pairs']}
        choices.update(coverage='missing_predicate',form='unresolved_reference')
        choices[req['state']['argument_pairs'][-1]['question']]='actor'
        d=pairs.resolve(self.p,self.b,self.f,self.t,self.s,choose(req,choices))
        v=pairs.project(self.p,self.b,self.f,self.t,d)
        self.assertEqual(v['status'],'partial')
        self.assertEqual(len(v['qualifications']),1)
        self.assertIn('predicate_coverage_missing_predicate',v['issues'])

    def test_mutated_response_or_source_cannot_replay_as_original_decision(self):
        req=pairs.request(self.p,self.b,self.f,self.t,self.s)
        d=pairs.resolve(self.p,self.b,self.f,self.t,self.s,choose(req))
        d['relations'][0]['role']='unresolved'
        with self.assertRaises(InputError):pairs.project(self.p,self.b,self.f,self.t,d)

    def test_each_pair_uses_raw_argmax_without_a_confidence_gate(self):
        req=pairs.request(self.p,self.b,self.f,self.t,self.s)
        raw=choose(req,{'coverage':'covered','form':'unresolved_reference'})
        question=req['state']['argument_pairs'][-1]['question']
        keys=req['questions'][question]['criteria'];total=len(keys)+.001
        raw['answers'][question].update(choice='not_argument',confidence=0,
            probabilities={k:(1.001 if k=='actor' else 1)/total for k in keys})
        d=pairs.resolve(self.p,self.b,self.f,self.t,self.s,raw)
        self.assertEqual(d['relations'][-1]['role'],'actor')


if __name__=='__main__':unittest.main()
