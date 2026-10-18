from copy import deepcopy
from functools import partial
from unittest import TestCase
from unittest.mock import patch

from tracker.adapters import normalize
from tracker import criterion_review as review
from tracker.schema import InputError, digest
from tracker.semantic_map import evidence

legacy_request = partial(review.make_request, protocol=review.VERSION)


def fixture():
    run = normalize(dict(trajectory_format='devai/1', trajectory=[
        dict(step=0, user_message='Write /output/data.bin with valid framing and all records.',
             agent=dict(thought='I think the format is correct.', action='write_file("/output/data.bin", payload)'),
             environment='Process exited with code 0.'),
        dict(step=1, user_message='Use the other path next time.', agent=dict(thought=None,action='read_file("/output/data.bin")'),
             environment='future result'),
    ]))[0]
    events=run['events']
    term=next(e for e in events if e['actor']=='user')
    action=next(e for e in events if e['kind']=='action')
    feedback=next(e for e in events if e['kind']=='feedback')
    thought=next(e for e in events if e['actor']=='agent' and e['kind']=='reasoning')
    return run, {name:evidence(run,event['id']) for name,event in dict(term=term,action=action,feedback=feedback,thought=thought).items()}


class CriterionReviewTests(TestCase):
    def test_new_reviews_require_a_basis_and_invalid_protocols_fail(self):
        run,refs=fixture()
        for kwargs in [{},{'basis':[]},{'basis':'dispatch','protocol':'unversioned'},
                       {'basis':'dispatch','protocol':review.VERSION}]:
            with self.assertRaises(InputError):review.make_request(run,refs['term'],refs['action'],**kwargs)

    def test_declared_evidence_basis_binds_findings_to_the_witness(self):
        run,refs=fixture()
        for kind,basis in [('action','dispatch'),('action','implementation'),('feedback','check_result'),('thought','participant_report')]:
            req=review.make_request(run,refs['term'],refs[kind],basis=basis)
            self.assertEqual(req['state']['harness'],review.TYPED_VERSION)
            self.assertEqual(req['state']['evidence_basis']['origin'],'caller_declared')
            self.assertEqual(set(req['questions']['reading']['criteria']),
                             review.BASIS[basis] | {'insufficient_property_evidence','ambiguous_requirement','unresolved'})
        for kind,basis in [('thought','check_result'),('feedback','dispatch'),('action','unknown')]:
            with self.assertRaises(InputError):review.make_request(run,refs['term'],refs[kind],basis=basis)

    def test_source_identity_attribution_and_cutoff_are_preserved(self):
        run,refs=fixture();before=deepcopy(run)
        req=review.make_request(run,refs['term'],refs['feedback'],context=[refs['action']],basis='check_result')
        self.assertEqual(req['state']['source_hash'],digest(run))
        self.assertEqual(req['state']['candidate']['actor'],'environment')
        self.assertEqual(req['state']['context'][0]['source'],refs['action'])
        self.assertNotIn('future result',str(req))
        self.assertEqual(run,before)
        self.assertIn('valid framing and all records',req['state']['criterion']['source']['text'])

    def test_kind_limits_do_not_turn_claims_into_recorded_checks(self):
        run,refs=fixture()
        for kind in ['thought','action','feedback']:
            choices=legacy_request(run,refs['term'],refs[kind])['questions']['reading']['criteria']
            self.assertEqual('matching_dispatch' in choices,kind=='action')
            self.assertEqual('recorded_check_success' in choices,kind=='feedback')
            self.assertIn('unresolved',choices)
            self.assertIn('insufficient_property_evidence',choices)

    def test_corrupt_future_cross_context_and_hidden_refs_fail(self):
        run,refs=fixture()
        bad=deepcopy(refs['term']);bad['text']='invented criterion'
        with self.assertRaisesRegex(InputError,'Evidence mismatch'):
            review.make_request(run,bad,refs['action'],basis='implementation')
        with self.assertRaisesRegex(InputError,'Future'):
            review.make_request(run,refs['term'],refs['action'],context=[refs['feedback']],basis='implementation')
        for key,value,pattern in [('context_id','different','another recorded context'),
                                  ('trajectory_id','other','another trajectory'),
                                  ('agent_visibility','not_established','not established as agent-visible'),
                                  ('copied_context',True,'Copied context')]:
            changed=deepcopy(run)
            next(e for e in changed['events'] if e['id']==refs['term']['event_id'])[key]=value
            with self.assertRaisesRegex(InputError,pattern):
                review.make_request(changed,refs['term'],refs['action'],basis='implementation')

    def test_explicit_budget_and_duplicate_context_fail_before_inference(self):
        run,refs=fixture()
        with self.assertRaisesRegex(InputError,'Duplicate'):
            review.make_request(run,refs['term'],refs['feedback'],context=[refs['action'],refs['action']],basis='check_result')
        with patch.object(review,'MAX_BYTES',10):
            with self.assertRaisesRegex(InputError,'byte budget'):
                review.make_request(run,refs['term'],refs['action'],basis='implementation')

    def test_raw_argmax_receipt_keeps_review_separate_from_verification(self):
        run,refs=fixture()
        req=review.make_request(run,refs['term'],refs['action'],basis='dispatch',context=[refs['thought']])
        choices=req['questions']['reading']['criteria']
        response=dict(model=req['model'],answers=dict(reading=dict(type='choice',choice='matching_dispatch',confidence=1,
            probabilities={k:.7 if k=='insufficient_property_evidence' else .3/(len(choices)-1) for k in choices})))
        result=review.resolve(run,refs['term'],refs['action'],response,basis='dispatch',context=iter([refs['thought']]))
        self.assertEqual(result['reading'],'insufficient_property_evidence')
        self.assertEqual(result['request_hash'],digest(req))
        self.assertEqual(result['publication'],'review_only')
        self.assertEqual(result['reward_hacking'],'not_established')
        self.assertEqual(result['runtime_verification'],'not_performed')
        self.assertEqual(result['context'],[refs['thought']])
        self.assertEqual(result['evidence_basis']['value'],'dispatch')
        with self.assertRaisesRegex(InputError,'model differs'):
            review.resolve(run,refs['term'],refs['action'],dict(response,model='another'),basis='dispatch')
