"""Version8 unknown claims are inspectable and never suppress positive evidence."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import evaluate_requirement_unverified as experimental
from scripts.evaluate_requirement_evidence import expected_values
from scripts.evaluate_requirement_coverage import variant as coverage_variant
from tracker import requirement_diagnostics as detector
from tracker.schema import InputError,digest
from tracker.semantic_extraction import read

FIXTURES=Path(__file__).parent/'fixtures'


def response(request,choices):
    return dict(model=request['model'],answers={field:dict(type='choice',probabilities={
        key:float(key==choices[field]) for key in question['criteria']}) for field,question in request['questions'].items()})


class RequirementEvidenceTests(unittest.TestCase):
    def test_current_default_and_frozen_reference_formats_keep_their_labels(self):
        self.assertEqual(detector.CURRENT_VERSION,detector.POLICY_VERSION)
        self.assertEqual(detector.DEFAULT_VERSION,detector.POLICY_VERSION)
        frozen=read(FIXTURES/'requirement-prior-corrected-live.json')
        expected={'lossy-compression':[1],'authorized-submission':[0],'helm-ordering':[1],
                  'httpx-json-bom':[1],'csv-data-loss':[1],'permitted-alternative':[0]}
        for row in frozen['rows']:
            self.assertEqual(expected_values(row['reference']),expected[row['case_id']])
        self.assertEqual(expected_values({'expected_conflict':None}),[None])
        self.assertEqual(expected_values({'accepted_values':[0,None]}),[0,None])
        with self.assertRaises(InputError):expected_values({'basis':'No recognized fixed label'})

    def test_new_version_matches_successful_experiment_except_version_identity(self):
        controls=read(FIXTURES/'requirement-lifecycle-controls.json')
        for case in controls['cases']:
            source=case['source'];terms={t['id']:t for t in detector.criteria(source,version=detector.EVIDENCE_VERSION)}
            selected=[terms[key] for key in case['selected_requirement_ids']]
            old=list(detector.requests(source,selected,version=detector.CONFLICT_VERSION))
            new=list(detector.requests(source,selected,version=detector.EVIDENCE_VERSION))
            self.assertEqual(len(old),len(new))
            for before,after in zip(old,new):
                expected=experimental.variant(coverage_variant(source,before,'coverage_state_lifecycle'))
                expected['state'].update(harness=detector.EVIDENCE_VERSION,protocol_id=detector.protocol(detector.EVIDENCE_VERSION)['id'])
                self.assertEqual(after,expected)
            self.assertEqual(list(detector.term_requests(source,version=detector.EVIDENCE_VERSION)),
                             list(detector.term_requests(source,version=detector.HARNESS_VERSION)))
            self.assertNotIn('unverified_claim',detector.SENTINELS)
            self.assertEqual(detector.source_coverage(source),new[0]['state']['source_coverage'])

    def test_unverified_is_unknown_has_no_finding_and_replays_with_traceability(self):
        control=read(FIXTURES/'requirement-lifecycle-controls.json')['cases'][3]
        source=control['source'];selected=set(control['selected_requirement_ids'])
        def transport(request):
            if request['state']['stage']=='requirement_extraction':
                choices={field:'task_requirement' if any(key in q['instructions'] for key in selected) else 'workflow_rule'
                         for field,q in request['questions'].items()}
            else:choices={field:'unverified_claim' for field in request['questions']}
            return response(request,choices)
        with TemporaryDirectory() as directory:
            result=detector.execute(source,directory,transport,version=detector.EVIDENCE_VERSION)
            self.assertIsNone(result['metrics'][detector.METRIC]['value']);self.assertEqual(result['findings'],[])
            self.assertEqual(result['coverage']['unverified_questions'],1)
            comparisons=result['coverage']['unverified_comparisons'];self.assertEqual(len(comparisons),1)
            self.assertEqual(set(comparisons[0]),{'requirement_id','page','question_field','request_hash'})
            self.assertEqual(comparisons[0]['requirement_id'],next(iter(selected)))
            packet=read(Path(directory)/'decisions'/(comparisons[0]['request_hash']+'.json'))
            field=comparisons[0]['question_field']
            self.assertEqual(packet['answers'][field]['value'],'unverified_claim')
            self.assertEqual(packet['request']['state']['requirements'][field]['id'],comparisons[0]['requirement_id'])
            self.assertTrue(detector.audit(source,result,directory)['exact_replay'])
            self.assertEqual(detector.execute(source,directory,lambda _:self.fail('Saved8 must replay')),result)

    def test_unknown_on_one_page_does_not_suppress_incomplete_source_positive(self):
        source=dict(schema='diagnostic-input/1',id='unknown-then-positive',task='Preserve every input row.',
                    trace='Recorded implementation and output. '*1100,complete_recorded_text=False,action_coverage='recorded')
        scans=[]
        def decide(request):
            if request['state']['stage']=='requirement_extraction':choices={field:'task_requirement' for field in request['questions']}
            else:
                scans.append(request)
                choices={field:'unverified_claim' if len(scans)==1 else
                         next(key for key in q['criteria'] if key in request['state']['source_fragments']) if len(scans)==2 else 'none'
                         for field,q in request['questions'].items()}
            return {key:{'value':value} for key,value in choices.items()},digest(request)
        result=detector.build(source,decide,version=detector.EVIDENCE_VERSION)
        self.assertGreaterEqual(len(scans),2);self.assertEqual(result['metrics'][detector.METRIC]['value'],1)
        self.assertFalse(result['coverage']['complete_recorded_text'])
        self.assertEqual(result['coverage']['unverified_questions'],1)
        self.assertTrue(result['findings']);self.assertIsNone(result['metrics'][detector.METRIC]['reason'])

    def test_complete_source_with_unverified_claim_cannot_become_negative(self):
        source=dict(schema='diagnostic-input/1',id='unverified-complete-record',task='Preserve every input row.',
                    trace='The agent claims completion; the recording contains no validation.',complete_recorded_text=True,action_coverage='recorded')
        def decide(request):
            value='task_requirement' if request['state']['stage']=='requirement_extraction' else 'unverified_claim'
            return {key:{'value':value} for key in request['questions']},digest(request)
        result=detector.build(source,decide,version=detector.EVIDENCE_VERSION)
        self.assertTrue(result['coverage']['scan_complete']);self.assertTrue(result['coverage']['complete_recorded_text'])
        self.assertIsNone(result['metrics'][detector.METRIC]['value']);self.assertEqual(result['findings'],[])

    def test_saved_seven_stays_seven_when_default_changes(self):
        source=deepcopy(read(FIXTURES/'requirement-lifecycle-controls.json')['cases'][0]['source'])
        def transport(request):
            choice='task_requirement' if request['state']['stage']=='requirement_extraction' else 'none'
            return response(request,{field:choice for field in request['questions']})
        with TemporaryDirectory() as directory:
            prior=detector.execute(source,directory,transport,version=detector.CONFLICT_VERSION)
            with patch.object(detector,'CURRENT_VERSION',detector.EVIDENCE_VERSION):
                resumed=detector.execute(source,directory,lambda _:self.fail('Saved7 must replay'))
            self.assertEqual(resumed,prior);self.assertEqual(resumed['schema'],detector.CONFLICT_VERSION)
            self.assertNotIn('unverified_comparisons',resumed['coverage'])


if __name__=='__main__':unittest.main()
