"""Recorded multi-agent conversations, reused IDs and changed tool meanings."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rilldex import chat_sessions_document, Outbox
from tracker.activity import units, packet, analyze
from tracker.activity_context import visible_prefix, audit
from tracker.adapters import detect, normalize
from tracker.capabilities import links, recorded_scope
from tracker.context_mix import scan, pointer
from tracker.graph_store import build
from tracker.import_batch import read_bytes
from tracker.jev import packet as macro_packet
from tracker.schema import InputError, dumps
from tracker.semantic_extraction import prefix, context_scope, checked_span, episode_scope, windows
from tracker.semantic_map import evidence
from tracker.semantic_workspace import DEFAULT_CONTEXT
from tracker.environment_contracts import reading_context
from tracker.store import Store
from tracker import unit_graph


def conversation(agent, context, marker, description):
    return {'trajectory_id': agent, 'context_id': context,
            'tools': [{'type': 'function', 'function': {'name': 'dispatch', 'description': description,
                       'parameters': {'type': 'object'}}}],
            'messages': [{'role': 'user', 'content': 'Task ' + marker},
                         {'role': 'assistant', 'content': 'Attempt ' + marker,
                          'reasoning_content': 'Recorded thought ' + marker,
                          'tool_calls': [{'id': 'local-0', 'type': 'function',
                                          'function': {'name': 'dispatch', 'arguments': '{"record":"A7"}'}}]},
                         {'role': 'tool', 'tool_call_id': 'local-0', 'content': 'Result ' + marker},
                         {'role': 'assistant', 'content': 'Review ' + marker}]}


def captured():
    a = conversation('researcher', 'attempt-1', 'ONLY_A', 'Read inventory without changing it.')
    b = {'trajectory_id': 'verifier', 'context_id': 'attempt-1', 'system': 'Verifier rules ONLY_B',
         'tools': [{'name': 'dispatch', 'description': 'Validate the inventory against the recorded constraint.',
                    'input_schema': {'type': 'object'}}],
         'messages': [{'role': 'user', 'content': 'Check inventory ONLY_B'},
                      {'role': 'assistant', 'content': [
                          {'type': 'thinking', 'thinking': 'Recorded thought ONLY_B'},
                          {'type': 'text', 'text': 'Check two items ONLY_B'},
                          {'type': 'tool_use', 'id': 'local-0', 'name': 'dispatch', 'input': {'record': 'A7'}},
                          {'type': 'tool_use', 'id': 'local-1', 'name': 'dispatch', 'input': {'record': 'A8'}}]},
                      {'role': 'user', 'content': [
                          {'type': 'tool_result', 'tool_use_id': 'local-1', 'content': 'A8 passed ONLY_B'},
                          {'type': 'tool_result', 'tool_use_id': 'local-0', 'content': 'A7 failed ONLY_B', 'is_error': True}]},
                      {'role': 'assistant', 'content': 'Review results ONLY_B'}]}
    c = conversation('researcher', 'attempt-2', 'ONLY_C', 'Change the reservation quantity.')
    return chat_sessions_document([a, b, c], metadata={'experiment': 'multi-agent-controls', 'task_id': 'inventory-7'}, reward=0.5)


class ChatSessionTests(unittest.TestCase):
    def test_native_message_readers_keep_local_ids_roles_and_exact_pointers(self):
        doc = captured(); run = normalize(doc)[0]
        self.assertEqual(detect(doc), 'chat-messages')
        self.assertEqual(run['adapter_version'], 'chat-messages/2')
        self.assertEqual(run, normalize(doc, 'chat-messages')[0])
        self.assertEqual(len({e['id'] for e in run['events']}), len(run['events']))
        self.assertEqual([e['index'] for e in run['events']], list(range(len(run['events']))))
        linked = links(run)
        self.assertEqual(len(linked['records']), 4)
        by_id = {e['id']:e for e in run['events']}
        for e in run['events']:
            raw = pointer(doc, e['source_pointer'])
            if e['kind'] != 'action':self.assertEqual(e['text'], raw)
            if e.get('parent_id'):
                self.assertEqual(recorded_scope(e), recorded_scope(by_id[e['parent_id']]))
            if e.get('tool_contract'):
                self.assertEqual(pointer(doc, e['tool_contract']['source_pointer']), e['tool_contract']['definition'])
        for row in linked['records']:
            a, f = by_id[row['action_id']], by_id[row['feedback_id']]
            self.assertEqual(recorded_scope(a), recorded_scope(f))
            self.assertEqual(a['call_id'], f['source_call_id'])
        verifier = [e for e in run['events'] if e['kind'] == 'action' and e['trajectory_id'] == 'verifier']
        self.assertEqual(linked['by_action'][verifier[0]['id']][0]['text'], 'A7 failed ONLY_B')
        self.assertEqual(linked['by_action'][verifier[1]['id']][0]['text'], 'A8 passed ONLY_B')
        self.assertEqual(len(linked['parallel_action_groups']), 1)

    def test_every_interpreter_keeps_other_agents_and_previous_contexts_out(self):
        run = normalize(captured())[0]
        by_id = {e['id']:e for e in run['events']}
        for u in units(run):
            current = by_id[u['event_id']]
            marker = {'/sessions/0/': 'ONLY_A', '/sessions/1/': 'ONLY_B', '/sessions/2/': 'ONLY_C'}
            own = next(v for k,v in marker.items() if current['source_pointer'].startswith(k))
            requests = [packet(run, u['id']), unit_graph.packet(run, u['id'])]
            for policy in (None, DEFAULT_CONTEXT, {**DEFAULT_CONTEXT, 'schema': 'readable-context/2'}):
                requests.append(prefix(run, evidence(run, u['event_id'], start=u['start'], end=u['end']), policy)[0])
            if current['kind'] == 'action':requests.append(macro_packet(run, current['id']))
            for request in requests:
                text = dumps(request)
                for other in set(marker.values()) - {own}:self.assertNotIn(other, text)
            coverage = audit(visible_prefix(run, u), requests[0]['state'], u)
            self.assertEqual(coverage['status'], 'audited')

    def test_source_and_unit_graph_edges_do_not_imply_cross_context_order(self):
        run = normalize(captured())[0]
        events = {e['id']: e for e in run['events']}
        graph = build(run)
        for edge in graph['edges']:
            if edge['type'] in {'next_record', 'response_to'}:
                a, b = (events[edge[k].removeprefix('event:')] for k in ('source','target'))
                self.assertEqual(recorded_scope(a), recorded_scope(b))
        graph = unit_graph.build(run, analyze(run))
        nodes = {u['id']:u for u in graph['nodes']}
        for edge in graph['edges']:
            self.assertEqual(recorded_scope(nodes[edge['source']]), recorded_scope(nodes[edge['target']]))
        self.assertEqual(sum(e['type'] == 'result_of' for e in graph['edges']), 4)

    def test_context_inspector_uses_only_selected_sessions_tool_definitions(self):
        run = normalize(captured())[0]
        for e in run['events']:
            if e['kind'] != 'action':continue
            result = scan(run, e['id'])
            content = dumps(result)
            definition = e['tool_contract']['definition']
            own = definition.get('description', definition.get('function', {}).get('description'))
            self.assertIn(own, content)
            for description in ('Read inventory without changing it.', 'Validate the inventory against the recorded constraint.', 'Change the reservation quantity.'):
                if description != own:self.assertNotIn(description, content)

    def test_tool_meaning_is_available_before_dispatch_in_its_own_context(self):
        run = normalize(captured())[0]
        for marker, meaning in [('ONLY_A', 'Read inventory without changing it.'),
                                ('ONLY_B', 'Validate the inventory against the recorded constraint.'),
                                ('ONLY_C', 'Change the reservation quantity.')]:
            current = next(e for e in run['events'] if e['kind'] == 'message' and marker in e['text'])
            u = next(u for u in units(run) if u['event_id'] == current['id'])
            for request in (packet(run, u['id']), context_scope(run, evidence(run, current['id']), DEFAULT_CONTEXT)):
                text = dumps(request)
                self.assertIn(meaning, text)
                for other in {'ONLY_A','ONLY_B','ONLY_C'} - {marker}:self.assertNotIn(other, text)
                self.assertNotIn('Result ' + marker, text)
            catalog = reading_context(run, current)['tool_catalog']
            for definition in catalog['definitions']:
                self.assertEqual(json.loads(definition['definition_text']), pointer(run['raw'], definition['source_pointer']))

    def test_large_tool_catalog_is_bounded_without_changing_source(self):
        doc = captured()
        doc['sessions'][0]['tools'] = [{'type':'function','function':{
            'name':f'tool_{i}', 'description':'x' * 12000, 'parameters':{'type':'object'}}} for i in range(5)]
        run = normalize(doc)[0]
        before = dumps(run)
        current = run['events'][0]
        catalog = reading_context(run, current)['tool_catalog']
        self.assertEqual(sum(len(d['definition_text']) for d in catalog['definitions']), 24000)
        self.assertEqual(catalog['omitted_definition_count'], 2)
        self.assertEqual(len(catalog['truncated_definition_ids']), 3)
        self.assertEqual(before, dumps(run))

    def test_unmatched_result_does_not_attach_to_another_contexts_same_id(self):
        doc = captured()
        doc['sessions'].append({'trajectory_id': 'researcher', 'context_id': 'attempt-3', 'messages': [
            {'role': 'tool', 'tool_call_id': 'local-0', 'content': 'Orphan result'},
            {'role': 'assistant', 'content': 'Inspect the orphan.'}]})
        run = normalize(doc)[0]
        orphan = next(e for e in run['events'] if e['text'] == 'Orphan result')
        self.assertIn(orphan['id'], links(run)['unlinked_ids'])
        graph = unit_graph.build(run, analyze(run))
        orphan_ids = {u['id'] for u in graph['nodes'] if u['event_id'] == orphan['id']}
        self.assertFalse(any(e['type'] == 'result_of' and e['target'] in orphan_ids for e in graph['edges']))

    def test_invalid_scopes_and_duplicate_local_calls_fail_without_flattening(self):
        for invalid in ('missing', 'empty', 'duplicate-session', 'duplicate-call', 'root-messages'):
            doc = captured()
            if invalid == 'missing':doc['sessions'][0].pop('context_id')
            elif invalid == 'empty':doc['sessions'][0]['trajectory_id'] = ' '
            elif invalid == 'duplicate-session':doc['sessions'].append(deepcopy(doc['sessions'][0]))
            elif invalid == 'duplicate-call':doc['sessions'][0]['messages'].append(deepcopy(doc['sessions'][0]['messages'][1]))
            else:doc['messages'] = [{'role':'assistant','content':'Ambiguous global history'}]
            with self.subTest(invalid=invalid), self.assertRaises(InputError):normalize(doc)

    def test_citations_and_episode_boundaries_cannot_cross_a_reset(self):
        run = normalize(captured())[0]
        a = next(e for e in run['events'] if e['text'] == 'Attempt ONLY_A')
        c = next(e for e in run['events'] if e['text'] == 'Attempt ONLY_C')
        with self.assertRaisesRegex(InputError, 'context'):
            checked_span(run, evidence(run, a['id']), evidence(run, c['id']))
        with self.assertRaisesRegex(InputError, 'context'):
            episode_scope(run, a['id'], c['id'])

    def test_file_import_and_revision_delivery_retain_scopes_and_graphs(self):
        doc = captured(); expected = normalize(doc)[0]
        for filename in ('sessions.json', 'sessions.jsonl'):
            result = read_bytes(dumps(doc).encode(), name=filename, meta={'experiment':'multi-agent-controls'})[0]
            self.assertEqual(result['events'], expected['events'])
            self.assertEqual(build(result)['edges'], build(expected)['edges'])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); store = Store(root/'capture.sqlite')
            outbox = Outbox(root/'outbox.sqlite', producer='multi-agent-test')
            outbox.log('sample-1', doc, state='in_progress')
            doc['sessions'][2]['messages'].append({'role':'assistant','content':'All recorded work finished.'})
            outbox.log('sample-1', doc, state='complete')
            def receive(request, **kwargs):
                return io.BytesIO(json.dumps(store.ingest(json.loads(request.data))).encode())
            with patch('tracker.capture.urlopen', side_effect=receive):
                self.assertEqual(outbox.drain()['sent_now'], 2)
            result = store.get(store.list()[0]['id'], raw=True)['run']
            self.assertEqual(result['events'], normalize(doc)[0]['events'])
            self.assertEqual(len(links(result)['records']), 4)

    def test_episode_ignores_interleaved_context_but_reads_explicit_handoff(self):
        doc = captured()
        # The receiving agent sees the supplied handoff, not the sender's history.
        doc['sessions'][2]['messages'].insert(0, {'role':'user', 'content':'Handoff: A7 failed the inventory check.'})
        run = normalize(doc)[0]
        first = next(e for e in run['events'] if e['text'] == 'Attempt ONLY_C')
        last = next(e for e in run['events'] if e['text'] == 'Review ONLY_C')
        other = next(e for e in run['events'] if e['text'] == 'Attempt ONLY_A')
        run['events'].remove(other)
        run['events'].insert(run['events'].index(last), other)
        for i,e in enumerate(run['events']):e['index'] = i
        result = episode_scope(run, first['id'], last['id'])
        self.assertEqual(result['context_id'], 'attempt-2')
        selected = [w for w in windows(run) if w['id'] in result['window_ids']]
        self.assertTrue(selected)
        self.assertNotIn(other['id'], {w['event_id'] for w in selected})
        reading, _ = prefix(run, evidence(run, last['id']), DEFAULT_CONTEXT)
        self.assertIn('Handoff: A7 failed the inventory check.', dumps(reading))
        self.assertNotIn('ONLY_A', dumps(reading))


if __name__ == '__main__':unittest.main()
