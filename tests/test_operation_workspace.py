"""Synthetic software tests; these are not semantic accuracy measurements."""
from copy import deepcopy
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tracker import operation_workspace as workspace
from tracker.adapters import normalize
from tracker.rollout_metrics import report, training_series
from tracker.schema import InputError, digest
from tracker.semantic_extraction import read, write
from tracker.semantic_workspace import exclusive
from tracker.store import Store
from tests.test_operation_outcomes import answer
from test_tracker import harbor


class OperationWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.work=self.root/'observer'
        self.store=Store(self.root/'tracker.sqlite')

    def run_fixture(self,step=0):
        run=normalize(harbor(),'harbor',{'experiment':'synthetic-test','training_step':step})[0]
        self.store.add([run]);return run

    def records(self):
        return [r for r in report(self.store)['rows'] if r['observation_kind']=='operations']

    def test_common_protocol_compares_two_rollouts_without_checkpoint_names(self):
        runs=[self.run_fixture(0),self.run_fixture(2)]
        result=workspace.execute(self.store,self.work,[r['id'] for r in runs],answer)
        self.assertEqual(result['new_calls'],18);self.assertEqual(len(result['completed']),2)
        records=self.records();self.assertEqual(len({r['observer'] for r in records}),1)
        series=training_series(report(self.store),'operation_failed_fraction',observer=result['protocol']['id'])
        self.assertEqual(len(series['cohorts']),1)
        self.assertEqual([p['training_step'] for p in series['cohorts'][0]['points']],[0,2])
        self.assertTrue(all(r['metrics']['completed_after_failed_call_count']['value'] is None for r in records))
        saved=self.store.operation_observation(result['completed'][0]['id'])
        self.assertEqual(len(saved['action_outcomes']),3)
        self.assertEqual(workspace.audit(self.work)['runs'][0]['status'],'complete')

    def test_budget_resume_and_idempotence_without_partial_measurements(self):
        run=self.run_fixture();ids=[run['id']]
        partial=workspace.execute(self.store,self.work,ids,answer,max_new_calls=2)
        self.assertEqual(partial['pending_run_ids'],ids);self.assertEqual(self.records(),[])
        self.assertEqual(workspace.status(self.work)['runs'][0]['saved_decision_files'],2)
        self.assertEqual(workspace.audit(self.work)['runs'][0]['status'],'incomplete')
        resumed=workspace.execute(self.store,self.work,ids,answer,max_new_calls=7)
        self.assertEqual(resumed['new_calls'],7);self.assertEqual(len(self.records()),1)
        repeat=workspace.execute(self.store,self.work,ids,lambda _:self.fail('Must reuse cache'),max_new_calls=0)
        self.assertEqual(repeat['new_calls'],0);self.assertEqual(len(self.records()),1)
        self.assertEqual(repeat['completed'],resumed['completed'])

    def test_invalid_wire_response_is_retained_without_publishing_result(self):
        run=self.run_fixture()
        with self.assertRaisesRegex(InputError,'model mismatch'):
            workspace.execute(self.store,self.work,[run['id']],lambda _: {'model':'wrong','answers':{}})
        folder=workspace.frozen(self.work,run);wire=list((folder/'wire').glob('*/*.json'))
        self.assertEqual(len(wire),1);self.assertEqual(read(wire[0])['response']['model'],'wrong')
        self.assertEqual(read(folder/'last-execution.json')['status'],'interrupted')
        self.assertEqual(self.records(),[])
        resumed=workspace.execute(self.store,self.work,[run['id']],answer)
        self.assertEqual(resumed['new_calls'],9);self.assertEqual(len(list((folder/'wire').glob('*/*.json'))),10)

    def test_source_config_and_saved_decisions_are_checked(self):
        run=self.run_fixture();workspace.execute(self.store,self.work,[run['id']],answer)
        folder=workspace.frozen(self.work,run);source=read(folder/'source.json')
        changed=deepcopy(source);changed['events'][0]['text']='Changed';write(folder/'source.json',changed)
        with self.assertRaisesRegex(InputError,'source changed'):workspace.audit(self.work)
        with self.assertRaisesRegex(InputError,'source changed'):workspace.execute(self.store,self.work,[run['id']],answer)
        write(folder/'source.json',source)
        config=workspace.protocol();config['model']='changed';write(self.work/'protocol.json',config)
        with self.assertRaisesRegex(InputError,'protocol changed'):workspace.execute(self.store,self.work,[run['id']],answer)
        write(self.work/'protocol.json',workspace.protocol())
        path=next((folder/'decisions').glob('*.json'));packet=read(path)
        packet['answers']={};write(path,packet)
        with self.assertRaisesRegex(InputError,'argmax'):workspace.audit(self.work)

    def test_workspace_lock_and_latest_complete_snapshot_selection(self):
        explicit=self.run_fixture()
        payload={'producer':'test','rollout_id':'A','revision':0,'state':'in_progress','document':harbor()}
        old=self.store.ingest(payload)
        self.assertEqual(workspace.latest_ids(self.store),[explicit['id']])
        payload.update(revision=1,state='complete');last=self.store.ingest(payload)
        self.assertEqual(set(workspace.latest_ids(self.store)),{explicit['id'],last['id']})
        payload.update(rollout_id='B',revision=0,state='failed');failed=self.store.ingest(payload)
        self.assertNotIn(failed['id'],workspace.latest_ids(self.store))
        workspace.initialize(self.work)
        with exclusive(self.work):
            self.assertTrue(workspace.status(self.work)['workspace_busy'])
            with self.assertRaisesRegex(InputError,'Another process'):workspace.execute(self.store,self.work,[],answer)
        self.assertFalse(workspace.status(self.work)['workspace_busy'])

    def test_watch_follows_new_imports_with_one_process_wide_request_budget(self):
        from tracker.operation_cli import execute
        self.run_fixture(0)
        args=SimpleNamespace(outcome_command='watch',directory=self.work,prompt_key=False,
                             max_new_calls=18,interval=.2,once=False)
        with patch('tracker.jev.JevClient._post',side_effect=answer) as transport:
            with patch('tracker.operation_cli.time.sleep',side_effect=lambda _:self.run_fixture(2)) as wait:
                with redirect_stdout(StringIO()):execute(args,self.store)
        self.assertEqual(transport.call_count,18);self.assertEqual(wait.call_count,1)
        self.assertEqual(len(self.records()),2)


if __name__=='__main__':unittest.main()
