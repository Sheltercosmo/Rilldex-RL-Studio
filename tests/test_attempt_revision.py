from copy import deepcopy
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from tracker import attempt_revision as ar
from tracker.schema import digest,InputError
from tracker.semantic_extraction import Pipeline
from research.attempt_revision_trial import fixture,CASES


class AttemptRevisionTests(TestCase):
    def test_wire_encoding_preserves_every_source_character_and_unit(self):
        run,doc=fixture(CASES[0]);a,b=[u['id'] for u in doc['units'] if u['kind']=='action']
        req=ar.declaration_request(run,doc,a,b)
        req['state']['source_ranges'][0]['text']+='\n'+'━'*100+'\nend'
        compact=ar.compact_request(req)
        self.assertEqual(ar.expand_request(compact),req)
        self.assertLess(len(str(compact)),len(str(req)))
        self.assertNotIn('content',compact['state']['rationale_candidates'][0])
        self.assertIn('text_runs',compact['state']['source_ranges'][0])

    def decide(self,req):
        choice='procedure_change' if req['state']['stage']=='declared_change' else req['state']['current']['unit_id']
        return {k:{'value':choice} for k in req['questions']},digest(req)

    def test_source_bound_declared_change_and_execution_are_separate(self):
        run,doc=fixture(CASES[0]);before=deepcopy(doc);requests=[]
        def decide(req):requests.append(req);return self.decide(req)
        result=ar.build(run,doc,decide)
        self.assertEqual(len(requests),2);self.assertNotIn('WITHHELD_FUTURE_RESULT',str(requests))
        change=result['observations'][0]['declarations'][0]
        self.assertEqual(change['selection'],'procedure_change')
        projected=ar.project(run,{'document':doc},result)['document']
        self.assertEqual(doc,before);self.assertEqual(projected['units'],doc['units'])
        self.assertTrue(any(r['type']=='changes_attempt_procedure' for r in projected['relations']))
        self.assertTrue(any(r['type']=='attempts_declared_change' for r in projected['relations']))
        self.assertFalse(any(r['type']=='revises' for r in projected['relations']))

    def test_no_matching_action_keeps_declaration_without_fabricated_execution(self):
        run,doc=fixture(CASES[4])
        def decide(req):
            answers,key=self.decide(req)
            if req['state']['stage']=='change_execution':answers['execution']['value']='no_matching_action'
            return answers,key
        result=ar.build(run,doc,decide);p=ar.project(run,{'document':doc},result)['document']
        self.assertTrue(any(r['type']=='changes_attempt_procedure' for r in p['relations']))
        self.assertFalse(any(r['type']=='attempts_declared_change' for r in p['relations']))

    def test_both_changes_have_independent_execution_selections(self):
        run,doc=fixture(CASES[10])
        def decide(req):
            if req['state']['stage']=='declared_change':return {k:{'value':'procedure_and_prerequisite'} for k in req['questions']},digest(req)
            selected=req['state']['current']['unit_id'] if req['state']['declared_change']['selection']=='procedure_change' else 'no_matching_action'
            return {'execution':{'value':selected}},digest(req)
        result=ar.build(run,doc,decide);p=ar.project(run,{'document':doc},result)['document'];types=[r['type'] for r in p['relations']]
        self.assertIn('changes_attempt_procedure',types);self.assertIn('changes_attempt_prerequisite',types)
        self.assertEqual(types.count('attempts_declared_change'),1)

    def test_unrepresented_expression_is_unknown_not_no_revision(self):
        run,doc=fixture(CASES[0]);candidate=next(u for u in doc['units'] if u['source']['text']==CASES[0]['thought'])
        doc['units'].remove(candidate);doc['relations']=[r for r in doc['relations'] if r['from']!=candidate['id']]
        result=ar.build(run,doc,lambda req:self.fail('No supplied unit should be classified'))
        self.assertEqual(result['observations'][0]['status'],'unknown')
        self.assertFalse(result['observations'][0]['complete_candidate_window'])

    def test_wrong_work_dispute_and_budget_keep_unavailable(self):
        for variant in ('different_work','disputed','budget'):
            run,doc=fixture(CASES[0]);method=doc['method_comparison']['observations'][0]
            if variant=='different_work':method['work_instance']='different_work'
            if variant=='disputed':method['upstream_identity_disputed']=True
            with patch.object(ar,'MAX_CHARS',0 if variant=='budget' else ar.MAX_CHARS):
                result=ar.build(run,doc,lambda req:self.fail('Ineligible source must not invoke the model'))
            self.assertIn(result['observations'][0]['status'],{'ineligible','uninspected'})

    def test_invalid_selection_and_changed_projection_are_rejected(self):
        run,doc=fixture(CASES[0])
        with self.assertRaises(InputError):ar.build(run,doc,lambda req:({k:{'value':'invented'} for k in req['questions']},digest(req)))
        result=ar.build(run,doc,self.decide);doc['units'][0]['content']['target']['text']='changed'
        with self.assertRaises(InputError):ar.project(run,{'document':doc},result)

    def test_saved_probability_argmax_is_replayed_without_thresholds(self):
        run,doc=fixture(CASES[0])
        def transport(req):
            answers,_=self.decide(req)
            return {'model':req['model'],'answers':{k:{'type':'choice','choice':'wrong_claimed_winner','confidence':0,
                'probabilities':{v:float(v==answers[k]['value']) for v in q['criteria']}} for k,q in req['questions'].items()}}
        with TemporaryDirectory() as folder:
            p=Pipeline(folder,None,transport);result,validation=ar.execute(run,doc,p)
            self.assertTrue(validation['argmax_replayed']);self.assertEqual(p.calls,2)
            ar.execute(run,doc,p);self.assertEqual(p.calls,2)
