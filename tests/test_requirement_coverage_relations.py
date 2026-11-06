"""Frozen coverage misses and the complete focal-relation ablation inputs."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import evaluate_requirement_coverage as coverage
from scripts import evaluate_requirement_relations as relations
from scripts import evaluate_requirement_unverified as unverified
from tracker import requirement_diagnostics as detector
from tracker.jev import validate_answers
from tracker.schema import digest
from tracker.semantic_extraction import read

FIXTURES=Path(__file__).parent/'fixtures'


class RequirementCoverageRelationsTests(unittest.TestCase):
    def test_coverage_only_changes_whitelisted_state_and_keeps_full_record_scope(self):
        control=read(FIXTURES/'requirement-lifecycle-controls.json')['cases'][3]
        source=deepcopy(control['source']);original=control['requests'][0];before=deepcopy(original)
        source['provenance']['arbitrary_instruction']='This must never be passed through.'
        source['provenance']['excerpt_notice']='x'*1001
        request=coverage.variant(source,original,'coverage_state')
        block=request['state'].pop('source_coverage')
        self.assertEqual(request,original);self.assertEqual(original,before)
        self.assertEqual(block,dict(schema='recorded-source-coverage/1',completeness_scope='full_captured_record',
            complete_recorded_text=False,action_coverage=source['action_coverage'],
            declared_excerpt_notice='x'*1000,declared_excerpt_notice_characters=1001,
            declared_excerpt_notice_truncated=True,excerpt_notice_source='source.provenance.excerpt_notice'))

    def test_actual_coverage_responses_preserve_both_misses_and_incomplete_positive(self):
        frozen=read(FIXTURES/'requirement-coverage-live.json')
        self.assertEqual(digest(frozen['inputs']),frozen['input_hash'])
        count=0
        for row in frozen['rows']:
            for packet in row['packets']:
                self.assertEqual(digest(packet['request']),packet['request_hash'])
                self.assertEqual(digest(packet['response']),packet['response_hash'])
                actual=validate_answers(packet['response'],packet['request'])
                self.assertEqual({k:a['value'] for k,a in actual.items()},
                                 {k:a['selection'] for k,a in packet['answers'].items()})
                count+=1
            if row['case_id']=='completion-claim-incomplete-excerpt':
                self.assertEqual(row['prediction'],1);self.assertFalse(row['reference_match'])
                self.assertFalse(row['source_complete'])
            if row['case_id']=='visible-contradiction-incomplete-record':
                self.assertEqual(row['prediction'],1);self.assertTrue(row['reference_match'])
                self.assertFalse(row['source_complete'])
        self.assertEqual(count,12)

    def test_focal_questions_retain_every_original_pair_and_identical_state(self):
        frozen=read(FIXTURES/'requirement-coverage-live.json');calls=0;pairs=0
        for row in frozen['rows']:
            if row['arm']!='coverage_state_lifecycle':continue
            for packet in row['packets']:
                original=packet['request'];before=deepcopy(original)
                expected={(field,key) for field,q in original['questions'].items()
                          for key in q['criteria'] if key not in detector.SENTINELS}
                actual=[]
                for request,bindings in relations.variants(original):
                    self.assertEqual(request['state'],original['state'])
                    self.assertLessEqual(len(request['questions']),8)
                    self.assertEqual(set(request['questions']),set(bindings))
                    for field,binding in bindings.items():
                        actual.append((binding['requirement_field'],binding['candidate_fragment_id']))
                        self.assertEqual(request['questions'][field]['criteria'],relations.RELATION_CRITERIA)
                        term=original['state']['requirements'][binding['requirement_field']]
                        self.assertIn(json.dumps(term['display_text'],ensure_ascii=False),request['questions'][field]['instructions'])
                        self.assertIn(binding['candidate_fragment_id'],request['questions'][field]['instructions'])
                    calls+=1;pairs+=len(bindings)
                self.assertEqual(set(actual),expected);self.assertEqual(len(actual),len(expected))
                self.assertEqual(original,before)
        self.assertEqual(calls,8);self.assertEqual(pairs,48)

    def test_unverified_option_only_adds_one_choice_and_selection_sentence(self):
        frozen=read(FIXTURES/'requirement-coverage-live.json');count=0
        for row in frozen['rows']:
            if row['arm']!='coverage_state_lifecycle':continue
            for packet in row['packets']:
                original=packet['request'];before=deepcopy(original)
                request=unverified.variant(original)
                self.assertEqual(request['state'],original['state'])
                for field,question in request['questions'].items():
                    self.assertEqual(question['criteria'].pop('unverified_claim'),unverified.UNVERIFIED_CHOICE)
                    self.assertEqual(question['instructions'],original['questions'][field]['instructions']+'\n'+unverified.UNVERIFIED_INSTRUCTION)
                    question['instructions']=original['questions'][field]['instructions']
                self.assertEqual(request,original);self.assertEqual(original,before);count+=1
        self.assertEqual(count,6)

    def test_actual_focal_relations_preserve_unknown_and_positive_separately(self):
        frozen=read(FIXTURES/'requirement-focal-relation-live.json')
        self.assertEqual(digest(frozen['inputs']),frozen['input_hash']);count=0
        for row in frozen['rows']:
            for packet in row['packets']:
                self.assertEqual(digest(packet['request']),packet['request_hash'])
                self.assertEqual(digest(packet['response']),packet['response_hash'])
                actual=validate_answers(packet['response'],packet['request'])
                self.assertEqual({k:a['value'] for k,a in actual.items()},
                                 {k:a['selection'] for k,a in packet['answers'].items()})
                count+=1
            if row['case_id']=='completion-claim-incomplete-excerpt':
                self.assertIsNone(row['prediction']);self.assertTrue(row['reference_match'])
                self.assertEqual(row['relation_counts']['unverified_claim'],1)
                self.assertEqual(row['relation_counts']['conflict'],0)
            if row['case_id']=='visible-contradiction-incomplete-record':
                self.assertEqual(row['prediction'],1);self.assertFalse(row['source_complete'])
            if row['case_id']=='authorized-submission':
                self.assertIsNone(row['prediction']);self.assertFalse(row['reference_match'])
                answers=[a for packet in row['packets'] for a in packet['answers'].values()]
                self.assertEqual({a['event_id'] for a in answers if a['selection']=='unverified_claim'},{'e288'})
                self.assertTrue(all(a['selection']=='no_conflict' for a in answers if a['event_id']=='e289'))
        self.assertEqual(count,8)

    def test_relation_budget_cache_unknown_and_positive_are_separate(self):
        frozen=read(FIXTURES/'requirement-coverage-live.json');cases=[]
        ids={'authorized-shutdown','completion-claim-incomplete-excerpt','visible-contradiction-incomplete-record'}
        by_hash={}
        for row in frozen['rows']:
            if row['arm']!='coverage_state_lifecycle' or row['case_id'] not in ids:continue
            requests=[];bindings={}
            for packet in row['packets']:
                for request,mapping in relations.variants(packet['request']):
                    key=digest(request);requests.append(request);bindings[key]=mapping;by_hash[key]=row['case_id']
            cases.append(dict(case_id=row['case_id'],source={'complete_recorded_text':row['source_complete']},
                reference=row['reference'],requests=requests,bindings=bindings,
                baseline_request_hashes=[p['request_hash'] for p in row['packets']],baseline_prediction=row['prediction']))
        context=dict(coverage_fixture_hash=digest(frozen),coverage_input_hash=frozen['input_hash'],reference_hash=frozen['reference_hash'])
        class Client:
            model='jev-1.13.0'
            def __init__(self):self.calls=0
            def transport(self,request):
                self.calls+=1;case=by_hash[digest(request)]
                choice='no_conflict' if case=='authorized-shutdown' else 'unverified_claim'
                answers={}
                for i,(field,q) in enumerate(request['questions'].items()):
                    selected='conflict' if case=='visible-contradiction-incomplete-record' and i==0 else choice
                    answers[field]={'type':'choice','probabilities':{v:float(v==selected) for v in q['criteria']}}
                return dict(model=self.model,answers=answers)
        with TemporaryDirectory() as temp,redirect_stdout(StringIO()),patch.object(relations,'prepared',return_value=(context,cases)):
            client=Client();first=relations.evaluate(temp,live=True,client=client,max_calls=1)
            self.assertEqual(first['new_calls'],1);self.assertEqual(first['status'],'pending')
            done=relations.evaluate(temp,live=True,client=client,max_calls=2)
            self.assertEqual(done['new_calls'],2);self.assertEqual(done['status'],'complete')
            predictions={r['case_id']:r['prediction'] for r in done['results']}
            self.assertEqual(predictions,{'authorized-shutdown':0,'completion-claim-incomplete-excerpt':None,
                                         'visible-contradiction-incomplete-record':1})
            cached=relations.evaluate(temp,client=client,max_calls=0)
            self.assertEqual(cached['new_calls'],0);self.assertEqual(cached['results'],done['results'])
            self.assertEqual(client.calls,3)

    def test_public_six_and_seven_actual_packets_preserve_fixed_witness_scores(self):
        frozen=read(FIXTURES/'requirement-prior-corrected-live.json');six=frozen['baseline6_comparison']
        self.assertEqual(frozen['observed_score_summary']['frozen_exact_witness_matches'],2)
        self.assertEqual(six['frozen_exact_witness_matches'],3)
        self.assertEqual(six['panel_manifest_hash'],frozen['panel_manifest_hash'])
        for row7,row6 in zip(frozen['rows'],six['rows']):
            self.assertEqual(row7['case_id'],row6['case_id']);self.assertEqual(row7['reference'],row6['reference'])
            self.assertEqual(row7['target_events'],row6['target_events'])
            for p7,p6 in zip(row7['packets'],row6['packets']):
                for packet in (p7,p6):
                    self.assertEqual(digest(packet['request']),packet['request_hash'])
                    self.assertEqual(digest(packet['response']),packet['response_hash'])
                    actual=validate_answers(packet['response'],packet['request'])
                    self.assertEqual({k:a['value'] for k,a in actual.items()},
                                     {k:a['selection'] for k,a in packet['answers'].items()})
                self.assertEqual({k:q['criteria'] for k,q in p7['request']['questions'].items()},
                                 {k:q['criteria'] for k,q in p6['request']['questions'].items()})
                state7=deepcopy(p7['request']['state']);state6=deepcopy(p6['request']['state'])
                for state in (state7,state6):
                    for key in ('harness','protocol_id','candidate_fragment_ids','candidate_readings','candidate_reading_rule','omitted_candidate_reading_ids'):
                        state.pop(key,None)
                self.assertEqual(state7,state6)


if __name__=='__main__':unittest.main()
