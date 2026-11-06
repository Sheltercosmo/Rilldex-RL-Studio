"""Experimental lifecycle inputs, cache budgets and incomplete-source status."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import evaluate_requirement_lifecycle as evaluation
from tracker import requirement_diagnostics as detector
from tracker.schema import digest
from tracker.semantic_extraction import read

FIXTURES=Path(__file__).parent/'fixtures'


class RequirementLifecycleTests(unittest.TestCase):
    def test_singleton_changes_only_grouping_and_clarification_only_instructions(self):
        frozen=read(FIXTURES/'requirement-prior-corrected-live.json')
        case=next(r for r in frozen['rows'] if r['case_id']=='authorized-submission')
        original=case['packets'][0]['request'];before=deepcopy(original)
        singles=list(evaluation.variants(original,'single_requirement'))
        self.assertEqual(len(singles),8)
        restored={}
        for request in singles:
            self.assertEqual(len(request['questions']),1)
            field=next(iter(request['questions']));restored[field]=request['questions'][field]
            self.assertEqual(request['questions'][field],original['questions'][field])
            expected=deepcopy(original['state']);expected['requirements']={field:original['state']['requirements'][field]}
            self.assertEqual(request['state'],expected)
        self.assertEqual(restored,original['questions'])
        clarification=next(evaluation.variants(original,'lifecycle_clarification'))
        self.assertEqual(clarification['state'],original['state'])
        for key,question in clarification['questions'].items():
            expected=deepcopy(original['questions'][key]);expected['instructions']+='\n'+evaluation.LIFECYCLE_RULE
            self.assertEqual(question,expected)
        self.assertEqual(original,before)

    def test_reviewed_controls_keep_source_labels_and_exact_production_requests(self):
        review=read(FIXTURES/'requirement-lifecycle-controls.json')
        self.assertEqual(digest({c['id']:c['reference'] for c in review['cases']}),review['reference_hash'])
        for case in review['cases']:
            source=case['source'];self.assertEqual(digest(source),case['source_hash'])
            terms={t['id']:t for t in detector.criteria(source,version=detector.CONFLICT_VERSION)}
            generated=list(detector.requests(source,[terms[key] for key in case['selected_requirement_ids']],version=detector.CONFLICT_VERSION))
            self.assertEqual(generated,case['requests'])
            self.assertEqual([digest(r) for r in generated],case['request_hashes'])
            self.assertEqual(source['complete_recorded_text'],case['reference']['expected_complete_recorded_text'])
            self.assertEqual(list(evaluation.variants(generated[0],'production7')),[generated[0]])

    def test_shared_budget_cache_and_incomplete_excerpt_remain_explicit(self):
        review=read(FIXTURES/'requirement-lifecycle-controls.json');rows=[]
        refs={case['id']:case['reference'] for case in review['cases']}
        for case in review['cases']:
            for arm in ('production7','lifecycle_clarification'):
                rows.append(dict(case_id=case['id'],arm=arm,source_hash=case['source_hash'],target_events=None,
                    requests=[r for req in case['requests'] for r in evaluation.variants(req,arm)],
                    expected_values=[None if case['reference']['expected_conflict'] is None else int(case['reference']['expected_conflict'])],
                    independent_review_control=True,source_complete=case['source']['complete_recorded_text'],
                    accepted_local_selections=case['reference']['accepted_local_selections']))
        context=dict(panel_manifest_hash='test-only',reference_hash=digest(refs),references=refs,
                     control_receipts_hash='test-only',protocol=detector.protocol(detector.CONFLICT_VERSION))
        class Client:
            model='jev-1.13.0'
            def __init__(self):self.calls=0
            def transport(self,request):
                self.calls+=1
                return {'model':self.model,'answers':{key:{'type':'choice','probabilities':{
                    value:float(value=='none') for value in question['criteria']}} for key,question in request['questions'].items()}}
        with TemporaryDirectory() as temp,redirect_stdout(StringIO()),patch.object(evaluation,'prepared',return_value=(context,rows,{})):
            client=Client()
            first=evaluation.evaluate(temp,client=client,live=True,max_calls=3)
            self.assertEqual(first['new_calls'],3);self.assertEqual(first['status'],'pending')
            done=evaluation.evaluate(temp,client=client,live=True,max_calls=5)
            self.assertEqual(done['new_calls'],5);self.assertEqual(done['status'],'complete')
            self.assertEqual(client.calls,8)
            for result in done['results']:
                if result['case_id']=='completion-claim-incomplete-excerpt':
                    self.assertIsNone(result['prediction'])
                    self.assertEqual(result['local_selections'],['none'])
                    self.assertTrue(result['local_reference_match'])
                    self.assertFalse(result['source_complete'])
            cached=evaluation.evaluate(temp,client=client,max_calls=0)
            self.assertEqual(cached['results'],done['results']);self.assertEqual(cached['new_calls'],0)


if __name__=='__main__':unittest.main()
