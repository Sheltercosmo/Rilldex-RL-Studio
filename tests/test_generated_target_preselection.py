"""The interval reader must be constructible before target identities exist."""
from copy import deepcopy
import unittest

from scripts.evaluate_generated_target_preselection import records, local_document
from tracker.schema import InputError
from tracker.semantic_extraction import checked_span
from tracker.semantic_extraction import read
from tracker.jev import validate_answers
from tracker.schema import digest
from pathlib import Path


class GeneratedTargetPreselectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.rows=list(records())

    def test_eleven_fresh_pairs_have_same_evidence_without_any_target_or_plan_history(self):
        rows=[r for r in self.rows if r['extraction_origin']=='actual complete local extraction']
        self.assertEqual(len(rows),11)
        for row in rows:
            self.assertEqual(row['evidence_changed_fields'],[])
            self.assertNotIn('work_context',row['document'])
            self.assertNotIn('work_paths',row['document'])
            self.assertTrue(all(r['type'] in {'recorded_with','feedback_for'} for r in row['document']['relations']))

    def test_no_selected_endpoint_frames_leak_from_legacy_documents(self):
        rows=[r for r in self.rows if r['case_id'].startswith('recorded_airline_')]
        self.assertEqual(len(rows),2)
        for row in rows:
            self.assertEqual(row['request']['state']['selected_endpoint_scopes'],{})
            self.assertIn('selected_endpoint_scopes',row['evidence_changed_fields'])
        payment=next(r for r in rows if r['event_id']=='e46')
        self.assertNotIn('e29',{r['event_id'] for r in payment['request']['state']['source_ranges']})

    def test_derived_outputs_cannot_change_pre_target_projection(self):
        for row in self.rows:
            extraction=deepcopy(row['extraction'])
            extraction.update(relations=[dict(type='same_action_target',**{'from':'invented','to':'invented'})],
                              work_context=dict(frames=[dict(text='invented truth')]),
                              requested_work=dict(status='complete'),work_paths=[dict(id='invented')])
            self.assertEqual(local_document(row['source'],extraction),row['document'])
        broken=deepcopy(self.rows[0]['extraction']);broken['status']='incomplete'
        with self.assertRaises(InputError):local_document(self.rows[0]['source'],broken)

    def test_all_supplied_ranges_and_native_inputs_are_bound_to_actual_cutoff(self):
        for row in self.rows:
            state=row['request']['state'];events={e['id']:e for e in row['source']['events']}
            current=events[state['cutoff']['event_id']]
            for ref in state['source_ranges']:
                event=checked_span(row['source'],ref,state['cutoff'])
                self.assertEqual((event['trajectory_id'],event.get('context_id')),
                                 (current['trajectory_id'],current.get('context_id')))
            for native in state['native_dispatches']:
                if native['fields'] is None:continue
                event=events[native['event_id']]
                self.assertEqual(native['fields'],dict(tool=event['tool'],arguments=event['arguments']))

    def test_actual_no_history_requests_preserve_all_seventeen_decisions(self):
        frozen=read(Path(__file__).parent/'fixtures/generated-generalization-target-preselection.json')
        self.assertEqual((frozen['pairs'],frozen['correct']),(17,17))
        for row in frozen['rows']:
            request=frozen['requests'][row['request_hash']]
            self.assertEqual(digest(request),row['request_hash'])
            answers=validate_answers(row['response'],request)
            self.assertTrue(all(answers[key]['value']==value for key,value in row['reference'].items()))
