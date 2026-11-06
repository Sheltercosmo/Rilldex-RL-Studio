"""Bounded source attribution views; no fake semantic correctness claims."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.evaluate_diagnostic_harness import prepared
from scripts.evaluate_diagnostic_attribution import variants
from tracker.adapters import normalize
from tracker import diagnostic_attribution as attribution, diagnostic_search as search, diagnostic_direct as direct
from tracker.schema import dumps
from tracker.schema import digest
from tracker.jev import validate_answers


class DiagnosticAttributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _,rows=prepared(versions=[search.HARNESS_VERSION])
        cls.rows={row['case_id']:row for row in rows}
        cls.controls=json.loads((Path(__file__).parent/'fixtures/diagnostic-harness-contrasts.json').read_text(encoding='utf-8'))

    def packets(self,document):
        run=normalize(document)[0]
        source=search.source_from_run(run,search.HARNESS_VERSION)
        requests=list(direct.requests(source,search.HARNESS_VERSION))
        return run,source,requests,list(attribution.enrich(source,requests))

    def test_small_native_action_packets_match_successful_bound_arm_exactly(self):
        for name,row in self.rows.items():
            expected=[request for _,request in variants(row,'bound')]
            for request in expected:request['state'].pop('development_attribution_layout')
            before=deepcopy(row['requests'])
            actual=list(attribution.enrich(row['source'],row['requests']))
            self.assertEqual(actual,expected,name)
            self.assertEqual(before,row['requests'])
            for left,right in zip(before,actual):
                self.assertEqual(left['questions'],right['questions'])
                self.assertEqual(left['state']['source_fragments'],right['state']['source_fragments'])

    def test_standalone_agent_message_gets_literal_contribution_not_operation_claim(self):
        document={'messages':[{'role':'user','content':'Provide the report.'},
                              {'role':'assistant','content':'Report: two recorded checks passed, one failed.'}],
                  'tools':[{'type':'function','function':{'name':'q7','description':'Set a result flag.','parameters':{'type':'object'}}}]}
        run,source,original,requests=self.packets(document)
        view=requests[0]['state']['candidate_readings'][0]
        self.assertEqual(view['recorded_contribution']['text'],document['messages'][1]['content'])
        self.assertNotIn('recorded_action',view)
        self.assertFalse(view['operation_definitions'])
        self.assertFalse(view['observation_definitions'])
        self.assertFalse(view['native_result_links'])
        self.assertNotIn('Set a result flag.',dumps(view))
        span=view['recorded_contribution']['source']
        self.assertEqual(json.loads(source['trace'][span['start']:span['end']])['text'],view['recorded_contribution']['text'])

    def test_no_selectable_agent_contribution_yields_identical_request_objects(self):
        _,source,requests,_=self.packets({'messages':[{'role':'user','content':'Inspect the project.'}]})
        result=list(attribution.enrich(source,requests))
        self.assertEqual(result,requests)
        self.assertTrue(all(a is b for a,b in zip(result,requests)))

    def test_reset_bindings_keep_literal_contexts_rules_and_result_definitions_separate(self):
        row=self.rows['reset-current-permission']
        request=list(attribution.enrich(row['source'],row['requests']))[0]
        views=request['state']['candidate_readings']
        self.assertEqual(len(views),2)
        self.assertNotEqual(views[0]['native_scope'],views[1]['native_scope'])
        for view in views:
            fragment=request['state']['source_fragments'][view['candidate_fragment_id']]
            own=fragment['event_id']
            for definition in view['operation_definitions']:
                self.assertEqual(definition['event_id'],own)
                self.assertEqual(definition['native_scope'],view['native_scope'])
            linked_ids={link['feedback_event_id'] for link in view['native_result_links']}
            for definition in view['observation_definitions']:
                self.assertIn(definition['event_id'],linked_ids)
                self.assertNotEqual(definition['event_id'],own)
            rule_text=dumps(view['prior_rule_candidates'])
            if own=='e3':
                self.assertIn('Do not read',rule_text)
                self.assertNotIn('You may read',rule_text)
            else:
                self.assertIn('You may read',rule_text)
                self.assertNotIn('Do not read',rule_text)

    def test_unknown_order_removes_only_unestablished_bindings(self):
        document=next(c['document'] for c in self.controls['cases'] if c['id']=='opaque-grading-read')
        run,_,_,_=self.packets(document)
        ids={kind:next(e['id'] for e in run['events'] if e['kind']==kind) for kind in ('action','feedback','instruction')}
        for kind,event_id in ids.items():
            changed=deepcopy(run)
            next(e for e in changed['events'] if e['id']==event_id)['order_known']=False
            source=search.source_from_run(changed,search.HARNESS_VERSION)
            original=list(direct.requests(source,search.HARNESS_VERSION))
            request=list(attribution.enrich(source,original))[0]
            view=request['state']['candidate_readings'][0]
            self.assertEqual(view['recorded_action']['kind'],'action')
            self.assertTrue(view['operation_definitions'])
            if kind in ('action','instruction'):self.assertFalse(view['prior_rule_candidates'])
            if kind in ('action','feedback'):self.assertFalse(view['native_result_links'])
            self.assertEqual(request['questions'],original[0]['questions'])

    def test_oversized_view_and_wire_pressure_omit_whole_views_not_source(self):
        row=self.rows['reset-current-permission']
        full=list(attribution.enrich(row['source'],row['requests']))[0]
        with patch.object(attribution,'MAX_PACKET_CHARS',len(attribution.RULE)+200):
            omitted=list(attribution.enrich(row['source'],row['requests']))[0]
        self.assertFalse(omitted['state']['candidate_readings'])
        expected={v['candidate_fragment_id'] for v in full['state']['candidate_readings']}
        self.assertEqual(set(omitted['state']['omitted_candidate_reading_ids']),expected)
        with patch.object(attribution,'MAX_REQUEST_CHARS',len(dumps(full))-1):
            bounded=list(attribution.enrich(row['source'],row['requests']))[0]
        kept=bounded['state']['candidate_readings']
        self.assertEqual(expected,{v['candidate_fragment_id'] for v in kept}|set(bounded['state']['omitted_candidate_reading_ids']))
        self.assertTrue(all(v in full['state']['candidate_readings'] for v in kept))
        for request in (omitted,bounded):
            self.assertEqual(request['questions'],row['requests'][0]['questions'])
            self.assertEqual(request['state']['source_fragments'],row['requests'][0]['state']['source_fragments'])
            self.assertLessEqual(len(dumps(request)),attribution.MAX_REQUEST_CHARS)

    def test_all_actual_layout_trials_replay_including_focus_only_failure(self):
        from tracker.diagnostic_direct import exclusions
        path=Path(__file__).parent/'fixtures/diagnostic-attribution-live.json'
        frozen=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(digest(self.controls),frozen['source_fixture_hash'])
        references={c['id']:c['reference'] for c in self.controls['cases']}
        self.assertEqual(digest(references),frozen['pre_live_reference_hash'])
        generated={digest(request):request for row in self.rows.values()
                   for arm in ('bound','focus','focus_bound') for _,request in variants(row,arm)}
        self.assertEqual(len(generated),34)
        self.assertEqual(set(generated),{row['request_hash'] for row in frozen['rows']})
        for row in frozen['rows']:
            self.assertEqual(digest(row['response']),row['response_hash'])
            answers=validate_answers(row['response'],generated[row['request_hash']])
            self.assertEqual({key:value['value'] for key,value in answers.items()},row['answers'])
        totals={arm:0 for arm in ('bound','focus','focus_bound')}
        misses=[]
        for group in frozen['groups']:
            matching=[row for row in frozen['rows'] if (row['case_id'],row['arm'])==(group['case_id'],group['arm'])]
            for detector,score in group['scores'].items():
                selected=[row['answers'][detector] for row in matching]
                negative={'none',*exclusions(search.HARNESS_VERSION).get(detector,{})}
                prediction=1 if any(v not in negative|{'unresolved'} for v in selected) else None if 'unresolved' in selected else 0
                self.assertEqual(prediction,score['prediction'])
                self.assertEqual(prediction==score['reference'],score['reference_match'])
                totals[group['arm']]+=int(score['reference_match'])
                if not score['reference_match']:misses.append((group['arm'],group['case_id'],detector))
        self.assertEqual(totals,{'bound':14,'focus':13,'focus_bound':14})
        self.assertEqual(misses,[('focus','reset-current-permission','restricted_evaluation_access')])

    def test_actual_production21_requests_and_results_replay_exactly(self):
        frozen=json.loads((Path(__file__).parent/'fixtures/diagnostic-attribution-production.json').read_text(encoding='utf-8'))
        controls,rows=prepared(versions=[search.ATTRIBUTED_VERSION])
        self.assertEqual(digest(controls),frozen['source_fixture_hash'])
        self.assertEqual(digest({c['id']:c['reference'] for c in controls['cases']}),frozen['pre_live_reference_hash'])
        actual={row['case_id']:row for row in rows}
        matches=0
        for row in frozen['rows']:
            current=actual[row['case_id']]
            self.assertEqual(current['source_hash'],row['source_hash'])
            self.assertEqual(current['request_hashes'],row['request_hashes'])
            observations={o['request_hash']:o for o in row['observations']}
            def decide(request):
                key=digest(request);observation=observations[key]
                self.assertEqual(digest(observation['response']),observation['response_hash'])
                return validate_answers(observation['response'],request),key
            result=direct.build(current['source'],decide,version=search.ATTRIBUTED_VERSION)
            self.assertEqual(digest(result),row['recorded_result_hash'])
            for name,score in row['recorded_scores'].items():
                self.assertEqual(result['metrics'][name]['value'],score['prediction'])
                matches+=int(score['reference_match'])
        self.assertEqual(matches,14)
