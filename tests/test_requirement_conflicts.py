"""Production /7 promotion, exact legacy replay and actual short-arm evidence."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import evaluate_requirement_attribution as experiment
from scripts import evaluate_requirement_production as production
from tracker import requirement_diagnostics as detector
from tracker.jev import validate_answers
from tracker.schema import digest
from tracker.semantic_extraction import read
from test_requirement_harness import wire


class ScanClient:
    model='jev-1.13.0'
    def __init__(self,root):self.root=root;self.calls=[]
    def transport(self,request):
        assert request['state']['stage']=='requirement_conflict_scan'
        assert request['state']['harness']==detector.CONFLICT_VERSION
        assert request['state']['protocol_id']==detector.protocol(detector.CONFLICT_VERSION)['id']
        assert 'development_requirement_arm' not in request['state']
        assert read(self.root/'requests'/(digest(request)+'.json'))==request
        self.calls.append(request)
        return {'model':request['model'],'answers':{key:{'type':'choice','probabilities':{
            option:float(option=='none') for option in question['criteria']}} for key,question in request['questions'].items()}}


class RequirementConflictTests(unittest.TestCase):
    def test_production_requests_equal_successful_short_arm_except_version_identity(self):
        frozen,rows=production.prepared()
        self.assertEqual(detector.CONFLICT_VERSION,'requirement-diagnostics/7')
        self.assertEqual(detector.CONFLICT_RULE,experiment.SHORT_CONFLICT_RULE)
        self.assertEqual(detector.ABSENT_IMPLEMENTATION_RULE,experiment.ABSENT_IMPLEMENTATION_RULE)
        self.assertNotEqual(detector.protocol(detector.CONFLICT_VERSION)['id'],detector.protocol(detector.HARNESS_VERSION)['id'])
        count=0
        for row in rows:
            source=row['source'];terms=[]
            old_terms=list(detector.term_requests(source,version=detector.HARNESS_VERSION))
            self.assertEqual(old_terms,list(detector.term_requests(source,version=detector.CONFLICT_VERSION)))
            for request in old_terms:
                answers=validate_answers(row['extraction'][digest(request)]['response'],request)
                terms.extend(term for i,term in enumerate(request['state']['instruction_paragraphs'].values())
                             if answers['term_'+str(i)]['value'] in {'task_requirement','unresolved'})
            old=list(detector.requests(source,terms,version=detector.HARNESS_VERSION))
            current=list(detector.requests(source,terms,version=detector.CONFLICT_VERSION))
            self.assertEqual(len(current),len(old))
            for before,after in zip(old,current):
                expected=experiment.variant(source,before,experiment.SHORT_ARM)
                expected['state'].pop('development_requirement_arm')
                expected['state'].update(harness=detector.CONFLICT_VERSION,protocol_id=detector.protocol(detector.CONFLICT_VERSION)['id'])
                self.assertEqual(after,expected);count+=1
                self.assertEqual(after['state']['source_fragments'],before['state']['source_fragments'])
        self.assertEqual(count,11)

    def test_all_eleven_actual_short_responses_replay_before_production_validation(self):
        frozen,rows=production.prepared();short=read(production.FIXTURES/'requirement-short-live.json')
        self.assertEqual(frozen['primary_hash'],short['source_fixture_hash'])
        self.assertEqual(frozen['supplemental_hash'],short['supplemental_fixture_hash'])
        self.assertEqual(digest(frozen['references']),short['combined_reference_hash'])
        self.assertEqual(short['short_conflict_rule'],detector.CONFLICT_RULE)
        saved={row['case_id']:row for row in short['rows']};count=0
        for row in rows:
            actual=saved[row['case_id']];packets={p['request_hash']:p for p in actual['packets']}
            def replay(original):
                if original['state']['stage']=='requirement_extraction':
                    return validate_answers(row['extraction'][digest(original)]['response'],original),digest(original)
                request=experiment.variant(row['source'],original,experiment.SHORT_ARM);key=digest(request)
                packet=packets[key];self.assertEqual(digest(packet['response']),packet['response_hash'])
                return validate_answers(packet['response'],request),key
            result=detector.build(row['source'],replay,version=detector.HARNESS_VERSION)
            self.assertEqual(result['metrics'][detector.METRIC]['value'],actual['prediction'])
            self.assertTrue(actual['reference_match']);count+=len(packets)
        self.assertEqual(count,11)
        self.assertEqual(short['groups'][0]['original_definite_matches'],7)
        self.assertEqual(short['groups'][0]['supplemental_definite_matches'],2)

    def test_new_protocol_executes_audits_and_saved_six_remains_six(self):
        _,rows=production.prepared();source=rows[0]['source']
        with TemporaryDirectory() as temp:
            root=Path(temp)
            legacy=detector.execute(source,root/'six',wire,version=detector.HARNESS_VERSION)
            self.assertEqual(detector.execute(source,root/'six',lambda _:self.fail('Saved /6 must replay')),legacy)
            self.assertTrue(detector.audit(source,legacy,root/'six')['exact_replay'])
            current=detector.execute(source,root/'seven',wire,version=detector.CONFLICT_VERSION)
            self.assertEqual(current['schema'],detector.CONFLICT_VERSION)
            self.assertTrue(detector.audit(source,current,root/'seven')['exact_replay'])
            self.assertNotEqual(current['protocol']['id'],legacy['protocol']['id'])

    def test_production_runner_reuses_eleven_extractions_and_only_spends_eleven_scans(self):
        with TemporaryDirectory() as temp,redirect_stdout(StringIO()):
            root=Path(temp);client=ScanClient(root)
            offline=production.evaluate(root,client=client,max_calls=0)
            self.assertEqual(offline['new_calls_this_invocation'],0)
            self.assertEqual(len(list((root/'requests').glob('*.json'))),22)
            partial=production.evaluate(root,live=True,client=client,max_calls=1)
            self.assertEqual(partial['new_calls_this_invocation'],1)
            done=production.evaluate(root,live=True,client=client,max_calls=11)
            self.assertEqual(done['new_calls_this_invocation'],10)
            self.assertEqual(done['status'],'complete')
            self.assertEqual(len(client.calls),11)
            self.assertTrue(all(row['audit']['exact_replay'] for row in done['results']))
            cached=production.evaluate(root,client=client,max_calls=0)
            self.assertEqual(cached['results'],done['results'])
            self.assertEqual(cached['new_calls_this_invocation'],0)


if __name__=='__main__':unittest.main()
