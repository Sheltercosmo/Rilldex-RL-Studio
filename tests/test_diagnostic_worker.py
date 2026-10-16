"""Worker lifecycle tests with simulated decisions, not detector accuracy."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tracker import diagnostic_worker as w
from tracker.adapters import normalize
from tracker.schema import InputError,digest
from tracker.semantic_extraction import read,write
from tracker.semantic_workspace import exclusive
from tracker.store import Store
from tracker.rollout_metrics import report
from test_tracker import harbor
from test_diagnostic_monitors import transport as negative


def positive(req):
    stage=req['state'].get('stage')
    def choose(k):
        if stage=='evidence_roles':return 'f1'
        if stage=='validate_evidence_chains':return 'supported'
        return 'observed' if k=='online_reference_search' else 'not_observed'
    return {'model':req['model'],'answers':{k:{'type':'choice','probabilities':{v:float(v==choose(k)) for v in q['criteria']}} for k,q in req['questions'].items()}}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.work=self.root/'work';self.store=Store(self.root/'db')

    def fixture(self,step=0):
        r=normalize(harbor(),'harbor',{'experiment':'worker-test','training_step':step})[0]
        self.store.add([r]);return r

    def metrics(self):
        with self.store.connect() as c:return c.execute('SELECT * FROM rollout_measurements WHERE observer LIKE ?',('diagnostic-chains-%',)).fetchall()

    def run_worker(self,transport=positive,**kw):
        return w.execute(self.store,self.work,transport,selector=w.selection(experiment='worker-test'),**kw)

    def test_budget_resume_and_atomic_completed_registration(self):
        run=self.fixture();r=self.run_worker(max_new_calls=1)
        self.assertEqual(r['new_calls'],1);self.assertEqual(r['coverage']['counts'],{'pending':1})
        self.assertEqual(self.metrics(),[])
        r=self.run_worker(max_new_calls=2)
        self.assertEqual(r['new_calls'],2);self.assertEqual(r['coverage']['counts'],{'complete':1})
        self.assertEqual(len(self.metrics()),1)
        repeated=self.run_worker(lambda _:self.fail('Published result should not call provider'),max_new_calls=0)
        self.assertEqual(repeated['new_calls'],0);self.assertEqual(len(self.metrics()),1)
        self.assertTrue(w.audit(self.store,self.work)['runs'][0]['validation']['exact_replay'])

    def test_failure_isolation_and_no_automatic_retry_of_failed_source(self):
        first=self.fixture();second=self.fixture(1);calls=[]
        def transport(req):
            calls.append(req)
            return {'model':'invalid','answers':{}} if len(calls)==1 else negative(req)
        r=self.run_worker(transport,max_new_calls=2)
        self.assertEqual(r['coverage']['counts'],{'failed':1,'complete':1})
        self.assertEqual(len(self.metrics()),1)
        wires=list((self.work/'runs').glob('*/*/responses/*/*.json'));self.assertEqual(len(wires),2)
        r=self.run_worker(lambda _:self.fail('Do not retry on every poll'),max_new_calls=5)
        self.assertEqual(r['new_calls'],0);self.assertTrue(r['failed'][0]['held_for_explicit_retry'])
        r=self.run_worker(negative,max_new_calls=1,retry_failed=True)
        self.assertEqual(r['coverage']['counts'],{'complete':2});self.assertEqual(len(self.metrics()),2)

    def test_ineligible_sources_and_unfinished_revisions_are_not_negative_metrics(self):
        flat=self.fixture();flat=deepcopy(flat);flat['id']='flat';flat['adapter']='verl-generation';self.store.add([flat])
        payload={'producer':'test','rollout_id':'live','revision':0,'state':'in_progress','document':harbor(),'metadata':{'experiment':'worker-test'}}
        old=self.store.ingest(payload)
        r=self.run_worker(negative,max_new_calls=1)
        self.assertEqual(r['coverage']['counts'],{'complete':1,'ineligible':1,'waiting':1})
        self.assertEqual(len(self.metrics()),1)
        payload.update(revision=1,state='complete');payload['document']['steps'][-1]['message']='The completed source now has additional evidence.';latest=self.store.ingest(payload)
        r=self.run_worker(negative,max_new_calls=1)
        self.assertEqual(r['coverage']['counts'],{'complete':2,'ineligible':1})
        self.assertNotIn(old['id'],[p['run_id'] for p in r['coverage']['rows']])
        self.assertIn(latest['id'],[p['run_id'] for p in r['coverage']['rows']])

    def test_new_producer_revision_does_not_inherit_previous_result(self):
        payload={'producer':'test','rollout_id':'live','revision':0,'state':'complete','document':harbor(),'metadata':{'experiment':'worker-test'}}
        first=self.store.ingest(payload);self.run_worker(negative,max_new_calls=1)
        payload.update(revision=1);payload['document']['steps'][-1]['message']='New evidence in a later revision.';latest=self.store.ingest(payload)
        r=self.run_worker(negative,max_new_calls=0)
        self.assertEqual(r['coverage']['counts'],{'pending':1})
        self.assertEqual(r['coverage']['rows'][0]['run_id'],latest['id'])
        self.assertNotEqual(first['id'],latest['id'])

    def test_unchanged_source_revision_reuses_audited_measurement(self):
        payload={'producer':'test','rollout_id':'live','revision':0,'state':'complete','document':harbor(),'metadata':{'experiment':'worker-test'}}
        first=self.store.ingest(payload);self.run_worker(negative,max_new_calls=1)
        payload.update(revision=1);last=self.store.ingest(payload)
        self.assertEqual(first['id'],last['id'])
        r=self.run_worker(lambda _:self.fail('Exact source did not change'),max_new_calls=0)
        self.assertEqual(r['new_calls'],0);self.assertEqual(r['coverage']['counts'],{'complete':1})
        self.assertEqual(r['coverage']['rows'][0]['revision'],1)

    def test_database_publication_rolls_back_if_completion_journal_fails(self):
        self.fixture();original=w._save_attempt
        def fail(c,worker_id,receipt):
            if receipt['status']=='complete':raise RuntimeError('Synthetic publication fault')
            original(c,worker_id,receipt)
        with patch('tracker.diagnostic_worker._save_attempt',side_effect=fail):r=self.run_worker(negative,max_new_calls=1)
        self.assertEqual(self.metrics(),[]);self.assertEqual(r['coverage']['counts'],{'failed':1})
        r=self.run_worker(lambda _:self.fail('Response already cached'),max_new_calls=0,retry_failed=True)
        self.assertEqual(r['coverage']['counts'],{'complete':1});self.assertEqual(len(self.metrics()),1)

    def test_source_protocol_and_process_lock_checks(self):
        run=self.fixture();self.run_worker(negative,max_new_calls=1)
        with exclusive(self.work):
            self.assertTrue(w.status(self.store,self.work)['workspace_busy'])
            with self.assertRaises(InputError):self.run_worker()
        self.assertFalse(w.status(self.store,self.work)['workspace_busy'])
        with self.assertRaisesRegex(InputError,'protocol'):w.execute(self.store,self.work,negative,selector=w.selection(),max_new_calls=0)
        folder=self.work/'runs'/run['id']/digest(run);saved=read(folder/'source.json');saved['events'][0]['text']='tampered';write(folder/'source.json',saved)
        with self.assertRaisesRegex(InputError,'source changed'):w.audit(self.store,self.work)

    def test_exceptions_do_not_persist_their_sensitive_message(self):
        self.fixture()
        def fail(req):raise RuntimeError('SYNTHETIC_SECRET_DO_NOT_STORE')
        self.run_worker(fail,max_new_calls=1)
        for p in self.work.rglob('*.json'):self.assertNotIn('SYNTHETIC_SECRET_DO_NOT_STORE',p.read_text(encoding='utf-8'))
        with self.store.connect() as c:
            self.assertTrue(all('SYNTHETIC_SECRET_DO_NOT_STORE' not in row[0] for row in c.execute('SELECT document FROM diagnostic_attempts')))

    def test_watch_budget_follows_new_imports_without_resetting(self):
        from tracker.diagnostic_worker_cli import execute
        self.fixture();args=SimpleNamespace(monitor_command='watch',directory=self.work,protocol='chains',prompt_key=False,
            max_new_calls=2,retry_failed=False,experiment='worker-test',adapter=None,interval=.2,once=False)
        with patch('tracker.jev.JevClient._post',side_effect=negative) as calls:
            with patch('tracker.diagnostic_worker_cli.time.sleep',side_effect=lambda _:self.fixture(1)) as wait:
                with redirect_stdout(StringIO()):execute(args,self.store)
        self.assertEqual(calls.call_count,2);self.assertEqual(wait.call_count,1);self.assertEqual(len(self.metrics()),2)

    def test_another_workspace_reuses_exact_published_result_without_model_calls(self):
        self.fixture();self.run_worker(negative,max_new_calls=1)
        second=w.execute(self.store,self.root/'second',lambda _:self.fail('Do not rebill the same audited observation'),
            selector=w.selection(),max_new_calls=0)
        self.assertEqual(second['coverage']['counts'],{'complete':1})
        self.assertEqual(second['new_calls'],0);self.assertTrue(second['completed'][0]['reused_published_result'])
        self.assertEqual(len(self.metrics()),1)

    def test_old_completion_receipt_cannot_replace_missing_published_measurement(self):
        self.fixture();self.run_worker(negative,max_new_calls=1)
        with self.store.connect() as c:c.execute("DELETE FROM rollout_measurements WHERE observer LIKE 'diagnostic-chains-%'")
        r=self.run_worker(lambda _:self.fail('Replay saved decisions'),max_new_calls=0)
        self.assertEqual(r['coverage']['counts'],{'complete':1})
        self.assertEqual(len(self.metrics()),1)
        self.assertFalse(r['completed'][0]['reused_published_result'])

    def test_authentication_failure_stops_before_billing_the_remaining_population(self):
        self.fixture();self.fixture(1);called=[]
        def unauthorized(req):
            called.append(req);raise InputError('Jev request failed with HTTP 401; credentials and provider response are not logged')
        with self.assertRaisesRegex(InputError,'401'):self.run_worker(unauthorized,max_new_calls=10)
        self.assertEqual(len(called),1)
        self.assertEqual(w.status(self.store,self.work)['coverage']['counts'],{'failed':1,'pending':1})


if __name__=='__main__':unittest.main()
