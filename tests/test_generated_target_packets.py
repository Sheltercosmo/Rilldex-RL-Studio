"""Packet ablations must isolate representation rather than change evidence."""
from copy import deepcopy
from pathlib import Path
import unittest

from scripts.evaluate_generated_target_packets import ARMS, transform
from tracker.jev import validate_answers
from tracker.schema import digest
from tracker.semantic_extraction import read


class GeneratedTargetPacketControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).parent/'fixtures'
        baseline=read(folder/'generated-generalization-target-identity.json')
        sources=read(folder/'generated-generalization-target-method-packets.json')['sources']
        fresh=read(folder/'generated-generalization-e2e.json')['cases'];cls.rows=[]
        for row in baseline['rows']:
            if row['arm']!='original':continue
            original=baseline['requests'][row['request_hash']];case=sources[row['case_id']]
            units=(fresh[row['case_id']]['selected']['units'] if row['case_id'] in fresh else case['document']['units'])
            for arm in ARMS:
                request,changes=transform(original,arm,case['source'],units)
                cls.rows.append({**row,'arm':arm,'request':request,'request_hash':digest(request),
                    'source_hash':digest(case['source']),'original_request_hash':digest(original),
                    'packet_changes':changes,'original_response':row['response'] if request==original else None})

    def test_every_arm_keeps_the_original_six_way_questions_and_source(self):
        originals={(r['case_id'],r['event_id']):r for r in self.rows if r['arm']=='original'}
        for row in self.rows:
            baseline=originals[row['case_id'],row['event_id']]
            a,b=row['request'],baseline['request']
            self.assertEqual(a['questions'],b['questions'])
            for key in ('prefix','subject','tool_contracts','tool_catalog','context_projection','context_policy',
                        'comparison_rule','current_meaning','cutoff_event_id','cutoff_codepoint'):
                self.assertEqual(a['state'].get(key),b['state'].get(key))
            self.assertEqual(row['source_hash'],baseline['source_hash'])

    def test_generic_field_filter_had_dropped_recorded_changes_and_checks(self):
        restored=[r for r in self.rows if r['arm']=='full_selected_content']
        movement=next(r for r in restored if r['case_id']=='simulation' and r['event_id']=='e8')
        self.assertEqual(list(movement['packet_changes']['restored_fields'].values()),[['change'],['change']])
        current=movement['request']['state']['current_action']['content']
        self.assertIn('to G',current['change']['text'])
        checking=next(r for r in restored if r['case_id']=='software' and r['event_id']=='e12')
        self.assertIn('check',checking['request']['state']['current_action']['content'])
        # Already complete controls remain identical and reuse original receipts.
        unchanged=[r for r in restored if r['request_hash']==r['original_request_hash']]
        self.assertEqual(len(unchanged),5)
        self.assertTrue(all(r['original_response'] is not None for r in unchanged))

    def test_segmentation_rule_arm_removes_only_that_incidental_instruction(self):
        originals={(r['case_id'],r['event_id']):r['request'] for r in self.rows if r['arm']=='original'}
        for row in self.rows:
            if row['arm']!='no_segmentation_rule':continue
            original=deepcopy(originals[row['case_id'],row['event_id']])
            removed=original['state'].pop('rule')
            self.assertEqual(row['request'],original)
            self.assertEqual(row['packet_changes']['removed_incidental_rule'],removed)

    def test_endpoint_views_duplicate_only_already_supplied_native_fields(self):
        for row in self.rows:
            if row['arm']!='endpoint_dispatch_views':continue
            state=row['request']['state'];prefix={e['id']:e for e in state['prefix']}
            priors={p['id']:p for p in state['prior_actions']}
            for key,pair in state['dispatch_pairs'].items():
                self.assertEqual(pair['earlier'],priors[key])
                self.assertEqual(pair['current'],state['current_action'])
                for native in pair['native_dispatches']:
                    if native['fields'] is None:continue
                    event=prefix[native['event_id']]
                    self.assertEqual(native['fields']['tool'],event['tool'])
                    self.assertEqual(native['fields']['arguments'],event['arguments'])


class GeneratedTargetPacketFieldEvidenceTests(unittest.TestCase):
    def test_restoring_content_or_removing_segmentation_rule_did_not_fix_rover(self):
        fixture=read(Path(__file__).parent/'fixtures/generated-generalization-target-packet-fields.json')
        self.assertEqual(len(fixture['rows']),5)
        for row in fixture['rows']:
            request=fixture['requests'][row['request_hash']]
            self.assertEqual(digest(request),row['request_hash'])
            answer=validate_answers(row['response'],request)['a0']['value']
            self.assertEqual(answer,'different_work_same_subject')
            self.assertFalse(row['scores']['a0']['correct'])
            self.assertEqual(fixture['groups'][row['arm']]['correct'],0)
            source=fixture['sources'][row['case_id']]['source']
            self.assertEqual(digest(source),row['source_hash'])
