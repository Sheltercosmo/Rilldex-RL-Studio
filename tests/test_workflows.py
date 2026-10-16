import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from tracker.analytics import Analysis
from tracker.cli import main
from tracker.collector_lock import ProducerLock
from tracker.portable import generation_document
from tracker.schema import InputError
from tracker.store import Store
from tracker.workflows import Workflow, initialize, package, package_request, recipe, validate


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.store = Store(self.root / 'live.sqlite')
        self.value = recipe(database=str(self.store.path), experiment='job')
        self.value['queries'] = [{'name': 'count', 'sql': 'SELECT COUNT(*) AS n FROM rl_rollouts'}]

    def ingest(self, name='a', revision=0):
        return self.store.ingest(dict(producer='worker', rollout_id=name, revision=revision,
            state='complete', format='generation', metadata={'experiment': 'job'},
            document=generation_document('Question', f'Answer {name}/{revision}', reward=1)))

    def save(self):
        self.project.mkdir(exist_ok=True)
        (self.project / 'rilldex.json').write_text(json.dumps(self.value), encoding='utf-8')

    def report(self, result):
        return json.loads((self.project / 'results' / result['generation'] / 'analysis.json').read_text())

    def test_publication_scope_consistency_and_fast_unchanged_reuse(self):
        self.ingest()
        self.save()
        with Workflow(self.project) as job:
            first = job.run()
            self.assertEqual(first['status'], 'published')
            folder = job.output / first['generation']
            self.assertEqual(self.report(first)['queries']['count']['rows'], [{'n': 1}])
            self.assertEqual(Analysis(folder/'data.sqlite').query('SELECT COUNT(*) n FROM rl_rollouts')['rows'], [{'n': 1}])
            with zipfile.ZipFile(folder/'tables.zip') as z:
                manifest = json.loads(z.read('manifest.json'))
                self.assertEqual(manifest['tables']['rollouts']['rows'], 1)
            with patch.object(Analysis, 'database', side_effect=AssertionError('Unchanged database should not be copied')):
                self.assertEqual(job.run()['status'], 'unchanged')
            self.ingest('b')
            second = job.run()
            self.assertNotEqual(first['generation'], second['generation'])
            self.assertEqual(self.report(second)['queries']['count']['rows'], [{'n': 2}])
        with Workflow(self.project) as restarted:
            self.assertEqual(restarted.run()['status'], 'unchanged')
        self.assertEqual(len(list((self.project/'results').glob('snapshot-*'))), 2)

    def test_query_failure_never_advances_latest(self):
        self.ingest(); self.save()
        with Workflow(self.project) as job: job.run()
        pointer = (self.project/'results/latest.json').read_bytes()
        for query in ('DELETE FROM rl_rollouts', 'SELECT 1 n UNION ALL SELECT 2 n'):
            self.value['queries'] = [{'name': 'bad', 'sql': query, 'limit': 1}]
            self.save()
            with Workflow(self.project) as job, self.assertRaises(InputError): job.run()
            self.assertEqual((self.project/'results/latest.json').read_bytes(), pointer)
            self.assertFalse(list((self.project/'results').glob('.pending-*')))

    def test_partial_rows_replay_and_restart_without_blocking_valid_data(self):
        source = self.root/'source'; source.mkdir()
        row = json.dumps({'input': 'Q', 'output': 'A', 'step': 1, 'score': 1})
        records = source/'records.jsonl'
        records.write_text(row+'\n'+row, encoding='utf-8')
        self.value['database'] = 'workspace/tracker.sqlite'
        self.value['source'] = dict(root=str(source), producer='job/source', mode='exports', metadata={'experiment': 'job'})
        self.save()
        with Workflow(self.project) as job:
            first = job.run()
            self.assertTrue(first['pending'])
            self.assertEqual(self.report(first)['queries']['count']['rows'], [{'n': 1}])
        with records.open('a', encoding='utf-8') as file: file.write('\n')
        with Workflow(self.project) as job:
            second = job.run()
            self.assertFalse(second['pending'])
            self.assertEqual(self.report(second)['queries']['count']['rows'], [{'n': 2}])
            self.assertEqual(job.run()['generation'], second['generation'])
        self.assertEqual(len(Store(self.project/'workspace/tracker.sqlite').list()), 2)

    def test_wait_for_pretraining_source_and_check_without_writes(self):
        self.value['database'] = 'workspace/tracker.sqlite'
        self.value['source'] = dict(root='../future', producer='job/future', mode='exports', metadata={'experiment': 'job'})
        self.save()
        with Workflow(self.project) as job:
            self.assertFalse(job.check()['database_exists'])
            self.assertFalse(job.output.exists())
            self.assertEqual(job.run()['status'], 'waiting')
            self.assertFalse(job.database.exists())
            self.assertFalse((self.root/'future').exists())
            source=self.root/'future'; source.mkdir()
            (source/'a.jsonl').write_text('{"input":"Q","output":"A","step":1}\n')
            self.assertEqual(job.run()['status'], 'published')

    def test_namespace_boundaries_and_competing_writer(self):
        self.ingest(); self.save()
        with Workflow(self.project) as job:
            job.output.mkdir()
            with ProducerLock(SimpleNamespace(path=job.output/'workflow'), 'workflow-publication'):
                with self.assertRaises(InputError): job.run()
            (job.output/'latest.json').write_text('{"schema":"foreign"}')
            with self.assertRaises(InputError): job.run()
        self.value['outputs'] = '.'; self.save()
        with Workflow(self.project) as job, self.assertRaises(InputError): job.check()
        self.value['outputs'] = 'results'
        self.value['source'] = dict(root='.',producer='job',mode='native'); self.save()
        with Workflow(self.project) as job, self.assertRaises(InputError): job.check()

    def test_portable_package_runs_without_install_or_checkout_imports(self):
        self.ingest()
        raw = package(self.value)
        destination = self.root/'portable'
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            self.assertIn('runtime/tracker/web/connections.html', z.namelist())
            self.assertIn('runtime/rilldex/__main__.py', z.namelist())
            self.assertFalse(any(name.endswith(('.sqlite', '.env', '.pyc')) for name in z.namelist()))
            z.extractall(destination)
        env = dict(os.environ); env.pop('PYTHONPATH', None); env.pop('JEV_API_KEY', None)
        for flags in (['--check'], [], []):
            result = subprocess.run([sys.executable, '-I', str(destination/'run.py'), *flags],
                cwd=self.root, env=env, capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
        self.assertEqual(receipt['status'], 'unchanged')
        self.assertTrue((destination/'results/latest.json').is_file())
        self.assertFalse((self.root/'results').exists())

    def test_package_selected_scope_and_cli_init(self):
        raw = package_request({'analysis': {'experiment': 'job', 'observer': 'source', 'history': True, 'profile': 'graphs', 'format': 'csv'}}, self.store.path)
        with zipfile.ZipFile(io.BytesIO(raw)) as z: value = json.loads(z.read('rilldex.json'))
        self.assertEqual(value['scope'], {'experiment': 'job', 'observer': 'source', 'history': True})
        self.assertIn('edges', value['tables']); self.assertNotIn('sources', value['tables'])
        self.assertIsNone(value['source'])
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()): main(['workflow','init',str(self.project),'--source',str(self.root/'outputs'),'--mode','exports','--experiment','job','--producer','job/worker'])
        self.assertTrue((self.project/'run.py').exists())
        with self.assertRaises(FileExistsError): initialize(self.project, self.value)

    def test_invalid_configs_and_profile(self):
        for value in ({**self.value,'interval':True}, {**self.value,'tables':['unknown']}, {**self.value,'scope':{'history':'false'}}):
            with self.assertRaises(InputError): validate(value)
        with self.assertRaises(InputError): package_request({'analysis':{'profile':'missing'}},self.store.path)

    def test_native_and_snapshot_changes_keep_revision_history(self):
        from test_tracker import harbor
        for mode in ('native', 'snapshots'):
            with self.subTest(mode=mode):
                source=self.root/mode; source.mkdir()
                path=source/'trial/agent/trajectory.json' if mode=='native' else source/'rollout.json'
                path.parent.mkdir(parents=True, exist_ok=True)
                doc=harbor() if mode=='native' else generation_document('Q','A')
                path.write_text(json.dumps(doc),encoding='utf-8')
                value=recipe(database=str(self.root/(mode+'.sqlite')),source=dict(root=str(source),producer='job/'+mode,mode=mode,metadata={'experiment':'job'}),experiment='job',history=True)
                folder=self.root/('workflow-'+mode); initialize(folder,value)
                with Workflow(folder) as job:
                    first=job.run(); self.assertEqual(first['status'],'published')
                    if mode=='native':
                        (source/'trial/result.json').write_text(json.dumps({'finished_at':'2026-10-15T10:00:00Z','verifier_result':{'rewards':{'reward':1}}}))
                    else:
                        path.write_text(json.dumps(generation_document('Q','Changed answer')),encoding='utf-8')
                    second=job.run(); self.assertNotEqual(first['generation'],second['generation'])
                    data=Analysis(job.output/second['generation']/'data.sqlite')
                    self.assertEqual(len(data.table('revisions',history=True)['rows']),2)
                    with zipfile.ZipFile(job.output/second['generation']/'tables.zip') as z:
                        exported=json.loads(z.read('manifest.json'))
                        self.assertEqual(exported['tables']['rollouts']['rows'],2)
                        self.assertTrue(exported['scope']['history'])

    def test_follow_cli_processes_later_data_and_stops_cleanly(self):
        self.value['publish_interval']=0
        self.ingest(); self.save()
        calls=[]
        def advance(_):
            calls.append(1)
            if len(calls)==1: self.ingest('later')
            else: raise KeyboardInterrupt
        from contextlib import redirect_stdout
        output=io.StringIO()
        with patch('tracker.workflow_cli.time.sleep',side_effect=advance), redirect_stdout(output):
            main(['workflow','run',str(self.project),'--follow'])
        receipts=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r['status'] for r in receipts],['published','published','stopped'])
        self.assertEqual(self.report(receipts[1])['queries']['count']['rows'],[{'n':2}])

    def test_capture_continues_after_failed_publication_and_status_retains_failure(self):
        source=self.root/'outputs';source.mkdir()
        records=source/'a.jsonl';records.write_text('{"input":"Q","output":"A","step":1}\n')
        self.value['database']='workspace/tracker.sqlite'
        self.value['source']=dict(root=str(source),producer='job/worker',mode='exports',metadata={'experiment':'job'})
        self.save()
        with Workflow(self.project) as job:
            first=job.run()
            pointer=(job.output/'latest.json').read_bytes()
            with records.open('a') as f:f.write('{"input":"Q2","output":"B","step":1}\n')
            with patch.object(Analysis,'export',side_effect=OSError('Simulated unavailable export disk')):
                failed=job.run(resilient=True)
            self.assertEqual(failed['error']['stage'],'publication')
            self.assertEqual((job.output/'latest.json').read_bytes(),pointer)
            with records.open('a') as f:f.write('{"input":"Q3","output":"C","step":1}\n')
            captured=job.run(publish=False)
            self.assertEqual(captured['capture']['ingested'],1)
            self.assertEqual(job.status()['publication']['status'],'error')
            self.assertIn('publication_error',captured)
            self.assertEqual(len(Store(job.database).list()),3)
            recovered=job.run()
            self.assertEqual(self.report(recovered)['queries']['count']['rows'],[{'n':3}])
            self.assertNotEqual(first['generation'],recovered['generation'])
            self.assertNotIn('error',job.status()['publication'])
            self.assertFalse(list(job.output.glob('.pending-*')))

    def test_follow_separates_capture_and_publication_cadence(self):
        self.ingest();self.save()
        clock=[0.0];calls=[]
        def advance(_):
            calls.append(1)
            if len(calls)==1:self.ingest('later');clock[0]=10
            elif len(calls)==2:clock[0]=300
            else:raise KeyboardInterrupt
        from contextlib import redirect_stdout
        output=io.StringIO()
        with patch('tracker.workflow_cli.time.sleep',side_effect=advance), patch('tracker.workflow_cli.time.monotonic',side_effect=lambda:clock[0]), redirect_stdout(output):
            main(['workflow','run',str(self.project),'--follow'])
        receipts=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r['status'] for r in receipts],['published','collected','published','stopped'])
        self.assertEqual(self.report(receipts[0])['queries']['count']['rows'],[{'n':1}])
        self.assertEqual(self.report(receipts[2])['queries']['count']['rows'],[{'n':2}])
        with Workflow(self.project) as job:self.assertEqual(job.status()['phase'],'stopped')

    def test_session_owns_source_and_outputs_between_cycles(self):
        self.value['source']=dict(root='../future',producer='job/worker',mode='native')
        self.save()
        with Workflow(self.project) as job, job.session():
            job.run(publish=False)
            with Workflow(self.project) as competitor, self.assertRaises(InputError):competitor.run()
            with self.assertRaises(InputError):
                with ProducerLock(SimpleNamespace(path=job.database),'job/worker'):pass
        with ProducerLock(SimpleNamespace(path=self.store.path),'job/worker'):pass

    def test_preflight_and_status_are_read_only_and_stateful(self):
        self.save()
        with Workflow(self.project) as job:
            self.assertEqual(job.status()['phase'],'not_started')
            self.assertEqual(job.check()['status'],'ready')
            self.assertFalse(job.output.exists())
            job.run()
            status_path=job.output/'status.json'
            value=json.loads(status_path.read_text());value['updated_at']='2020-01-01T00:00:00+00:00'
            status_path.write_text(json.dumps(value))
            self.assertTrue(job.status()['heartbeat_overdue'])
            self.assertIn('not process liveness',job.status()['note'])
        self.value['database']='missing.sqlite';self.save()
        with Workflow(self.project) as job:self.assertEqual(job.check()['status'],'blocked')
        self.value['source']=dict(root='../future',producer='job/worker',mode='native');self.save()
        with Workflow(self.project) as job:self.assertEqual(job.check()['status'],'waiting')
        (self.root/'future').write_text('not a directory')
        with Workflow(self.project) as job:self.assertEqual(job.check()['status'],'blocked')
        self.assertFalse((self.project/'missing.sqlite').exists())

    def test_cloud_preflight_requires_client_without_cloud_requests(self):
        self.value['source']=dict(root='s3://bucket/run',producer='job/worker',mode='native');self.save()
        with Workflow(self.project) as job, patch('tracker.workflows.importlib.util.find_spec',return_value=None), patch('tracker.cloud_watch.filesystem',side_effect=AssertionError('No cloud requests')):
            self.assertEqual(job.check()['status'],'blocked')
            self.assertFalse(job.output.exists())

    def test_cross_field_validation_and_launch_port(self):
        source=dict(root='outputs',producer='job/worker',mode='exports',metadata={'experiment':'job'})
        for change in ({'metadata':{}},{'producer':'x'*241},{'pattern':'../*.jsonl'},{'snapshot_state':'complete'},{'mode':'native','format':'generation'},{'root':'s3://bucket/run?token=secret'}):
            with self.subTest(change=change), self.assertRaises(InputError):validate({**self.value,'source':{**source,**change}})
        for change in ({'publish_interval':True},{'publish_interval':-1},{'ui_port':65536}):
            with self.assertRaises(InputError):validate({**self.value,**change})
        raw=package_request({'launch':{'schema':'rilldex-launch/1','database':'workspace/tracker.sqlite','source':{**source,'interval':.5},'port':9898}},self.store.path)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:value=json.loads(z.read('rilldex.json'))
        self.assertEqual(value['ui_port'],9898)
        self.assertEqual(value['interval'],.5)
        self.assertNotIn('interval',value['source'])

    def test_termination_restores_handler_and_unwinds_session(self):
        import signal
        from tracker.workflow_cli import stop_signals
        previous=signal.getsignal(signal.SIGTERM)
        self.save()
        with self.assertRaises(KeyboardInterrupt), stop_signals(), Workflow(self.project) as job, job.session():
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
        self.assertEqual(signal.getsignal(signal.SIGTERM),previous)
        with Workflow(self.project) as job:job.run()

    def test_unwritable_health_file_does_not_block_intake(self):
        source=self.root/'outputs';source.mkdir()
        (source/'a.jsonl').write_text('{"input":"Q","output":"A","step":1}\n')
        self.value['source']=dict(root=str(source),producer='job/worker',mode='exports',metadata={'experiment':'job'})
        self.save()
        with Workflow(self.project) as job, patch('tracker.workflows._atomic_json',side_effect=OSError('Status storage unavailable')):
            result=job.run()
            self.assertEqual(result['capture']['ingested'],1)
            self.assertEqual(result['status'],'published')
            self.assertEqual(result['health_error']['stage'],'status')
            self.assertEqual(len(Store(job.database).list()),1)
            self.assertEqual(job.stopped()['health_error']['stage'],'status')


if __name__ == '__main__': unittest.main()
