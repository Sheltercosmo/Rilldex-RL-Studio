"""Actual candidate deliveries and Jev responses, with known errors retained."""
import json
from pathlib import Path
import tempfile
import unittest

from rilldex.scopes import extract
from tracker import work_content_bindings as scopes, work_content_stages as stages
from tracker.schema import InputError, digest


class ScopedWorkflowReplayTests(unittest.TestCase):
    def test_exact_source_binding_candidate_failures_and_scope_contrasts(self):
        data=json.loads((Path(__file__).parent/'fixtures/scoped_workflow.json').read_text(encoding='utf-8'))
        baseline=[];direct=[]
        for row in data['cases']:
            with self.subTest(case=row['case']):
                p=row['packet'];uid=row['bound']['unit_id']
                req=stages.scoped_content_request(p,uid)
                self.assertEqual(req,row['content_request'])
                with self.assertRaises(InputError):
                    stages.bind_scoped_contents(p,req,row['content_original'],'luna-subagent/content-stage/1')
                contents=stages.bind_scoped_contents(p,req,row['content_repaired'],'luna-subagent/content-stage/1')
                fq=stages.scoped_feature_request(p,contents)
                self.assertEqual(fq,row['feature_request'])
                bound=stages.bind_scoped_features(p,contents,fq,row['feature_response'],'luna-subagent/content-stage/1')
                self.assertEqual(bound,row['bound'])
                for item in row['decisions']:
                    fid=item['feature_id'];feature=next(f for f in bound['features'] if f['id']==fid)
                    args=dict(intent_rule='expressed_work' if feature['type']=='intent' else 'attachment',argument_rule=item['argument_rule'])
                    self.assertEqual(scopes.membership_scope_request(p,bound,fid,**args),item['request'])
                    result=scopes.membership_scope_result(p,bound,fid,item['response'],**args)
                    view=scopes.project_membership_scope(p,bound,result)
                    self.assertEqual(view['unit']['source'],req['unit']['source'])
                    target=direct if item['argument_rule']=='direct_owner' else baseline
                    target.append(result['content_ids']==item['expected'])
                    if item['argument_rule']=='direct_owner':
                        self.assertEqual(view['scope_semantics'],'direct_argument_owner')
        self.assertEqual((len(baseline),sum(baseline)),(20,17))
        self.assertEqual((len(direct),sum(direct)),(4,3))
        # This fixture includes omitted content and role ambiguity, independently
        # of whether a scope selector agrees on the supplied contents.
        self.assertTrue(any(c['reference']['content_issues'] for c in data['cases']))
        self.assertTrue(any(c['reference']['feature_issues'] for c in data['cases']))
        self.assertIsNone(data['candidate_tokens'])

    def test_candidate_to_partial_review_to_resume_uses_frozen_responses(self):
        data=json.loads((Path(__file__).parent/'fixtures/scoped_workflow.json').read_text(encoding='utf-8'))
        row=data['cases'][0];p=row['packet'];uid=row['bound']['unit_id'];calls=[]
        decisions={digest(d['request']):d['response'] for d in row['decisions'] if d['argument_rule']=='attachment'}
        def propose(payload):
            q=payload['request'];calls.append(('candidate',q['stage']))
            body=row['feature_response'] if q['stage']=='features' else row['content_repaired'] if 'repair' in q else row['content_original']
            return dict(raw_output=json.dumps(body),usage={})
        def choose(q):calls.append(('jev',q['state']['feature']['id']));return decisions[digest(q)]
        with tempfile.TemporaryDirectory() as temp:
            args=dict(candidate_calls=3,decision_calls=1,input_bytes=1000000,candidate_transport=propose,
                candidate_identity='luna-subagent/content-stage/1',decision_transport=choose,direct_arguments=False,content_policy='legacy')
            first=extract(p,uid,temp,**args)
            self.assertEqual(first['status'],'budget_reached')
            self.assertEqual(len(first['review']['features']),1)
            args['decision_calls']=8
            final=extract(p,uid,temp,**args)
            self.assertEqual(final['status'],'complete')
            self.assertEqual(len(final['review']['features']),7)
            self.assertEqual(final['bound'],row['bound'])
            count=len(calls);extract(p,uid,temp,**args)
            self.assertEqual(len(calls),count)


if __name__=='__main__':unittest.main()
