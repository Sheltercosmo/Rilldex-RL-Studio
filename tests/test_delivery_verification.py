"""Contradictory captured checks must not become a selected successful verdict."""
from copy import deepcopy
import unittest
from tracker import work_state
from test_investigation_process import captured


def contradictory():
    run=captured(); cap=run['raw']['work_state']
    for s in cap['snapshots']:s['objects']['app.py']='v2'
    cap['edits']=[]
    return run


class DeliveryVerificationTests(unittest.TestCase):
    def test_pass_and_failure_on_same_captured_inputs_are_unresolved(self):
        out=work_state.derive(contradictory()); row=out['deliveries'][0]
        self.assertEqual(row['status'],'conflicting_check_results')
        self.assertIsNone(row['check_action_id'])
        self.assertEqual({h['result'] for h in row['check_history']},{'passed','failed'})
        self.assertEqual(len(row['conflicts']),1)
        self.assertEqual(out['metrics']['applicable_verification'],dict(numerator=0,denominator=0,opportunities=1,value=None,unknown=1))

    def test_changed_inputs_separate_the_old_failure_from_current_pass(self):
        run=captured();run['raw']['work_state']['snapshots'][-1]['objects']['app.py']='v2'
        out=work_state.derive(run);row=out['deliveries'][0]
        self.assertEqual(row['status'],'applicable_pass')
        self.assertEqual([h['applicability'] for h in row['check_history']],['changed_inputs','matching_inputs'])
        self.assertEqual(row['conflicts'],[])

    def test_scope_change_is_not_resolved_by_selecting_the_smaller_passing_check(self):
        run=contradictory();run['raw']['work_state']['checks'][1]['required_objects']=['app.py']
        row=work_state.derive(run)['deliveries'][0]
        self.assertEqual(row['status'],'inconsistent_check_scope')
        self.assertIsNone(row['check_action_id'])
        self.assertEqual(row['conflicts'],[])

    def test_result_arrival_order_does_not_choose_a_preferred_verdict(self):
        run=contradictory();cap=run['raw']['work_state']
        fail=next(e for e in run['events'] if e['id']==cap['checks'][0]['result_event_id'])
        passed=next(e for e in run['events'] if e['id']==cap['checks'][1]['result_event_id'])
        fail['index']=passed['index']+1
        self.assertEqual(work_state.derive(run)['deliveries'][0]['status'],'conflicting_check_results')

    def test_late_result_is_pending_at_delivery_and_cannot_leak_its_verdict(self):
        run=contradictory();cap=run['raw']['work_state'];check=cap['checks'][0]
        next(e for e in run['events'] if e['id']==check['result_event_id'])['index']=100
        row=work_state.derive(run)['deliveries'][0]
        self.assertEqual(row['status'],'applicable_pass')
        pending=next(h for h in row['check_history'] if h['action_id']==check['action_id'])
        self.assertEqual(pending['result'],'unknown');self.assertIsNone(pending['result_event_id'])
        self.assertEqual(pending['availability'],'pending_at_delivery')
        self.assertNotIn(check['result_event_id'],row['event_ids'])
        self.assertEqual(row['coverage']['pending'],1)

    def test_other_version_or_context_does_not_supply_delivery_evidence(self):
        for change in ('version','context'):
            run=contradictory();cap=run['raw']['work_state'];q=cap['checks'][0]
            if change=='version':q['criterion_version']='other'
            else:
                for e in run['events']:
                    if e['id'] in (q['action_id'],q['result_event_id']):e['context_id']='other'
            row=work_state.derive(run)['deliveries'][0]
            self.assertEqual(row['status'],'applicable_pass')
            self.assertEqual(len(row['check_history']),1)

    def test_future_unrelated_data_and_input_permutation_preserve_the_decision(self):
        run=contradictory();first=work_state.derive(run)['deliveries'][0]
        permuted=deepcopy(run);permuted['raw']['work_state']['checks'].reverse()
        self.assertEqual(first,work_state.derive(permuted)['deliveries'][0])
        permuted['events'].append(dict(run['events'][-1],id='future',index=200,text='Unrelated future success'))
        self.assertEqual(first,work_state.derive(permuted)['deliveries'][0])

    def test_monitor_unknown_and_graph_witnesses_reconcile(self):
        from test_analysis_monitors import AnalysisMonitorTests
        from tracker import monitoring, monitor_evidence
        fixture=AnalysisMonitorTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        run=contradictory();fixture.store.add([run]);monitor=fixture.monitor('delivery_verification','source')
        monitoring.sync(fixture.store)
        value=fixture.value(monitor,run['id'])
        self.assertEqual((value['value'],value['denominator'],value['unknown']),(None,0,1))
        receipt=monitor_evidence.read(fixture.store,value['id'])
        case=receipt['explanation']['analysis_cases'][0]
        self.assertIsNone(case['taken']);self.assertEqual(case['status'],'conflicting_check_results')
        self.assertEqual(len(case['record']['check_history']),2)
        graph=receipt['graph']
        self.assertEqual(sum(n['kind']=='delivery_verification' for n in graph['nodes']),1)
        self.assertEqual(sum(e['type']=='considers_check_at_delivery' for e in graph['edges']),2)
        self.assertEqual(monitoring.sync(fixture.store)['inserted'],0)
        from rilldex import Workspace
        from tracker.schema import InputError
        projected=Workspace(fixture.store.path).work_state(run['id'])
        self.assertEqual(projected['deliveries'][0],case['record'])
        with self.assertRaises(InputError):Workspace(fixture.store.path,experiment='other').work_state(run['id'])


if __name__=='__main__':unittest.main()
