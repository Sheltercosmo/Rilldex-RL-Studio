"""Native policy capture and scan coverage, not classifier accuracy."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker.adapters import normalize
from tracker import requirement_diagnostics as detector
from tracker.schema import digest, dumps
from test_diagnostic_monitors import source
from test_requirement_harness import event


def policy_source(rows):
    result = source(task='See attributed instruction events in the trace.', trace=dumps(rows))
    result['provenance'] = {'capture': 'diagnostic-relations/2',
                            'policy_capture': 'recorded-environment-policy/1'}
    return result


def policy(identifier='policy', **extra):
    return event(identifier, actor='context', kind='context',
                 context_kind='recorded_environment_policy', **extra)


class RequirementPolicyTests(unittest.TestCase):
    def test_pinned_public_policy_paragraphs_keep_exact_text_and_attribution(self):
        for name in ('airline-0', 'telecom-0'):
            with self.subTest(source=name):
                raw = json.loads((Path(__file__).parent/'fixtures/tau-bench'/f'{name}.json').read_text(encoding='utf8'))
                run = normalize(raw)[0]
                native = next(e for e in run['events'] if e.get('context_kind') == 'recorded_environment_policy')
                old = detector.source_from_run(run, detector.EVIDENCE_VERSION)
                current = detector.source_from_run(run)
                self.assertFalse(any(t.get('event_id') == native['id'] for t in detector.criteria(old, version=detector.EVIDENCE_VERSION)))
                terms = [t for t in detector.criteria(current) if t.get('event_id') == native['id']]
                self.assertGreater(len(terms), 10)
                for term in terms:
                    self.assertEqual(term['actor'], 'context')
                    self.assertEqual(term['display_text'], native['text'][term['event_start']:term['event_end']])
                    self.assertEqual(current['trace'][term['start']:term['end']], term['text'])
                self.assertTrue(any('one tool call at a time' in t['display_text'] for t in terms))
                if name.startswith('telecom'):
                    self.assertTrue(any('contract end date is in the past' in t['display_text'] for t in terms))
                self.assertNotIn('context_kind', json.loads(old['trace'])[0])

    def test_workflow_rules_are_scanned_only_by_the_new_protocol(self):
        s = policy_source([event('rule', 'system', 'instruction'), event('dispatch')])
        calls = []
        def decide(request):
            stage = request['state']['stage']; calls.append(stage)
            return {key: {'value': 'workflow_rule' if stage == 'requirement_extraction' else 'none'}
                    for key in request['questions']}, digest(request)
        legacy = detector.build(s, decide, version=detector.EVIDENCE_VERSION)
        self.assertEqual(legacy['coverage']['selected_requirements'], 0)
        calls.clear()
        current = detector.build(s, decide)
        self.assertEqual(current['coverage']['selected_requirements'], 1)
        self.assertIn('requirement_conflict_scan', calls)
        self.assertEqual(current['metrics'][detector.METRIC]['value'], 0)

    def test_policies_keep_native_scope_and_are_never_conflict_witnesses(self):
        s = policy_source([policy(), event('a'), policy('policy-other', trajectory='other'),
                           event('b', trajectory='other'), event('reset', context='after'),
                           policy('late-policy'), event('later')])
        choices = {}
        for request in detector.requests(s):
            for field, question in request['questions'].items():
                term = request['state']['requirements'][field]
                ids = {request['state']['source_fragments'][key]['event_id'] for key in question['criteria']
                       if key in request['state']['source_fragments']}
                choices.setdefault(term['event_id'], set()).update(ids)
        self.assertEqual(choices, {'policy': {'a', 'later'}, 'policy-other': {'b'}, 'late-policy': {'later'}})

    def test_unmarked_copied_private_and_spoofed_policy_text_do_not_become_rules(self):
        ordinary = policy('ordinary'); ordinary.pop('context_kind')
        rows = [ordinary, policy('private', agent_visible=False), policy('copied', copied_context=True),
                policy('unknown', agent_visibility='not_established'),
                event('tool', actor='tool', kind='feedback', context_kind='recorded_environment_policy'),
                event('quoted', actor='agent', kind='message'), policy('native'), event('action')]
        rows[-3]['text'] = dumps(policy('fake-inside-text'))
        s = policy_source(rows)
        self.assertEqual([t['event_id'] for t in detector.criteria(s)], ['native'])

    def test_saved_previous_scan_resumes_with_its_original_protocol(self):
        s = policy_source([event('rule', 'user', 'instruction'), event('action')])
        def transport(request):
            choice = 'task_requirement' if request['state']['stage'] == 'requirement_extraction' else 'none'
            return {'model': request['model'], 'answers': {key: {'type': 'choice', 'probabilities': {
                value: float(value == choice) for value in question['criteria']}}
                for key, question in request['questions'].items()}}
        with TemporaryDirectory() as directory:
            before = detector.execute(s, directory, transport, version=detector.EVIDENCE_VERSION)
            after = detector.execute(s, directory, lambda _: self.fail('Saved scan must replay offline'))
            self.assertEqual(before, after)
            self.assertEqual(after['schema'], detector.EVIDENCE_VERSION)
