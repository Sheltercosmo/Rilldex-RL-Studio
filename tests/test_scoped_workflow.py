from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rilldex import candidate, scopes
from tracker.schema import InputError
from tracker.semantic_extraction import read


def decision(request):
    # Low argmax, intentionally contradictory provider choice and confidence.
    return dict(model=request['model'],usage=dict(input_tokens=100,output_tokens=10),
        answers={k:dict(type='choice',choice='does_not_apply',confidence=0,
            probabilities=dict(applies=.4,does_not_apply=.3,unresolved=.3)) for k in request['questions']})


class ScopedWorkflowTests(unittest.TestCase):
    def setUp(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/scope_membership.json').read_text(encoding='utf-8'))
        row=next(c for c in fixture['cases'] if c['intent_rule']=='expressed_work')
        self.packet=deepcopy(row['packet']);self.uid=row['bound']['unit_id']
        self.body=deepcopy(row['bound']['raw_response'])
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.candidates=[];self.decisions=[]

    def proposal(self,payload):
        stage=payload['request']['stage'];self.candidates.append(stage)
        field='contents' if stage=='contents' else 'features'
        body=deepcopy(self.body[field])
        if field=='features' and 'scopes' not in payload['request']['response_format']['features'][0]:
            for feature in body:feature.pop('scopes')
        return dict(raw_output=json.dumps({field:body}),usage=dict(input_tokens=20,output_tokens=5))

    def select(self,request):
        self.decisions.append(request)
        return decision(request)

    def run_extract(self,**kwargs):
        defaults=dict(candidate_transport=self.proposal,candidate_identity='authored-control/1',
            decision_transport=self.select,candidate_calls=2,decision_calls=32,input_bytes=1000000)
        return scopes.extract(self.packet,self.uid,self.root,**{**defaults,**kwargs})

    def test_budget_resume_preserves_completed_features_and_source(self):
        first=self.run_extract(decision_calls=1)
        self.assertEqual(first['status'],'budget_reached')
        self.assertEqual(len(first['review']['features']),1)
        self.assertTrue(first['review']['pending_feature_ids'])
        snapshot=deepcopy(first['review']['features'])
        again=self.run_extract(decision_calls=1)
        self.assertEqual(again['review'],first['review'])
        self.assertEqual(self.candidates,['contents','features']);self.assertEqual(len(self.decisions),1)
        final=self.run_extract()
        self.assertEqual(final['status'],'complete')
        self.assertEqual(final['review']['features'][:1],snapshot)
        self.assertFalse(final['review']['pending_feature_ids'])
        self.assertEqual(final['review']['inventory_status'],'not_evaluated')
        self.assertTrue(all(d['choice']=='applies' for r in final['review']['receipts'] for d in r['decisions']))
        source=first['review']['features'][0]['unit']['source']
        self.assertEqual(source,self.packet['units'][0]['source'])
        calls=len(self.decisions);self.run_extract()
        self.assertEqual(len(self.decisions),calls)
        self.assertEqual(final['usage']['providers']['candidate']['reported_usage']['input_tokens'],40)

    def test_zero_budget_sends_nothing_and_retains_no_false_negative(self):
        result=self.run_extract(candidate_calls=0,decision_calls=0)
        self.assertEqual(result['status'],'budget_reached')
        self.assertIsNone(result['bound']);self.assertIsNone(result['review'])
        self.assertFalse(self.candidates);self.assertFalse(self.decisions)

    def test_content_only_resume_does_not_regenerate(self):
        first=self.run_extract(candidate_calls=1)
        self.assertEqual(first['stage'],'features');self.assertEqual(first['status'],'budget_reached')
        self.assertTrue(first['bound']['contents']);self.assertIsNone(first['review'])
        self.run_extract()
        self.assertEqual(self.candidates,['contents','features'])

    def test_content_policy_upgrade_preserves_legacy_resume_without_rebilling(self):
        first=self.run_extract(candidate_calls=1,content_policy='legacy')
        self.assertEqual(first['content_policy'],'legacy')
        final=self.run_extract()
        self.assertEqual(final['status'],'complete')
        self.assertEqual(final['content_policy'],'legacy')
        self.assertEqual(self.candidates,['contents','features'])
        with self.assertRaises(InputError):self.run_extract(content_policy='separate-work/1')
        self.assertEqual(self.candidates,['contents','features'])

    def test_new_content_policy_is_pinned_without_changing_source_units(self):
        seen=[]
        def capture(payload):seen.append(payload['request']);return self.proposal(payload)
        result=self.run_extract(candidate_transport=capture)
        self.assertEqual(result['content_policy'],'separate-work/3')
        self.assertEqual(seen[0]['unit'],self.packet['units'][0])
        self.assertIn('granularity',seen[0])
        self.run_extract(candidate_transport=capture)
        self.assertEqual(len(seen),2)
        with self.assertRaises(InputError):self.run_extract(content_policy='unrecognized')
        with self.assertRaises(InputError):self.run_extract(content_policy='legacy')
        self.assertEqual(len(seen),2)

    def test_first_separate_work_protocol_resumes_with_its_original_request(self):
        first=self.run_extract(candidate_calls=1,content_policy='separate-work/1')
        self.assertEqual(first['status'],'budget_reached')
        final=self.run_extract()
        self.assertEqual(final['content_policy'],'separate-work/1')
        self.assertEqual(final['status'],'complete')
        self.assertEqual(self.candidates,['contents','features'])
        before=len(self.decisions)
        self.run_extract()
        self.assertEqual(len(self.decisions),before)
        with self.assertRaises(InputError):self.run_extract(content_policy='separate-work/2')

    def test_empty_contents_skip_remaining_model_calls(self):
        self.body['contents']=[]
        result=self.run_extract()
        self.assertEqual(result['status'],'complete')
        self.assertEqual(self.candidates,['contents']);self.assertFalse(self.decisions)
        self.assertEqual(result['review']['inventory_status'],'not_evaluated')

    def test_no_features_remain_unmeasured_not_negative(self):
        self.body['features']=[]
        result=self.run_extract()
        self.assertEqual(result['status'],'complete');self.assertFalse(self.decisions)
        self.assertTrue(result['bound']['contents']);self.assertEqual(result['review']['features'],[])

    def test_invalid_completion_is_saved_and_not_billed_again(self):
        calls=[]
        def broken(payload):
            calls.append(payload);return dict(raw_output='invalid json',usage={})
        first=self.run_extract(candidate_transport=broken,max_repairs=0)
        self.assertEqual(first['status'],'needs_review')
        self.run_extract(candidate_transport=broken,max_repairs=0)
        self.assertEqual(len(calls),1)
        self.assertEqual(first['usage']['providers']['candidate']['attempts_without_reported_usage'],1)
        saved=read(next((self.root/'responses/candidate').glob('*.json')))
        self.assertEqual(saved['response']['raw_output'],'invalid json')

    def test_contract_repair_is_bounded_recorded_and_resumable(self):
        requests=[]
        def repair(payload):
            request=payload['request'];requests.append(request)
            if request['stage']=='contents' and 'repair' not in request:
                return dict(raw_output=json.dumps(dict(schema='extra',contents=self.body['contents'])),usage={})
            return self.proposal(payload)
        first=self.run_extract(candidate_calls=1,candidate_transport=repair)
        self.assertEqual(first['status'],'budget_reached')
        self.assertIsNone(first['bound']);self.assertEqual(len(requests),1)
        final=self.run_extract(candidate_calls=3,candidate_transport=repair)
        self.assertEqual(final['status'],'complete')
        self.assertEqual(len(requests),3)
        self.assertIn('contents-only response required',requests[1]['repair']['binding_error'])
        self.assertNotIn('reference',requests[1]['repair'])
        self.assertEqual(len(list((self.root/'responses/candidate').glob('*.json'))),3)
        self.run_extract(candidate_calls=3,candidate_transport=repair)
        self.assertEqual(len(requests),3)

    def test_failed_provider_requires_explicit_retry_and_counts_attempt(self):
        calls=[]
        def fail(payload):calls.append(payload);raise TimeoutError('private provider detail')
        first=self.run_extract(candidate_transport=fail)
        self.assertEqual(first['status'],'needs_review')
        self.assertNotIn('private provider detail',json.dumps(first))
        second=self.run_extract()
        self.assertEqual(second['status'],'retry_required');self.assertFalse(self.candidates)
        final=self.run_extract(candidate_calls=3,retry_failed=True)
        self.assertEqual(final['status'],'complete')
        self.assertEqual(final['usage']['providers']['candidate']['attempts'],3)

    def test_invalid_later_scope_does_not_erase_completed_feature(self):
        def failing(request):
            self.decisions.append(request)
            return decision(request) if len(self.decisions)==1 else dict(model=request['model'],answers={})
        result=self.run_extract(decision_transport=failing)
        self.assertEqual(result['status'],'needs_review')
        self.assertEqual(len(result['review']['features']),1)
        self.assertEqual(len(result['review']['pending_feature_ids']),len(self.body['features'])-1)
        self.run_extract(decision_transport=failing)
        self.assertEqual(len(self.decisions),2)

    def test_model_source_and_lifetime_budget_changes_are_explicit(self):
        self.run_extract(decision_calls=1)
        for kwargs in ({'candidate_identity':'different/2'},{'candidate_calls':0}):
            with self.subTest(kwargs=kwargs),self.assertRaises(InputError):self.run_extract(**kwargs)
        self.packet['units'][0]['source']['text']+=' Changed'
        with self.assertRaises(InputError):self.run_extract()
        self.assertEqual(self.candidates,['contents','features'])

    def test_default_adapter_preserves_usage_and_uses_wrapped_request(self):
        bodies=[]
        def server(request,**kwargs):
            body=json.loads(request.data);bodies.append(body)
            payload=json.loads(body['messages'][1]['content'])
            value=self.proposal(payload)
            return io.BytesIO(json.dumps(dict(model='fixture-model',usage=dict(prompt_tokens=77,completion_tokens=11,total_tokens=88),
                choices=[dict(message=dict(content=value['raw_output']))])).encode())
        env=dict(RILLDEX_LLM_URL='http://localhost:8000/v1/chat/completions',RILLDEX_LLM_MODEL='fixture-model')
        with patch.dict('os.environ',env),patch('rilldex.candidate.urlopen',side_effect=server):
            result=self.run_extract(candidate_transport=None,candidate_identity=None)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(len(bodies),2)
        self.assertEqual(result['usage']['providers']['candidate']['reported_usage'],dict(input_tokens=154,output_tokens=22,total_tokens=176))

    def test_workspace_reads_a_saved_graph_without_export_or_mutation(self):
        from rilldex import Workspace
        from tracker import graph_store
        from tracker.store import Store
        from test_work_scope_frames import fixture
        run,graph=fixture();store=Store(self.root/'study.sqlite');store.add([run])
        with store.connect() as connection:graph_store.save(connection,graph)
        seen=[]
        def propose(payload):
            seen.append(payload['request'])
            return dict(raw_output='{"contents":[]}',usage={})
        workspace=Workspace(store.path)
        result=workspace.extract_work_contents(graph['id'],'unit-0',self.root/'saved-unit',
            candidate_calls=1,decision_calls=0,input_bytes=100000,candidate_transport=propose,
            candidate_identity='empty-content-control/1')
        self.assertEqual(result['status'],'complete')
        self.assertEqual(seen[0]['unit']['source']['text'],run['events'][0]['text'])
        self.assertEqual(graph_store.read(store,graph['id'])['id'],graph['id'])
        with self.assertRaises(InputError):
            workspace.extract_work_contents(graph['id'],'missing-unit',self.root/'invalid',
                candidate_transport=propose,candidate_identity='empty-content-control/1')
        self.assertEqual(len(seen),1)


if __name__=='__main__':unittest.main()
