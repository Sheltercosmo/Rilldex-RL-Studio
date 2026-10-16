from copy import deepcopy
import json,tempfile,unittest
from pathlib import Path

from tracker.schema import InputError,digest
from tracker.jev import validate_answers,SELECTION_POLICY
from research.actor_intent_study import prepare,validate_cases,review_case,summarize,VARIANT
from research.relation_review import evaluate,evidence
from test_prefix_encoding_study import fixture as prefix_fixture
from test_relation_review import review


def result(case,variant,model):
    request=case['requests'][variant]
    answers=validate_answers({'answers':{k:{'type':'choice','choice':'absent','confidence':0,
        'probabilities':{'present':.34,'absent':.33,'unresolved':.33}} for k in request['questions']}},request)
    for a in answers.values():a.pop('evidence',None)
    return {'case_id':case['case_id'],'variant':variant,'set':'development','request_hash':digest(request),
            'model':model,'selection_policy':SELECTION_POLICY,'answers':answers}


def fixture(root):
    root=Path(root);parent=prefix_fixture(root)
    m=json.loads((parent/'manifest.json').read_text(encoding='utf-8'))
    cases=json.loads((parent/'cases.json').read_text(encoding='utf-8'))
    # Synthetic fixture only: complete its parent observations without a provider.
    (parent/'compact-development.jsonl').write_text(''.join(json.dumps(result(c,'compact',m['model']))+'\n' for c in cases),encoding='utf-8')
    folder=root/'actor';prepare(parent,folder)
    return folder


class ActorStudyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=fixture(self.temp.name)
        self.m=json.loads((self.folder/'manifest.json').read_text(encoding='utf-8'))
        self.cases=json.loads((self.folder/'cases.json').read_text(encoding='utf-8'))

    def test_blind_reviews_omit_earlier_results_and_binding_checks_reject_rewrites(self):
        _,_,blind,saved,_=evidence(self.folder)
        self.assertEqual(saved,{})
        for c in blind:
            text=json.dumps(c);self.assertNotIn('probabilities',text);self.assertNotIn('prior_plan_result',text)
            self.assertEqual(len(c['fields']),4)
            self.assertTrue(all(isinstance(e['text'],str) for e in c['available_prefix']))
        bad=deepcopy(self.cases);bad[0]['prior_plan_result']['answers']['source_plan']['value']='absent'
        with self.assertRaises(InputError):validate_cases(self.m,bad)
        bad=deepcopy(self.cases);bad[0]['requests'][VARIANT]['questions']['other_request']['instructions']='Changed'
        with self.assertRaises(InputError):validate_cases(self.m,bad)

    def test_prior_plan_cannot_supply_new_field_references_or_rewrite_predictions(self):
        report=evaluate(self.folder)
        self.assertEqual(report['by_profile'],{})
        first=report['inspection']['cases'][0]
        self.assertEqual(first['related_observations'][0]['answers']['source_plan']['value'],'present')
        self.assertTrue(all(f['prediction']['status']=='unobserved' for f in first['fields']))
        self.assertEqual(summarize(self.folder)['observed'],0)

    def test_scores_only_the_new_fields_and_preserves_overlapping_winners(self):
        rows=[result(c,VARIANT,self.m['model']) for c in self.cases]
        (self.folder/(VARIANT+'-development.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
        c=review_case(self.cases[0]);values={k:'present' for k in c['fields']}
        reviews=[review(c,self.m,name,values=values) for name in ('SYNTHETIC_A','SYNTHETIC_B')]
        labels=self.folder/'synthetic-reviews.jsonl';labels.write_text(''.join(json.dumps(r)+'\n' for r in reviews),encoding='utf-8')
        scored=evaluate(self.folder,[labels]);fields=next(iter(scored['by_profile'].values()))['fields']
        self.assertEqual(set(fields),set(values));self.assertNotIn('source_plan',fields)
        self.assertTrue(all(f['recall']==1 for f in fields.values()))
        self.assertTrue(all(f['prediction']['value']=='present' for f in scored['inspection']['cases'][0]['fields']))


if __name__=='__main__':unittest.main()
