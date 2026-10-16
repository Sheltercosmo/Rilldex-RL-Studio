"""Synthetic request controls, provenance and review separation, not semantic truth."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from test_relation_contracts import evidence
from research.plan_locality import prepare,validate_cases,summarize,export_reviews,VARIANTS
from research.relation_review import evaluate
from test_relation_review import review
from tracker.relation_contracts import source_plan_packet,local_plan_packet
from tracker.jev import DEFAULT_MODEL,SELECTION_POLICY,validate_answers
from tracker.schema import InputError,digest


def write_json(path,data):path.write_text(json.dumps(data),encoding='utf-8')
def read_json(path):return json.loads(path.read_text(encoding='utf-8'))


def fixture(root):
    root=Path(root);prefix,a,b=evidence();scope=root/'scope';scope.mkdir()
    scope_cases=[{'case_id':'pair','domain':'software','adapter':'synthetic-test'}]
    sm={'version':'relation-scope-study/1','selection_policy':SELECTION_POLICY,'cases_hash':digest(scope_cases)}
    write_json(scope/'manifest.json',sm);write_json(scope/'cases.json',scope_cases)
    for name,source in [('corpus',a),('roles',b)]:
        folder=root/name;folder.mkdir();request=source_plan_packet(prefix,source)
        case={'case_id':name,'set':'development','trace_id':'trace','source_hash':'synthetic-source','requests':{'source_time':request}}
        if name=='corpus':case.update(domain='reasoning',adapter='synthetic-test',native_reference={'value':'absent','labels':['reasoning','reasoning'],'product_reference':False})
        else:case['parent_cases']=['pair']
        manifest={'version':'source-plan-corpus-study/1' if name=='corpus' else 'source-role-study/1',
                  'model':DEFAULT_MODEL,'selection_policy':SELECTION_POLICY,'variants':['source_time'],'cases_hash':digest([case])}
        if name=='roles':manifest['parent_manifest_hash']=digest(sm)
        write_json(folder/'manifest.json',manifest);write_json(folder/'cases.json',[case])
        answer=validate_answers({'answers':{'source_plan':{'type':'choice','confidence':0,'choice':'absent',
            'probabilities':{'present':.34,'absent':.33,'unresolved':.33}}}},request)
        row={'case_id':name,'variant':'source_time','set':'development','request_hash':digest(request),
             'selection_policy':SELECTION_POLICY,'model':DEFAULT_MODEL,'answers':answer,'usage':{'input_tokens':50}}
        (folder/'source_time-development.jsonl').write_text(json.dumps(row)+'\n',encoding='utf-8')
    prepare(root/'corpus',root/'roles',root/'scope',root/'comparison')
    return root/'comparison'


class PlanLocalityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.pack=fixture(self.root)
        self.cases=read_json(self.pack/'cases.json');self.manifest=read_json(self.pack/'manifest.json')

    def fill(self,variant,values):
        rows=[]
        for case,value in zip(self.cases,values):
            request=case['requests'][variant]
            answers=validate_answers({'answers':{'source_plan':{'type':'choice','probabilities':{k:float(k==value) for k in ('present','absent','unresolved')}}}},request)
            rows.append({'case_id':case['case_id'],'variant':variant,'set':'development','model':DEFAULT_MODEL,
                         'selection_policy':SELECTION_POLICY,'request_hash':digest(request),'answers':answers,'usage':{'input_tokens':10}})
        (self.pack/(variant+'-development.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')

    def test_local_candidate_changes_only_question_and_harness(self):
        prefix,a,b=evidence();base=source_plan_packet(prefix,a);saved=deepcopy(base);candidate=local_plan_packet(prefix,a)
        state=deepcopy(candidate['state']);state['harness']=base['state']['harness']
        self.assertEqual(state,base['state']);self.assertEqual(base,saved)
        self.assertEqual(candidate['model'],base['model']);self.assertEqual(set(candidate['questions']),{'source_plan'})
        prefix[0]['text']+=' HIDDEN FUTURE RESULT';prefix[0]['label']='hidden native annotation'
        self.assertEqual(candidate,local_plan_packet(prefix,a))
        self.assertNotEqual(candidate['questions'],base['questions'])

    def test_saved_baseline_preserved_and_partial_study_never_invents_decisions(self):
        report=summarize(self.pack)
        self.assertFalse(report['complete']);self.assertEqual(report['reused_results'],2)
        self.assertEqual(report['new_provider_calls'],0);self.assertEqual(report['new_usage'],{})
        self.assertEqual(report['rows'][0]['choices'],{'baseline':'present','repeat':None,'local':None})
        self.assertIsNone(report['product_accuracy'])
        with self.assertRaises(InputError):prepare(self.root/'corpus',self.root/'roles',self.root/'scope',self.pack)

    def test_repeat_differences_and_changed_wording_are_separate_from_accuracy(self):
        self.fill('repeat',['present','absent']);self.fill('local',['absent','present'])
        report=summarize(self.pack);counts=report['counts']['all']
        self.assertTrue(report['complete']);self.assertEqual(report['new_provider_calls'],4)
        self.assertEqual(report['new_usage']['input_tokens'],40);self.assertEqual(report['reused_results'],2)
        self.assertEqual((counts['repeat_differs'],counts['local_differs_baseline'],counts['local_differs_repeat'],counts['local_differs_with_baselines_agreeing']),(1,1,2,1))
        self.assertEqual(report['native_schema_comparison']['local']['matching'],1)
        self.assertEqual(report['independent_product_references'],0);self.assertIsNone(report['product_accuracy'])

    def test_review_contracts_are_bound_separately_and_omit_predictions_and_native_labels(self):
        export_reviews(self.pack)
        base=read_json(self.pack/'blind-cases-baseline.json');repeat=read_json(self.pack/'blind-cases-repeat.json');local=read_json(self.pack/'blind-cases-local.json')
        self.assertEqual(base,repeat)
        self.assertNotEqual(base['cases'][0]['case_hash'],local['cases'][0]['case_hash'])
        for data in (base,repeat,local):
            self.assertNotIn('probabilities',json.dumps(data));self.assertNotIn('native_reference',json.dumps(data))
        with self.assertRaises(InputError):export_reviews(self.pack)

    def test_mutated_control_or_result_rejected_even_with_updated_container_hash(self):
        cases=deepcopy(self.cases);cases[0]['requests']['repeat']['questions']['source_plan']['instructions']='changed repeat'
        with self.assertRaises(InputError):validate_cases({**self.manifest,'cases_hash':digest(cases)},cases)
        cases=deepcopy(self.cases);cases[1]=deepcopy(cases[0]);cases[1]['case_id']='duplicate-source'
        with self.assertRaises(InputError):validate_cases({**self.manifest,'cases_hash':digest(cases)},cases)
        self.fill('repeat',['present','absent'])
        path=self.pack/'repeat-development.jsonl';rows=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
        rows[0]['answers']['source_plan']['value']='absent'
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
        with self.assertRaises(InputError):summarize(self.pack)

    def test_review_scoring_binds_the_variant_and_preserves_missing_observations(self):
        export_reviews(self.pack)
        with self.assertRaises(InputError):evaluate(self.pack)
        baseline=read_json(self.pack/'blind-cases-baseline.json')['cases'][0]
        rows=[review(baseline,self.manifest,name) for name in ('SYNTHETIC_A','SYNTHETIC_B')]
        labels=self.root/'baseline-reviews.jsonl'
        labels.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
        original=evaluate(self.pack,[labels],variant='baseline')
        repeat=evaluate(self.pack,[labels],variant='repeat')
        self.assertEqual(next(iter(original['by_profile'].values()))['fields']['source_plan']['recall'],1)
        self.assertEqual(next(iter(repeat['by_profile'].values()))['fields']['source_plan']['missed_positive_unobserved'],1)
        with self.assertRaises(InputError):evaluate(self.pack,[labels],variant='local')
        local=evaluate(self.pack,variant='local')
        self.assertEqual(local['by_profile'],{});self.assertEqual(local['variant'],'local')
        compared=local['inspection']['cases'][0]['observer_comparison']
        self.assertEqual(compared[0]['answers']['source_plan']['value'],'present')
        self.assertIsNone(compared[1]['answers']);self.assertIsNone(compared[2]['answers'])


if __name__=='__main__':unittest.main()
