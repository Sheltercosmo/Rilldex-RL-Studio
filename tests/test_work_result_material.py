from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker import work_results, work_result_material
from tracker.schema import InputError, digest
from tracker.semantic_extraction import Pipeline
from tests.test_work_results import fixture


def response(req):
    winners={'material':'invocation_echo_only','result':'not_established','unmet_condition':'unresolved'}
    return {'model':req['model'],'answers':{name:{'type':'choice','choice':next(iter(q['criteria'])),
        'confidence':1,'probabilities':{option:float(option==winners[name]) for option in q['criteria']}}
        for name,q in req['questions'].items()}}


class WorkResultMaterialTests(unittest.TestCase):
    def test_operation_evidence_reused_with_selective_material_and_exact_replay(self):
        run,doc,matches=fixture(command='touch report.md',response='shell $ touch report.md\nshell $',plan=True)
        stages=[]
        def answer(req):
            stages.append(req['state']['stage'])
            winners={'mechanism':'change','error':'not_reported','warning':'not_reported',
                     'outcome':'not_established_change','material':'invocation_echo_only',
                     'result':'not_established','unmet_condition':'not_reported'}
            return {'model':req['model'],'answers':{k:{'type':'choice','probabilities':{c:float(c==winners[k]) for c in q['criteria']}} for k,q in req['questions'].items()}}
        with TemporaryDirectory() as root:
            engine=Pipeline(Path(root),None,answer)
            result,_=work_results.execute(run,doc,matches,engine,work_results.SUPPORTED_VERSION)
            self.assertEqual(engine.calls,6)
            self.assertEqual(stages[:4],['operation_mechanism','executor_reports','operation_outcome','work_response_material'])
            self.assertEqual(result['observations'][0]['operation_context'],result['observations'][1]['operation_context'])
            self.assertEqual(result['observations'][0]['operation_context']['source_material']['value'],'invocation_echo_only')
            replay=Pipeline(Path(root),None,lambda _:self.fail('Should reuse every request'))
            self.assertEqual(work_results.execute(run,doc,matches,replay,work_results.SUPPORTED_VERSION)[0],result)
            changed=deepcopy(result);changed['observations'][0]['operation_context']['outcome']='completed'
            with self.assertRaisesRegex(InputError,'replay'):work_results.audit(run,doc,matches,changed,root)

    def test_shared_material_but_separate_scope_results_and_no_future(self):
        run,doc,matches=fixture(command='touch report.md',response='shell $ touch report.md\nshell $',plan=True)
        requests=[]
        def decide(req):
            requests.append(req)
            return {k:{'value':v} for k,v in (
                {'material':'invocation_echo_only'} if req['state']['stage']=='work_response_material' else
                {'result':'not_established','unmet_condition':'not_reported'}).items()},digest(req)
        result=work_results.build(run,doc,matches,decide,work_results.MATERIAL_VERSION)
        self.assertEqual(len(requests),3)
        self.assertEqual(len(result['observations']),2)
        self.assertNotIn('FUTURE_',str(requests))
        self.assertNotIn('scope_text',requests[0]['state'])
        self.assertEqual(result['observations'][0]['response_material'],result['observations'][1]['response_material'])
        self.assertEqual(set(requests[1]['questions']['result']['criteria']),set(work_results.OPTIONS))
        projected=work_results.project(doc,result)
        self.assertEqual(projected['units'],doc['units'])
        self.assertEqual(projected['relations'][-1]['harness'],work_results.MATERIAL_VERSION)

    def test_missing_media_blocks_absence_but_not_positive_report_option(self):
        run,doc,matches=fixture(response='Image: data:image/png;base64,AAAA')
        pair=work_results.pairs(run,doc,matches)[0]
        req=work_results.request(run,doc,matches,pair,work_results.MATERIAL_VERSION,
            {'value':'returned_material','request_hash':'material-id'})
        self.assertEqual(set(req['questions']['unmet_condition']['criteria']),{'reported','unresolved'})
        self.assertEqual(req['state']['candidate_constraints'],['absence_requires_complete_readable_response'])
        self.assertFalse(work_result_material.complete({'unobserved_auxiliary_media':[{'field':'x'}]}))
        old=work_results.request(run,doc,matches,pair)
        self.assertIn('not_reported',old['questions']['unmet_condition']['criteria'])

    def test_invalid_material_fails_before_result_and_legacy_has_no_extra_call(self):
        run,doc,matches=fixture();calls=[]
        def decide(req):calls.append(req);return {'material':{'value':'made_up'}},digest(req)
        with self.assertRaisesRegex(InputError,'material selection'):
            work_results.build(run,doc,matches,decide,work_results.MATERIAL_VERSION)
        self.assertEqual(len(calls),1)
        pair=work_results.pairs(run,doc,matches)[0]
        with self.assertRaisesRegex(InputError,'prior response-material'):
            work_results.request(run,doc,matches,pair,work_results.MATERIAL_VERSION)

    def test_raw_argmax_replay_and_material_tamper(self):
        run,doc,matches=fixture()
        with TemporaryDirectory() as root:
            engine=Pipeline(Path(root),None,response)
            result,validation=work_results.execute(run,doc,matches,engine,work_results.MATERIAL_VERSION)
            self.assertTrue(validation['argmax_replayed']);self.assertEqual(engine.calls,2)
            self.assertEqual(result['observations'][0]['response_material']['value'],'invocation_echo_only')
            replay=Pipeline(Path(root),None,lambda _:self.fail('No new calls during replay'))
            self.assertEqual(work_results.execute(run,doc,matches,replay,work_results.MATERIAL_VERSION)[0],result)
            tampered=deepcopy(result);tampered['observations'][0]['response_material']['value']='execution_report'
            with self.assertRaisesRegex(InputError,'replay'):
                work_results.audit(run,doc,matches,tampered,root)


if __name__=='__main__':unittest.main()
