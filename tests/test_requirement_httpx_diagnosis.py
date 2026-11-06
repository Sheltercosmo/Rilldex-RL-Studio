"""Preserve the independently reproduced HTTPX miss and controlled probes."""
import ast
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import evaluate_requirement_httpx_ablation as ablation
from tracker import requirement_diagnostics as detector
from tracker.jev import validate_answers
from tracker.schema import digest
from tracker.semantic_extraction import read

FIXTURE=Path(__file__).parent/'fixtures/requirement-httpx-implementation-live.json'


class RequirementHttpxDiagnosisTests(unittest.TestCase):
    def test_exact_production_pages_keep_all_six_requirements_and_both_actual_misses(self):
        frozen=read(FIXTURE);source=frozen['source']
        self.assertEqual(digest(source),frozen['source_hash'])
        self.assertEqual(digest(frozen['inputs']),frozen['input_hash'])
        terms=list(frozen['rows'][0]['request']['state']['requirements'].values())
        self.assertEqual(len(terms),6)
        generated={r['state']['page']:r for r in detector.requests(source,terms,version=detector.EVIDENCE_VERSION)}
        for row in frozen['rows']:
            self.assertEqual(row['request'],generated[row['page']])
            self.assertEqual(digest(row['request']),row['request_hash'])
            self.assertEqual(digest(row['response']),row['response_hash'])
            answers=validate_answers(row['response'],row['request'])
            self.assertEqual(len(answers),6)
            self.assertEqual({a['value'] for a in answers.values()},{'none'})
            self.assertFalse(row['reference_match']);self.assertEqual(row['target_prediction'],0)
            self.assertTrue(row['reference']['expected_conflict'])
        for request in frozen['boundary_requests']:
            self.assertEqual(request,generated[request['state']['page']])
        self.assertEqual({r['page'] for r in frozen['rows']},{9,21})
        self.assertEqual({r['state']['page'] for r in frozen['boundary_requests']},{10,22})
        self.assertEqual(frozen['inputs']['original_target_events'],['e218'])

    def test_independent_reproduction_and_exact_compact_code_remain_separate(self):
        frozen,baseline,provenance,requests=ablation.prepared()
        reproduction=frozen['independent_reproduction']
        self.assertEqual(digest(reproduction),frozen['independent_reproduction_hash'])
        self.assertEqual(hashlib.sha256(ast.unparse(ast.parse(reproduction['selected_pure_code'])).encode()).hexdigest(),reproduction['selected_pure_code_sha256'])
        self.assertEqual(sum(len(r['variants']) for r in reproduction['results']),32)
        self.assertEqual({r['case'] for r in reproduction['results'] if not r['matches_literal_requirement']},
                         {'bom-only-line-before-json','bom-and-whitespace-only-line','bom-only-final-line'})
        event=next(e for e in json.loads(frozen['source']['trace']) if e.get('id')=='e68')
        exact='\n\n'.join(event['text'][start:end] for start,end in ablation.SLICES)
        compact=requests['compact_code'];self.assertEqual(compact['state']['source_fragments']['e68']['text'],exact)
        self.assertEqual(digest(exact),provenance['joined_code_hash'])
        tree=ast.parse(exact)
        self.assertEqual({n.name for n in tree.body if isinstance(n,ast.FunctionDef)},
                         {'_skip_json_whitespace','_is_json_whitespace_only','_parse_json_text'})
        parser=next(n for n in tree.body if isinstance(n,ast.ClassDef))
        self.assertEqual(parser.name,'NDJSONParser')
        self.assertEqual({n.name for n in parser.body if isinstance(n,ast.FunctionDef)},
                         {'__init__','feed','flush','_pop_line','_parse_line'})
        self.assertEqual(compact['questions'][ablation.FIELD]['instructions'],baseline['request']['questions'][ablation.FIELD]['instructions'])
        for request in requests.values():
            text=json.dumps(request)
            for forbidden in ('independent_reproduction','expected_conflict','bom-only-line-before-json','matches_literal_requirement','reference_match'):
                self.assertNotIn(forbidden,text)

    def test_singleton_and_event_choice_only_change_the_predeclared_dimensions(self):
        _,baseline,_,requests=ablation.prepared();original=baseline['request'];before=deepcopy(original)
        singleton=requests['requirement_only'];event=requests['event_choice']
        self.assertEqual(singleton['state'],original['state'])
        self.assertEqual(singleton['questions'],{ablation.FIELD:original['questions'][ablation.FIELD]})
        self.assertEqual(event['state'],original['state'])
        self.assertEqual(event['questions'][ablation.FIELD]['instructions'],singleton['questions'][ablation.FIELD]['instructions'])
        self.assertEqual(set(event['questions'][ablation.FIELD]['criteria']),{'e68','none','unverified_claim','unresolved'})
        for key in ('none','unverified_claim','unresolved'):
            self.assertEqual(event['questions'][ablation.FIELD]['criteria'][key],original['questions'][ablation.FIELD]['criteria'][key])
        self.assertEqual(original,before)

    def test_actual_ablation_misses_and_invalid_compact_trial_are_preserved(self):
        frozen=read(Path(__file__).parent/'fixtures/requirement-httpx-ablation-live.json')
        self.assertEqual(digest(frozen['inputs']),frozen['input_hash'])
        self.assertEqual(digest(frozen['reference']),frozen['reference_hash'])
        self.assertEqual(frozen['actual_new_calls'],3)
        _,baseline,_,requests=ablation.prepared()
        _,_,_,repaired=ablation.prepared(complete_schema=True)
        for row in frozen['rows']:
            self.assertEqual(row['request'],requests[row['arm']])
            self.assertEqual(digest(row['request']),row['request_hash'])
            self.assertEqual(digest(row['response']),row['response_hash'])
            if row['arm']=='compact_code':
                self.assertEqual(row['validation_status'],'invalid_request_schema_missing_validator_fields')
                self.assertEqual(row['error_type'],'KeyError');self.assertFalse(row['complete'])
                with self.assertRaises(KeyError):validate_answers(row['response'],row['request'])
                probabilities=row['response']['answers'][ablation.FIELD]['probabilities']
                self.assertEqual(max(probabilities,key=probabilities.get),row['unvalidated_raw_argmax'])
                self.assertEqual(row['unvalidated_raw_argmax'],'none')
            else:
                answers=validate_answers(row['response'],row['request'])
                self.assertEqual(answers[ablation.FIELD]['value'],'none')
                self.assertFalse(row['reference_match'])
        compact=deepcopy(repaired['compact_code'])
        for key in ('missingness','cutoff_event_id'):
            self.assertEqual(compact['state'].pop(key),baseline['request']['state'][key])
        self.assertEqual(compact,requests['compact_code'])

    def test_corrected_compact_actual_response_validates_and_preserves_the_miss(self):
        root=Path(__file__).parent/'fixtures'
        frozen=read(root/'requirement-httpx-compact-live.json');row=frozen['row']
        self.assertEqual(digest(frozen['inputs']),frozen['input_hash'])
        self.assertEqual(digest(frozen['reference']),frozen['reference_hash'])
        self.assertEqual(digest(row['request']),row['request_hash'])
        self.assertEqual(digest(row['response']),row['response_hash'])
        _,baseline,_,requests=ablation.prepared(complete_schema=True)
        self.assertEqual(row['request'],requests['compact_code'])
        answers=validate_answers(row['response'],row['request'])
        self.assertEqual(answers[ablation.FIELD]['value'],'none')
        self.assertTrue(row['complete']);self.assertEqual(row['prediction'],0);self.assertFalse(row['reference_match'])
        self.assertTrue(frozen['reference']['expected_conflict'])
        prior=read(root/'requirement-httpx-ablation-live.json')
        invalid=next(r for r in prior['rows'] if r['arm']=='compact_code')
        restored=deepcopy(row['request'])
        for key in ('missingness','cutoff_event_id'):
            self.assertEqual(restored['state'].pop(key),baseline['request']['state'][key])
        self.assertEqual(restored,invalid['request'])
        self.assertEqual(frozen['reference'],prior['reference'])
        implementation=read(FIXTURE)
        hashes=[r['request_hash'] for r in implementation['rows']+prior['rows']]+[row['request_hash']]
        self.assertEqual(len(set(hashes)),6)
        self.assertEqual(implementation['actual_new_calls']+prior['actual_new_calls']+frozen['actual_new_calls'],6)

    def test_shared_three_call_budget_and_cache_never_change_the_reference(self):
        class Client:
            model='jev-1.13.0'
            def __init__(self,root):self.root=root;self.calls=0
            def transport(self,request):
                self.calls+=1
                self_check=read(self.root/'requests'/(digest(request)+'.json'))
                if self_check!=request:raise AssertionError('Request must be exported before call')
                return dict(model=self.model,answers={field:dict(type='choice',probabilities={key:float(key=='none')
                    for key in q['criteria']}) for field,q in request['questions'].items()})
        with TemporaryDirectory() as directory,redirect_stdout(StringIO()):
            root=Path(directory);client=Client(root)
            first=ablation.evaluate(root,live=True,client=client,max_calls=1,complete_schema=True)
            self.assertEqual(first['new_calls_this_invocation'],1);self.assertEqual(first['status'],'pending')
            reference=read(root/'reference.json')
            done=ablation.evaluate(root,live=True,client=client,max_calls=2,complete_schema=True)
            self.assertEqual(done['new_calls_this_invocation'],2);self.assertEqual(done['status'],'complete')
            self.assertEqual(client.calls,3);self.assertEqual(read(root/'reference.json'),reference)
            self.assertTrue(reference['expected_conflict'])
            cached=ablation.evaluate(root,client=client,max_calls=0,complete_schema=True)
            self.assertEqual(cached['new_calls_this_invocation'],0);self.assertEqual(cached['results'],done['results'])


if __name__=='__main__':unittest.main()
