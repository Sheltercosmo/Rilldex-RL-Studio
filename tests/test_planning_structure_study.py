import copy
import json
from pathlib import Path
import tempfile
import unittest

from research.planning_structure_study import make_pair, validate_collection, validate_cases, review_case, VERSION
from research.relation_review import evidence as review_evidence, evaluate
from tracker.prefix_encoding import expand
from tracker.schema import digest, InputError


class PlanningStudyTests(unittest.TestCase):
    def pair(self):
        text='Investigate both causes. Then compare their predictions. LATER_SECRET'
        record={'id':'e1','trace_id':'trace','actor_id':'main','event_index':1,'source_pointer':'/message',
                'text':text,'role':'model','kind':'text'}
        start=text.index('Then');end=text.index(' LATER_SECRET')
        local={'id':'unit','trace_id':'trace','actor_id':'main','event_index':1,'source_pointer':'/message',
               'start':start,'end':end,'text':text[start:end],'role':'model'}
        return make_pair('case',[record],local,0,{'trace_id':'trace','adapter':'fixture','domain':'fixture','source_hash':'source'})

    def test_paired_grains_share_cutoff_but_preserve_distinct_subjects(self):
        cases=self.pair();validate_cases({'version':VERSION,'variants':['planning']},cases)
        local,block=[expand(c['requests']['planning'])['state'] for c in cases]
        self.assertEqual(local['prefix'],block['prefix'])
        self.assertEqual(local['source']['end'],block['source']['end'])
        self.assertGreater(local['source']['start'],block['source']['start'])
        self.assertNotEqual(local['source']['id'],block['source']['id'])
        self.assertNotIn('LATER_SECRET',str(cases))
        for case in cases:
            reviewed=review_case(case)
            self.assertEqual(reviewed['subject']['text'],expand(case['requests']['planning'])['state']['source']['text'])
            self.assertNotIn('prediction',reviewed)

    def test_grain_metadata_and_source_changes_cannot_hide_as_comparable(self):
        original=self.pair();manifest={'version':VERSION,'variants':['planning']}
        changed=copy.deepcopy(original);changed[1]['grain']='local'
        with self.assertRaises(InputError):validate_cases(manifest,changed)
        changed=copy.deepcopy(original);changed[1]['requests']['planning']['state']['source']['text']+='changed'
        with self.assertRaises(InputError):validate_cases(manifest,changed)

    def test_real_frozen_review_pack_has_no_automatic_accuracy_reference(self):
        directory=Path(__file__).resolve().parents[1]/'research/planning-structure-2026-10-07'
        manifest,cases=validate_collection(directory)
        self.assertEqual(len(cases),24);self.assertEqual(len({c['group_id'] for c in cases}),12)
        _,_,projected,_,variant=review_evidence(directory)
        self.assertEqual(variant,'planning');self.assertEqual(len(projected),24)
        report=evaluate(directory)
        self.assertEqual(report['by_profile'],{})
        self.assertTrue(all(not c.get('native_reference') for c in cases))
        self.assertEqual(report['planning_structure_summary']['independent_product_references'],0)
        _,_,_,saved,_=review_evidence(directory)
        if saved:
            conflicts=[]
            for case in report['inspection']['cases']:
                result=saved[case['case_id']]
                self.assertEqual({f['field']:f['prediction']['value'] for f in case['fields']},
                                 {k:v['value'] for k,v in result['answers'].items()})
                companion=case['related_observations'][0]
                self.assertEqual(companion['subject']['end'],case['subject']['end'])
                self.assertNotEqual(companion['subject']['start'],case['subject']['start'])
                if any(f['kind']=='organization_scope_conflict' for f in case['findings']):
                    conflicts.append(case['case_id'])
            self.assertEqual(set(conflicts),{'software-reproduction--block','retail-options--block'})
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)
            for name in ('manifest.json','cases.json','sources.json','review-rubric.json'):
                (target/name).write_bytes((directory/name).read_bytes())
            rubric=json.loads((target/'review-rubric.json').read_text(encoding='utf-8'));rubric['rules']=[]
            (target/'review-rubric.json').write_text(json.dumps(rubric),encoding='utf-8')
            with self.assertRaises(InputError):validate_collection(target)


if __name__=='__main__':unittest.main()
