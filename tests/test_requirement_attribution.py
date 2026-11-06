"""Actual baseline misses and controlled scan ablations remain inspectable."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import evaluate_requirement_attribution as evaluation
from scripts.evaluate_requirement_harness import prepared as controls
from tracker import diagnostic_attribution as attribution,requirement_diagnostics as detector
from tracker.jev import validate_answers
from tracker.schema import digest,dumps
from tracker.semantic_extraction import read


class ScanClient:
    model='jev-1.13.0'
    def __init__(self,root):self.root=root;self.calls=[]
    def transport(self,request):
        assert request['state']['stage']=='requirement_conflict_scan'
        assert (self.root/'inputs.json').exists()
        assert (self.root/'references.json').exists()
        assert (self.root/'requests'/(digest(request)+'.json')).exists()
        assert 'accepted_values' not in dumps(request)
        assert 'baseline_prediction' not in dumps(request)
        self.calls.append(request)
        return {'model':request['model'],'answers':{key:{'type':'choice','probabilities':{
            option:float(option=='none') for option in question['criteria']}} for key,question in request['questions'].items()}}


class RequirementAttributionTests(unittest.TestCase):
    def test_third_live_arm_preserves_selected_action_and_completion_contrast_results(self):
        frozen=read(Path(__file__).parent/'fixtures/requirement-intermediate-live.json')
        supplement=Path(__file__).parent/'fixtures/requirement-intermediate-controls.json'
        fixture,baseline,primary=evaluation.prepared((evaluation.INTERMEDIATE_ARM,))
        extra,extra_rows=controls(supplement)
        refs={c['id']:c['reference'] for c in [*fixture['cases'],*extra['cases']]}
        self.assertEqual(digest(extra),frozen['supplemental_fixture_hash'])
        self.assertEqual(digest(refs),frozen['combined_reference_hash'])
        primary={r['case_id']:r for r in primary};sources={r['case_id']:r['source'] for r in [*primary.values(),*extra_rows]}
        count=0;misses=[]
        for row in frozen['rows']:
            packets={p['request_hash']:p for p in row['packets']};source=sources[row['case_id']]
            def replay(original):
                request=evaluation.variant(source,original,evaluation.INTERMEDIATE_ARM);key=digest(request)
                if key in packets:
                    packet=packets[key]
                    self.assertEqual(digest(packet['response']),packet['response_hash'])
                    answers=validate_answers(packet['response'],request)
                    selected={k:request['state']['source_fragments'][v['value']] for k,v in answers.items()
                              if v['value'] in request['state'].get('source_fragments',{})}
                    self.assertEqual(selected,packet['selected_fragments'])
                    return answers,key
                return validate_answers(primary[row['case_id']]['packets'][key]['response'],request),key
            result=detector.build(source,replay,version=fixture['protocol']);count+=len(packets)
            self.assertEqual(result['metrics'][detector.METRIC]['value'],row['prediction'])
            if not row['reference_match']:misses.append(row['case_id'])
            if row['case_id']=='encoded-completion-read':
                fragment=result['findings'][0]['candidate']
                self.assertEqual((fragment['id'],fragment['event_id'],fragment['kind']),('trace:501:713','e4','action'))
        self.assertEqual(count,13)
        self.assertEqual(misses,['encoded-completion-read'])
        self.assertEqual(frozen['groups'][0]['supplemental_definite_matches'],2)

    def test_completed_first_two_arms_replay_with_all_remaining_misses(self):
        frozen=read(Path(__file__).parent/'fixtures/requirement-attribution-live.json')
        fixture,baseline,rows=evaluation.prepared()
        self.assertEqual(digest(fixture),frozen['source_fixture_hash'])
        self.assertEqual(digest(baseline),frozen['baseline_hash'])
        self.assertEqual(baseline['pre_live_reference_hash'],frozen['pre_live_reference_hash'])
        self.assertEqual(evaluation.ABSENT_IMPLEMENTATION_RULE,frozen['absent_implementation_rule'])
        actual={(r['case_id'],r['arm']):r for r in frozen['rows']};misses=[];count=0
        for row in rows:
            saved=actual[(row['case_id'],row['arm'])];packets={p['request_hash']:p for p in saved['packets']}
            def replay(original):
                request=row['requests'][digest(original)];key=digest(request)
                if original['state']['stage']=='requirement_extraction':response=row['packets'][key]['response']
                else:
                    response=packets[key]['response'];self.assertEqual(digest(response),packets[key]['response_hash'])
                return validate_answers(response,request),key
            result=detector.build(row['source'],replay,version=fixture['protocol']);count+=len(packets)
            self.assertEqual(result['metrics'][detector.METRIC]['value'],saved['prediction'])
            self.assertEqual(saved['prediction'] in saved['accepted_values'],saved['reference_match'])
            if not saved['reference_match']:misses.append((row['arm'],row['case_id'],saved['prediction']))
        self.assertEqual(count,18)
        self.assertEqual(misses,[('bound','encoded-completion-read',1),('bound_absent_implementation','encoded-completion-read',1),('bound','opaque-implementation-insufficient',1)])
        self.assertIsNone(actual[('opaque-implementation-insufficient','bound_absent_implementation')]['prediction'])

    def test_all_actual_baseline_responses_replay_and_both_misses_are_preserved(self):
        fixture,rows=controls();frozen=read(evaluation.BASELINE)
        self.assertEqual(digest(fixture),frozen['source_fixture_hash'])
        refs={c['id']:c['reference'] for c in fixture['cases']}
        self.assertEqual(digest(refs),frozen['pre_live_reference_hash'])
        saved={r['case_id']:r for r in frozen['rows']};misses=[];packet_count=0
        for row in rows:
            actual=saved[row['case_id']];packets={p['request_hash']:p for p in actual['packets']};seen=[]
            def replay(request):
                key=digest(request);packet=packets[key];seen.append(key)
                self.assertEqual(digest(packet['response']),packet['response_hash'])
                self.assertEqual(packet['response']['model'],request['model'])
                return validate_answers(packet['response'],request),key
            result=detector.build(row['source'],replay,version=fixture['protocol'])
            self.assertEqual(digest(result),actual['result_hash'])
            self.assertEqual(set(seen),set(packets));packet_count+=len(seen)
            prediction=result['metrics'][detector.METRIC]['value']
            self.assertEqual(prediction,actual['prediction'])
            self.assertEqual(prediction in refs[row['case_id']]['accepted_values'],actual['reference_match'])
            if not actual['reference_match']:misses.append((row['case_id'],prediction,actual['ambiguous']))
        self.assertEqual(packet_count,18)
        self.assertEqual(misses,[('encoded-completion-read',1,False),('opaque-implementation-insufficient',1,True)])
        self.assertEqual(frozen['observed_score_summary']['definite_reference_matches'],6)

    def test_bound_and_rule_arms_retain_every_original_question_choice_and_source(self):
        fixture,base,rows=evaluation.prepared()
        for row in rows:
            source=row['source']
            frozen={p['request_hash']:p for p in row['baseline']['packets']}
            original=[]
            def replay(req):
                original.append(deepcopy(req));return validate_answers(frozen[digest(req)]['response'],req),digest(req)
            detector.build(source,replay,version=fixture['protocol'])
            for request in original:
                before=deepcopy(request);actual=evaluation.variant(source,request,row['arm'])
                self.assertEqual(request,before)
                self.assertEqual(actual,row['requests'][digest(request)])
                if request['state']['stage']=='requirement_extraction':
                    self.assertIs(actual,request);continue
                self.assertEqual(actual['state']['source_fragments'],request['state']['source_fragments'])
                self.assertEqual(actual['state']['requirements'],request['state']['requirements'])
                self.assertEqual(set(actual['questions']),set(request['questions']))
                choices={cid for q in request['questions'].values() for cid in q['criteria'] if cid in request['state']['source_fragments']}
                self.assertEqual(set(actual['state']['candidate_fragment_ids']),choices)
                for field,question in request['questions'].items():
                    self.assertEqual(actual['questions'][field]['criteria'],question['criteria'])
                    self.assertEqual(actual['questions'][field]['type'],question['type'])
                    expected=question['instructions']+('\n'+evaluation.ABSENT_IMPLEMENTATION_RULE if row['arm']=='bound_absent_implementation' else '')
                    self.assertEqual(actual['questions'][field]['instructions'],expected)
                for key,value in request['state'].items():self.assertEqual(actual['state'][key],value)
                self.assertLessEqual(len(dumps(actual)),120000)
                self.assertNotIn('accepted_values',dumps(actual))
                if row['case_id']=='encoded-completion-read':
                    views=actual['state']['candidate_readings']
                    own=[v for v in views if v.get('recorded_action')]
                    self.assertEqual(len(own),1)
                    view=own[0];fid=view['candidate_fragment_id'];event_id=actual['state']['source_fragments'][fid]['event_id']
                    self.assertTrue(view['operation_definitions'])
                    self.assertTrue(all(v['event_id']==event_id for v in view['operation_definitions']))
                    self.assertIn('Read',dumps(view['operation_definitions']))
                    self.assertNotIn('Write the recorded completion score',dumps(view['operation_definitions']))

    def test_only_scan_calls_spend_budget_and_extraction_is_exactly_reused(self):
        with TemporaryDirectory() as temp,redirect_stdout(StringIO()):
            root=Path(temp);client=ScanClient(root)
            offline=evaluation.evaluate(root,client=client,max_calls=0)
            self.assertEqual(offline['new_calls_this_invocation'],0)
            self.assertEqual(offline['status'],'pending')
            self.assertEqual(len(list((root/'requests').glob('*.json'))),27)
            self.assertTrue(all(row['reused_extraction_request_hashes'] for row in offline['results']))
            partial=evaluation.evaluate(root,live=True,client=client,max_calls=1)
            self.assertEqual(partial['new_calls_this_invocation'],1)
            done=evaluation.evaluate(root,live=True,client=client,max_calls=24)
            self.assertEqual(done['new_calls_this_invocation'],17)
            self.assertEqual(done['status'],'complete')
            self.assertEqual(len(client.calls),18)
            self.assertTrue(all(group['definite_complete']==7 for group in done['groups']))
            self.assertTrue(any(row['reference_match'] is False for row in done['results']))
            self.assertTrue(all(len(row['reused_extraction_request_hashes'])==(2 if row['case_id']=='reset-local-converter' else 1) for row in done['results']))
            cached=evaluation.evaluate(root,client=client,max_calls=0)
            self.assertEqual(cached['results'],done['results'])
            self.assertEqual(cached['new_calls_this_invocation'],0)

    def test_third_arm_adds_only_generic_intermediate_rule_and_keeps_options(self):
        fixture,_,rows=evaluation.prepared((evaluation.INTERMEDIATE_ARM,))
        for row in rows:
            originals=[]
            def replay(req):
                originals.append(req)
                return validate_answers(row['packets'][digest(req)]['response'],req),digest(req)
            detector.build(row['source'],replay,version=fixture['protocol'])
            for original in originals:
                bound=evaluation.variant(row['source'],original,'bound_absent_implementation')
                intermediate=evaluation.variant(row['source'],original,evaluation.INTERMEDIATE_ARM)
                if original['state']['stage']=='requirement_extraction':
                    self.assertEqual(bound,intermediate);continue
                expected=deepcopy(bound);expected['state']['development_requirement_arm']=evaluation.INTERMEDIATE_ARM
                for question in expected['questions'].values():question['instructions']+='\n'+evaluation.INTERMEDIATE_EVIDENCE_RULE
                self.assertEqual(intermediate,expected)
                self.assertLessEqual(len(dumps(intermediate)),120000)
        for case_word in ('report.txt','gzip','score','location','total=42'):
            self.assertNotIn(case_word,evaluation.INTERMEDIATE_EVIDENCE_RULE)

    def test_separate_completion_contrasts_use_full_extraction_and_original_cases_reuse_it(self):
        supplement=Path(__file__).parent/'fixtures/requirement-intermediate-controls.json'
        frozen=read(supplement);left,right=frozen['cases']
        self.assertEqual(left['document']['messages'][:3],right['document']['messages'][:3])
        self.assertEqual(left['reference']['accepted_values'],[0])
        self.assertEqual(right['reference']['accepted_values'],[1])
        class ExtraClient(ScanClient):
            def transport(self,request):
                if request['state']['stage']!='requirement_extraction':return super().transport(request)
                self.calls.append(request)
                return {'model':request['model'],'answers':{key:{'type':'choice','probabilities':{
                    option:float(option=='task_requirement') for option in question['criteria']}} for key,question in request['questions'].items()}}
        with TemporaryDirectory() as temp,redirect_stdout(StringIO()):
            root=Path(temp);client=ExtraClient(root)
            args=dict(arms=(evaluation.INTERMEDIATE_ARM,),supplement_path=supplement)
            offline=evaluation.evaluate(root,client=client,max_calls=0,**args)
            self.assertEqual(offline['new_calls_this_invocation'],0)
            manifest=read(root/'inputs.json')
            self.assertEqual(manifest['supplemental_fixture_hash'],digest(frozen))
            done=evaluation.evaluate(root,live=True,client=client,max_calls=13,**args)
            self.assertEqual(done['status'],'complete')
            self.assertEqual(done['new_calls_this_invocation'],13)
            self.assertEqual(sum(req['state']['stage']=='requirement_extraction' for req in client.calls),2)
            self.assertEqual(sum(req['state']['stage']=='requirement_conflict_scan' for req in client.calls),11)
            self.assertEqual(done['groups'][0]['original_definite_complete'],7)
            self.assertEqual(done['groups'][0]['supplemental_definite_complete'],2)
            self.assertTrue(all(row['reused_extraction_request_hashes'] for row in done['results'] if not row.get('supplemental')))
            self.assertTrue(all(not row['reused_extraction_request_hashes'] for row in done['results'] if row.get('supplemental')))

    def test_short_question_replaces_old_rule_without_changing_evidence_or_choices(self):
        fixture,_,rows=evaluation.prepared((evaluation.SHORT_ARM,))
        for row in rows:
            def replay(original):
                short=row['requests'][digest(original)]
                if original['state']['stage']=='requirement_extraction':self.assertEqual(short,original)
                else:
                    bound=evaluation.variant(row['source'],original,'bound_absent_implementation')
                    expected=deepcopy(bound);expected['state']['development_requirement_arm']=evaluation.SHORT_ARM
                    expected['questions']=short['questions'];self.assertEqual(short,expected)
                    for key,question in short['questions'].items():
                        self.assertEqual(question['criteria'],original['questions'][key]['criteria'])
                        self.assertTrue(question['instructions'].startswith(evaluation.SHORT_CONFLICT_RULE))
                        self.assertNotIn(detector.RULE,question['instructions'])
                        self.assertNotIn(evaluation.INTERMEDIATE_EVIDENCE_RULE,question['instructions'])
                        self.assertTrue(question['instructions'].endswith(evaluation.ABSENT_IMPLEMENTATION_RULE))
                        self.assertIn('requirement that already applies at that point',question['instructions'])
                        self.assertIn(detector.TARGET_PREFIX,question['instructions'])
                        self.assertIn(detector.TARGET_SUFFIX,question['instructions'])
                return validate_answers(row['packets'][digest(original)]['response'],original),digest(original)
            detector.build(row['source'],replay,version=fixture['protocol'])

    def test_short_arm_reuses_all_eleven_extraction_receipts_and_only_calls_eleven_scans(self):
        supplement=Path(__file__).parent/'fixtures/requirement-intermediate-controls.json'
        receipts=Path(__file__).parent/'fixtures/requirement-intermediate-live.json'
        with TemporaryDirectory() as temp,redirect_stdout(StringIO()):
            root=Path(temp);client=ScanClient(root)
            args=dict(arms=(evaluation.SHORT_ARM,),supplement_path=supplement,supplement_extraction_path=receipts)
            offline=evaluation.evaluate(root,client=client,max_calls=0,**args)
            self.assertEqual(offline['new_calls_this_invocation'],0)
            self.assertTrue(all(r['reused_extraction_request_hashes'] for r in offline['results']))
            done=evaluation.evaluate(root,client=client,live=True,max_calls=11,**args)
            self.assertEqual(done['status'],'complete');self.assertEqual(done['new_calls_this_invocation'],11)
            self.assertEqual(len(client.calls),11)
            self.assertEqual(sum(len(r['reused_extraction_request_hashes']) for r in done['results']),11)
            cached=evaluation.evaluate(root,client=client,max_calls=0,**args)
            self.assertEqual(cached['results'],done['results'])


if __name__=='__main__':unittest.main()
