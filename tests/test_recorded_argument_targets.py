"""Actual selector replay, retaining failed and regressed development cases."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from tracker import work_content_targets as targets, work_qualified_contents as qualified
from tracker import work_scope_interpretations as scopes
from tracker.schema import digest
from test_work_qualified_contents import choose

FIXTURE=Path(__file__).parent/'fixtures/feature-membership/argument-targets.json'


class RecordedArgumentTests(unittest.TestCase):
    def setUp(self):self.data=json.loads(FIXTURE.read_text(encoding='utf-8'))

    def replay(self,c,arm):
        a=c['arms'][arm];p,b,t,f=c['packet'],c['bound'],a['targets'],c['feature_id']
        req=targets.request(p,b,f,t,version=a['selector_version'])
        self.assertEqual(digest(req),a['request_hash'])
        raw=self.data['responses'][a['request_hash']]
        d=targets.resolve(p,b,f,t,raw,version=a['selector_version'])
        self.assertEqual(digest(d),a['decision_hash'])
        view=targets.project(p,b,f,t,d)
        self.assertEqual(digest(view),a['projection_hash'])
        return d,view

    def test_actual_requests_replay_offline_including_known_failures(self):
        counts={a:0 for a in self.data['cases'][0]['arms']}
        with patch('tracker.jev.JevClient._post',side_effect=AssertionError('offline')):
            for c in self.data['cases']:
                for arm in counts:
                    with self.subTest(case=c['case'],arm=arm):
                        d,_=self.replay(c,arm);r=c['reference']
                        selected=d['detail']['expression']['text'] if d['detail'] else d['target_choice']
                        counts[arm]+=d['role']==r['role'] and d['form']==r['form'] and selected in r['acceptable']
        self.assertEqual(counts,{'arguments':3,'arguments-predicates':5,'arguments-assertions':7,'arguments-head':8})
        self.assertEqual(len(self.data['responses']),32)

    def test_syntax_predicate_candidates_do_not_keep_participant_nouns(self):
        for c in self.data['cases']:
            if not c['syntax'] or c['case']=='missing-predicate':continue
            actual=targets.argument_targets_from_syntax(c['packet'],c['bound'],c['content_id'],c['syntax'])
            self.assertEqual(actual,c['arms']['arguments-predicates']['targets'])
            self.assertTrue(all(p['expression']['text'] not in {'we','me','pdflatex','the Markdown file'} for p in actual['parts']))

    def test_occurrence_highlighting_distinguishes_repeated_we_without_offset_guess(self):
        snippets=[]
        for name in ['reasoning-simplifier','reasoning-possession']:
            c=next(c for c in self.data['cases'] if c['case']==name);a=c['arms']['arguments-head']
            req=targets.request(c['packet'],c['bound'],c['feature_id'],a['targets'],version=a['selector_version'])
            marked=req['state']['source_with_argument_occurrence'];snippets.append(marked)
            self.assertEqual(marked.replace('[ARGUMENT OCCURRENCE]','').replace('[/ARGUMENT OCCURRENCE]',''),c['packet']['units'][0]['source']['text'])
        self.assertNotEqual(*snippets)
        self.assertIn('[ARGUMENT OCCURRENCE]we[/ARGUMENT OCCURRENCE] can simplify',snippets[0])
        self.assertIn('[ARGUMENT OCCURRENCE]we[/ARGUMENT OCCURRENCE] have',snippets[1])

    def test_connected_review_carries_real_argument_receipt_into_partial_view(self):
        c=next(c for c in self.data['cases'] if c['case']=='installation-state')
        p,b,f=c['packet'],c['bound'],c['feature_id'];messages=[]
        def send(req):
            messages.append(req)
            if req['state']['harness']==scopes.VERSION:
                key=next(r['id'] for r in req['state']['readings'] if r['content_ids']==[c['content_id']] and r['application']=='individual')
                return choose(req,{'reading':key}) # Scope plumbing only, not semantic gold.
            return self.data['responses'][digest(req)]
        result=qualified.review(p,b,syntax=c['syntax'],send=send,feature_ids=[f],argument_roles=True)
        self.assertTrue(result['argument_roles'])
        self.assertEqual(result['completed_requests'],2)
        row=next(x for x in result['view']['qualifications'] if x['feature']['id']==f)
        self.assertEqual(row['feature']['type'],'argument')
        self.assertEqual(row['targets'][0]['role'],'state_bearer')
        self.assertEqual(row['targets'][0]['target']['expression']['text'],'that `pdflatex` is not installed')
        self.assertFalse(result['view']['ready_for_relationships'])
        self.assertEqual(result['view']['contents'],b['contents'])


if __name__=='__main__':unittest.main()
