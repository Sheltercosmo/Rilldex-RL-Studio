import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tracker import (retry_outcomes as ro, recovery_windows as rw, work_state, graph_store,
                     analysis_metrics as am, investigation_plans as plans, monitoring, monitor_evidence)
from tracker.schema import InputError, digest
from tracker.store import Store
from tests.test_recovery_windows import captured, check, change


def project(run, state=None, graph=None):
    graph = graph or graph_store.build(run)
    recovery = rw.project(state or work_state.derive(run), graph)
    recovery['id'] = 'fixture-recovery-' + digest(recovery)
    return ro.project(recovery, graph)


class NextCheckTests(unittest.TestCase):
    def test_success_does_not_require_a_change(self):
        for steps, group in [([check(), check('passed')], 'unchanged_captured_inputs'),
                             ([check(), change(), check('passed')], 'recorded_relevant_change')]:
            with self.subTest(group=group):
                out = project(captured(steps)); row = out['records'][0]
                self.assertTrue(row['value']); self.assertEqual(row['input_response'], group)
                self.assertEqual(out['metrics'], dict(value=1, numerator=1, denominator=1, opportunities=1, unknown=0))

    def test_first_failed_retry_is_not_rescued_by_later_success(self):
        run = captured([check(), change(), check(), change(state={'record':2}), check('passed')])
        self.assertTrue(rw.project(work_state.derive(run), graph_store.build(run))['records'][0]['value'])
        out = project(run)
        self.assertEqual([r['value'] for r in out['records']], [False, True])
        self.assertEqual(out['metrics']['value'], .5)
        self.assertEqual(len(out['records'][0]['attempts']), 1)

    def test_first_incomparable_pass_is_not_skipped(self):
        out = project(captured([check(), change(), check('passed', version='2'), check('passed')]))
        row = out['records'][0]
        self.assertIsNone(row['value']); self.assertEqual(row['input_response'], 'unresolved_inputs')
        self.assertIn('criterion_version_changed', row['unknown_reasons'])
        self.assertEqual(len(row['attempts']), 1)

    def test_unknown_outcome_can_have_known_input_group(self):
        out = project(captured([check(), change(), check('unknown')]))
        row = out['records'][0]
        self.assertIsNone(row['value']); self.assertEqual(row['input_response'], 'recorded_relevant_change')
        self.assertEqual(row['unknown_reasons'], ['check_result_unknown'])

    def test_missing_retry_retained_as_unknown_not_a_failure(self):
        out = project(captured([check()]))
        self.assertEqual(out['metrics']['unknown'], 1); self.assertIsNone(out['metrics']['value'])
        self.assertEqual(out['records'][0]['unknown_reasons'], ['next_check_not_recorded'])

    def test_unrelated_or_reverted_edit_is_unchanged_at_dispatch(self):
        for edits in [[change(state={'auxiliary':1})], [change(), change(state={'record':0})]]:
            out = project(captured([check(), *edits, check('passed')]))
            row = out['records'][0]
            self.assertTrue(row['value']); self.assertEqual(row['input_response'], 'unchanged_captured_inputs')
            self.assertEqual(row['attempts'][0]['changes'], [])

    def test_state_difference_without_recorded_edit_has_separate_group(self):
        run = captured([check(), change(), check('passed')]); state = work_state.derive(run)
        state['edits'] = []
        row = project(run, state)['records'][0]
        self.assertTrue(row['value']); self.assertEqual(row['input_response'], 'changed_inputs_without_recorded_edit')

    def test_unstable_or_changed_scope_is_not_comparable(self):
        for kwargs in [dict(stable=None), dict(scope=['record', 'auxiliary'])]:
            row = project(captured([check(), change(), check('passed', **kwargs)]))['records'][0]
            self.assertIsNone(row['value']); self.assertEqual(row['input_response'], 'unresolved_inputs')

    def test_other_criterion_does_not_consume_first_retry(self):
        out = project(captured([check(), check('passed', criterion='other'), check('passed')]))
        self.assertTrue(out['records'][0]['value'])
        self.assertEqual(out['records'][0]['attempts'][0]['action_id'], work_state.derive(captured([check(), check('passed', criterion='other'), check('passed')]))['checks'][2]['action_id'])

    def test_hidden_failure_excluded_and_other_lane_not_a_retry(self):
        run = captured([check(), check('passed')])
        next(e for e in run['events'] if e['kind']=='feedback')['agent_visibility'] = 'not_established'
        out = project(run); self.assertEqual(out['metrics']['opportunities'], 0)
        self.assertEqual(len(out['coverage']['excluded_failures']), 1)
        run = captured([check(), check('passed')])
        for e in run['events']:
            if e.get('call_id')=='c1' or e.get('source_call_id')=='c1': e['trajectory_id']='other'
        self.assertIsNone(project(run)['records'][0]['value'])

    def test_subgroups_exclude_known_others_and_retain_unknown_membership(self):
        out = project(captured([check(), check(), change(), check(), check('unknown')]))
        # unchanged failed, changed failed, unchanged unknown; add a missing-retry opportunity.
        extra = project(captured([check()]))['records'][0]
        out['records'].append(extra)
        m = ro.measure(out, 'recorded_relevant_change')
        self.assertEqual((m['numerator'],m['denominator'],m['opportunities'],m['unknown']), (0,1,2,1))
        self.assertEqual(m['coverage']['excluded_known_other_inputs'], 2)
        self.assertEqual(m['coverage']['unknown_input_membership'], 1)

    def test_later_feedback_reference_is_not_attributed_to_first_retry(self):
        run = captured([check(), check(), change(), check('passed')]); graph = graph_store.build(run)
        recovery = rw.project(work_state.derive(run), graph); recovery['id']='fixture'
        events = {n['properties']['id']:n for n in graph['nodes'] if n['kind']=='event'}
        first = recovery['records'][0]['attempts'][0]['action_id']
        before = next(n for n in events.values() if n['event_index'] < events[first]['event_index'])
        later = next(n for n in events.values() if n['event_index'] > events[first]['event_index'])
        for name, node in [('before',before), ('later',later)]:
            graph['edges'].append(dict(id=name,source=node['id'],target=before['id'],type='assesses',properties={}))
        recovery['records'][0]['feedback_reference_edge_ids']=['before','later']
        row = ro.project(recovery, graph)['records'][0]
        self.assertEqual(row['feedback_reference_edge_ids'], ['before'])

    def test_source_binding_and_projection_arithmetic_are_checked(self):
        run = captured([check(), check('passed')]); graph = graph_store.build(run)
        recovery = rw.project(work_state.derive(run), graph); recovery['id']='fixture'; recovery['source_hash']='wrong'
        with self.assertRaises(InputError): ro.project(recovery, graph)
        out=project(run);out['metrics']['numerator']=0
        with self.assertRaises(InputError): ro.measure(out)

    def test_saved_monitors_receipts_cache_and_legacy_survive(self):
        run = captured([check(), check(), change(), check('passed')])
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'db.sqlite'); store.add([run])
            monitors = {key:monitoring.create(store, dict(name=key,kind='analysis',observer='source',analysis={'measure':key}))
                for key in ['next_check_success','next_check_success_changed','next_check_success_unchanged','criterion_recovery_window']}
            self.assertEqual(monitoring.sync(store)['errors'],0)
            values = {key:monitoring.values(store,m['id'],{run['id']})[run['id']] for key,m in monitors.items()}
            self.assertEqual([values[k]['value'] for k in monitors], [.5,1,0,1])
            for value in values.values(): monitor_evidence.read(store, value['id'])
            value=values['next_check_success']; result=monitor_evidence.read(store,value['id'])
            self.assertEqual(len(result['explanation']['analysis_cases']),2)
            plan=plans.read_plan(store,value['analysis']['plan_id'])
            self.assertEqual([n['op'] for n in plan['definition']['nodes']], ['work_state','recovery_windows','retry_outcomes'])
            self.assertEqual(plans.execute(store,plan['definition'])['execution'], dict(cache_hits=3,computed=0,inference_calls=0))
            graph=graph_store.read(store,value['graph_id'])
            links=[e for e in graph['edges'] if e['type']=='recorded_recheck_of']
            self.assertEqual(len(links),2)
            self.assertTrue(all(e['properties']['window_version']==ro.VERSION for e in links))
            self.assertEqual(graph['observer'],'next-check-evidence/1')
            original=plans.read_output
            def tamper(store, identifier):
                saved=original(store,identifier)
                if saved.get('schema')==rw.VERSION: saved['records']=[]
                return saved
            with patch.object(plans,'read_output',tamper):
                with self.assertRaisesRegex(InputError,'dependency'): am.receipt(store,value,monitors['next_check_success'])

    def test_legacy_evidence_graph_content_survives_versioned_work_state(self):
        # Compare against a retained execution receipt predating this operator.
        frozen=json.loads((Path(__file__).resolve().parents[1]/'research/recovery-windows-2026-10-11/final/receipts/sqlite-order-recovered.json').read_text(encoding='utf-8'))
        run=frozen['run']; graph=graph_store.build(run)
        with tempfile.TemporaryDirectory() as tmp:
            from tracker.analysis_operations import work_graph
            store=Store(Path(tmp)/'db.sqlite');store.add([run]);state=work_state.derive(run)
            state_graph=graph_store.read(store,work_graph(store,run,state));state['graph_id']=state_graph['id'];out=rw.project(state,graph)
            a=rw.evidence_graph(graph,state_graph,out)
            # Evidence receipts order cards for display; storage orders by ID.
            b=frozen['graph'];b['nodes']=sorted(b['nodes'],key=lambda n:n['id']);b['edges']=sorted(b['edges'],key=lambda e:e['id'])
            # Work-state/7 intentionally versions source-context changes. Compare
            # content by endpoints, not hashes derived from the former /6 label.
            self.assertEqual(a['nodes'],b['nodes'])
            def content(edges):
                return sorted((e['source'],e['target'],e['type'],
                    json.dumps({k:v for k,v in e['properties'].items() if k!='version'},sort_keys=True)) for e in edges)
            self.assertEqual(content(a['edges']),content(b['edges']))
            self.assertEqual({e['properties']['version'] for e in a['edges'] if 'version' in e['properties']},{work_state.VERSION})
            if work_state.VERSION!='work-state/6':self.assertNotEqual(a['id'],b['id'])

    def test_readiness_accepts_only_the_new_measure_for_its_question(self):
        from tracker import investigation_readiness as ready
        run=captured([check(),check('passed')]);run['metadata']['experiment']='next-check-controls'
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite');store.add([run])
            monitor=monitoring.create(store,dict(name='First retry',kind='analysis',observer='source',analysis={'measure':'next_check_success'}))
            monitoring.sync(store)
            result=ready.check(store,dict(recipe='next_check',experiment='next-check-controls',monitor=monitor['id']))
            self.assertEqual(result['summary']['opportunity_totals'],dict(opportunities=1,denominator=1,unknown=0))
            with self.assertRaises(InputError):ready.check(store,dict(recipe='recovery',experiment='next-check-controls',monitor=monitor['id']))


if __name__ == '__main__': unittest.main()
