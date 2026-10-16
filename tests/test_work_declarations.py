from copy import deepcopy
import unittest
from unittest.mock import patch

from tracker.adapters import normalize
from tracker.schema import InputError, digest
from tracker.semantic_map import evidence
from tracker.work_declarations import build, make_request, STAGED_VERSION


def fixture(texts, targets=None):
    run = normalize({'trajectory_format': 'devai/1', 'trajectory': [
        {'step': i, 'agent': {'thought': text, 'action': 'DO_NOT_USE_FUTURE_DISPATCH_' + str(i)},
         'environment': 'DO_NOT_USE_FUTURE_RESULT_' + str(i)} for i, text in enumerate(texts)]})[0]
    units = []
    for i, event in enumerate(e for e in run['events'] if e['kind'] == 'reasoning'):
        ref = evidence(run, event['id'])
        units.append({'id': 'u' + str(i), 'actor': 'agent', 'kind': 'semantic', 'activity': 'orient',
                      'trajectory_id': event['trajectory_id'], 'source': ref,
                      'content': {'summary': {'text': event['text'], 'evidence': [ref]},
                                  'target': {'text': targets[i] if targets else 'Produce report A.', 'evidence': [ref]}}})
    return run, {'source_hash': digest(run), 'units': units, 'relations': []}


def choices(declarations, identities=None, captured=None):
    identities = iter(identities or [])
    def decide(req):
        if captured is not None:
            captured.append(req)
        if req['state']['stage'] == 'work_declaration':
            value = declarations[int(req['state']['unit_id'][1:])]
        else:
            value = next(identities, 'same')
            if value == 'same':
                value = req['state']['prior_work_records'][0]['id']
        return {'choice': {'value': value}}, digest(req)
    return decide


