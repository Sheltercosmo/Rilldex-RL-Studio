"""Representation/review controls; authored examples are not accuracy evidence."""
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path

from tracker import graph_store, work_subjects as ws, work_navigation, investigation_plans as plans
from tracker.adapters import normalize
from tracker.portable import chat_document, generation_document
from tracker.schema import digest, InputError
from tracker.store import Store


def fixture(texts=('Find the roots.', 'Check the sign.', 'Return to the roots.'), *, one_event=False, tools=False):
    if one_event:
        run = normalize(generation_document('Solve the problem.', '\n'.join(texts)))[0]
    else:
        messages = [{'role': 'user', 'content': 'Solve the problem.'}]
        for i, text in enumerate(texts):
            messages.append({'role': 'assistant', 'content': text})
            if tools and i == 0:
                messages[-1]['tool_calls'] = [{'id': 'call', 'type': 'function', 'function': {'name': 'calculate', 'arguments': '{}'}}]
                messages.append({'role': 'tool', 'tool_call_id': 'call', 'content': 'Two roots.'})
        run = normalize(chat_document(messages))[0]
    units = []
    for e in run['events']:
        if e.get('actor') != 'agent' or not e['text'].strip(): continue
        parts = texts if one_event else [e['text']]
        cursor = 0
        for text in parts:
            a = e['text'].index(text, cursor); b = a+len(text); cursor = b
            units.append(dict(id='unit-'+str(len(units)), actor='agent', kind='action' if e['kind']=='action' else 'semantic',
                status='selected', activity='execute' if e['kind']=='action' else 'reason',
                source=dict(event_id=e['id'], start=a, end=b, text=text, source_pointer=e['source_pointer'])))
    g = graph_store.build(run, dict(observer=dict(id='authored-units', label='Authored units'),
        document=dict(schema='semantic-unit-map/1', source_hash=digest(run), units=units, relations=[])))
    return run, g, units


def binding(uid, sid, *, status=None):
    return dict(unit_id=uid, status=status or ('bound' if sid else 'unresolved'), subject_id=sid,
        note='Authored representation control.', provenance=dict(kind='review', author='test-author', protocol='authored-control/1'))


def annotation(g, units, names=('A', 'B', 'A')):
    d = ws.template(g)['document']; origins = {}
    for u, sid in zip(units, names):
        if sid and sid not in origins:
            origins[sid] = u['id']; d['subjects'].append(dict(id=sid, label='Target '+sid, origin_unit_id=u['id']))
        d['bindings'].append(binding(u['id'], sid))
    return d


