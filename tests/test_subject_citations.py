from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
import sys

from tracker import contribution_readings as readings
from tracker.readable_context import resolve_citation
from tracker.semantic_extraction import generation_request,validate_proposals,windows
from tracker.candidate_worker import CommandCandidates
from tracker.schema import InputError,digest
from tests.test_semantic_extraction import fixture


class SubjectCitationTests(unittest.TestCase):
    def setUp(self):
        self.run=fixture();self.ref=windows(self.run)[0]
        self.req=readings.generation_request(self.run,self.ref,version=readings.SCOPED_VERSION)

    def response(self):
        return dict(request_hash=digest(self.req),producer='authored-control',reading_protocol=readings.SCOPED_VERSION,
            citation_format='source-references/1',readings=[dict(activity='orient',text='Recognizes the local situation.',evidence=[{'subject':True}])])

    def test_current_unit_materializes_exact_source_without_changing_request(self):
        original=deepcopy(self.req);value=readings.validate(self.run,self.req,self.response())
        self.assertEqual(self.req,original)
        expected={k:self.ref[k] for k in ('event_id','source_pointer','start','end','text')}
        self.assertEqual(value['readings'][0]['evidence'],[expected])
        # Materialized stored responses remain valid on replay.
        self.assertEqual(readings.validate(self.run,self.req,value),value)

    def test_alias_requires_explicit_format_and_exact_shape(self):
        for alias,format in (({'subject':True},None),({'subject':1},'source-references/1'),
                             ({'subject':True,'start':0},'source-references/1')):
            with self.subTest(alias=alias,format=format),self.assertRaises(InputError):
                resolve_citation(self.run,self.req,alias,format)

    def test_wrong_quote_remains_wrong_and_hash_cannot_rebind_source(self):
        bad=self.response();bad['readings'][0]['evidence']=[{'event_id':self.ref['event_id'],'quote':'FABRICATED_SOURCE'}]
        with self.assertRaises(InputError):readings.validate(self.run,self.req,bad)
        other=deepcopy(self.req);other['source']['end']-=1
        with self.assertRaises(InputError):readings.validate(self.run,other,self.response())

    def test_omitted_or_external_subject_cannot_be_cited(self):
        req=deepcopy(self.req);req['prefix']=[]
        with self.assertRaises(InputError):resolve_citation(self.run,req,{'subject':True},'source-references/1')
        run=deepcopy(self.run);next(e for e in run['events'] if e['id']==self.ref['event_id'])['agent_visibility']='not_established'
        with self.assertRaises(InputError):resolve_citation(run,self.req,{'subject':True},'source-references/1')

    def test_content_can_mix_current_unit_and_exact_quote(self):
        req=generation_request(self.run,self.ref,'orient')
        fields={k:{'status':'not_expressed'} for k in req['field_contract']}
        prior=req['prefix'][0]
        fields['summary']=dict(status='expressed',text='Local situation.',evidence=[{'subject':True},
            {'event_id':prior['id'],'quote':prior['text']}])
        response=dict(request_hash=digest(req),producer='authored-control',citation_format='source-references/1',candidates=[dict(fields=fields)])
        value=validate_proposals(self.run,req,response)
        self.assertEqual(value[0]['fields']['summary']['evidence'][0]['text'],self.ref['text'])
        self.assertEqual(value[0]['fields']['summary']['evidence'][1]['text'],prior['text'])

    def test_whole_unit_cannot_claim_uninspected_encoded_media(self):
        from tracker.readable_context import VERSION
        run=deepcopy(self.run)
        event=next(e for e in run['events'] if e['id']==self.ref['event_id'])
        event['text']='Inspect this image: data:image/png;base64,aGVsbG8= before proceeding.'
        ref={**self.ref,'start':0,'end':len(event['text']),'text':event['text']}
        policy=dict(schema=VERSION,recent_events=8,max_event_chars=4000,extra_ranges=[])
        # The request builder rejects this even before a response can cite it.
        with self.assertRaisesRegex(InputError,'Binary media occurs inside the required subject'):
            readings.generation_request(run,ref,policy,version=readings.SCOPED_VERSION)

    def test_external_worker_and_cached_readings_use_same_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);script=root/'worker.py'
            script.write_text("import json,sys\nr=json.load(sys.stdin)\nprint(json.dumps({'citation_format':'source-references/1','reading_protocol':'contribution-readings/2','readings':[{'activity':'orient','text':'Local situation.','evidence':[{'subject':True}]}]}))\n",encoding='utf-8')
            worker=CommandCandidates(root/'c',[sys.executable,str(script)],'authored-worker',contribution_readings=True,reading_protocol=readings.SCOPED_VERSION)
            first=worker.readings(self.run,self.ref);second=worker.readings(self.run,self.ref)
            self.assertEqual(first,second);self.assertEqual(worker.generation_calls,1)
            self.assertEqual(first['response']['readings'][0]['evidence'][0]['text'],self.ref['text'])


if __name__=='__main__':unittest.main()