class WorkDeclarationTests(unittest.TestCase):
    def test_declarations_link_without_computing_active_or_verified_status(self):
        run, doc = fixture(['I could produce report A.', 'I will produce report A.',
                            'I will set report A aside for now.', 'I will resume report A.', 'Report A is complete.'])
        original = deepcopy(doc)
        result = build(run, doc, choices(['proposes', 'commits', 'defers', 'commits', 'reports_finished']))
        self.assertEqual(doc, original)
        record, = result['records']
        self.assertEqual([d['declaration'] for d in record['declarations']], ['proposes', 'commits', 'defers', 'commits', 'reports_finished'])
        self.assertEqual([d['previous_unit_id'] for d in record['declarations']], [None, 'u0', 'u1', 'u2', 'u3'])
        self.assertEqual(record['prior_state'], 'not_established')
        self.assertNotIn('active', record)
        self.assertNotIn('completed', record)
        self.assertEqual(result['counts']['records_with_history'], 1)

    def test_first_completion_report_does_not_invent_prior_commitment(self):
        run, doc = fixture(['Report A is complete.'])
        result = build(run, doc, choices(['reports_finished']))
        self.assertEqual(len(result['records'][0]['declarations']), 1)
        self.assertIsNone(result['records'][0]['declarations'][0]['previous_unit_id'])

    def test_prose_with_no_declaration_does_not_withdraw_old_work(self):
        run, doc = fixture(['I will produce report A.', 'Package P requires installation.', 'Please choose whether to produce report A.'])
        result = build(run, doc, choices(['commits', 'no_declaration', 'proposes']))
        self.assertEqual([r['unit_id'] for r in result['records'][0]['declarations']], ['u0', 'u2'])
        self.assertFalse(any(d['declaration'] == 'withdraws' for r in result['records'] for d in r['declarations']))

    def test_unresolved_and_multiple_identity_do_not_mutate_earlier_record(self):
        run, doc = fixture(['I will produce A.', 'A and B are done.', 'I will resume it.'])
        result = build(run, doc, choices(['commits', 'reports_finished', 'commits'], ['multiple_records', 'unresolved']))
        self.assertEqual([r['status'] for r in result['observations']], ['linked', 'needs_membership', 'unresolved_identity'])
        self.assertEqual(len(result['records'][0]['declarations']), 1)

    def test_missing_target_and_retrieval_limit_remain_uninspected(self):
        run, doc = fixture(['I will produce A.', 'I will produce B.', 'I will produce C.'], ['A', 'B', 'C'])
        with patch('tracker.work_declarations.LIMIT', 0):
            result = build(run, doc, choices(['commits'] * 3))
        self.assertEqual([r['status'] for r in result['observations']], ['linked', 'needs_record_retrieval', 'needs_record_retrieval'])
        doc['units'][0]['content'].pop('target')
        result = build(run, doc, choices(['commits'] * 3))
        self.assertEqual(result['observations'][0]['status'], 'missing_local_target')

    def test_requests_preserve_cutoffs_and_never_use_future_dispatch_or_result(self):
        run, doc = fixture(['I will produce A.', 'A is done.'])
        captured = []
        build(run, doc, choices(['commits', 'reports_finished'], captured=captured))
        for req in captured:
            index = int(req['state']['unit_id'][1:])
            self.assertNotIn('DO_NOT_USE_FUTURE_DISPATCH_' + str(index), str(req))
            self.assertNotIn('DO_NOT_USE_FUTURE_RESULT_' + str(index), str(req))
        bad = deepcopy(doc['units'][0])
        bad['content']['target']['evidence'] = [doc['units'][1]['source']]
        with self.assertRaises(InputError):
            make_request(run, doc, bad)

    def test_other_actor_and_trajectory_do_not_supply_identity_candidates(self):
        run, doc = fixture(['I will produce A.', 'I will produce A.'])
        doc['units'][0]['trajectory_id'] = 'other'
        next(e for e in run['events'] if e['id'] == doc['units'][0]['source']['event_id'])['trajectory_id'] = 'other'
        doc['source_hash'] = digest(run)
        captured = []
        result = build(run, doc, choices(['commits', 'commits'], captured=captured))
        self.assertEqual(len(result['records']), 2)
        self.assertEqual(len(captured), 2)

    def test_source_hash_and_choice_integrity(self):
        run, doc = fixture(['I will produce A.'])
        with self.assertRaises(InputError):
            build(run, {**doc, 'source_hash': 'wrong'}, choices(['commits']))
        with self.assertRaises(InputError):
            build(run, doc, choices(['verified_success']))

    def test_staged_target_rejection_prevents_a_completion_on_the_wrong_work(self):
        run, doc = fixture(['Report A is complete.'], ['Communicate the status of report A.'])
        calls = []
        def decide(req):
            calls.append(req)
            return {'choice': {'value': 'needs_work_target'}}, digest(req)
        result = build(run, doc, decide, version=STAGED_VERSION)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['records'], [])
        self.assertEqual(result['observations'][0]['status'], 'needs_work_target')
        self.assertEqual(result['counts']['declaration_decisions'], 0)

    def test_scope_gate_keeps_subset_separate_and_records_the_relation(self):
        run, doc = fixture(['I will check temperature and pressure.', 'I will check pressure.'], ['Check temperature and pressure.', 'Check pressure.'])
        def decide(req):
            stage = req['state']['stage']
            choice = {'declaration_target_suitability': 'adequate', 'work_declaration': 'commits',
                      'declared_work_scope': 'partial_work_overlap'}.get(stage)
            if choice is None:
                choice = req['state']['prior_work_records'][0]['id']
            return {'choice': {'value': choice}}, digest(req)
        result = build(run, doc, decide, version=STAGED_VERSION)
        self.assertEqual(len(result['records']), 2)
        row = result['observations'][1]
        self.assertEqual(row['related_record']['record_id'], result['records'][0]['id'])
        self.assertEqual(row['scope_relation'], 'partial_work_overlap')
        self.assertEqual(len(result['records'][0]['declarations']), 1)


if __name__ == '__main__':
    unittest.main()
