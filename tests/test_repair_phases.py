import copy
import tempfile
import unittest
from pathlib import Path

from tracker import repair_phases as phases, graph_store, investigation_plans as plans
from tracker.adapters import normalize
from tracker.schema import digest, InputError
from tracker.store import Store


def run_with(commands, family='software_repair'):
    return normalize({'problem_statement': 'Repair the defect.', 'trajectory': [
        {'action': c, 'thought': 'Recorded agent text.', 'observation': 'Returned result.'} for c in commands]},
        'swe-agent', {'task_id': 'case', 'task_family': family})[0]


def result(commands):
    run = run_with(commands)
    return phases.project(run, graph_store.build(run)['id'])


class RepairPhaseTests(unittest.TestCase):
    def test_activity_framework_and_programming_are_not_domain_activation(self):
        run = run_with(['pytest test_app.py'], family='report_generation')
        out = phases.project(run, 'graph')
        self.assertFalse(out['applicable']); self.assertEqual(out['records'], [])
        self.assertIsNone(out['coverage'])

    def test_context_changes_phase_without_claiming_success(self):
        out = result(['pytest test_app.py', 'str_replace_editor str_replace app.py --old_str a --new_str b',
                      'pytest test_app.py', 'submit'])
        self.assertEqual([r['phase'] for r in out['records']], ['localization', 'patch', 'validation', 'submission'])
        self.assertEqual(out['records'][2]['prior_patch_event_id'], out['records'][1]['event_id'])
        # All return text is opaque and may report a failed edit; labels describe
        # attempts only and are prefix-based, independent of subsequent feedback.
        run = run_with(['str_replace_editor str_replace app.py --old_str a --new_str b', 'pytest test_app.py'])
        for e in run['events']:
            if e['kind'] == 'feedback': e['text'] = 'The edit failed. No tests ran.'
        self.assertEqual([r['phase'] for r in phases.project(run, 'graph')['records']], ['patch', 'validation'])

    def test_test_creation_is_not_an_application_patch(self):
        out = result(['str_replace_editor create tests/test_app.py --file_text x',
                      'python tests/test_app.py'])
        self.assertEqual([r['phase'] for r in out['records']], ['localization', 'localization'])

    def test_quotes_preserve_editor_content_and_compounds_remain_unknown(self):
        commands = ["str_replace_editor str_replace app.py --old_str 'a; b\nc' --new_str 'd && e'",
                    'false && pytest test_app.py', 'echo pytest', 'python -c "print(1)"',
                    'cat a.py > b.py', 'find . -exec rm {} ;', 'cat a.py\npytest test_app.py']
        self.assertEqual([r['phase'] for r in result(commands)['records']], ['patch'] + ['unknown'] * 6)

    def test_opaque_history_and_gap_transitions_are_retained(self):
        out = result(['cat app.py', './opaque.sh', 'pytest tests/test_app.py'])
        self.assertEqual([r['phase'] for r in out['records']], ['localization', 'unknown', 'unknown'])
        self.assertEqual(out['pairs'], [])
        self.assertEqual(out['records'][-1]['rule'], 'ambiguous_prior_patch_history')
        self.assertEqual(out['coverage'], 1/3)

    def test_no_cross_lane_or_parallel_patch_context(self):
        run = run_with(['str_replace_editor str_replace app.py --old_str a --new_str b', 'pytest test_app.py'])
        actions = [e for e in run['events'] if e['kind'] == 'action']
        actions[1]['trajectory_id'] = 'other'
        out = phases.project(run, 'graph')
        self.assertEqual(out['records'][1]['phase'], 'localization'); self.assertEqual(out['pairs'], [])
        actions[1]['trajectory_id'] = 'main'; actions[1]['parent_id'] = actions[0]['parent_id']
        self.assertEqual([r['phase'] for r in phases.project(run, 'graph')['records']], ['unknown', 'unknown'])

    def test_structured_editor_and_shell_have_equivalent_roles(self):
        direct = phases.operation({'tool': 'str_replace_editor', 'arguments': {'command': 'view', 'path': 'tests/test_app.py'}})
        shell = phases.operation({'tool': 'shell', 'arguments': {'command': 'str_replace_editor view tests/test_app.py'}})
        self.assertEqual(direct, shell)
        self.assertEqual(phases.operation({'tool': 'get_balance', 'arguments': {'command': 'pytest'}})['kind'], 'unknown')
        self.assertEqual(phases.operation({'tool': 'shell', 'text': 'cat app.py\n'})['kind'], 'read')

    def test_prefix_is_stable_and_input_is_unchanged(self):
        run = run_with(['cat app.py', 'pytest tests/test_app.py', 'str_replace_editor create app.py --file_text x'])
        before = copy.deepcopy(run); out = phases.project(run, 'graph')
        short = copy.deepcopy(run); short['events'] = short['events'][:7]
        self.assertEqual(phases.project(short, 'graph')['records'], out['records'][:2])
        self.assertEqual(run, before)

    def test_comparison_weights_rollouts_equally_and_keeps_unknowns(self):
        a = result(['cat app.py'] * 10); b = result(['opaque']); c = phases.project(run_with(['cat app.py'], 'other'), 'graph')
        g = phases.compare([a, b, c], [a['run_id'], b['run_id'], c['run_id']], [])['groups']['focus']
        self.assertEqual((g['rollouts'], g['applicable'], g['measured']), (3, 2, 2))
        self.assertEqual(g['mean_action_share']['unknown'], .5)
        self.assertEqual(g['action_counts']['localization'], 10)
        with self.assertRaises(InputError): phases.compare([a, a], [a['run_id']], [])

    def test_typed_plan_cache_and_source_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'test.sqlite'); run = run_with(['cat app.py', 'pytest tests/test_app.py']); store.add([run])
            g = graph_store.build(run)
            node = {'name': 'p', 'op': 'repair_phases', 'inputs': [], 'params': {'run_id': run['id'], 'source_hash': digest(run), 'graph_id': g['id']}}
            plan = {'schema': plans.VERSION, 'nodes': [node, {'name': 'compare', 'op': 'compare_repair_phases', 'inputs': ['p'], 'params': {'focus': [run['id']], 'reference': []}}]}
            a = plans.execute(store, plan); b = plans.execute(store, plan)
            self.assertEqual(a['outputs'], b['outputs']); self.assertEqual(b['execution']['cache_hits'], 2)
            self.assertEqual(b['execution']['inference_calls'], 0)
            bad = copy.deepcopy(plan); bad['nodes'][0]['params']['source_hash'] = 'wrong'
            with self.assertRaises(InputError): plans.execute(store, bad)
            bad = copy.deepcopy(plan); bad['nodes'][0]['op'] = 'sequence'
            with self.assertRaises(InputError): plans.execute(store, bad)
