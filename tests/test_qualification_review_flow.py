"""Software workflow controls; manufactured replies do not measure accuracy."""
from copy import deepcopy
import tempfile
import unittest

from tracker import work_content_bindings as contents,work_qualified_contents as qualified
from tracker.metered_jev import BoundedTransport,BudgetExhausted
from tracker.schema import InputError
from tests.test_work_syntax_evidence import recorded


def source(name='shared-method'):
    c,s=recorded(name);p,b=c['packet'],c['bound']
    body=deepcopy(b['raw_response']);body['features'][0]['scopes']=[[body['contents'][-1]['id']]]
    b=contents.bind(p,contents.request(p,b['unit_id']),body,'omitted group control')
    return p,b,s['syntax']


def answer(req,application='individual',ids=('inspect','validate'),sentinel=None):
    key=next(iter(req['questions']));q=req['questions'][key]
    choice=('whole_content' if key=='target' else sentinel or next(r['id'] for r in req['state']['readings']
        if r['content_ids']==list(ids) and r['application']==application))
    return dict(model=req['model'],answers={key:dict(type='choice',probabilities={c:float(c==choice) for c in q['criteria']})})


class QualificationReviewFlowTests(unittest.TestCase):
    def test_missing_group_flows_from_syntax_to_per_content_detail_review(self):
        p,b,s=source();before=deepcopy((p,b,s));requests=[];progress=[]
        def send(req):requests.append(deepcopy(req));return answer(req)
        out=qualified.review(p,b,syntax=s,send=send,on_progress=progress.append)
        self.assertEqual(len(requests),3)
        self.assertEqual([x['stage'] for x in progress],['scope','target','target'])
        self.assertEqual([x['completed_requests'] for x in progress],[1,2,3])
        self.assertEqual(progress[0]['view']['qualifications'][0]['status'],'target_review_incomplete')
        row=out['view']['qualifications'][0]
        self.assertEqual(row['status'],'selected')
        self.assertEqual([t['target']['content_id'] for t in row['targets']],['inspect','validate'])
        self.assertTrue(all(t['target']['kind']=='whole_content' for t in row['targets']))
        self.assertEqual(out['view']['inventory_assessment'],'not_reviewed')
        self.assertFalse(out['view']['ready_for_relationships'])
        progress[-1]['reviews']['scope_reviews'].clear()
        self.assertEqual(len(out['reviews']['scope_reviews']),1)
        self.assertEqual((p,b,s),before)

    def test_stop_and_resume_reuses_exact_requests_without_repeating_paid_calls(self):
        p,b,s=source();progress=[]
        with tempfile.TemporaryDirectory() as temp:
            limited=BoundedTransport(temp,2,send=answer)
            with self.assertRaises(BudgetExhausted):
                qualified.review(p,b,syntax=s,send=limited,on_progress=progress.append)
            self.assertEqual(limited.calls,2)
            self.assertEqual(progress[-1]['completed_requests'],2)
            resumed=BoundedTransport(temp,3,send=answer)
            out=qualified.review(p,b,syntax=s,send=resumed)
            self.assertEqual(resumed.calls,1);self.assertEqual(out['completed_requests'],3)
            offline=BoundedTransport(temp,0,send=lambda req:self.fail('Unchanged request must use cache'))
            self.assertEqual(qualified.review(p,b,syntax=s,send=offline),out)

    def test_joint_scope_does_not_trigger_individual_detail_requests(self):
        p,b,s=source('joint-negation');requests=[]
        def send(req):requests.append(req);return answer(req,'joint',('delete','overwrite'))
        out=qualified.review(p,b,syntax=s,send=send)
        self.assertEqual(len(requests),1);self.assertEqual(out['reviews']['target_reviews'],[])
        row=out['view']['qualifications'][0]
        self.assertEqual(row['application'],'joint')
        self.assertEqual(row['targets'][0]['distribution'],'not_distributed')

    def test_unresolved_scope_remains_visible_without_fabricated_detail_targets(self):
        p,b,s=source()
        out=qualified.review(p,b,syntax=s,send=lambda r:answer(r,sentinel='unresolved'))
        self.assertEqual(out['completed_requests'],1)
        self.assertEqual(out['view']['qualifications'][0]['status'],'unresolved')
        self.assertEqual(out['reviews']['target_reviews'],[])

    def test_invalid_inputs_are_rejected_before_transport(self):
        p,b,s=source();bad=deepcopy(s);bad['parsed']['source']['text']='Different source'
        for opts in (dict(feature_ids=['absent']),dict(feature_ids=['attachment','attachment']),
                     dict(scope_version='guessed'),dict(inventory_selection={}),dict(syntax=bad)):
            with self.subTest(opts=list(opts)),self.assertRaises(InputError):
                qualified.review(p,b,**(dict(syntax=s)|opts),send=lambda r:self.fail('No paid call'))


if __name__=='__main__':unittest.main()
