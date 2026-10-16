from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from tracker import condition_dispatch as cd
from tracker.schema import InputError,digest
from tracker.semantic_extraction import Pipeline,FileCandidates,read,write
from research.condition_dispatch_trial import fixture,CASES


class ConditionDispatchTests(TestCase):
    def choose(self,req):
        field='alignment' if req['state']['stage']=='condition_alignment' else 'scope'
        return {key:{'value':'aligned' if field=='alignment' else 'applies'} for key in req['questions']},digest(req)

    def test_applicability_precedes_alignment_and_later_evidence_is_excluded(self):
        run,doc=fixture(CASES[3]);calls=[];original=deepcopy(doc)
        def decide(req):calls.append(req);return self.choose(req)
        result=cd.build(run,doc,decide)
        self.assertNotIn('WITHHELD_FUTURE_RESULT',str(calls));self.assertEqual(doc,original)
        self.assertEqual([r['state']['stage'] for r in calls],['condition_routing','condition_alignment']*2)
        self.assertEqual(result['actions'][-1]['conditions'][0]['selections'],{'scope':'applies','alignment':'aligned'})

    def test_outside_or_unresolved_scope_cannot_acquire_an_alignment_verdict(self):
        for value in ['outside_scope','unresolved']:
            run,doc=fixture(CASES[0]);calls=[]
            def decide(req):
                calls.append(req);return {k:{'value':value} for k in req['questions']},digest(req)
            result=cd.build(run,doc,decide)
            self.assertEqual(len(calls),2)
            self.assertTrue(all('alignment' not in i['selections'] for a in result['actions'] for i in a['conditions']))

    def test_checks_and_claims_do_not_become_requirement_compliance(self):
        run,doc=fixture(CASES[9]);calls=[]
        def decide(req):calls.append(req);return {k:{'value':'attempts'} for k in req['questions']},digest(req)
        result=cd.build(run,doc,decide)
        self.assertEqual(result['actions'][-1]['conditions'][0]['selections'],{'check':'attempts'})
        run,doc=fixture(CASES[12]);result=cd.build(run,doc,lambda r:self.fail('Claim triggered a model call'))
        self.assertTrue(all(i['status']=='claim_not_obligation' for a in result['actions'] for i in a['conditions']))

    def test_budgeted_context_is_uninspected_not_a_negative(self):
        run,doc=fixture(CASES[0])
        with patch.object(cd,'MAX_CHARS',1):result=cd.build(run,doc,lambda r:self.fail('Over-budget request'))
        self.assertTrue(all(not i['selections'] and i['status']=='needs_context_selection' for a in result['actions'] for i in a['conditions']))

    def test_missing_clauses_and_unrepresented_actions_are_coverage_gaps(self):
        from test_request_dispatch import fixture as older
        run,doc,actions=older();doc.pop('work_correspondence');doc['relations']=[]
        doc['units']=[u for u in doc['units'] if u['id']!=actions[0]['id']]
        result=cd.build(run,doc,lambda r:self.fail('Unstructured condition should not be classified'))
        self.assertEqual(result['unrepresented_action_event_ids'],[actions[0]['source']['event_id']])
        self.assertTrue(result['actions'][0]['unstructured_record_versions'])

    def test_raw_argmax_cache_and_tamper_detection(self):
        run,doc=fixture(CASES[0]);calls=[]
        def transport(req):
            calls.append(req);winners=self.choose(req)[0]
            return {'model':req['model'],'answers':{k:{'type':'choice','choice':'unresolved','confidence':0,
                'probabilities':{v:.7 if v==winners[k]['value'] else .3/(len(q['criteria'])-1) for v in q['criteria']}}
                for k,q in req['questions'].items()}}
        with TemporaryDirectory() as directory:
            engine=Pipeline(directory,FileCandidates(directory),transport);result,check=cd.execute(run,doc,engine)
            self.assertTrue(check['raw_argmax_replayed']);n=len(calls);cd.execute(run,doc,engine);self.assertEqual(len(calls),n)
            key=result['actions'][-1]['conditions'][0]['requests']['alignment'];path=Path(directory)/'decisions'/f'{key}.json'
            value=read(path);next(iter(value['answers'].values()))['value']='conflicts';write(path,value)
            with self.assertRaisesRegex(InputError,'argmax'):cd.audit(run,doc,result,directory)

    def test_invalid_source_or_forged_decision_never_becomes_an_observation(self):
        run,doc=fixture(CASES[0])
        with self.assertRaises(InputError):cd.build(run,doc,lambda r:({'invented':{'value':'applies'}},digest(r)))
        doc['source_hash']='wrong'
        with self.assertRaises(InputError):cd.build(run,doc,lambda r:self.fail('Invalid source reached model'))

    def test_copied_feedback_cannot_supply_a_new_approval_event(self):
        run,doc=fixture(CASES[0]);old=next(e for e in run['events'] if e['kind']=='feedback')
        old['copied_context']=True;old['text']='COPIED_APPROVAL_NOT_CURRENT'
        doc['source_hash']=doc['requested_work']['source_hash']=digest(run);calls=[]
        def decide(req):calls.append(req);return self.choose(req)
        cd.build(run,doc,decide)
        self.assertNotIn('COPIED_APPROVAL_NOT_CURRENT',str(calls))
        self.assertTrue(any(old['id'] in r['state']['excluded_copied_context_event_ids'] for r in calls))

    def test_cli_default_reuses_cache_without_new_calls(self):
        import contextlib,io
        run,doc=fixture(CASES[0])
        def transport(req):
            winners=self.choose(req)[0]
            return {'model':req['model'],'answers':{k:{'type':'choice','probabilities':{v:1 if v==winners[k]['value'] else 0 for v in q['criteria']}} for k,q in req['questions'].items()}}
        with TemporaryDirectory() as directory:
            root=Path(directory);cd.execute(run,doc,Pipeline(root,FileCandidates(root),transport))
            write(root/'input.json',{'run':run,'document':doc})
            with patch('sys.argv',['condition_dispatch','--input',str(root/'input.json'),'--workspace',str(root)]),patch('tracker.jev.JevClient') as client,contextlib.redirect_stdout(io.StringIO()):
                client.return_value.transport.side_effect=AssertionError('Cached replay tried inference');cd.main()
            receipt=read(next((root/'executions').glob('*.json')))
            self.assertEqual(receipt['new_requests'],0);self.assertEqual(receipt['status'],'complete')
