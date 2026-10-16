from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from test_relation_contracts import evidence as text_evidence
from research.relation_scope import source_review_case,export_role_review
from research.relation_review import evaluate,evidence
from tracker.relation_contracts import source_plan_packet
from tracker.activity_reference import render_report
from tracker.jev import DEFAULT_MODEL,SELECTION_POLICY,validate_answers
from tracker.schema import digest,InputError


def fixture(root):
    prefix,source,_=text_evidence();request=source_plan_packet(prefix,source)
    case={'case_id':'synthetic-role-case','set':'development','trace_id':'synthetic-trace','source_hash':'synthetic-source',
          'native_reference':{'value':'present','labels':['planning','planning'],'product_reference':False},
          'requests':{'source_time':request}}
    manifest={'version':'source-role-study/1','model':DEFAULT_MODEL,'selection_policy':SELECTION_POLICY,
              'variants':['source_time'],'cases':1,'cases_hash':digest([case])}
    root=Path(root);root.mkdir(parents=True)
    for name,data in [('manifest.json',manifest),('cases.json',[case])]:
        (root/name).write_text(json.dumps(data),encoding='utf-8')
    answer=validate_answers({'answers':{'source_plan':{'type':'choice','choice':'absent','confidence':0,
                  'probabilities':{'present':.34,'absent':.33,'unresolved':.33}}}},request)
    result={'case_id':case['case_id'],'variant':'source_time','set':'development','request_hash':digest(request),
            'selection_policy':SELECTION_POLICY,'model':DEFAULT_MODEL,'answers':answer}
    (root/'source_time-development.jsonl').write_text(json.dumps(result)+'\n',encoding='utf-8')
    export_role_review(root)
    return manifest,case,source_review_case(case)


def review(case,manifest,name,value='present',**extra):
    return {'annotation_id':name,'case_id':case['case_id'],'case_hash':case['case_hash'],'manifest_hash':digest(manifest),
            'reviewer':name,'reference_kind':'human','exposure':'prediction_blind','annotation_type':'independent',
            'checks':{'attribution':'valid','segmentation':'usable','context':'sufficient'},'values':{'source_plan':value},
            'evidence_ids':[case['subject']['id']],'rationale':'Synthetic test reference, not actual human annotation.',**extra}


class RelationReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'pack';self.manifest,self.original,self.case=fixture(self.root)

    def score(self,rows):
        target=Path(self.temp.name)/'synthetic-reviews.jsonl'
        target.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
        return evaluate(self.root,[target])

    def reviews(self):return [review(self.case,self.manifest,name) for name in ('SYNTHETIC_A','SYNTHETIC_B')]

    def test_publisher_annotations_and_proposals_never_supply_product_references(self):
        for rows in ([],self.reviews()[:1],[{**r,'reference_kind':'model_proposal'} for r in self.reviews()],
                     [{**r,'exposure':'seen_predictions'} for r in self.reviews()]):
            report=self.score(rows)
            self.assertEqual(report['by_profile'],{});self.assertEqual(report['status'],'no_eligible_reference_consensus')
            item=report['inspection']['cases'][0]
            self.assertEqual(item['publisher_reference']['value'],'present')
            self.assertEqual(len(item['submitted_reviews']),len(rows))
            self.assertFalse(any(f['stage']=='choice' for f in item['findings']))

    def test_consensus_scoring_and_raw_argmax_ignore_provider_choice_and_confidence(self):
        report=self.score(self.reviews());metric=next(iter(report['by_profile'].values()))['fields']['source_plan']
        self.assertEqual((metric['precision'],metric['recall']),(1,1))
        field=report['inspection']['cases'][0]['fields'][0]
        self.assertEqual(field['prediction']['value'],'present');self.assertEqual(field['prediction']['confidence'],0)
        self.assertEqual(field['prediction']['provider_choice'],'absent')

    def test_disagreement_needs_explicit_adjudication_of_all_eligible_reviews(self):
        rows=self.reviews();rows[1]['values']['source_plan']='absent'
        report=self.score(rows);self.assertEqual(report['by_profile'],{})
        self.assertEqual(report['resolutions'][0]['status'],'disagreement')
        adj=review(self.case,self.manifest,'SYNTHETIC_ADJUDICATOR','absent',annotation_type='adjudication',
                   reviewed_annotation_ids=[r['annotation_id'] for r in rows])
        report=self.score(rows+[adj]);self.assertEqual(report['resolutions'][0]['status'],'adjudicated')
        self.assertTrue(report['resolutions'][0]['disagreement'])
        adj['reviewed_annotation_ids']=adj['reviewed_annotation_ids'][:1]
        with self.assertRaises(InputError):self.score(rows+[adj])

    def test_missing_predictions_reduce_recall_without_erasing_references(self):
        (self.root/'source_time-development.jsonl').unlink()
        report=self.score(self.reviews());metric=next(iter(report['by_profile'].values()))['fields']['source_plan']
        self.assertEqual(metric['recall'],0);self.assertEqual(metric['missed_positive_unobserved'],1)
        self.assertIsNone(metric['precision']);self.assertEqual(report['completed_predictions'],0)

    def test_unit_exclusion_and_context_concern_are_distinct(self):
        rows=self.reviews();rows[0]['checks']['segmentation']='split_needed'
        self.assertEqual(self.score(rows)['resolutions'][0]['status'],'unit_excluded')
        rows=self.reviews()
        for r in rows:r['checks']['context']='insufficient'
        report=self.score(rows);self.assertTrue(report['by_profile'])
        self.assertEqual(report['inspection']['cases_by_stage']['context'],1)

    def test_tampered_blind_export_conflicting_ids_and_duplicate_reviewers_fail(self):
        rows=self.reviews();rows[1]['annotation_id']=rows[0]['annotation_id']
        with self.assertRaises(InputError):self.score(rows)
        rows=self.reviews();rows[1]['reviewer']=rows[0]['reviewer']
        with self.assertRaises(InputError):self.score(rows)
        path=self.root/'blind-cases.json';blind=json.loads(path.read_text(encoding='utf-8'))
        blind['cases'][0]['subject']['text']='Changed source';path.write_text(json.dumps(blind),encoding='utf-8')
        with self.assertRaises(InputError):evidence(self.root)

    def test_report_escapes_review_text_and_publisher_annotations_are_separate(self):
        rows=self.reviews();rows[0]['rationale']='</script><script>window.BAD_SOURCE=true</script>'
        html=render_report(self.score(rows))
        self.assertNotIn('</script><script>window.BAD_SOURCE',html)
        self.assertIn('Separate publisher annotation',html)
        self.assertIn('"probabilities"',html)
        self.assertNotIn('"probabilities"',(self.root/'review.html').read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
