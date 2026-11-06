"""Offline evaluation lifecycle checks; scripted replies do not score semantics."""
from contextlib import redirect_stdout
import importlib.util
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker import requirement_diagnostics as detector
from tracker.schema import InputError,digest,dumps
from tracker.semantic_extraction import read,write

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/evaluate_requirement_harness.py'
SPEC=importlib.util.spec_from_file_location('requirement_eval',SCRIPT)
evaluation=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(evaluation)


class ScriptedClient:
    model='jev-1.13.0'
    def __init__(self,root,*,reject_terms=False,fail=False):
        self.root=root;self.calls=[];self.reject_terms=reject_terms;self.fail=fail
    def transport(self,request):
        assert (self.root/'inputs.json').exists()
        assert (self.root/'references.json').exists()
        assert (self.root/'requests'/(digest(request)+'.json')).exists()
        assert len(list((self.root/'cases').glob('*/source.json')))==8
        assert request==read(self.root/'requests'/(digest(request)+'.json'))
        assert all(key not in dumps(request) for key in ('accepted_values','source_evidence','reference_match','development_judgment'))
        self.calls.append(request)
        if self.fail:raise RuntimeError('scripted failure')
        extraction=request['state']['stage']=='requirement_extraction'
        value=('context' if self.reject_terms else 'task_requirement') if extraction else 'none'
        return {'model':request['model'],'answers':{field:{'type':'choice','probabilities':{
            choice:float(choice==value) for choice in question['criteria']}}
            for field,question in request['questions'].items()}}


class RequirementHarnessEvaluationTests(unittest.TestCase):
    def test_export_has_full_production_questions_and_no_reference_leak(self):
        fixture,rows=evaluation.prepared()
        self.assertEqual(len(rows),8)
        self.assertEqual(sum(len(r['term_requests'])+len(r['scan_preview']) for r in rows),18)
        for row in rows:
            self.assertEqual(row['term_requests'],list(detector.term_requests(row['source'],version=fixture['protocol'])))
            self.assertEqual(row['scan_preview'],list(detector.requests(row['source'],version=fixture['protocol'])))
            for request in [*row['term_requests'],*row['scan_preview']]:
                self.assertNotIn('accepted_values',dumps(request))
                self.assertNotIn('reference',request['state'])
        with TemporaryDirectory() as temp,redirect_stdout(StringIO()):
            root=Path(temp);client=ScriptedClient(root)
            report=evaluation.evaluate(root,client=client,max_calls=0)
            self.assertEqual(client.calls,[])
            self.assertEqual(report['completed_cases'],0)
            self.assertEqual(report['status'],'pending')
            self.assertEqual(len(list((root/'exports'/'extraction').glob('*.json'))),9)
            self.assertEqual(len(list((root/'exports'/'all-terms-scan-preview').glob('*.json'))),9)

    def test_budget_resume_replay_and_mismatches_are_retained(self):
        with TemporaryDirectory() as temp,redirect_stdout(StringIO()):
            root=Path(temp);client=ScriptedClient(root)
            partial=evaluation.evaluate(root,live=True,client=client,max_calls=1)
            self.assertEqual(partial['new_calls_this_invocation'],1)
            self.assertEqual(partial['status'],'pending')
            done=evaluation.evaluate(root,live=True,client=client,max_calls=24)
            self.assertEqual(done['new_calls_this_invocation'],17)
            self.assertEqual(done['status'],'complete')
            self.assertEqual(done['completed_cases'],8)
            self.assertEqual(done['definite_completed'],7)
            self.assertTrue(any(r['reference_match'] is False for r in done['results']))
            self.assertTrue(all(r['audit']['exact_replay'] for r in done['results']))
            self.assertEqual({r['state']['stage'] for r in client.calls},{'requirement_extraction','requirement_conflict_scan'})
            cached=evaluation.evaluate(root,client=client,max_calls=0)
            self.assertEqual(cached['results'],done['results'])
            self.assertEqual(cached['new_calls_this_invocation'],0)

    def test_rejected_requirements_do_not_turn_into_zero_or_hidden_case(self):
        with TemporaryDirectory() as temp,redirect_stdout(StringIO()):
            root=Path(temp);client=ScriptedClient(root,reject_terms=True)
            done=evaluation.evaluate(root,live=True,client=client,max_calls=24)
            self.assertEqual(done['status'],'complete')
            definite=[r for r in done['results'] if not r['ambiguous']]
            self.assertTrue(all(r['prediction'] is None for r in definite))
            self.assertTrue(all(r['reference_match'] is False for r in definite))
            self.assertTrue(all(r['requirement_selections'] for r in definite))

    def test_reference_change_and_provider_failure_remain_visible(self):
        with TemporaryDirectory() as temp,redirect_stdout(StringIO()):
            root=Path(temp);client=ScriptedClient(root,fail=True)
            failed=evaluation.evaluate(root,live=True,client=client,max_calls=2)
            self.assertEqual(failed['status'],'failed')
            self.assertEqual(failed['new_calls_this_invocation'],2)
            self.assertEqual(len(failed['results']),8)
            self.assertEqual(sum(r['error_type']=='RuntimeError' for r in failed['results']),2)
            changed=read(evaluation.FIXTURE);changed['cases'][0]['reference']['accepted_values']=[0]
            path=root/'changed.json';write(path,changed)
            with self.assertRaisesRegex(InputError,'Frozen inputs changed'):
                evaluation.evaluate(root,client=client,fixture_path=path)


if __name__=='__main__':unittest.main()
