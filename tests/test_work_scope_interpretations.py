from copy import deepcopy
import json
from pathlib import Path
import unittest

from tracker import work_content_bindings as scoped, work_scope_interpretations as readings
from tracker.schema import InputError,digest


def fixture(name='joint-negation'):
    path=Path(__file__).parent/'fixtures/feature-membership/recorded-controls.json'
    case=next(c for c in json.loads(path.read_text(encoding='utf-8'))['cases'] if c['case']==name)
    return case['packet'],case['bound'],case['feature_id']


def response(req, *, application='joint', ids=('delete','overwrite'), sentinel=None):
    chosen=sentinel or next(r['id'] for r in req['state']['readings'] if r['application']==application and r['content_ids']==list(ids))
    keys=req['questions']['reading']['criteria']
    return dict(model=req['model'],answers=dict(reading=dict(type='choice',choice='unresolved',confidence=0,
        probabilities={k:.4 if k==chosen else .6/(len(keys)-1) for k in keys})))


class ScopeInterpretationTests(unittest.TestCase):
    def test_same_targets_have_distinct_application_readings_and_argmax(self):
        p,b,f=fixture();req=readings.request(p,b,f)
        modes={r['application'] for r in req['state']['readings'] if r['content_ids']==['delete','overwrite']}
        self.assertEqual(modes,{'individual','joint'})
        selected=readings.resolve(p,b,f,response(req))
        self.assertEqual(selected['selected']['application'],'joint')
        self.assertEqual(selected['selection_policy'],'argmax/1')
        self.assertNotEqual(selected['choice'],selected['response']['answers']['reading']['choice'])
        self.assertEqual(req['state']['unit']['source'],p['units'][0]['source'])

    def test_joint_projection_never_distributes_qualification_to_members(self):
        p,b,f=fixture();before=deepcopy((p,b));req=readings.request(p,b,f)
        selected=readings.resolve(p,b,f,response(req));view=readings.project(p,b,f,selected)
        self.assertEqual(view['individual_applications'],[])
        group=view['joint_applications'][0]
        self.assertEqual([c['id'] for c in group['members']],['delete','overwrite'])
        self.assertEqual(group['feature']['expression']['text'],'Do not both')
        self.assertEqual(group['source_context'],p['units'][0]['source'])
        self.assertTrue(all('features' not in c for c in group['members']))
        self.assertEqual(view['publication'],'review_only')
        self.assertEqual(view['execution_status'],'not_established_by_prose')
        self.assertEqual((p,b),before)

    def test_individual_projection_excludes_unselected_work(self):
        p,b,f=fixture('shared-negation');req=readings.request(p,b,f)
        selected=readings.resolve(p,b,f,response(req,application='individual'))
        view=readings.project(p,b,f,selected)
        self.assertEqual(view['joint_applications'],[])
        self.assertEqual([row['content']['id'] for row in view['individual_applications']],['delete','overwrite'])

    def test_no_suitable_or_unresolved_reading_does_not_create_applications(self):
        p,b,f=fixture();req=readings.request(p,b,f)
        for choice in ['no_suitable_reading','unresolved']:
            selected=readings.resolve(p,b,f,response(req,sentinel=choice))
            self.assertIsNone(selected['selected'])
            view=readings.project(p,b,f,selected)
            self.assertEqual(view['status'],choice)
            self.assertEqual(view['individual_applications'],[])
            self.assertEqual(view['joint_applications'],[])

    def test_reordered_proposals_and_redundant_singletons_keep_request(self):
        p,b,f=fixture();body=deepcopy(b['raw_response'])
        body['contents'].reverse();body['features'][0]['scopes'].reverse()
        changed=scoped.bind(p,scoped.request(p,b['unit_id']),body,'reordered')
        self.assertEqual(readings.request(p,b,f),readings.request(p,changed,f))
        body['features'][0]['scopes']=[scope for scope in body['features'][0]['scopes'] if len(scope)>1]
        changed=scoped.bind(p,scoped.request(p,b['unit_id']),body,'without explicit singleton options')
        self.assertEqual(readings.request(p,b,f),readings.request(p,changed,f))

    def test_missing_group_is_not_invented_or_claimed_as_complete_coverage(self):
        p,b,f=fixture();body=deepcopy(b['raw_response']);body['features'][0]['scopes']=[['list']]
        changed=scoped.bind(p,scoped.request(p,b['unit_id']),body,'missing group')
        req=readings.request(p,changed,f)
        self.assertTrue(all(len(r['content_ids'])==1 for r in req['state']['readings']))
        self.assertFalse(req['state']['scope_coverage']['all_multi_content_scopes'])
        self.assertNotEqual(req,readings.request(p,b,f))

    def test_mutated_receipts_foreign_features_models_and_probabilities_fail(self):
        p,b,f=fixture();req=readings.request(p,b,f)
        selected=readings.resolve(p,b,f,response(req));selected['selected']['application']='individual'
        with self.assertRaisesRegex(InputError,'receipt changed'):readings.project(p,b,f,selected)
        with self.assertRaises(InputError):readings.request(p,b,'foreign')
        for field in ['model','probability']:
            raw=response(req)
            if field=='model':raw['model']='other'
            else:raw['answers']['reading']['probabilities']['foreign']=0.1
            with self.subTest(field=field),self.assertRaises(InputError):readings.resolve(p,b,f,raw)

    def test_original_api_results_replay_including_incorrect_application(self):
        path=Path(__file__).parent/'fixtures/feature-membership/scope-interpretations.json'
        results={}
        for case in json.loads(path.read_text(encoding='utf-8'))['cases']:
            with self.subTest(case=case['case']):
                p,b,f=case['packet'],case['bound'],case['feature_id']
                req=readings.request(p,b,f)
                self.assertEqual(req,case['request'])
                self.assertEqual(case['receipt']['request_hash'],digest(req))
                self.assertEqual(case['receipt']['response_hash'],digest(case['response']))
                self.assertEqual(case['receipt']['status'],'response_received')
                decision=readings.resolve(p,b,f,case['response'])
                self.assertEqual(decision,case['result'])
                view=readings.project(p,b,f,decision)
                self.assertEqual(digest(view),case['projection_hash'])
                results[case['case']]=decision['selected']
        self.assertEqual(results['shared-negation']['application'],'individual')
        self.assertEqual(results['joint-negation']['application'],'joint')
        self.assertEqual(results['same-sentence-motivation']['content_ids'],['cache'])
        # Preserved failure: "neither A nor B" should qualify each prohibited
        # operation, but this response selected joint application. Do not repair
        # it in the projector or call replay success a semantic accuracy pass.
        self.assertEqual(results['neither-coordination']['application'],'joint')


if __name__=='__main__':unittest.main()
