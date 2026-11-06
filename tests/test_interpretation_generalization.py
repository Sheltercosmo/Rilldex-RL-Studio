"""Cross-domain evidence controls, not a model-accuracy benchmark.

Author-constructed captures use documented encodings. Public airline/telecom
traces additionally exercise the existing native reader without mocked parsing.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from rilldex import Episode
from tracker.activity import packet as activity_packet, units
from tracker.adapters import normalize
from tracker.capabilities import links
from tracker.graph_store import build
from tracker.import_batch import read_bytes
from tracker.jev import packet as macro_packet
from tracker.readable_context import LINKED_VERSION, contains, resolve_quote
from tracker.schema import InputError, digest, dumps
from tracker.semantic_extraction import generation_request, prefix, context_scope
from tracker.semantic_map import evidence
from tracker.store import Store

POLICY = {'schema': LINKED_VERSION, 'recent_events': 1, 'max_event_chars': 128, 'extra_ranges': []}


def encoded_domains():
    return [
        ('navigation', 5, {'type': 'integer', 'oneOf': [
            {'const': 2, 'title': 'move forward'}, {'const': 5, 'title': 'toggle door'}]},
         {'door': 2}, {'type': 'object', 'properties': {'door': {'oneOf': [
             {'const': 0, 'title': 'open'}, {'const': 1, 'title': 'closed'}, {'const': 2, 'title': 'locked'}]}}}),
        ('continuous-control', [-0.2, 0.1], {'type': 'array', 'prefixItems': [
            {'type': 'number', 'title': 'joint torque', 'description': 'Nm'},
            {'type': 'number', 'title': 'gripper displacement', 'description': 'metres'}]},
         [0.4, 0.05], {'type': 'array', 'prefixItems': [
             {'title': 'joint position', 'description': 'radians'}, {'title': 'finger separation', 'description': 'metres'}]}),
        ('inventory', {'sku': 'A-7', 'quantity': 4}, {'type': 'object', 'description': 'Reserve inventory, not a purchase.',
            'properties': {'sku': {'type': 'string'}, 'quantity': {'type': 'integer'}}},
         {'available': 3}, {'type': 'object', 'properties': {'available': {'description': 'Units available for reservation'}}}),
        ('browser', {'target': 'button-4', 'operation': 'click'}, {'type': 'object', 'description': 'Dispatch a click to a recorded accessibility target.'},
         {'button-4': {'name': 'Continue', 'disabled': True}}, {'type': 'object', 'description': 'Accessible controls; disabled controls cannot be activated.'}),
    ]


def episode(name, action, action_schema, observation, observation_schema):
    return (Episode(episode_id=name, goal='Complete the recorded task.', action_schema=action_schema,
                    observation_schema=observation_schema)
            .reset(observation, {'hidden_solution': 'PRIVATE_RESET'})
            .step(action, observation, reward=-1, done=True, info={'hidden_solution': 'PRIVATE_RESULT'},
                  model_response='Attempt the next operation.').snapshot())


def conversation():
    return {'messages': [
        {'role': 'user', 'content': 'Check inventory before placing an order.'},
        {'role': 'assistant', 'content': 'Read stock first.', 'tool_calls': [
            {'id': 'stock', 'type': 'function', 'function': {'name': 'dispatch', 'arguments': '{"sku":"A-7"}'}}]},
        {'role': 'tool', 'tool_call_id': 'stock', 'content': 'Only 3 units available.'},
        *[{'role': 'assistant', 'content': f'Consider option {i}.'} for i in range(12)],
        {'role': 'assistant', 'content': 'Request 4 units.', 'tool_calls': [
            {'id': 'order', 'type': 'function', 'function': {'name': 'reserve', 'arguments': '{"quantity":4}'}}]},
        {'role': 'tool', 'tool_call_id': 'order', 'content': 'FUTURE_RESULT'},
    ], 'tools': [{'type': 'function', 'function': {'name': 'dispatch',
           'description': 'Read available inventory without modifying it.', 'parameters': {'type': 'object'}}}]}


class InterpretationGeneralizationTests(unittest.TestCase):
    def test_domain_encodings_survive_ingestion_and_reach_all_readers(self):
        for case in encoded_domains():
            with self.subTest(domain=case[0]):
                doc = episode(*case)
                run = normalize(doc)[0]
                a = next(e for e in run['events'] if e['kind'] == 'action')
                obs = next(e for e in run['events'] if e['kind'] == 'context')
                self.assertEqual(a['text'], dumps(case[1]))
                self.assertEqual(a['tool_contract']['definition'], case[2])
                self.assertEqual(obs['observation_contract']['definition'], case[4])
                self.assertEqual(run['adapter_version'], 'environment-episode/2+contracts-1')
                self.assertEqual(run['raw'], doc)
                u = next(u for u in units(run) if u['event_id'] == a['id'])
                packets = [macro_packet(run, a['id']), activity_packet(run, u['id']),
                           generation_request(run, evidence(run, a['id']), 'construct', POLICY)]
                for packet in packets:
                    text = dumps(packet)
                    self.assertIn('/action_schema', text)
                    self.assertIn('/observation_schema', text)
                    self.assertNotIn('PRIVATE_', text)
                    self.assertNotIn('recorded_reward', text)
                self.assertEqual(len(links(run)['records']), 1)

    def test_capture_is_copied_and_no_semantics_are_invented_without_schemas(self):
        case = encoded_domains()[0]
        doc = episode(*case)
        case[2]['title'] = 'Changed outside capture'
        self.assertNotIn('title', doc['action_schema'])
        original = normalize(doc)[0]
        plain = deepcopy(doc)
        plain.pop('action_schema'); plain.pop('observation_schema')
        untyped = normalize(plain)[0]
        self.assertFalse(any('tool_contract' in e or 'observation_contract' in e for e in untyped['events']))
        self.assertEqual(original['events'][2]['id'], untyped['events'][2]['id'])
        self.assertEqual(build(original)['edges'], build(untyped)['edges'])
        self.assertNotEqual(original['id'], untyped['id'])
        self.assertEqual(untyped['adapter_version'], 'environment-episode/2')

    def test_first_model_expression_gets_encodings_without_future_actions_or_outcomes(self):
        for case in encoded_domains():
            doc = episode(*case)
            doc['steps'][0]['observation'] = 'FUTURE_OBSERVATION'
            run = normalize(doc)[0]
            unit = next(u for u in units(run) if u['kind'] == 'model_span')
            for req in (activity_packet(run, unit['id']),
                        generation_request(run, evidence(run, unit['event_id']), 'orient', POLICY)):
                text = dumps(req)
                self.assertIn('/action_schema', text)
                self.assertIn('/observation_schema', text)
                self.assertNotIn('FUTURE_OBSERVATION', text)
                self.assertNotIn('env-turn:', text)
                self.assertNotIn('PRIVATE_', text)

    def test_schema_describes_encoding_but_does_not_reject_invalid_behavior(self):
        doc = episode(*encoded_domains()[0])
        doc['steps'][0]['action'] = 999  # Invalid action is evidence, not dropped.
        run = normalize(doc)[0]
        self.assertEqual(next(e['text'] for e in run['events'] if e['kind'] == 'action'), '999')
        self.assertIsNone(run['outcome']['verified_success'])
        for invalid in (None, [], 'description', {'minimum': float('nan')}):
            bad = deepcopy(doc); bad['action_schema'] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(InputError):
                normalize(bad)

    def test_json_jsonl_and_store_replay_keep_contracts_and_source_links(self):
        for case in encoded_domains():
            doc = episode(*case)
            expected = normalize(doc)[0]
            for name in ('rollout.json', 'rollout.jsonl'):
                imported = read_bytes(dumps(doc).encode(), name=name, meta={'experiment': 'generalization'})[0]
                self.assertEqual(expected['events'], imported['events'])
            with tempfile.TemporaryDirectory() as temp:
                store = Store(Path(temp) / 'runs.sqlite'); store.add([expected])
                saved = store.get(expected['id'], raw=True)['run']
                self.assertEqual(saved['events'], expected['events'])

    def test_opaque_or_misleading_tool_names_do_not_lose_recorded_meaning(self):
        for name in ('dispatch', 'write_file', 'x73', '查询'):
            doc = conversation()
            doc['tools'][0]['function']['name'] = name
            doc['messages'][1]['tool_calls'][0]['function']['name'] = name
            run = normalize(doc)[0]
            action = next(e for e in run['events'] if e.get('call_id') == 'stock')
            req = macro_packet(run, action['id'])
            self.assertIn('Read available inventory without modifying it.', dumps(req))
            self.assertIn('/tools/0', dumps(req))
            self.assertNotIn('Only 3 units available.', dumps(req))

    def test_compact_context_retains_latest_observation_dispatch_and_parent(self):
        run = normalize(conversation())[0]
        a = next(e for e in run['events'] if e.get('call_id') == 'order')
        ref = evidence(run, a['id'])
        old, _ = prefix(run, ref, {**POLICY, 'schema': 'readable-context/3'})
        self.assertNotIn('Only 3 units available.', dumps(old))
        before = digest(run)
        packet, _ = prefix(run, ref, POLICY)
        self.assertIn('Only 3 units available.', dumps(packet))
        self.assertIn('Read stock first.', dumps(packet))
        self.assertIn('Read available inventory without modifying it.', dumps(packet))
        self.assertIn('Request 4 units.', dumps(packet))
        self.assertNotIn('FUTURE_RESULT', dumps(packet))
        self.assertNotIn('Consider option 0.', dumps(packet))
        result = next(e for e in packet if e['kind'] == 'feedback')
        quote = resolve_quote(run, packet, {'event_id': result['id'], 'quote': 'Only 3 units available.'})
        self.assertTrue(contains(result, quote))
        retained = context_scope(run, ref, POLICY)['context_projection']['retained_dependency_event_ids']
        self.assertIn(result['id'], retained)
        self.assertEqual(before, digest(run))

    def test_reused_ids_cannot_bridge_agents_sessions_or_ambiguous_calls(self):
        for scenario in ('session', 'agent', 'hidden', 'unordered', 'duplicate'):
            run = normalize(conversation())[0]
            action = next(e for e in run['events'] if e.get('call_id') == 'stock')
            current = next(e for e in run['events'] if e.get('call_id') == 'order')
            if scenario == 'session': action['context_id'] = 'other'
            elif scenario == 'agent': action['trajectory_id'] = 'other'
            elif scenario == 'hidden': action['agent_visibility'] = 'not_established'
            elif scenario == 'unordered': action['order_known'] = False
            else:
                clone = deepcopy(action); clone.update(id='duplicate', index=action['index'] + 0.1)
                run['events'].insert(run['events'].index(action) + 1, clone)
            packet, _ = prefix(run, evidence(run, current['id']), POLICY)
            self.assertNotIn(action['id'], [e['id'] for e in packet], scenario)

    def test_activity_does_not_misattribute_other_session_or_private_results(self):
        run = normalize(conversation())[0]
        for e in run['events']:
            if e['text'] in ('Read stock first.', 'Only 3 units available.'):
                e['context_id'] = 'another-session'
        a = next(e for e in run['events'] if e.get('call_id') == 'order')
        u = next(u for u in units(run) if u['event_id'] == a['id'])
        req = activity_packet(run, u['id'])
        self.assertNotIn('Only 3 units available.', dumps(req))
        self.assertNotIn('Read stock first.', dumps(req))

    def test_public_customer_service_traces_keep_exact_feedback_correspondence(self):
        for name in ('airline-0', 'airline-3', 'telecom-0', 'telecom-4'):
            raw = json.loads((Path(__file__).parent / 'fixtures/tau-bench' / (name + '.json')).read_text(encoding='utf-8'))
            run = normalize(raw)[0]
            by_id = {e['id']: e for e in run['events']}
            rows = links(run)['records']
            self.assertTrue(rows)
            for row in rows:
                feedback = by_id[row['feedback_id']]
                req, _ = prefix(run, evidence(run, feedback['id']), POLICY)
                self.assertIn(row['action_id'], [e['id'] for e in req])
                self.assertEqual(feedback['source_call_id'], by_id[row['action_id']]['call_id'])
                self.assertNotIn('reward_info', dumps(req))

    def test_evaluation_exports_requests_without_claiming_model_accuracy(self):
        from scripts.evaluate_environment_reading import evaluate, requests
        rows = list(requests('jev-1.13.0'))
        for row in rows:
            self.assertNotIn('reference', row['request'])
            self.assertNotIn('reference', row['request']['state'])
            self.assertEqual(set(row['request']['questions']), {'mode'})
        descriptions = [r for r in rows if r['case_id'].startswith('opaque-') and r['variant'] == 'described']
        removed = [r for r in rows if r['case_id'].startswith('opaque-') and r['variant'] == 'without_definitions']
        self.assertEqual(len({r['request_hash'] for r in descriptions}), 3)
        self.assertEqual(len({r['reference'] for r in descriptions}), 3)
        # Same visible action, task and expression: the only distinguishing
        # evidence is the supplied operation definition.
        self.assertEqual(len({r['request_hash'] for r in removed}), 1)
        with tempfile.TemporaryDirectory() as tmp:
            report = evaluate(tmp)
            self.assertEqual(report['status'], 'requests_only')
            self.assertTrue(all(g['accuracy'] is None for g in report['groups'].values()))
            self.assertTrue((Path(tmp) / 'requests.json').exists())


if __name__ == '__main__':
    unittest.main()
