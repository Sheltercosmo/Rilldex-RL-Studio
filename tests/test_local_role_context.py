import copy
import unittest

from tracker.anchored_occurrences import AnchoredOccurrenceClient, prepare, HARNESS
from tracker.entity_contracts import FIELD_RULES
from tracker.entity_occurrences import OccurrenceClient
from tracker.local_role_context import DEPENDENCIES, context_for, exact_local_candidate
from tracker.schema import InputError
from research.occurrence_controls import control_input, fixed_response


def fixture():
    run, nodes, uid = control_input('role-dependency', 'I will run the code to see the output.', 'plan', 'intended_target')
    node = next(n for n in nodes if n['id'] == uid)
    head = next(f for r in node['entity_extraction']['routes'] for f in r['fields'] if f['role'] == 'intended_operation')
    candidates = node['entity_extraction']['observation']['_span_request']['state']['candidates']
    selected = next(c for c in candidates if c['text'] == 'run the code')
    head.update(presence_decision='local_expression', status='selected_span', selected_candidate=selected, raw_choice=selected['id'], review_note=None)
    return run, nodes, uid, node, head


class LocalRoleContextTests(unittest.TestCase):
    def test_every_mention_role_has_a_category_specific_dependency(self):
        self.assertEqual(set(DEPENDENCIES), {k for k, (profile, _) in FIELD_RULES.items() if profile == 'mention'})
        for key, (head, contrasts) in DEPENDENCIES.items():
            self.assertEqual(key.split('__')[0], head.split('__')[0])
            self.assertNotEqual(FIELD_RULES[head][0], 'mention')
            self.assertTrue(all(c in FIELD_RULES for c in contrasts))

    def test_local_dependency_neither_changes_choices_nor_infers_a_link(self):
        run, nodes, uid, node, head = fixture(); before = copy.deepcopy(node)
        context = context_for(run, node, 'plan__intended_target')
        self.assertEqual(context['status'], 'ready_for_role_inspection')
        self.assertEqual(context['governing_expression']['selection']['text'], 'run the code')
        self.assertEqual(node, before)
        self.assertNotIn('relations', context)

    def test_missing_conflicting_and_forged_heads_block_without_absence_or_provider_calls(self):
        for mutation in ({'selected_candidate': None}, {'review_note': 'presence/span conflict'}, {'status': 'unresolved'}):
            run, nodes, uid, node, head = fixture(); head.update(mutation)
            called = []
            context = context_for(run, node, 'plan__intended_target')
            self.assertEqual(context['status'], 'governing_expression_needed')
            with self.assertRaises(InputError): AnchoredOccurrenceClient(nodes=nodes, transport=lambda r: called.append(r)).evaluate(run, uid)
            self.assertEqual(called, [])
        run, nodes, uid, node, head = fixture()
        head['selected_candidate']['text'] = 'an invented operation'
        self.assertEqual(context_for(run, node, 'plan__intended_target')['status'], 'governing_expression_needed')

    def test_presence_and_completion_remain_separate_from_head_readiness(self):
        run, nodes, uid, node, head = fixture()
        target = next(f for r in node['entity_extraction']['routes'] for f in r['fields'] if f['role'] == 'intended_target')
        target['presence_decision'] = 'no_local_expression'
        self.assertEqual(context_for(run, node, 'plan__intended_target')['status'], 'no_local_role')
        node['entity_extraction']['extraction_status'] = 'stale'
        self.assertEqual(context_for(run, node, 'plan__intended_target')['status'], 'local_extraction_needed')

    def test_structured_argument_and_source_scope_integrity(self):
        run, nodes, uid, node, head = fixture()
        c = copy.deepcopy(head['selected_candidate']); c['event_id'] = 'future'
        self.assertFalse(exact_local_candidate(run, node, c))
        e = next(e for e in run['events'] if e['id'] == node['event_id']); e['arguments'] = {'items': ['value']}
        c = {'kind': 'structured_argument', 'event_id': e['id'], 'source_pointer': node['source_pointer'], 'normalized_event_pointer': '/arguments/items/0', 'value': 'value'}
        self.assertTrue(exact_local_candidate(run, node, c))
        c['value'] = 'different'; self.assertFalse(exact_local_candidate(run, node, c))
        c.update(normalized_event_pointer='/text', value=e['text']); self.assertFalse(exact_local_candidate(run, node, c))
        c = copy.deepcopy(head['selected_candidate']); c['source_pointer'] = '/wrong-record'
        self.assertFalse(exact_local_candidate(run, node, c))

    def test_packets_preserve_candidate_evidence_options_and_argmax(self):
        run, nodes, uid, node, head = fixture()
        baseline = OccurrenceClient(nodes=nodes).request(run, uid)
        calls = []
        def transport(request):
            calls.append(request)
            return fixed_response(request, lambda k, q: 'no_local_mention' if k.endswith('__coverage') else 'wrong_role')
        client = AnchoredOccurrenceClient(nodes=nodes, transport=transport)
        request = client.request(run, uid)
        self.assertEqual(request['state']['candidates'], baseline['state']['candidates'])
        self.assertEqual(request['state']['subject'], baseline['state']['subject'])
        for k, q in request['questions'].items(): self.assertEqual(q['criteria'], baseline['questions'][k]['criteria'])
        saved = client.evaluate(run, uid)
        self.assertEqual(saved['_provenance']['harness'], HARNESS)
        self.assertTrue(client.cache_matches(saved, run, uid))
        self.assertTrue(all(a['selection_policy'] == 'argmax/1' for k, a in saved.items() if not k.startswith('_')))
        client.evaluate(run, uid, resume=saved); self.assertEqual(len(calls), 1)
        head['review_note'] = 'conflicting upstream'; self.assertEqual(prepare(run, nodes, uid)[0]['questions'], {})


if __name__ == '__main__': unittest.main()
