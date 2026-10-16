from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import execution_reports as er
from tracker.schema import InputError, digest, event, dumps
from tracker.semantic_extraction import Pipeline, read, write
from tracker.semantic_map import evidence


def fixture(action='run tests',response='Error: test process could not start'):
    events=[]
    event(events,kind='action',text=action,pointer='/action',trajectory_id='main',call_id='a')
    event(events,kind='feedback',text=response,pointer='/response',trajectory_id='main',actor='environment',source_call_id='a')
    event(events,kind='message',text='FUTURE_CLAIM: all tests passed',pointer='/future',trajectory_id='main')
    return {'id':'test','events':events,'metadata':{},'adapter_version':'test'}


def answer(req,error='reported',warning='not_reported'):
    values={'error':error,'warning':warning}
    return {'model':req['model'],'answers':{k:{'type':'choice','confidence':0,
        'choice':'provider-choice-is-ignored','probabilities':{v:1.0 if v==values[k] else 0.0 for v in q['criteria']}}
        for k,q in req['questions'].items()}}


class ExecutionReportTests(unittest.TestCase):
    def test_only_bound_current_response_and_replay_are_accepted(self):
        run=fixture()
        with tempfile.TemporaryDirectory() as folder:
            engine=Pipeline(folder,None,answer); result,validation=er.execute(run,engine)
            self.assertEqual(result['observations'][0]['error'],'reported')
            self.assertTrue(validation['argmax_replayed'])
            req=read(Path(folder)/'decisions'/f"{result['observations'][0]['request_hash']}.json")['request']
            self.assertNotIn('FUTURE_CLAIM',dumps(req))
            er.execute(run,engine);self.assertEqual(engine.calls,1)
            result['observations'][0]['error']='not_reported'
            with self.assertRaisesRegex(InputError,'replay'):er.audit(run,result,folder)
        changed=deepcopy(run['events'][1]);changed['text']='invented'
        with self.assertRaisesRegex(InputError,'exact visible'):er.request(run,run['events'][0],changed)

    def test_missing_or_ambiguous_binding_never_becomes_negative_observation(self):
        run=fixture();run['events'][1]['source_call_id']='missing'
        self.assertEqual(er.build(run,lambda r:None)['observations'],[])
        run=fixture();duplicate=deepcopy(run['events'][0]);duplicate['id']='duplicate';run['events'].append(duplicate)
        self.assertEqual(er.bound_responses(run),[])
        run=fixture();run['events'][1]['agent_visible']=False
        self.assertEqual(er.bound_responses(run),[])
        run=fixture();run['events'][1]['actor']='agent'
        self.assertEqual(er.bound_responses(run),[])
        run=fixture();run['events'][1]['agent_visibility']='not_established'
        self.assertEqual(er.bound_responses(run),[])

    def test_omissions_do_not_change_argmax_and_are_not_measured_as_absence(self):
        run=fixture(response='x'*100001+' data:image/png;base64,QUJDRA==')
        with tempfile.TemporaryDirectory() as folder:
            engine=Pipeline(folder,None,lambda req:answer(req,'not_reported'))
            result,_=er.execute(run,engine);row=result['observations'][0]
            self.assertEqual(row['error'],'not_reported');self.assertFalse(row['complete_readable_response'])
            self.assertTrue(row['omitted_text_ranges']);self.assertTrue(row['uninspected_media'])
            self.assertNotIn('QUJDRA==',dumps(er.request(run,*er.bound_responses(run)[0])))

    def test_return_needs_positive_identity_and_error_before_current_dispatch(self):
        run=fixture();event(run['events'],kind='action',text='retry tests',pointer='/retry',trajectory_id='main',call_id='b')
        units=[{'id':name,'source':evidence(run,eid),'actor':'agent','trajectory_id':'main','kind':'action'} for name,eid in [('a','e1'),('b','e4')]]
        recurrence={'unit_id':'b','previous_group_unit_id':'a','group_id':'g','supporting_identity_relations':[{'from':'b','to':'a','type':'same_action_target'}]}
        doc={'source_hash':digest(run),'units':units,'relations':[],'provenance':{},'work_history':{'recurrences':[recurrence]}}
        bundle={'document':doc};original=deepcopy(bundle)
        with tempfile.TemporaryDirectory() as folder:
            result,_=er.execute(run,Pipeline(folder,None,answer))
        projected=er.project(run,bundle,result)
        self.assertEqual(bundle,original);self.assertEqual(len(projected['document']['execution_returns']),1)
        self.assertEqual(projected['document']['units'],units)
        doc['work_history']['recurrences']=[]
        self.assertEqual(er.project(run,bundle,result)['document']['execution_returns'],[])
        doc['work_history']['recurrences']=[recurrence]
        doc['work_history']['streams']=[{'groups':[{'id':'g','disputed_identity':True}]}]
        self.assertEqual(er.project(run,bundle,result)['document']['execution_returns'],[])
        doc['work_history'].pop('streams')
        run['events'][1]['index']=10;doc['source_hash']=digest(run);result['source_hash']=digest(run)
        self.assertEqual(er.project(run,bundle,result)['document']['execution_returns'],[])


if __name__=='__main__':unittest.main()
