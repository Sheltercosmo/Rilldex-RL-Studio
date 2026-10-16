"""Cutoff/version/retrieval contract controls, not semantic annotation gold."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from rilldex import Workspace
from tracker import graph_store, investigation_plans, requested_evidence, requested_graph
from tracker.schema import InputError, digest
from tracker.store import Store
from test_requested_graph import fixture


def sample():
    run, doc, actions = fixture()
    return run, requested_graph.export_graph(run, doc), actions


class RequestedEvidenceTests(TestCase):
    def test_versions_clauses_and_retirement_follow_exact_cutoff(self):
        run, graph, actions = sample(); original = deepcopy(graph)
        first = requested_evidence.review(run, graph, {'anchor': {'event_id': 'e2'}})
        middle = requested_evidence.review(run, graph, {'anchor': {'event_id': 'e5'}})
        final = requested_evidence.review(run, graph, {'anchor': {'event_id': 'e8'}})
        self.assertEqual([q['kind'] for q in first['questions']], ['requirement', 'requested_check', 'attributed_claim'])
        self.assertEqual(len(first['history']), 1)
        self.assertEqual(first['questions'][0]['id'], final['questions'][0]['id'])
        self.assertNotEqual(first['questions'][1]['id'], middle['questions'][1]['id'])
        self.assertEqual(len(final['questions']), 2)
        self.assertEqual([h['lifecycle'] for h in final['history']], ['superseded', 'superseded', 'current'])
        self.assertEqual(final['history'][0]['clauses'][2]['kind'], 'attributed_claim')
        self.assertTrue(all(q['verdict'] == 'not_assessed' for q in final['questions']))
        self.assertEqual(graph, original)

    def test_old_clause_id_cannot_be_searched_as_a_current_requirement(self):
        run, graph, _ = sample()
        old = requested_evidence.review(run, graph, {'anchor': {'event_id': 'e2'}})['questions'][1]['id']
        with self.assertRaisesRegex(InputError, 'unavailable at this cutoff'):
            requested_evidence.review(run, graph, {'anchor': {'event_id': 'e8'}, 'question_ids': [old]})

    def test_originating_request_is_not_independent_evidence(self):
        run, graph, _ = sample()
        # Controlled exact request text: lexical match alone must never verify it.
        rec = min((n for n in graph['nodes'] if n['kind'] == 'requested_work_version'), key=lambda n: n['event_index'])['properties']
        rec['clauses'][0]['text'] = 'Write reports A and B.'
        query = {'anchor': {'event_id': 'e2'}}
        catalog = requested_evidence.review(run, graph, query)
        value = requested_evidence.review(run, graph, {**query, 'question_ids': [catalog['questions'][0]['id']]})
        question = value['questions'][0]
        self.assertEqual(question['retrieval_status'], 'originating_request_only')
        self.assertEqual(question['candidate_event_ids'], [])
        self.assertEqual(question['verdict'], 'not_assessed')
        self.assertEqual(value['coverage']['searched_questions'], 1)
        self.assertEqual(len(value['coverage']['unsearched_question_ids']), 2)
        self.assertLessEqual(value['evidence']['coverage']['source_text_chars'], 16000)

    def test_unknown_revision_blocks_fallback_and_other_sessions_are_excluded(self):
        run, graph, _ = sample()
        run['events'][3]['order_known'] = False
        graph['source_hash'] = digest(run)
        value = requested_evidence.review(run, graph, {'anchor': {'event_id': 'e5'}})
        self.assertEqual(value['questions'], [])
        self.assertEqual(value['coverage']['unresolved_record_ids'], ['conditions'])
        self.assertTrue(value['coverage']['excluded_versions'])
        run, graph, _ = sample()
        run['events'][4]['context_id'] = 'other-session'; graph['source_hash'] = digest(run)
        value = requested_evidence.review(run, graph, {'anchor': {'event_id': 'e5'}})
        self.assertEqual(value['questions'], [])
        self.assertEqual(value['history'], [])

    def test_visibility_copied_and_unknown_anchor_order_do_not_supply_terms(self):
        for field, value in [('copied_context', True), ('agent_visibility', 'not_established'), ('order_known', False)]:
            run, graph, _ = sample(); run['events'][0][field] = value; graph['source_hash'] = digest(run)
            result = requested_evidence.review(run, graph, {'anchor': {'event_id': 'e2'}})
            self.assertFalse(result['questions'], field)
        run, graph, _ = sample(); run['events'][1]['order_known'] = False; graph['source_hash'] = digest(run)
        self.assertFalse(requested_evidence.review(run, graph, {'anchor': {'event_id': 'e2'}})['questions'])

    def test_source_quote_or_source_revision_mismatch_fails(self):
        run, graph, _ = sample()
        with self.assertRaisesRegex(InputError, 'different source revision'):
            requested_evidence.review(dict(run, id='another'), graph, {'anchor': {'event_id': 'e2'}})
        owner = next(n for n in graph['nodes'] if n['kind'] == 'unit' and n['properties'].get('actor') == 'user')
        owner['properties']['source']['text'] = 'Invented'
        with self.assertRaisesRegex(InputError, 'Evidence mismatch'):
            requested_evidence.review(run, graph, {'anchor': {'event_id': 'e2'}})

    def test_unannotated_source_is_an_empty_catalog_not_satisfied_work(self):
        run, _, _ = sample(); graph = graph_store.build(run)
        value = requested_evidence.review(run, graph, {'anchor': {'event_id': 'e8'}})
        self.assertFalse(value['coverage']['recorded_terms_available'])
        self.assertIsNone(value['evidence'])
        self.assertEqual(value['questions'], [])

    def test_candidate_record_filter_is_explicit_and_bound_to_continuation(self):
        run, graph, _ = sample(); query = dict(anchor={'event_id': 'e8'}, limit=1)
        current = max((n for n in graph['nodes'] if n['kind'] == 'requested_work_version'), key=lambda n: n['event_index'])['properties']
        current['clauses'][1]['text'] = 'Read Write'
        catalog = requested_evidence.review(run, graph, query)
        query.update(question_ids=[catalog['questions'][1]['id']], source_types=['action', 'feedback'])
        result = requested_evidence.review(run, graph, query)
        events = {e['id']: e for e in run['events']}
        self.assertTrue(all(events[m['event_id']]['kind'] in {'action', 'feedback'} for m in result['evidence']['matches']))
        cursor = result['evidence']['pagination']['next_cursor']
        self.assertIsNotNone(cursor)
        following = requested_evidence.review(run, graph, {**query, 'cursor': cursor})
        self.assertNotEqual(result['evidence']['matches'], following['evidence']['matches'])
        with self.assertRaisesRegex(InputError, 'changed'):
            requested_evidence.review(run, graph, {**query, 'source_types': ['prose'], 'cursor': cursor})
        with self.assertRaises(InputError):
            requested_evidence.validate({**query, 'source_types': []})

    def test_question_budget_and_validation_do_not_silently_drop_terms(self):
        for ids in [['x'] * 2, ['x'+str(i) for i in range(9)], 'x', [1]]:
            with self.assertRaises(InputError):
                requested_evidence.validate({'anchor': {'event_id': 'e2'}, 'question_ids': ids})
        run, graph, _ = sample()
        rec = min((n for n in graph['nodes'] if n['kind'] == 'requested_work_version'), key=lambda n: n['event_index'])['properties']
        rec['clauses'][0]['text'] = 'x' * 2001
        cat = requested_evidence.review(run, graph, {'anchor': {'event_id': 'e2'}})
        self.assertEqual(len(cat['questions']), 3)
        with self.assertRaisesRegex(InputError, '1–2000'):
            requested_evidence.review(run, graph, {'anchor': {'event_id': 'e2'}, 'question_ids': [cat['questions'][0]['id']]})

    def test_missing_clauses_and_withdrawal_are_visible_not_completed_conditions(self):
        run, graph, _ = sample()
        current = max((n for n in graph['nodes'] if n['kind'] == 'requested_work_version'), key=lambda n: n['event_index'])['properties']
        current.pop('clauses')
        value = requested_evidence.review(run, graph, {'anchor': {'event_id': 'e8'}})
        self.assertFalse(value['questions'])
        self.assertEqual(value['coverage']['missing_prerequisites'][0]['reason'], 'condition_has_no_saved_clauses')
        current['status'] = 'withdrawn'
        value = requested_evidence.review(run, graph, {'anchor': {'event_id': 'e8'}})
        self.assertEqual(value['history'][-1]['lifecycle'], 'withdrawn')
        self.assertFalse(value['questions'])

    def test_future_versions_do_not_change_a_past_review(self):
        run, graph, _ = sample(); query = dict(anchor={'event_id': 'e2'})
        before = requested_evidence.review(run, graph, query)
        for n in graph['nodes']:
            if n['kind'] == 'requested_work_version' and n['event_index'] > 1:
                n['properties']['text'] = 'Changed future request'
                n['properties']['clauses'] = []
        after = requested_evidence.review(run, graph, query)
        self.assertEqual(before, after)

    def test_sdk_registry_reuse_and_source_graph_immutability(self):
        run, graph, _ = sample()
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'study.sqlite'); store.add([run])
            with store.connect() as c: graph_store.save(c, graph)
            stored_graph = graph_store.read(store, graph['id'])
            workspace = Workspace(store.path)
            options = dict(anchor={'event_id': 'e8'})
            expected = workspace.review_conditions(run['id'], graph['id'], **options)
            ids = [q['id'] for q in expected['questions']]
            local = workspace.review_conditions(run['id'], graph['id'], **options, question_ids=ids)
            plan = {'schema': 'investigation-plan/1', 'nodes': [{'name': 'review', 'op': 'requested_evidence', 'inputs': [],
                'params': {'run_id': run['id'], 'source_hash': digest(run), 'graph_id': graph['id'],
                           'query': {**options, 'question_ids': ids}}}]}
            first = investigation_plans.execute(store, plan); second = investigation_plans.execute(store, plan)
            self.assertEqual(first['id'], second['id'])
            self.assertEqual(first['outputs'], second['outputs'])
            self.assertEqual(first['outputs']['review'], local)
            self.assertEqual(investigation_plans.read_output(store, local['id']), local)
            self.assertEqual(graph_store.read(store, graph['id']), stored_graph)
            with self.assertRaises(InputError):
                Workspace(store.path, experiment='unrelated').review_conditions(run['id'], graph['id'], **options)