class WorkSubjectTests(unittest.TestCase):
    def test_reasoning_only_recurs_inside_one_generation(self):
        _, g, units = fixture(one_event=True); d = annotation(g, units); before = deepcopy(g)
        derived = ws.fork(g, d); out = work_navigation.project(derived)
        self.assertEqual(g, before); graph_store.validate(derived)
        self.assertEqual(out['axis'], 'contributions'); self.assertEqual(out['counts']['returned'], 1)
        self.assertEqual(out['counts']['bound'], 3); self.assertEqual(out['counts']['source_gaps'], 0)
        self.assertNotIn('recorded_actions', out['counts'])
        ep = out['episodes'][0]; edges = {e['id']: e for e in derived['edges']}
        self.assertEqual({edges[e]['type'] for e in ep['edge_ids']}, {'about_work_subject'})
        self.assertEqual({c['unit_id'] for c in ep['cards']}, {units[0]['id'], units[2]['id']})

    def test_tools_and_semantic_units_share_work_without_becoming_same_activity(self):
        _, g, units = fixture(tools=True); d = annotation(g, units, ('A', 'A', 'B', 'A'))
        derived = ws.fork(g, d); out = ws.project(derived)
        self.assertEqual(out['visits'][0]['unit_ids'], [units[0]['id'], units[1]['id']])
        self.assertEqual([p['activity'] for p in out['visits'][0]['occurrences']], ['reason', 'execute'])
        self.assertEqual(out['counts']['returned'], 1)

    def test_same_label_is_not_same_subject(self):
        _, g, units = fixture(('Same text.', 'Same text.')); d = annotation(g, units, ('A', 'B'))
        d['subjects'][1]['label'] = d['subjects'][0]['label']
        out = ws.project(ws.fork(g, d)); self.assertEqual(out['episodes'], [])
        self.assertEqual(len(out['visits']), 2)

    def test_gap_unreviewed_and_unresolved_each_interrupt_return(self):
        for mode in ('gap', 'unreviewed', 'unresolved'):
            with self.subTest(mode=mode):
                _, g, units = fixture(); d = annotation(g, units, ('A', None, 'A'))
                if mode != 'unresolved': d['bindings'].pop(1)
                if mode == 'gap':
                    g['nodes'] = [n for n in g['nodes'] if n['id'] != units[1]['id']]
                    g['edges'] = [e for e in g['edges'] if e['source'] != units[1]['id']]
                    g.pop('id'); g['id'] = 'graph-'+digest(g); d['base_graph_id'] = g['id']
                out = ws.project(ws.fork(g, d)); self.assertEqual(out['episodes'][0]['category'], 'interrupted')
                self.assertEqual(len(out['visits']), 3)

    def test_not_applicable_is_separate_from_unresolved_or_new_work(self):
        _, g, units = fixture(); d = annotation(g, units, ('A', None, 'A'))
        d['bindings'][1]['status'] = 'not_applicable'
        out = ws.project(ws.fork(g, d)); self.assertEqual(out['episodes'][0]['category'], 'resumed')
        self.assertEqual(out['counts']['returned'], 0)

    def test_whitespace_does_not_become_empty_card(self):
        _, g, units = fixture(('Find the roots.  ', '\n\t', 'Return to the roots.'))
        out = ws.project(ws.fork(g, annotation(g, units, ('A', 'A'))))
        self.assertEqual(out['counts']['contributions'], 2); self.assertEqual(out['counts']['source_gaps'], 0)
        self.assertEqual(out['counts']['continued'], 1)

    def test_rejects_duplicate_binding_future_origin_and_missing_origin_membership(self):
        _, g, units = fixture(one_event=True)
        for mode in ('duplicate', 'future', 'missing_origin', 'wrong_base'):
            d = annotation(g, units)
            if mode == 'duplicate': d['bindings'].append(deepcopy(d['bindings'][0]))
            elif mode == 'future': d['subjects'][0]['origin_unit_id'] = units[-1]['id']
            elif mode == 'missing_origin': d['bindings'][0] = binding(units[0]['id'], None)
            else: d['base_graph_id'] = 'wrong'
            with self.subTest(mode=mode), self.assertRaises(InputError): ws.fork(g, d)

    def test_rejects_cross_trajectory_or_context_without_handoff(self):
        for field in ('trajectory_id', 'context_id'):
            _, g, units = fixture()
            e = next(n['properties'] for n in g['nodes'] if n['kind']=='event' and n['properties']['id']==units[-1]['source']['event_id'])
            e[field] = 'other'; g.pop('id'); g['id']='graph-'+digest(g)
            with self.subTest(field=field), self.assertRaisesRegex(InputError, 'actor/context'):
                ws.fork(g, annotation(g, units))

    def test_overlap_and_private_source_are_not_reviewable(self):
        _, g, units = fixture(); duplicate = deepcopy(next(n for n in g['nodes'] if n['id']==units[0]['id']))
        duplicate['id'] = 'overlap'; g['nodes'].append(duplicate)
        data = ws.template(g); self.assertNotIn(units[0]['id'], [u['id'] for u in data['units']])
        self.assertTrue(data['issues'])
        e = next(n['properties'] for n in g['nodes'] if n['kind']=='event' and n['properties']['id']==units[-1]['source']['event_id'])
        e['agent_visibility'] = 'not_established'
        self.assertNotIn(units[-1]['id'], [u['id'] for u in ws.template(g)['units']])

    def test_parallel_dispatches_do_not_collapse(self):
        _, g, units = fixture(tools=True)
        e = next(n['properties'] for n in g['nodes'] if n['kind']=='event' and n['properties']['id']==units[1]['source']['event_id'])
        e['batch_size'] = 2; g.pop('id'); g['id']='graph-'+digest(g)
        out = ws.project(ws.fork(g, annotation(g, units, ('A', 'A', 'B', 'A'))))
        self.assertNotEqual(out['visits'][0]['id'], out['visits'][1]['id'])
        self.assertEqual(out['episodes'][0]['category'], 'interrupted')

    def test_revision_preserves_old_graph_and_changes_cached_result(self):
        run, g, units = fixture(); derived = ws.fork(g, annotation(g, units)); frozen = deepcopy(derived)
        d = ws.template(derived)['document']; d['subjects'][0]['label'] = 'Corrected natural-language target'
        newer = ws.fork(derived, d)
        self.assertEqual(derived, frozen); self.assertNotEqual(newer['id'], derived['id'])
        self.assertEqual(newer['observer'], derived['observer'])
        self.assertEqual(sum(n['kind']=='work_subject' for n in newer['nodes']), 2)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'test.sqlite'); store.add([run])
            with store.connect() as c:
                for value in (g, derived, newer): graph_store.save(c, value)
                c.execute("UPDATE rollout_graphs SET created_at='2026-10-11T00:00:00+00:00'")
            latest = next(v for v in graph_store.catalog(store)['graphs'] if v['observer']==newer['observer'])
            self.assertEqual(latest['id'], newer['id'])
            def plan(value):
                return dict(schema=plans.VERSION, nodes=[dict(name='route', op='work_navigation', inputs=[],
                    params=dict(run_id=run['id'], source_hash=digest(run), graph_id=value['id']))])
            first = plans.execute(store, plan(derived)); again = plans.execute(store, plan(derived))
            second = plans.execute(store, plan(newer))
            self.assertEqual(again['execution']['cache_hits'], 1)
            self.assertEqual(first['outputs'], again['outputs']); self.assertNotEqual(first['outputs'], second['outputs'])
            self.assertEqual(plans.preflight(store, plan(newer))['nodes'][0]['missing_evidence'], [])
            self.assertEqual(second['execution']['inference_calls'], 0)
            result = ws.receive(store, ws.template(newer)['document'])
            self.assertEqual(result['base_graph_id'], newer['id'])

    def test_provenance_cannot_impersonate_jev_or_a_confidence_gate(self):
        _, g, units = fixture(); d = annotation(g, units)
        d['bindings'][0]['provenance']['kind'] = 'jev_selection'
        with self.assertRaisesRegex(InputError, 'not a Jev'): ws.fork(g, d)
        d = annotation(g, units); d['bindings'][0]['confidence'] = .99
        with self.assertRaises(InputError): ws.fork(g, d)

    def test_retry_is_idempotent_and_stale_edit_cannot_overwrite_review(self):
        run, g, units = fixture(); d = annotation(g, units)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'test.sqlite'); store.add([run])
            with store.connect() as c: graph_store.save(c, g)
            first = ws.receive(store, d); self.assertEqual(ws.receive(store, d), first)
            d['subjects'][0]['label'] = 'Stale edit'
            with self.assertRaisesRegex(InputError, 'changed since'): ws.receive(store, d)
            saved = graph_store.read(store, first['graph_id'])
            revised = ws.template(saved)['document']; revised['subjects'][0]['label'] = 'Current edit'
            second = ws.receive(store, revised); self.assertNotEqual(second['graph_id'], first['graph_id'])
            self.assertEqual(ws.receive(store, revised), second)
            self.assertEqual(graph_store.read(store, first['graph_id']), saved)

    def test_missing_or_inconsistent_edges_do_not_create_return(self):
        _, g, units = fixture(); saved = ws.fork(g, annotation(g, units))
        for mode in ('missing', 'mismatch'):
            bad = deepcopy(saved); e = next(e for e in bad['edges'] if e['type']=='about_work_subject')
            if mode == 'missing': bad['edges'].remove(e)
            else: e['target'] = 'fiction'
            with self.subTest(mode=mode), self.assertRaisesRegex(InputError, 'binding edge'): ws.project(bad)


if __name__ == '__main__': unittest.main()
