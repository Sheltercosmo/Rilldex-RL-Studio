from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from tracker import condition_grounding as cg
from tracker.schema import InputError,digest
from tracker.semantic_extraction import Pipeline,FileCandidates,read,write
from research.condition_dispatch_trial import fixture,CASES


class ConditionGroundingTests(TestCase):
    def setup_case(self,index=0):
        run,doc=fixture(CASES[index]);pair=cg.candidates(run,doc)[-1]
        return run,doc,pair

    def answer(self,req,operation='direct',subject='within_scope',support='none',contradiction='none'):
        stage=req['state']['stage'].removeprefix('condition_grounding_')
        values={'support':support,'contradiction':contradiction} if stage=='evidence' else {'choice':operation if stage=='operation' else subject}
        return {k:{'value':v} for k,v in values.items()},digest(req)

    def test_non_direct_operation_stops_before_subject_and_evidence(self):
        for choice in ['preparatory','different_operation','unresolved']:
            run,doc,pair=self.setup_case();calls=[]
            def decide(req):calls.append(req);return self.answer(req,operation=choice)
            result=cg.build(run,doc,decide,[pair['id']])
            self.assertEqual(len(calls),1)
            self.assertEqual(result['pairs'][0]['status'],'operation_'+choice)
            self.assertEqual(result['pairs'][0]['witnesses'],{})

    def test_different_instance_stops_without_compliance_judgment(self):
        run,doc,pair=self.setup_case(7);calls=[]
        def decide(req):calls.append(req);return self.answer(req,subject='different_instance')
        row=cg.build(run,doc,decide,[pair['id']])['pairs'][0]
        self.assertEqual(len(calls),2);self.assertEqual(row['status'],'subject_different_instance')
        self.assertNotIn('evidence',row['requests'])
        self.assertIn('demanded',calls[1]['questions']['choice']['criteria']['within_scope'])

    def test_missing_proof_is_not_a_positive_contradiction(self):
        run,doc,pair=self.setup_case(4);original=deepcopy(doc);calls=[]
        def decide(req):calls.append(req);return self.answer(req)
        row=cg.build(run,doc,decide,[pair['id']])['pairs'][0]
        self.assertEqual(row['status'],'not_established');self.assertEqual(row['witnesses'],{})
        self.assertEqual(doc,original);self.assertNotIn('WITHHELD_FUTURE_RESULT',str(calls))
        self.assertEqual(calls[-1]['state']['earlier_selections'],{'operation':'direct','subject':'within_scope'})

    def test_selected_witness_carries_exact_readable_source_ranges(self):
        run,doc,pair=self.setup_case(5)
        event=next(e for e in run['events'] if e['kind']=='feedback')
        result=cg.build(run,doc,lambda req:self.answer(req,support=event['id']),[pair['id']])
        row=result['pairs'][0];witness=row['witnesses']['support']
        self.assertEqual(row['status'],'support_recorded')
        self.assertEqual(witness['source_pointer'],event['source_pointer'])
        self.assertEqual(witness['source_text_ranges'],[{'source_start':0,'source_end':len(event['text']),'view_start':0,'view_end':len(event['text'])}])

    def test_projected_witness_does_not_claim_omitted_text(self):
        case={**CASES[5],'feedback':'Issuer response: card A has $50. '+('unrelated detail '*1000)}
        run,doc=fixture(case);pair=cg.candidates(run,doc)[-1]
        event=next(e for e in run['events'] if e['kind']=='feedback')
        req=cg.make_request(run,pair,'evidence',{'operation':'direct','subject':'within_scope'})
        projected=next(e for e in req['state']['prefix'] if e['id']==event['id'])
        row=cg.build(run,doc,lambda r:self.answer(r,support=event['id']),[pair['id']])['pairs'][0]
        self.assertEqual(row['witnesses']['support']['source_text_ranges'],projected['source_text_ranges'])
        self.assertLess(sum(r['source_end']-r['source_start'] for r in projected['source_text_ranges']),len(event['text']))

    def test_copied_context_is_not_a_new_witness_option(self):
        run,doc,pair=self.setup_case();event=next(e for e in run['events'] if e['kind']=='feedback')
        event['copied_context']=True;event['text']='COPIED_APPROVAL_NOT_CURRENT'
        doc['source_hash']=doc['requested_work']['source_hash']=digest(run);pair=cg.candidates(run,doc)[-1]
        req=cg.make_request(run,pair,'evidence',{})
        self.assertNotIn('COPIED_APPROVAL_NOT_CURRENT',str(req))
        self.assertNotIn(event['id'],req['questions']['support']['criteria'])
        self.assertIn(event['id'],req['state']['excluded_copied_context_event_ids'])

    def test_positive_sides_and_unresolved_states_remain_distinct(self):
        run,doc,pair=self.setup_case();eid=pair['action']['source']['event_id']
        for support,contradiction,status in [('none',eid,'contradiction_recorded'),(eid,eid,'mixed_evidence'),
                ('several_required','none','needs_evidence_set'),('unresolved','none','evidence_unresolved')]:
            row=cg.build(run,doc,lambda r:self.answer(r,support=support,contradiction=contradiction),[pair['id']])['pairs'][0]
            self.assertEqual(row['status'],status)

    def test_subset_and_excluded_kinds_have_explicit_coverage(self):
        run,doc,pair=self.setup_case();result=cg.build(run,doc,lambda r:self.answer(r),[pair['id']])
        self.assertEqual(result['coverage']['candidate_pairs'],2);self.assertEqual(result['coverage']['selected_pairs'],1)
        for index in [9,12]:
            run,doc=fixture(CASES[index]);result=cg.build(run,doc,lambda r:self.fail('Out-of-scope kind triggered inference'))
            self.assertEqual(result['pairs'],[]);self.assertEqual(result['coverage']['represented_actions'],2)

    def test_invalid_ids_answers_and_context_limit_do_not_become_negatives(self):
        run,doc,pair=self.setup_case()
        for ids in [['missing'],[pair['id'],pair['id']]]:
            with self.assertRaises(InputError):cg.build(run,doc,lambda r:self.fail('Invalid selection reached inference'),ids)
        with self.assertRaises(InputError):cg.build(run,doc,lambda r:({'choice':{'value':'invented'}},digest(r)))
        with self.assertRaises(InputError):cg.build(run,doc,lambda r:({'choice':{'value':'direct'}},'wrong-hash'))
        with patch.object(cg,'MAX_CHARS',1):result=cg.build(run,doc,lambda r:self.fail('Oversized context reached inference'))
        self.assertTrue(all(p['status']=='needs_context_selection' and not p['selections'] for p in result['pairs']))

    def test_raw_argmax_replay_cache_and_tamper_detection(self):
        run,doc,pair=self.setup_case();calls=[]
        def transport(req):
            calls.append(req);winners=self.answer(req)[0]
            return {'model':req['model'],'answers':{k:{'type':'choice','choice':'unresolved','confidence':0,
                'probabilities':{v:.7 if v==winners[k]['value'] else .3/(len(q['criteria'])-1) for v in q['criteria']}}
                for k,q in req['questions'].items()}}
        with TemporaryDirectory() as directory:
            engine=Pipeline(directory,FileCandidates(directory),transport)
            result=cg.build(run,doc,engine.decide,[pair['id']]);self.assertEqual(len(calls),3)
            self.assertTrue(cg.audit(run,doc,result,directory)['raw_argmax_replayed'])
            cg.build(run,doc,engine.decide,[pair['id']]);self.assertEqual(len(calls),3)
            key=result['pairs'][0]['requests']['evidence'];path=Path(directory)/'decisions'/f'{key}.json'
            saved=read(path);saved['answers']['support']['value']='unresolved';write(path,saved)
            with self.assertRaisesRegex(InputError,'argmax'):cg.audit(run,doc,result,directory)

    def test_trial_budget_counts_prior_http_attempts_and_reuses_wire(self):
        from research.condition_grounding_trial import BoundedTransport
        calls=[]
        def send(req):calls.append(req);return {'model':'test','usage':{'input_tokens':10}}
        with TemporaryDirectory() as directory:
            root=Path(directory);first=BoundedTransport(root,1,send)
            response=first({'request':1});self.assertEqual(first.calls,1)
            resumed=BoundedTransport(root,1,send)
            self.assertEqual(resumed({'request':1}),response);self.assertEqual(resumed.calls,0)
            with self.assertRaisesRegex(InputError,'Aggregate'):resumed({'request':2})
            self.assertEqual(len(calls),1);self.assertEqual(read(root/'attempts'/'00001.json')['status'],'response_received')

    def test_unknown_http_attempt_is_not_automatically_repeated(self):
        from research.condition_grounding_trial import BoundedTransport
        with TemporaryDirectory() as directory:
            root=Path(directory);write(root/'attempts'/'00001.json',{'status':'pending'})
            transport=BoundedTransport(root,48,lambda r:self.fail('Unknown request repeated'))
            with self.assertRaisesRegex(InputError,'unknown outcome'):transport({'request':1})

    def test_failed_http_attempt_still_consumes_budget(self):
        from research.condition_grounding_trial import BoundedTransport
        def fail(req):raise TimeoutError('body must not be stored')
        with TemporaryDirectory() as directory:
            root=Path(directory);transport=BoundedTransport(root,1,fail)
            with self.assertRaises(TimeoutError):transport({'request':1})
            record=read(root/'attempts'/'00001.json')
            self.assertEqual(record['error_type'],'TimeoutError');self.assertNotIn('body',str(record))
            with self.assertRaisesRegex(InputError,'Aggregate'):BoundedTransport(root,1,fail)({'request':1})
            with self.assertRaisesRegex(InputError,'unknown outcome'):BoundedTransport(root,2,fail)({'request':1})

    def test_revision_has_explicit_witness_roles_without_rewriting_original_requests(self):
        run,doc,pair=self.setup_case()
        original=cg.make_request(run,pair,'evidence',{})
        revised=cg.make_request(run,pair,'evidence',{},cg.EVIDENCE_BINDING_VERSION)
        eid=pair['action']['source']['event_id']
        self.assertNotIn('CURRENT DISPATCH',str(original))
        self.assertIn('CURRENT DISPATCH',revised['questions']['support']['criteria'][eid])
        self.assertIn('Do not cite the request as fulfillment of itself',revised['questions']['support']['instructions'])
        self.assertEqual(original,cg.make_request(run,pair,'evidence',{}))
        self.assertNotEqual(digest(original),digest(revised))

    def test_revision_replay_uses_saved_protocol(self):
        run,doc,pair=self.setup_case()
        def transport(req):
            winners=self.answer(req)[0]
            return {'model':req['model'],'answers':{k:{'type':'choice','probabilities':{
                v:1 if v==winners[k]['value'] else 0 for v in q['criteria']}} for k,q in req['questions'].items()}}
        with TemporaryDirectory() as directory:
            engine=Pipeline(directory,FileCandidates(directory),transport)
            result=cg.build(run,doc,engine.decide,[pair['id']],cg.EVIDENCE_BINDING_VERSION)
            self.assertTrue(cg.audit(run,doc,result,directory)['raw_argmax_replayed'])
            result['schema']='invented'
            with self.assertRaises(InputError):cg.audit(run,doc,result,directory)

    def test_polarity_repair_only_changes_evidence_packets(self):
        run,doc,pair=self.setup_case()
        for stage in ['operation','subject']:
            self.assertEqual(cg.make_request(run,pair,stage,{},cg.EVIDENCE_BINDING_VERSION),
                             cg.make_request(run,pair,stage,{},cg.POLARITY_VERSION))
        req=cg.make_request(run,pair,'evidence',{},cg.POLARITY_VERSION)
        self.assertNotIn('select that record',str(req))
        eid=pair['action']['source']['event_id']
        self.assertIn('agrees',req['questions']['support']['criteria'][eid])
        self.assertIn('disagrees',req['questions']['contradiction']['criteria'][eid])
        self.assertIn('when values agree',req['questions']['contradiction']['criteria']['none'])

    def test_contract_interning_preserves_evidence_and_prior_stage_requests(self):
        from tracker.packet_interning import expand
        run,doc,pair=self.setup_case()
        for stage in ['operation','subject','evidence']:
            old=cg.make_request(run,pair,stage,{},cg.POLARITY_VERSION)
            new=cg.make_request(run,pair,stage,{},cg.SHARED_CONTRACT_VERSION)
            if stage=='evidence':old['state']['condition_harness']=cg.SHARED_CONTRACT_VERSION
            self.assertEqual(expand(new),old)
