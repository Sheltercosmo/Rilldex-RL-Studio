from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from tracker.candidate_worker import CommandCandidates
from tracker.contribution_readings import generation_request,validate,describe_partition_request
from tracker.schema import InputError,digest
from tracker.semantic_extraction import (FileCandidates,Pipeline,SEMANTIC_PARTITIONS,
    partition_options,partition_request,windows,read,write,audit_result,load_extraction)
from tracker.semantic_map import evidence
from tests.test_semantic_extraction import fixture,response,proposals


def reading(req):
    return {'request_hash':digest(req),'producer':'fixture only','readings':[{'activity':'orient',
        'text':'Recognizes the missing decorator and needed local correction.',
        'evidence':[{'event_id':req['source']['event_id'],'quote':req['source']['text']}]}]}


class ContributionReadingTests(unittest.TestCase):
    def test_unit_cutoff_and_activity_vocabulary_bind_every_reading(self):
        run=fixture();ref=windows(run)[0];req=generation_request(run,ref)
        valid=validate(run,req,reading(req));self.assertEqual(valid['readings'][0]['evidence'][0]['start'],0)
        for mutation in ['future','label','binding','earlier_only']:
            value=reading(req)
            if mutation=='future':value['readings'][0]['evidence']=[evidence(run,run['events'][-1]['id'])]
            elif mutation=='label':value['readings'][0]['activity']='assess'
            elif mutation=='binding':value['request_hash']='another'
            else:value['readings'][0]['evidence']=[evidence(run,run['events'][0]['id'])]
            with self.assertRaises(InputError):validate(run,req,value)

    def test_descriptions_bind_whole_candidate_without_inventing_boundaries(self):
        run=fixture();w=windows(run)[0];proposal={'spans':[{'start':w['start'],'end':w['end']}],
            'contributions':['A local setup gap and its correction.'],'rationale':'Rationale and needed correction belong together.'}
        original=partition_request(run,w,partition_options(run,w,[proposal],semantic_only=True))
        enriched=describe_partition_request(original,[proposal])
        self.assertNotIn('candidate_description_contract',original['state'])
        self.assertEqual(enriched['state']['partitions'][0]['units'],original['state']['partitions'][0]['units'])
        bad=deepcopy(proposal);bad['contributions'].append('An invented second unit')
        with self.assertRaisesRegex(InputError,'match its source units'):describe_partition_request(original,[bad])

    def test_reading_queue_blocks_classification_until_source_bound_candidates_exist(self):
        run=fixture();policy={'schema':'readable-context/2','recent_events':6,'max_event_chars':4000,'extra_ranges':[]}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);provider=FileCandidates(root/'c',policy,partition_policy=SEMANTIC_PARTITIONS,contribution_readings=True)
            engine=Pipeline(root,provider,response);pending=engine.run(run)
            key=pending['windows'][0]['repair_request'];req=read(root/'c/requests'/f'{key}.json');w=req['source']
            write(root/'c/responses'/f'{key}.json',{'request_hash':key,'producer':'fixture','partitions':[{
                'spans':[{'start':w['start'],'end':w['end']}],
                'contributions':['Recognizes the local gap.'],'rationale':'One local adjustment.'}]})
            pending=engine.run(run);self.assertEqual(engine.calls,1)
            self.assertEqual(pending['units'][0]['status'],'needs_activity_readings')
            self.assertTrue(audit_result(run,pending,root)['argmax_replayed'])
            key=pending['units'][0]['activity_reading_request'];req=read(root/'c/requests'/f'{key}.json')
            self.assertNotIn('FUTURE',str(req));write(root/'c/responses'/f'{key}.json',reading(req))
            pending=engine.run(run);key=pending['units'][0]['candidate_request'];req=read(root/'c/requests'/f'{key}.json')
            write(root/'c/responses'/f'{key}.json',proposals(req));complete=engine.run(run)
            self.assertEqual(complete['status'],'complete_local_extraction')
            self.assertTrue(audit_result(run,complete,root)['argmax_replayed'])
            context=load_extraction(run,root)['document']['units'][0]['inspector_context']['candidate_readings']
            self.assertEqual(context['producer'],'fixture only')
            self.assertEqual(context['selected_activity'],'orient')
            self.assertEqual(context['readings'][0]['evidence'][0]['text'],windows(run)[0]['text'])
            altered=deepcopy(complete);altered['units'][0]['activity_reading_request']='wrong'
            with self.assertRaisesRegex(InputError,'reading request differs'):audit_result(run,altered,root)

    def test_worker_generates_boundaries_readings_and_content_in_order(self):
        script='''import json,sys
r=json.load(sys.stdin)['request']
if r.get('stage')=='activity_readings':
 print(json.dumps({'readings':[{'activity':'orient','text':'Identifies the local gap.',
  'evidence':[{'event_id':r['source']['event_id'],'quote':r['source']['text']}]}]}))
elif r.get('stage')=='content':
 fields={k:{'status':'not_expressed'} for k in r['field_contract']}
 fields['summary']={'status':'expressed','text':'Identifies the local gap.','evidence':[r['source']]}
 print(json.dumps({'candidates':[{'fields':fields}]}))
else:
 print(json.dumps({'partitions':[{'units':[{'quote':r['source']['text']}],
  'contributions':['Identifies a local gap and correction.'],'rationale':'One local adjustment.'}]}))
'''
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'worker.py';path.write_text(script,encoding='utf-8')
            provider=CommandCandidates(root/'c',[sys.executable,str(path)],'fixture',
                partition_policy=SEMANTIC_PARTITIONS,contribution_readings=True)
            engine=Pipeline(root,provider,response);run=fixture();result=engine.run(run)
            self.assertEqual(provider.generation_calls,3);self.assertEqual(engine.calls,3)
            self.assertTrue(audit_result(run,result,root)['argmax_replayed'])
            engine.run(run);self.assertEqual(provider.generation_calls,3)


if __name__=='__main__':unittest.main()
