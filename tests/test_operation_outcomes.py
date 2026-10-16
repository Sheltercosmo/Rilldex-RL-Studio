from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import operation_outcomes as oo
from tracker.schema import InputError, digest, event, dumps
from tracker.semantic_map import evidence
from tracker.semantic_extraction import Pipeline, read
from tests.test_execution_reports import fixture


def answer(req, value='completed'):
    if 'error' in req['questions']:
        from tests.test_execution_reports import answer as reports
        return reports(req)
    return {'model':req['model'],'answers':{q:{'type':'choice','choice':'failed','confidence':0,
        'probabilities':{k:float(k=='compute' if q=='mechanism' else k.startswith(value+'_')) for k in definition['criteria']}}
        for q,definition in req['questions'].items()}}


def sample():
    run=fixture()
    event(run['events'],kind='action',text='retry operation',pointer='/retry',trajectory_id='main',call_id='b')
    event(run['events'],kind='feedback',text='Completed successfully',pointer='/result',trajectory_id='main',actor='environment',source_call_id='b')
    units=[{'id':uid,'source':evidence(run,eid),'actor':'agent','trajectory_id':'main','kind':'action'} for uid,eid in [('a','e1'),('b','e4')]]
    doc={'source_hash':digest(run),'units':units,'relations':[],'provenance':{},'work_history':{'recurrences':[
        {'unit_id':'b','previous_group_unit_id':'a','group_id':'g','supporting_identity_relations':[]}]}}
    with tempfile.TemporaryDirectory() as folder:
        result,_=oo.execute(run,Pipeline(folder,None,lambda r:answer(r,'failed' if r['state']['action']['id']=='e1' else 'completed')))
    return run,{'document':doc},result


class OperationOutcomeTests(unittest.TestCase):
    def test_raw_argmax_replay_keeps_current_evidence_only(self):
        run=fixture()
        with tempfile.TemporaryDirectory() as folder:
            engine=Pipeline(folder,None,answer);result,validation=oo.execute(run,engine)
            self.assertEqual(result['observations'][0]['outcome'],'completed')
            self.assertTrue(validation['argmax_replayed'])
            packet=read(Path(folder)/'decisions'/f"{result['observations'][0]['request_hash']}.json")
            self.assertNotIn('FUTURE_CLAIM',dumps(packet['request']))
            oo.execute(run,engine);self.assertEqual(engine.calls,3)
            result['observations'][0]['outcome']='failed'
            with self.assertRaisesRegex(InputError,'replay'):oo.audit(run,result,folder)

    def test_transition_requires_complete_outcomes_identity_and_prior_failure_cutoff(self):
        run,bundle,result=sample();before=deepcopy(bundle);projected=oo.project(run,bundle,result)
        self.assertEqual(bundle,before);self.assertEqual(projected['document']['units'],bundle['document']['units'])
        edges=projected['document']['operation_transitions'];self.assertEqual(len(edges),1)
        self.assertEqual(edges[0]['cutoff']['event_id'],'e5');self.assertEqual(edges[0]['previous_response_ids'],['e2'])
        result['observations'][1]['complete_readable_response']=False
        self.assertEqual(oo.project(run,bundle,result)['document']['operation_transitions'],[])
        result['observations'][1]['complete_readable_response']=True
        bundle['document']['work_history']['streams']=[{'groups':[{'id':'g','disputed_identity':True}]}]
        self.assertEqual(oo.project(run,bundle,result)['document']['operation_transitions'],[])
        bundle['document']['work_history'].pop('streams');run['events'][1]['index']=10
        result['source_hash']=bundle['document']['source_hash']=digest(run)
        self.assertEqual(oo.project(run,bundle,result)['document']['operation_transitions'],[])

    def test_incomplete_or_disagreeing_feedback_cannot_supply_completed_endpoint(self):
        run,bundle,result=sample()
        e=event(run['events'],kind='feedback',text='Still running',pointer='/more',trajectory_id='main',actor='environment',source_call_id='b')
        result['source_hash']=digest(run)
        self.assertEqual(oo.action_outcomes(run,result)['e4']['outcome'],'not_established')
        row=deepcopy(result['observations'][1]);row.update(response_event_id=e['id'],outcome='pending');result['observations'].append(row)
        self.assertEqual(oo.action_outcomes(run,result)['e4']['outcome'],'not_established')
        result['observations'].append(row)
        with self.assertRaisesRegex(InputError,'Duplicate'):oo.action_outcomes(run,result)

    def test_omission_preserves_selection_but_excludes_transition_endpoint(self):
        run=fixture(response='x'*100001+' data:image/png;base64,QUJDRA==')
        with tempfile.TemporaryDirectory() as folder:
            result,_=oo.execute(run,Pipeline(folder,None,answer))
        row=result['observations'][0];self.assertEqual(row['outcome'],'completed')
        self.assertFalse(row['complete_readable_response']);self.assertTrue(row['uninspected_media'])
        self.assertEqual(oo.action_outcomes(run,result)['e1']['outcome'],'not_established')
        self.assertNotIn('QUJDRA==',dumps(oo.request(run,*oo.bound_responses(run)[0],'compute','reported')))

    def test_mechanism_cannot_read_later_response_and_metrics_use_terminal_call_denominator(self):
        run,bundle,result=sample()
        req=oo.mechanism_request(run,run['events'][0])
        self.assertNotIn('Completed successfully',dumps(req));self.assertNotIn('response',req['state'])
        from tracker.rollout_metrics import semantic_record
        bundle['observer']={'id':'test','label':'Test'}
        projected=oo.project(run,bundle,result);m=semantic_record(run,projected)['metrics']
        self.assertEqual(m['operation_failed_fraction']['numerator'],1)
        self.assertEqual(m['operation_failed_fraction']['denominator'],2)
        self.assertEqual(m['completed_after_failed_call_count']['value'],1)
        self.assertIsNone(m['recovery_rate']['value'])
        result['observations'][1]['outcome']='pending'
        m=semantic_record(run,oo.project(run,bundle,result))['metrics']
        self.assertEqual(m['operation_failed_fraction']['denominator'],1)
        self.assertEqual(m['operation_unknown_fraction']['value'],0)
        result['observations'][1]['complete_readable_dispatch']=False
        m=semantic_record(run,oo.project(run,bundle,result))['metrics']
        self.assertEqual(m['operation_unknown_fraction']['value'],.5)

    def test_failed_candidate_requires_compatible_complete_error_observation(self):
        run=fixture(action='cat old.log',response='Old stored error text')
        a,r=oo.bound_responses(run)[0]
        req=oo.request(run,a,r,'read','not_reported')
        self.assertNotIn('failed_read',req['questions']['outcome']['criteria'])
        self.assertIn('completed_read',req['questions']['outcome']['criteria'])
        self.assertIn('not_established_read',req['questions']['outcome']['criteria'])
        self.assertIn('failed_read',oo.request(run,a,r,'read','unresolved')['questions']['outcome']['criteria'])
        r['text']+='x'*100001
        self.assertIn('failed_read',oo.request(run,a,r,'read','not_reported')['questions']['outcome']['criteria'])


if __name__=='__main__':unittest.main()
