from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tracker.candidate_worker import CommandCandidates, bind_candidate_response
from tracker.schema import InputError
from tracker.semantic_extraction import FileCandidates, Pipeline, audit_result, read, windows
from tests.test_semantic_extraction import fixture, response


GENERATOR='''import json,sys,os
if os.environ.get('JEV_API_KEY'): raise RuntimeError('credential leaked')
r=json.load(sys.stdin)['request']
if r.get('stage')=='content':
 fields={k:{'status':'not_expressed'} for k in r['field_contract']}
 fields['summary']={'status':'expressed','text':'Identifies the missing decorator and calls for adding it.',
                    'evidence':[{'event_id':r['source']['event_id'],'quote':r['source']['text']}]}
 print(json.dumps({'citation_format':'source-quotes/1','candidates':[{'fields':fields}]}))
else:
 print(json.dumps({'partitions':[{'units':[{'quote':r['source']['text']}]}]}))
'''


class CandidateWorkerTests(unittest.TestCase):
    def test_configured_metadata_leaves_generated_content_unchanged(self):
        from copy import deepcopy
        body={'candidates':[{'fields':{'summary':{'status':'expressed','text':'A proposal.',
                 'evidence':[{'subject':True}]}}}]}
        before=deepcopy(body)
        result=bind_candidate_response({'source':'exact request'},body,'configured generator',
                                       citation_format='source-references/1')
        self.assertEqual(body,before)
        self.assertEqual(result['candidates'],body['candidates'])
        self.assertEqual(result['producer'],'configured generator')
        self.assertEqual(result['citation_format'],'source-references/1')
        with self.assertRaisesRegex(InputError,'conflicts'):
            bind_candidate_response({},dict(body,citation_format='source-quotes/1'),'configured generator',
                                    citation_format='source-references/1')

    def test_subject_payload_needs_no_model_generated_transport_metadata(self):
        script_text='''import json,sys
p=json.load(sys.stdin)
assert p['response_metadata']['citation_format']=='source-references/1'
assert p['response_metadata']['producer']=='fixture'
r=p['request']
fields={k:{'status':'not_expressed'} for k in r['field_contract']}
fields['summary']={'status':'expressed','text':'Identifies a local reproduction adjustment.',
                   'evidence':[{'subject':True}]}
print(json.dumps({'candidates':[{'fields':fields}]}))
'''
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);script=root/'generator.py';script.write_text(script_text,encoding='utf-8')
            provider=CommandCandidates(root/'candidates',[sys.executable,str(script)],'fixture',
                                       citation_format='source-references/1')
            run=fixture();unit=windows(run)[0]
            result=provider.content(run,unit,'orient')
            self.assertEqual(result['status'],'ready')
            citation=result['candidates'][0]['fields']['summary']['evidence'][0]
            self.assertEqual(citation['text'],unit['text'])
            receipt=read(next((root/'candidates/receipts').glob('*.json')))
            self.assertEqual(receipt['configured_citation_format'],'source-references/1')
            provider.content(run,unit,'orient')
            self.assertEqual(provider.generation_calls,1)

    def test_metadata_binding_does_not_repair_wrong_evidence(self):
        from tracker.semantic_extraction import generation_request,validate_proposals
        run=fixture();req=generation_request(run,windows(run)[0],'orient')
        fields={k:{'status':'not_expressed'} for k in req['field_contract']}
        fields['summary']={'status':'expressed','text':'Unsupported content.',
            'evidence':[{'event_id':req['source']['event_id'],'quote':'This is absent from the source.'}]}
        result=bind_candidate_response(req,{'candidates':[{'fields':fields}]},'fixture',
                                       citation_format='source-references/1')
        with self.assertRaises(InputError):validate_proposals(run,req,result)

    def test_input_budget_counts_the_actual_configured_envelope(self):
        from types import SimpleNamespace
        from tracker.schema import dumps
        from tracker.semantic_budget import ExecutionBudget,BudgetReached
        from tracker.semantic_extraction import generation_request
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run=fixture();unit=windows(run)[0]
            provider=CommandCandidates(root/'candidates',['unused-program'],'fixture',
                                       citation_format='source-references/1')
            req=generation_request(run,unit,'orient');packet=provider.packet(req)
            size=len(dumps(packet).encode('utf-8'))
            provider.execution_budget=ExecutionBudget(root,1,{'input_bytes':size-1})
            with patch('tracker.candidate_worker.candidate_process.run',side_effect=AssertionError('Over-budget subprocess')):
                with self.assertRaises(BudgetReached):provider.content(run,unit,'orient')
            self.assertEqual(provider.generation_calls,0)
            fields={k:{'status':'not_expressed'} for k in req['field_contract']}
            fields['summary']={'status':'expressed','text':'Identifies a local adjustment.',
                               'evidence':[{'subject':True}]}
            def send(*args,**kwargs):
                self.assertEqual(len(kwargs['input'].encode('utf-8')),size)
                return SimpleNamespace(details={},stdout=dumps({'candidates':[{'fields':fields}]}))
            provider.execution_budget=ExecutionBudget(root,2,{'input_bytes':size})
            with patch('tracker.candidate_worker.candidate_process.run',side_effect=send):
                self.assertEqual(provider.content(run,unit,'orient')['status'],'ready')
            self.assertEqual(provider.execution_budget.used['input_bytes'],size)

    def test_semantic_mode_generates_boundaries_before_any_jev_decision(self):
        from tracker.semantic_extraction import SEMANTIC_PARTITIONS
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);script=root/'generator.py';script.write_text(GENERATOR,encoding='utf-8')
            provider=CommandCandidates(root/'candidates',[sys.executable,str(script)],'test fixture',
                partition_policy=SEMANTIC_PARTITIONS)
            def transport(req):
                self.assertGreaterEqual(provider.generation_calls,1)
                return response(req)
            engine=Pipeline(root,provider,transport);run=fixture();result=engine.run(run)
            self.assertEqual(result['status'],'complete_local_extraction')
            self.assertEqual(provider.generation_calls,2)
            self.assertTrue(audit_result(run,result,root)['argmax_replayed'])
            engine.run(run)
            self.assertEqual(provider.generation_calls,2)

    def test_subprocess_quote_handoff_runs_before_jev_selection_and_resumes_without_generation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);script=root/'generator.py';script.write_text(GENERATOR,encoding='utf-8')
            provider=CommandCandidates(root/'candidates',[sys.executable,str(script)],'test fixture, not LLM')
            engine=Pipeline(root,provider,response);run=fixture()
            with patch.dict('os.environ',{'JEV_API_KEY':'test-only-secret'}):result=engine.run(run)
            self.assertEqual(result['status'],'complete_local_extraction')
            self.assertEqual(provider.generation_calls,1);self.assertEqual(engine.calls,3)
            self.assertTrue(audit_result(run,result,root)['argmax_replayed'])
            self.assertIn('start',result['units'][0]['content']['summary']['evidence'][0])
            self.assertIn('quote',read(next((root/'candidates/responses').glob('*.json')))['candidates'][0]['fields']['summary']['evidence'][0])
            engine.run(run);self.assertEqual(provider.generation_calls,1);self.assertEqual(engine.calls,3)
            for path in root.rglob('*.json'):self.assertNotIn('test-only-secret',path.read_text(encoding='utf-8'))

    def test_partition_quotes_materialize_exact_original_spans(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);script=root/'generator.py';script.write_text(GENERATOR,encoding='utf-8')
            provider=CommandCandidates(root/'candidates',[sys.executable,str(script)],'test fixture')
            run=fixture();window=windows(run)[0]
            proposals,key=provider.partitions(run,window,needed=True)
            self.assertEqual(proposals[0]['spans'],[{'start':window['start'],'end':window['end']}])
            self.assertEqual(read(root/'candidates/receipts'/f'{key}.json')['status'],'candidate_ready')

    def test_failed_generator_does_not_publish_candidates_or_persist_stderr(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);script=root/'generator.py';script.write_text("import sys; print('private stderr marker',file=sys.stderr); sys.exit(4)",encoding='utf-8')
            provider=CommandCandidates(root/'candidates',[sys.executable,str(script)],'failing fixture')
            engine=Pipeline(root,provider,response)
            with self.assertRaisesRegex(InputError,'exit code 4'):engine.run(fixture())
            self.assertFalse((root/'candidates/responses').exists())
            receipt=next((root/'candidates/receipts').glob('*.json')).read_text(encoding='utf-8')
            self.assertNotIn('private stderr marker',receipt)
            self.assertEqual(engine.calls,2)

    def test_incomplete_new_pass_does_not_replace_the_published_complete_map(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);script=root/'generator.py';script.write_text(GENERATOR,encoding='utf-8')
            run=fixture();provider=CommandCandidates(root/'candidates',[sys.executable,str(script)],'test fixture')
            complete=Pipeline(root,provider,response).run(run)
            pending=Pipeline(root,FileCandidates(root/'empty-provider'),response).run(run)
            self.assertEqual(pending['status'],'needs_work')
            self.assertEqual(read(root/'results'/f'{run["id"]}.json'),complete)
            self.assertEqual(read(root/'checkpoints'/f'{run["id"]}.json'),pending)


if __name__=='__main__':unittest.main()
