"""Actual Jev receipts, frozen references and connected multi-role projection."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from tracker import work_argument_pairs as pairs, work_content_targets as targets
from tracker import work_qualified_contents as qualified, work_scope_interpretations as scopes
from tracker.schema import digest
from test_work_qualified_contents import choose, inventory

FIXTURE=Path(__file__).parent/'fixtures/feature-membership/argument-predicate-heads.json'


class RecordedArgumentPairTests(unittest.TestCase):
    def setUp(self):self.data=json.loads(FIXTURE.read_text(encoding='utf-8'))

    def replay(self,c,arm):
        a=c['arms'][arm];p,b,f,t,s=c['packet'],c['bound'],c['feature_id'],c['targets'],c['syntax']
        raw=self.data['responses'][a['request_hash']]
        if arm in {'pairs','occurrence_pairs'}:
            req=pairs.request(p,b,f,t,s,version=a['version'])
            decision=pairs.resolve(p,b,f,t,s,raw,version=a['version'])
            view=pairs.project(p,b,f,t,decision)
        else:
            extra={'syntax_record':s} if arm=='head_evidence' else {}
            req=targets.request(p,b,f,t,version=a['version'],**extra)
            decision=targets.resolve(p,b,f,t,raw,version=a['version'],**extra)
            view=targets.project(p,b,f,t,decision)
        self.assertEqual(digest(req),a['request_hash'])
        self.assertEqual(digest(decision),a['decision_hash'])
        self.assertEqual(digest(view),a['projection_hash'])
        return decision,view

    def test_all_sixty_requests_replay_without_hiding_regressions(self):
        single={a:{'known_development':0,'new_controls':0} for a in ['baseline','head_evidence']}
        paired={a:dict(correct_pairs=0,total_pairs=0,complete=0) for a in ['pairs','occurrence_pairs']}
        with patch('tracker.jev.JevClient._post',side_effect=AssertionError('offline replay')):
            for c in self.data['cases']:
                for arm in c['arms']:
                    with self.subTest(case=c['case'],arm=arm):
                        d,_=self.replay(c,arm)
                        if arm in single:
                            target=d['detail']['expression']['text'] if d['detail'] else d['target_choice']; r=c['single_reference']
                            single[arm][c['split']]+=d['role']==r['role'] and d['form']==r['form'] and target in r['acceptable']
                        else:
                            actual={r['expression']['text'] if r['target_choice']!='whole_content' else 'whole_content':r['role'] for r in d['relations']}
                            ref=c['pair_reference'];counts=paired[arm]
                            counts['total_pairs']+=len(ref['roles'])
                            counts['correct_pairs']+=sum(actual[k]==v for k,v in ref['roles'].items())
                            counts['complete']+=actual==ref['roles'] and d['coverage']==ref['coverage'] and d['form']==c['single_reference']['form']
        self.assertEqual(single,{'baseline':{'known_development':8,'new_controls':3},
                                 'head_evidence':{'known_development':9,'new_controls':3}})
        self.assertEqual(paired,{'pairs':dict(correct_pairs=28,total_pairs=31,complete=9),
                                 'occurrence_pairs':dict(correct_pairs=29,total_pairs=31,complete=12)})
        self.assertEqual(len(self.data['responses']),60)

    def test_connected_review_preserves_recipient_and_performer_for_same_mention(self):
        c=next(c for c in self.data['cases'] if c['case']=='nested-request')
        p,b,f=c['packet'],c['bound'],c['feature_id'];progress=[];requests=[]
        def send(req):
            requests.append(req)
            if req['state']['harness']==scopes.VERSION:
                reading=next(r['id'] for r in req['state']['readings'] if r['content_ids']==['switch'] and r['application']=='individual')
                return choose(req,{'reading':reading}) # Scope plumbing; not independent accuracy evidence.
            return self.data['responses'][digest(req)]
        result=qualified.review(p,b,syntax=c['syntax'],send=send,feature_ids=[f],
            inventory_selection=inventory(p,b),argument_roles=True,argument_version=pairs.VERSION,on_progress=progress.append)
        self.assertEqual(result['completed_requests'],2)
        self.assertEqual(len(requests),2) # Pair roles do not add a separate request per predicate.
        self.assertEqual([s['stage'] for s in progress],['scope','target'])
        view=result['view'];self.assertTrue(view['ready_for_relationships'])
        self.assertEqual(view['contents'],b['contents'])
        row=view['qualifications'][0]
        self.assertEqual([(r['role'],r['target']['expression']['text']) for r in row['targets']],
                         [('recipient','to ask Dana to review the log'),('actor','to review the log')])
        request=qualified.relationship_request(p,b,**result['reviews'])
        self.assertEqual(request['qualifications'],view['qualifications'])
        self.assertIn('recipient',request['argument_role_questions'])

    def test_known_repeated_pronoun_error_and_coverage_error_stay_visible(self):
        c=next(c for c in self.data['cases'] if c['case']=='reasoning-simplifier')
        d,_=self.replay(c,'occurrence_pairs')
        self.assertEqual(next(r['role'] for r in d['relations'] if r['expression']['text']=='we have'),'state_bearer')
        self.assertEqual(c['pair_reference']['roles']['we have'],'not_argument')
        c=next(c for c in self.data['cases'] if c['case']=='embedded-passive')
        d,v=self.replay(c,'occurrence_pairs')
        self.assertEqual(d['coverage'],'missing_predicate')
        self.assertEqual(v['status'],'partial')
        self.assertEqual(v['qualifications'][0]['role'],'object')


if __name__=='__main__':unittest.main()
