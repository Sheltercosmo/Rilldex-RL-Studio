"""Actual frozen Jev responses through current candidate and review defaults."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from tracker import work_qualified_contents as qualified,work_content_targets as details
from tracker import work_scope_interpretations as scopes
from tracker.schema import digest


def fixture():
    return json.loads((Path(__file__).parent/'fixtures/feature-membership/qualification-flow.json').read_text(encoding='utf-8'))


class RecordedQualificationFlowTests(unittest.TestCase):
    def test_current_flow_recovers_omitted_groups_and_preserves_meaningful_targets(self):
        data=fixture()
        for case in data['cases']:
            with self.subTest(case=case['case']):
                frozen=deepcopy(case);calls=[];progress=[]
                p,b,f,s=case['packet'],case['bound'],case['feature_id'],case['syntax']
                req=scopes.request(p,b,f)
                self.assertFalse(any(r['content_ids']==case['reference']['content_ids'] for r in req['state']['readings']))
                def send(req):
                    key=digest(req);stored=data['wires'][key]
                    self.assertEqual(stored['request'],req)
                    self.assertEqual(stored['receipt']['request_hash'],key)
                    self.assertEqual(stored['receipt']['response_hash'],digest(stored['response']))
                    self.assertEqual(stored['receipt']['status'],'response_received')
                    calls.append(key);return stored['response']
                out=qualified.review(p,b,syntax=s,feature_ids=[f],send=send,on_progress=progress.append)
                self.assertEqual(calls,case['calls'])
                self.assertEqual(digest(out),case['result_hash'])
                self.assertEqual(len(progress),out['completed_requests'])
                selected=out['reviews']['scope_reviews'][0]['decision']['selected']
                self.assertEqual(selected['content_ids'],case['reference']['content_ids'])
                row=next(q for q in out['view']['qualifications'] if q['feature']['id']==f)
                self.assertEqual(row['application'],case['reference']['application'])
                if row['application']=='individual':
                    owners={c['id']:c for c in b['contents']}
                    for target in row['targets']:
                        self.assertEqual(target['target']['kind'],'whole_content')
                        self.assertEqual(target['target']['expression'],owners[target['content_id']]['expression'])
                else:
                    self.assertEqual(row['targets'][0]['distribution'],'not_distributed')
                    self.assertEqual(out['reviews']['target_reviews'],[])
                self.assertEqual(case,frozen)
                self.assertFalse(out['view']['ready_for_relationships'])

    def test_default_intention_targets_keep_predicates_and_respect_owner_boundaries(self):
        for case in fixture()['intention_targets']:
            with self.subTest(case=case['case']):
                p,b,f,t=case['packet'],case['bound'],case['feature_id'],case['targets']
                req=details.request(p,b,f,t)
                self.assertEqual(req,case['request'])
                out=details.resolve(p,b,f,t,case['response'])
                self.assertEqual(out,case['decision'])
                self.assertEqual(out['schema'],details.SELECTOR_VERSION)
                self.assertEqual(out['status'],case['reference']['status'])
                if 'acceptable_texts' in case['reference']:
                    self.assertIn(out['detail']['expression']['text'],case['reference']['acceptable_texts'])


if __name__=='__main__':unittest.main()
