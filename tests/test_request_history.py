from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from tracker.schema import InputError
from tracker.jev import DEFAULT_MODEL
from tracker.semantic_extraction import Pipeline,read
from tracker.request_history import Observer,audit,packets,MAX_PRIORS
from tests.test_semantic_extraction import fixture,response
from tests.test_participant_extraction import CandidateFixture


def history_response(req):
    return {'model':DEFAULT_MODEL,'answers':{key:{'type':'choice','choice':'no_update','confidence':0,
        'probabilities':{k:0.7 if k=='reaffirms' else 0.06 for k in q['criteria']}}
        for key,q in req['questions'].items()}}


class RequestHistoryTests(unittest.TestCase):
    def test_only_prior_same_speaker_records_and_raw_argmax_survive_replay(self):
        run=fixture()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);result=Pipeline(root,CandidateFixture(root/'c'),response).run(run,include_user=True)
            observer=Observer(root,history_response);output=observer.run(run,result)
            self.assertEqual(observer.calls,1)
            self.assertEqual(output['relations'][0]['type'],'request_reaffirms')
            self.assertEqual(audit(run,result,output,root)['pair_choices'],1)
            current,prior,req=next(packets(run,result))
            self.assertEqual([u['actor'] for u in prior],['user'])
            self.assertEqual(prior[0]['source']['event_id'],'e1')
            self.assertEqual(current['source']['event_id'],'e3')
            self.assertNotIn('agent',set(u['actor'] for u in req['state']['prior_records']))
            observer.run(run,result);self.assertEqual(observer.calls,1)
            bad=deepcopy(output);bad['relations'][0]['type']='completed'
            with self.assertRaisesRegex(InputError,'Published request history differs'):audit(run,result,bad,root)
            changed=deepcopy(result);changed['units'][0]['content']['summary']['text']='Different reading'
            with self.assertRaisesRegex(InputError,'dependencies differ'):audit(run,changed,output,root)

    def test_long_history_retains_root_and_reports_every_omitted_prior(self):
        from tracker.adapters import normalize
        run=normalize({'schema_version':'ATIF-v1.7','session_id':'long-request-history',
            'agent':{'name':'test','version':'1'},'steps':[{'step_id':i+1,'source':'user',
              'message':f'Requested detail {i}.'} for i in range(MAX_PRIORS+4)]})[0]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);result=Pipeline(root,CandidateFixture(root/'c'),response).run(run,include_user=True)
            current,prior,req=list(packets(run,result))[-1]
            self.assertEqual(len(prior),MAX_PRIORS)
            self.assertEqual(prior[0]['source']['event_id'],run['events'][0]['id'])
            omitted=req['state']['omitted_prior_unit_ids']
            self.assertEqual(len(omitted),3)
            self.assertNotIn(current['id'],[u['id'] for u in prior])
            self.assertEqual(len(set(omitted)|{u['id'] for u in prior}),MAX_PRIORS+3)


if __name__=='__main__':unittest.main()
